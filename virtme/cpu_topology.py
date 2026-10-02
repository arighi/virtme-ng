"""Translate the CPUs available to vng into a QEMU CPU topology."""

import os
from collections import defaultdict
from pathlib import Path


class TopologyError(ValueError):
    """The available CPUs cannot be described by a QEMU topology."""


def _topology_id(cpu_dir, name, default=None):
    path = cpu_dir / "topology" / name
    try:
        return int(path.read_text(encoding="ascii").strip())
    except FileNotFoundError:
        if default is not None:
            return default
        raise TopologyError(f"missing host CPU topology file: {path}") from None
    except (OSError, ValueError) as exc:
        raise TopologyError(
            f"cannot read host CPU topology from {path}: {exc}"
        ) from exc


def _cpu_ranges(cpus):
    """Format a sorted list of CPU numbers as a cpulist (e.g., 0-3,8)."""
    ranges = []
    for cpu in cpus:
        if ranges and cpu == ranges[-1][1] + 1:
            ranges[-1][1] = cpu
        else:
            ranges.append([cpu, cpu])
    return ",".join(f"{a}-{b}" if a != b else str(a) for a, b in ranges)


def _split_cores(cores, threads):
    """Split host cores into guest cores of exactly `threads` host CPUs.

    A host core with n siblings provides n // threads guest cores; leftover
    siblings are dropped. With threads=1 every host CPU becomes a guest core.
    """
    guest_cores = []
    for core in sorted(cores):
        siblings = sorted(cores[core])
        usable = len(siblings) - len(siblings) % threads
        guest_cores.extend(siblings[i : i + threads] for i in range(0, usable, threads))
    return guest_cores


def _candidates(packages):
    """Yield (sockets, cores, threads, pin) for every uniform layout."""
    thread_counts = {
        len(siblings) for cores in packages.values() for siblings in cores.values()
    }
    for threads in thread_counts | {1}:
        per_socket = [_split_cores(packages[p], threads) for p in sorted(packages)]
        per_socket = [cores for cores in per_socket if cores]
        if not per_socket:
            continue

        # Keep the sockets, dropping the extra cores of the larger ones.
        cores = min(len(c) for c in per_socket)
        pin = [cpu for c in per_socket for core in c[:cores] for cpu in core]
        yield len(per_socket), cores, threads, pin

        # Merge all sockets into one, keeping every guest core.
        if len(per_socket) > 1:
            pin = [cpu for c in per_socket for core in c for cpu in core]
            yield 1, sum(len(c) for c in per_socket), threads, pin


def host_cpu_topology(sysfs_root=Path("/sys/devices/system/cpu"), allowed_cpus=None):
    """Return (QEMU -smp value, ordered pin list, warning) for the allowed CPUs.

    QEMU numbers vCPUs by socket, core, then thread. Keep the host CPUs in
    that order so each guest core is pinned to one host core.

    QEMU can only describe uniform topologies. If the available CPUs have
    unequal cores per socket or threads per core (e.g., hybrid CPUs, or a
    cpuset covering only part of a core), pick the uniform layout with the
    most threads per core, since splitting SMT siblings has the largest
    performance impact, then the one using the most host CPUs, then the one
    with the most sockets, and return a warning describing the compromise.
    Otherwise the warning is None.
    """
    if allowed_cpus is None:
        allowed_cpus = os.sched_getaffinity(0)
    allowed_cpus = sorted(allowed_cpus)
    if not allowed_cpus:
        raise TopologyError("no host CPUs are available to this process")

    packages = defaultdict(lambda: defaultdict(list))
    for cpu in allowed_cpus:
        cpu_dir = Path(sysfs_root) / f"cpu{cpu}"
        package = _topology_id(cpu_dir, "physical_package_id")
        die = _topology_id(cpu_dir, "die_id", default=0)
        core = _topology_id(cpu_dir, "core_id")
        packages[package][(die, core)].append(cpu)

    host_threads = max(
        len(siblings) for cores in packages.values() for siblings in cores.values()
    )
    sockets, cores, threads, pin = max(
        _candidates(packages), key=lambda c: (c[2], len(c[3]), c[0])
    )
    smp = f"{len(pin)},sockets={sockets},cores={cores},threads={threads}"

    uniform = len(pin) == len(allowed_cpus) and sockets == len(packages)
    uniform = uniform and threads == host_threads
    warning = None
    if not uniform:
        dropped = sorted(set(allowed_cpus) - set(pin))
        details = []
        if dropped:
            details.append(f"host CPUs {_cpu_ranges(dropped)} are not used")
        if threads < host_threads:
            details.append("SMT siblings are exposed as separate cores")
        if sockets < len(packages):
            details.append(f"{len(packages)} host sockets are merged into one")
        warning = (
            "available host CPUs have unequal cores per socket or threads "
            f"per core; using -smp {smp} ({'; '.join(details)}). Use explicit "
            "--cpus and --pin values to choose a different layout"
        )
    return smp, pin, warning
