# -*- mode: python -*-
# Copyright 2023 Andrea Righi

"""virtme-ng: main command-line frontend."""

import argparse
import re
import os
import sys
import socket
import shutil
import json
import signal
import tempfile
from subprocess import (
    check_call,
    check_output,
    Popen,
    DEVNULL,
    PIPE,
    CalledProcessError,
)
from select import select
from pathlib import Path
try:
    from argcomplete import autocomplete
except ModuleNotFoundError:
    def autocomplete(*args, **kwargs):
        # pylint: disable=unused-argument
        pass

from virtme.util import SilentError, uname, get_username
from virtme_ng.utils import CONF_FILE, spinner_decorator
from virtme_ng.mainline import KernelDownloader
from virtme_ng.version import VERSION


def check_call_cmd(command, quiet=False, dry_run=False):
    if dry_run:
        print(" ".join(command))
        return
    with Popen(
        command,
        stdout=PIPE,
        stderr=PIPE,
        stdin=DEVNULL,
    ) as process:
        process.stdout.flush()
        process.stderr.flush()

        stdout_fd = process.stdout.fileno()
        stderr_fd = process.stderr.fileno()

        # Use select to poll for new data in the file descriptors
        while process.poll() is None:
            ready_to_read, _, _ = select([stdout_fd, stderr_fd], [], [], 1)
            for file in ready_to_read:
                if file == stdout_fd:
                    line = process.stdout.readline().decode()
                    if line and not quiet:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                if file == stderr_fd:
                    line = process.stderr.readline().decode()
                    if line:
                        sys.stderr.write(line)
                        sys.stderr.flush()

        # Wait for the process to complete and get the return code
        return_code = process.wait()

        # Trigger a CalledProcessError exception if command failed
        if return_code:
            raise CalledProcessError(return_code, command)


def make_parser():
    """Main virtme-ng command line parser."""

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description="Build and run kernels inside a virtualized snapshot of your live system",
        epilog="""\
virtme-ng is a tool that allows to easily and quickly recompile and test a
Linux kernel, starting from the source code. It allows to re‐ compile  the
kernel in a few minutes (rather than hours), then the kernel is automatically
started in a virtualized environment that is an exact copy-on-write copy of
your live system, which means that any changes made to the virtualized
environment do not affect the host system.

In order to do this, a minimal config is produced (with the bare minimum
support to test the kernel inside qemu), then the selected kernel is
automatically built and started inside qemu, using the filesystem of the host
as a copy-on-write snapshot.

This means that you can safely destroy the entire filesystem, crash the kernel,
etc. without affecting the host.

NOTE: kernels produced with virtme-ng are lacking lots of features, in order to
reduce the build time to the minimum and still provide you a usable kernel
capable of running your tests and experiments.

virtme-ng is based on virtme, written by Andy Lutomirski <luto@kernel.org>.
""",
    )
    parser.add_argument(
        "--version", "-V", action="version", version=f"virtme-ng {VERSION}"
    )

    g_action = parser.add_argument_group(title="Action").add_mutually_exclusive_group()

    g_action.add_argument(
        "--run",
        "-r",
        action="store",
        nargs="?",
        const=uname.release,
        default=None,
        help="Run a specified kernel; "
        "--run can accept one of the following arguments: 1) nothing (in this "
        "case it'll try to boot the same kernel running on the host), 2) a kernel "
        "binary (like ./arch/x86/boot/bzImage), 3) a directory (where it'll try "
        "to find a valid kernel binary file), 4) an upstream version, for "
        "example `vng --run v6.6.17` (in this case vng will download a "
        "precompiled upstream kernel from the Ubuntu mainline repository)",
    )

    g_action.add_argument(
        "--build",
        "-b",
        action="store_true",
        help="Build the kernel in the current directory "
        "(or remotely if used with --build-host)",
    )

    g_action.add_argument(
        "--clean",
        "-x",
        action="store_true",
        help="Clean the kernel repository (local or remote if used with --build-host)",
    )

    g_action.add_argument(
        "--dump",
        "-d",
        action="store",
        help="Generate a memory dump of the running kernel "
        "(instance needs to be started with --debug)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show the commands without actually running them.",
    )

    parser.add_argument(
        "--skip-config",
        "-s",
        action="store_true",
        help="[deprecated] Do not re-generate kernel .config",
    )

    parser.add_argument(
        "--no-virtme-ng-init",
        action="store_true",
        help="Fallback to the bash virtme-init (useful for debugging/development)",
    )

    parser.add_argument(
        "--gdb",
        action="store_true",
        help="Attach a debugging session to a running instance started with --debug",
    )

    parser.add_argument(
        "--snaps", action="store_true", help="Allow to execute snaps inside virtme-ng"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Start the instance with debugging enabled (allow to generate crash dumps)",
    )

    parser.add_argument(
        "--kconfig",
        "-k",
        action="store_true",
        help="Only override the kernel .config without building/running anything",
    )

    parser.add_argument(
        "--skip-modules",
        "-S",
        action="store_true",
        help="Run a really fast build by skipping external modules "
        "(no external modules support)",
    )

    parser.add_argument(
        "--commit",
        "-c",
        action="store",
        help="Use a kernel identified by a specific commit id, tag or branch",
    )

    parser.add_argument(
        "--config",
        "--custom",
        "-f",
        action="append",
        help="Use one (or more) specific kernel .config snippet "
        "to override default config settings",
    )

    parser.add_argument(
        "--configitem",
        action="append",
        help="add a CONFIG_ITEM=val, after --config <fragments>, "
        "these override previous config settings",
    )

    parser.add_argument(
        "--compiler",
        action="store",
        help="[deprecated] Compiler to be used as CC when building the kernel. "
        "Please set CC= and HOSTCC= variables in the virtme-ng command line instead.",
    )

    parser.add_argument(
        "--busybox",
        metavar="PATH_TO_BUSYBOX",
        action="store",
        help="Use the specified busybox binary",
    )

    parser.add_argument("--qemu", action="store", help="Use the specified QEMU binary")

    parser.add_argument(
        "--name",
        action="store",
        default="virtme-ng",
        help="Set guest hostname and qemu -name flag"
    )

    parser.add_argument(
        "--user",
        action="store",
        help="Change user inside the guest (default is same user as the host)",
    )

    parser.add_argument(
        "--root",
        action="store",
        help="Pass a specific chroot to use inside the virtualized kernel "
        + "(useful with --arch)",
    )

    parser.add_argument(
        "--root-release",
        action="store",
        help="Use a target Ubuntu release to create a new chroot (used with --root)",
    )

    parser.add_argument(
        "--rw",
        action="store_true",
        help="Give the guest read-write access to its root filesystem. "
        "WARNING: this can be dangerous for the host filesystem!",
    )

    parser.add_argument(
        "--force-9p", action="store_true", help="Use legacy 9p filesystem as rootfs"
    )

    parser.add_argument(
        "--disable-microvm",
        action="store_true",
        help='Avoid using the "microvm" QEMU architecture (only on x86_64)',
    )

    parser.add_argument(
        "--disable-kvm",
        action="store_true",
        help='Avoid using hardware virtualization / KVM',
    )

    parser.add_argument(
        "--cwd",
        action="store",
        help="Change guest working directory "
        + "(default is current working directory when possible)",
    )

    parser.add_argument(
        "--pwd",
        action="store_true",
        help="[deprecated] --pwd is set implicitly by default",
    )

    parser.add_argument(
        "--rodir",
        action="append",
        default=[],
        help="Supply a read-only directory to the guest."
        + "Use --rodir=path or --rodir=guestpath=hostpath",
    )

    parser.add_argument(
        "--rwdir",
        action="append",
        default=[],
        help="Supply a read/write directory to the guest."
        + "Use --rwdir=path or --rwdir=guestpath=hostpath",
    )

    parser.add_argument(
        "--overlay-rwdir",
        action="append",
        default=[],
        help="Supply a directory that is r/w to the guest but read-only in the host."
        + "Use --overlay-rwdir=path.",
    )

    parser.add_argument(
        "--cpus", "-p", action="store", help="Set guest CPU count (qemu -smp flag)"
    )

    parser.add_argument(
        "--memory", "-m", action="store", help="Set guest memory size (qemu -m flag)"
    )

    parser.add_argument(
        "--numa",
        metavar="MEM[,cpus=FIRST_CPU1[-LAST_CPU1]][,cpus=FIRST_CPU2[-LAST_CPU2]]...",
        action="append",
        help="Create a NUMA node in the guest. "
        + "Use this option multiple times to create more NUMA nodes. "
        + "The total memory size assigned to NUMA nodes must match the guest memory size (specified with --memory/-m). "
        + "This option implicitly disables the microvm architecture."
    )

    parser.add_argument(
        "--balloon",
        action="store_true",
        help="Allow the host to ask the guest to release memory",
    )

    parser.add_argument(
        "--network",
        "-n",
        action="append",
        choices=['user', 'bridge', 'loop'],
        help="Enable network access",
    )

    parser.add_argument(
        "--disk",
        "-D",
        action="append",
        metavar="PATH",
        help="Add a file as virtio-scsi disk (can be used multiple times)",
    )

    parser.add_argument(
        "--exec",
        "-e",
        action="store",
        help="Execute a command inside the kernel and exit",
    )

    parser.add_argument(
        "--append",
        "-a",
        action="append",
        help="Additional kernel boot options (can be used multiple times)",
    )

    parser.add_argument(
        "--force-initramfs",
        action="store_true",
        help="Use an initramfs even if unnecessary",
    )

    parser.add_argument(
        "--sound",
        action="store_true",
        help="Enable audio device (if the architecture supports it)",
    )

    parser.add_argument(
        "--graphics",
        "-g",
        action="store_true",
        help="Show graphical output instead of using a console.",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Increase console output verbosity.",
    )

    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Override verbose mode (disable --verbose).",
    )

    parser.add_argument(
        "--qemu-opts",
        "-o",
        action="append",
        help="Additional arguments for QEMU (can be used multiple times)"
        " or bundled together: --qemu-opts='...'",
    )

    parser.add_argument(
        "--build-host",
        action="store",
        help="Perform kernel build on a remote server (ssh access required)",
    )

    parser.add_argument(
        "--build-host-exec-prefix",
        action="store",
        help="Prepend a command (e.g., chroot) "
        "to the make command executed on the remote build host",
    )

    parser.add_argument(
        "--build-host-vmlinux",
        action="store_true",
        help="Copy vmlinux back from the build host",
    )

    parser.add_argument(
        "--arch",
        action="store",
        help="Generate and test a kernel for a specific architecture "
        "(default is host architecture)",
    )

    parser.add_argument(
        "--cross-compile",
        action="store",
        help="Set cross-compile prefix"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reset git repository to target branch or commit "
        "(warning: this may drop uncommitted changes), "
        "and force kernel config override",
    )

    parser.add_argument(
        "envs",
        metavar="envs",
        type=str,
        nargs="*",
        help="Additional Makefile variables",
    )
    return parser


_ARGPARSER = make_parser()


def arg_fail(message, show_usage=True):
    """Print an error message and exit, optionally showing usage help."""
    sys.stderr.write(message + "\n")
    if show_usage:
        _ARGPARSER.print_usage()
    sys.exit(1)


ARCH_MAPPING = {
    "arm64": {
        "qemu_name": "aarch64",
        "linux_name": "arm64",
        "cross_compile": "aarch64-linux-gnu-",
        "kernel_target": "Image",
        "kernel_image": "Image",
    },
    "armhf": {
        "qemu_name": "arm",
        "linux_name": "arm",
        "cross_compile": "arm-linux-gnueabihf-",
        "kernel_target": "",
        "kernel_image": "zImage",
        "max-cpus": 4,
    },
    "ppc64el": {
        "qemu_name": "ppc64",
        "linux_name": "powerpc",
        "cross_compile": "powerpc64le-linux-gnu-",
        "kernel_target": "vmlinux",
        "kernel_image": "vmlinux",
    },
    "s390x": {
        "qemu_name": "s390x",
        "linux_name": "s390",
        "cross_compile": "s390x-linux-gnu-",
        "kernel_target": "bzImage",
        "kernel_image": "bzImage",
    },
    "riscv64": {
        "qemu_name": "riscv64",
        "linux_name": "riscv",
        "cross_compile": "riscv64-linux-gnu-",
        "kernel_target": "Image",
        "kernel_image": "Image",
    },
}

MAKE_COMMAND = "make LOCALVERSION=-virtme"

REMOTE_BUILD_SCRIPT = """#!/bin/bash
cd ~/.virtme
git reset --hard __virtme__
[ -f debian/rules ] && fakeroot debian/rules clean
{} {}
"""


def create_root(destdir, arch, release):
    """Initialize a rootfs directory, populating files/directory if it doesn't exist."""
    if os.path.exists(destdir):
        return
    # Use Ubuntu's cloud images to create a rootfs, these images are fairly
    # small and they provide a nice environment to test kernels.
    if release is None:
        release = (
            check_output("lsb_release -s -c", shell=True)
            .decode(sys.stdout.encoding)
            .rstrip()
        )
    url = (
        "https://cloud-images.ubuntu.com/"
        + f"{release}/current/{release}-server-cloudimg-{arch}-root.tar.xz"
    )
    prevdir = os.getcwd()
    os.system(f"sudo mkdir -p {destdir}")
    os.chdir(destdir)
    os.system(f"curl -s {url} | sudo tar xvJ")
    os.chdir(prevdir)


class KernelSource:
    """Main class that implement actions to perform on a kernel source directory."""

    def __init__(self):
        self.virtme_param = {}
        conf_path = self.get_conf_file_path()
        self.default_opts = []
        if conf_path is not None:
            with open(conf_path, "r", encoding="utf-8") as conf_fd:
                conf_data = json.loads(conf_fd.read())
                if "default_opts" in conf_data:
                    self.default_opts = conf_data["default_opts"]
        self.cpus = str(os.cpu_count())

    def get_conf_file_path(self):
        """Return virtme-ng main configuration file path."""

        # First check if there is a config file in the user's home config
        # directory, then check for a single config file in ~/.virtme-ng.conf and
        # finally check for /etc/virtme-ng.conf. If none of them exist, report an
        # error and exit.
        configs = (
            CONF_FILE,
            Path(Path.home(), ".virtme-ng.conf"),
            Path("/etc", "virtme-ng.conf"),
        )
        for conf in configs:
            if conf.exists():
                return conf
        return None

    def _format_cmd(self, cmd):
        return list(filter(None, cmd.split(" ")))

    def _is_dirty_repo(self):
        cmd = "git --no-optional-locks status -uno --porcelain"
        if check_output(self._format_cmd(cmd), stderr=DEVNULL, stdin=DEVNULL):
            return True
        return False

    def checkout(self, args):
        """Perform a git checkout operation on a local kernel git repository."""
        if not os.path.exists(".git"):
            arg_fail("error: must run from a kernel git repository", show_usage=False)
        target = args.commit or "HEAD"
        if args.build_host is not None or target != "HEAD":
            if not args.force and self._is_dirty_repo():
                arg_fail(
                    "error: you have uncommitted changes in your git repository, "
                    + "use --force to drop them",
                    show_usage=False,
                )
            check_call_cmd(
                ["git", "reset", "--hard", target],
                quiet=not args.verbose,
                dry_run=args.dry_run,
            )

    def config(self, args):
        """Perform a make config operation on a kernel source directory."""
        arch = args.arch
        cmd = "virtme-configkernel --defconfig"
        if args.verbose:
            cmd += " --verbose"
        if not args.force and not args.kconfig:
            cmd += " --no-update"
        if arch is not None:
            if arch not in ARCH_MAPPING:
                arg_fail(f"unsupported architecture: {arch}")
            arch = ARCH_MAPPING[arch]["qemu_name"]
            cmd += f" --arch {arch}"
        user_config = str(Path.home()) + "/.config/virtme-ng/kernel.config"
        if os.path.exists(user_config):
            cmd += f" --custom {user_config}"
        if args.config:
            for conf in args.config:
                cmd += f" --custom {conf}"
        if args.configitem:
            for citem in args.configitem:
                cmd += f" --configitem {citem}"
        # Propagate additional Makefile variables
        for var in args.envs:
            cmd += f" {var} "
        if args.verbose:
            print(f"cmd: {cmd}")
        check_call_cmd(
            self._format_cmd(cmd), quiet=not args.verbose, dry_run=args.dry_run
        )

    def _make_remote(self, args, make_command):
        check_call_cmd(
            ["ssh", args.build_host, "mkdir -p ~/.virtme"],
            quiet=not args.verbose,
            dry_run=args.dry_run,
        )
        check_call_cmd(
            ["ssh", args.build_host, "git init ~/.virtme"],
            quiet=not args.verbose,
            dry_run=args.dry_run,
        )
        check_call_cmd(
            [
                "git",
                "push",
                "--force",
                "--porcelain",
                f"{args.build_host}:~/.virtme",
                "HEAD:refs/heads/__virtme__",
            ],
            quiet=not args.verbose,
            dry_run=args.dry_run,
        )
        cmd = f"rsync .config {args.build_host}:.virtme/.config"
        check_call_cmd(
            self._format_cmd(cmd), quiet=not args.verbose, dry_run=args.dry_run
        )
        # Create remote build script
        with tempfile.NamedTemporaryFile(mode="w+t") as tmp:
            tmp.write(
                REMOTE_BUILD_SCRIPT.format(
                    args.build_host_exec_prefix or "",
                    make_command + " -j$(nproc --all)",
                )
            )
            tmp.flush()
            cmd = f"rsync {tmp.name} {args.build_host}:.virtme/.kc-build"
            check_call_cmd(
                self._format_cmd(cmd), quiet=not args.verbose, dry_run=args.dry_run
            )
        # Execute remote build script
        check_call_cmd(
            ["ssh", args.build_host, "bash", ".virtme/.kc-build"],
            quiet=not args.verbose,
            dry_run=args.dry_run,
        )
        # Copy artifacts back to the running host
        with tempfile.NamedTemporaryFile(mode="w+t") as tmp:
            if args.build_host_vmlinux or args.arch == "ppc64el":
                vmlinux = "--include=vmlinux"
            else:
                vmlinux = ""
            if args.skip_modules:
                cmd = (
                    "rsync -azS --progress --exclude=.config --exclude=.git/ "
                    + "--include=*/ --include=bzImage --include=zImage --include=Image "
                    + f'{vmlinux} --include=*.dtb --exclude="*" {args.build_host}:.virtme/ ./'
                )
            else:
                cmd = (
                    "rsync -azS --progress --exclude=.config --exclude=.git/ "
                    + '--include=*/ --include="*.ko" --include=".dwo" '
                    + f"--include=bzImage --include=zImage --include=Image {vmlinux} "
                    + "--include=.config --include=modules.* "
                    + "--include=System.map --include=Module.symvers --include=module.lds "
                    + '--include=*.dtb --include="**/generated/**" --exclude="*" '
                    + f"{args.build_host}:.virtme/ ./"
                )
            tmp.write(cmd)
            tmp.flush()
            check_call_cmd(
                ["bash", tmp.name], quiet=not args.verbose, dry_run=args.dry_run
            )
        if not args.skip_modules:
            if os.path.exists("./debian/rules"):
                check_call_cmd(
                    ["fakeroot", "debian/rules", "clean"], quiet=not args.verbose
                )
            check_call_cmd(
                self._format_cmd(
                    make_command + f" -j {self.cpus}" + " modules_prepare"
                ),
                quiet=not args.verbose,
                dry_run=args.dry_run,
            )

    def make(self, args):
        """Perform a make operation on a kernel source directory."""
        if not os.path.exists(".git") and args.build_host is not None:
            arg_fail(
                "error: --build-host can be used only on a kernel git repository",
                show_usage=False,
            )
        if args.build_host is not None and self._is_dirty_repo():
            arg_fail(
                "error: you have uncommitted changes in your git repository, "
                + "commit or drop them before building on a remote host",
                show_usage=False,
            )
        arch = args.arch
        if arch is not None:
            if arch not in ARCH_MAPPING:
                arg_fail(f"unsupported architecture: {arch}")
            target = ARCH_MAPPING[arch]["kernel_target"]
            cross_compile = ARCH_MAPPING[arch]["cross_compile"]
            if args.cross_compile != "":
                cross_compile = args.cross_compile

            cross_arch = ARCH_MAPPING[arch]["linux_name"]
        else:
            target = "bzImage"
            cross_compile = None
            cross_arch = None
        make_command = MAKE_COMMAND
        if args.compiler:
            make_command += f" HOSTCC={args.compiler} CC={args.compiler}"
        if args.skip_modules:
            make_command += f" {target}"
        if cross_compile and cross_arch:
            make_command += f" CROSS_COMPILE={cross_compile} ARCH={cross_arch}"
        # Propagate additional Makefile variables
        for var in args.envs:
            make_command += f" {var} "
        if args.build_host is None:
            # Build the kernel locally
            check_call_cmd(
                self._format_cmd(make_command + " -j" + self.cpus),
                quiet=not args.verbose,
                dry_run=args.dry_run,
            )
        else:
            # Build the kernel on a remote build host
            self._make_remote(args, make_command)

    def _get_virtme_name(self, args):
        if args.name is not None:
            self.virtme_param["name"] = "--name " + args.name
        else:
            self.virtme_param["name"] = "--name " + socket.gethostname()

    def _get_virtme_exec(self, args):
        if args.envs:
            args.exec = " ".join(args.envs)
        if args.exec is not None:
            self.virtme_param["exec"] = f'--script-sh "{args.exec}"'
        else:
            self.virtme_param["exec"] = ""

    def _get_virtme_user(self, args):
        # Default user for scripts is root, default user for interactive
        # sessions is current user.
        #
        # NOTE: graphic sessions are considered interactive.
        if args.exec and not args.graphics:
            self.virtme_param["user"] = ""
        else:
            self.virtme_param["user"] = "--user " + get_username()
        # Override default user, if specified by the --user argument.
        if args.user is not None:
            if args.user != "root":
                self.virtme_param["user"] = "--user " + args.user
            else:
                self.virtme_param["user"] = ""

    def _get_virtme_arch(self, args):
        if args.arch is not None:
            if args.arch not in ARCH_MAPPING:
                arg_fail(f"unsupported architecture: {args.arch}")
            if "max-cpus" in ARCH_MAPPING[args.arch]:
                self.cpus = ARCH_MAPPING[args.arch]["max-cpus"]
            self.virtme_param["arch"] = "--arch " + ARCH_MAPPING[args.arch]["qemu_name"]
        else:
            self.virtme_param["arch"] = ""

    def _get_virtme_root(self, args):
        if args.root is not None:
            create_root(args.root, args.arch or "amd64", args.root_release)
            self.virtme_param["root"] = f"--root {args.root}"
        else:
            self.virtme_param["root"] = ""

    def _get_virtme_rw(self, args):
        if args.rw:
            self.virtme_param["rw"] = "--rw"
        else:
            self.virtme_param["rw"] = ""

    def _get_virtme_cwd(self, args):
        if args.cwd is not None:
            if args.pwd:
                arg_fail("--pwd and --cwd are mutually exclusive")
            self.virtme_param["cwd"] = "--cwd " + args.cwd
        elif args.root is None:
            self.virtme_param["cwd"] = "--pwd"
        else:
            self.virtme_param["cwd"] = ""

    def _get_virtme_rodir(self, args):
        self.virtme_param["rodir"] = ""
        for item in args.rodir:
            self.virtme_param["rodir"] += "--rodir " + item

    def _get_virtme_rwdir(self, args):
        self.virtme_param["rwdir"] = ""
        for item in args.rwdir:
            self.virtme_param["rwdir"] += "--rwdir " + item

    def _get_virtme_overlay_rwdir(self, args):
        # Set default overlays if rootfs is mounted in read-only mode.
        if args.rw:
            self.virtme_param["overlay_rwdir"] = ""
        else:
            self.virtme_param["overlay_rwdir"] = " ".join(
                f"--overlay-rwdir {d}"
                for d in ("/etc", "/lib", "/home", "/opt", "/srv", "/usr", "/var", "/tmp")
            )
        # Add user-specified overlays.
        for item in args.overlay_rwdir:
            self.virtme_param["overlay_rwdir"] += " --overlay-rwdir " + item

    def _get_virtme_run(self, args):
        if args.run is not None:
            # If an upstream version is specified (using an upstream tag) fetch
            # and run the corresponding kernel from the Ubuntu mainline
            # repository.
            if re.match(r'^v\d+(\.\d+)*$', args.run):
                if args.arch is None:
                    arch = 'amd64'
                else:
                    arch = args.arch
                try:
                    mainline = KernelDownloader(args.run, arch=arch, verbose=args.verbose)
                    self.virtme_param["kdir"] = "--kimg " + mainline.target
                except FileNotFoundError as exc:
                    sys.stderr.write(str(exc) + "\n")
                    sys.exit(1)
            else:
                self.virtme_param["kdir"] = "--kimg " + args.run
        else:
            for var in args.envs:
                if var.startswith("O="):
                    self.virtme_param["kdir"] = "--kdir ./" + var[2:]
            if self.virtme_param.get("kdir") is None:
                self.virtme_param["kdir"] = "--kdir ./"

    def _get_virtme_mods(self, args):
        if args.skip_modules:
            self.virtme_param["mods"] = "--mods none"
        else:
            self.virtme_param["mods"] = "--mods auto"

    def _get_virtme_dry_run(self, args):
        if args.dry_run:
            self.virtme_param["dry_run"] = "--show-command --dry-run"
        else:
            self.virtme_param["dry_run"] = ""

    def _get_virtme_no_virtme_ng_init(self, args):
        if args.no_virtme_ng_init:
            self.virtme_param["no_virtme_ng_init"] = "--no-virtme-ng-init"
        else:
            self.virtme_param["no_virtme_ng_init"] = ""

    def _get_virtme_network(self, args):
        if args.network is not None:
            network_str = " ".join([f"--net {network}" for network in args.network])
            self.virtme_param["network"] = network_str
        else:
            self.virtme_param["network"] = ""

    def _get_virtme_disk(self, args):
        if args.disk is not None:
            disk_str = ""
            for dsk in args.disk:
                disk_str += f"--blk-disk {dsk}={dsk} "
            self.virtme_param["disk"] = disk_str
        else:
            self.virtme_param["disk"] = ""

    def _get_virtme_sound(self, args):
        if args.sound:
            self.virtme_param["sound"] = "--sound"
        else:
            self.virtme_param["sound"] = ""

    def _get_virtme_disable_microvm(self, args):
        # Automatically disable microvm in debug mode, since it seems to
        # produce incomplete memory dumps.
        if args.disable_microvm or args.debug:
            self.virtme_param["disable_microvm"] = "--disable-microvm"
        else:
            self.virtme_param["disable_microvm"] = ""

    def _get_virtme_disable_kvm(self, args):
        if args.disable_kvm:
            self.virtme_param["disable_kvm"] = "--disable-kvm"
        else:
            self.virtme_param["disable_kvm"] = ""

    def _get_virtme_9p(self, args):
        if args.force_9p:
            self.virtme_param["force_9p"] = "--force-9p"
        else:
            self.virtme_param["force_9p"] = ""

    def _get_virtme_initramfs(self, args):
        if args.force_initramfs:
            self.virtme_param["force_initramfs"] = "--force-initramfs"
        else:
            self.virtme_param["force_initramfs"] = ""

    def _get_virtme_graphics(self, args):
        if args.graphics:
            self.virtme_param["graphics"] = '--graphics'
        else:
            self.virtme_param["graphics"] = ""

    def _get_virtme_verbose(self, args):
        if args.verbose:
            self.virtme_param["verbose"] = "--verbose --show-boot-console"
        else:
            self.virtme_param["verbose"] = ""

    def _get_virtme_append(self, args):
        append = []
        if args.append is not None:
            for item in args.append:
                split_items = item.split()
                for split_item in split_items:
                    append.append("-a " + split_item)
        if args.debug:
            append.append("-a nokaslr")
        self.virtme_param["append"] = " ".join(append)

    def _get_virtme_memory(self, args):
        if args.memory is None:
            self.virtme_param["memory"] = "--memory 1G"
        else:
            self.virtme_param["memory"] = "--memory " + args.memory

    def _get_virtme_numa(self, args):
        if args.numa is not None:
            numa_str = " ".join([f"--numa {numa}" for numa in args.numa])
            self.virtme_param["numa"] = numa_str
        else:
            self.virtme_param["numa"] = ""

    def _get_virtme_balloon(self, args):
        if args.balloon:
            self.virtme_param["balloon"] = "--balloon"
        else:
            self.virtme_param["balloon"] = ""

    def _get_virtme_gdb(self, args):
        if args.gdb:
            def signal_handler(_signum, _frame):
                pass  # No action needed for SIGINT in child (gdb will handle)
            signal.signal(signal.SIGINT, signal_handler)
            self.virtme_param["gdb"] = "--gdb"
        else:
            self.virtme_param["gdb"] = ""

    def _get_virtme_snaps(self, args):
        if args.snaps:
            self.virtme_param["snaps"] = "--snaps"
        else:
            self.virtme_param["snaps"] = ""

    def _get_virtme_busybox(self, args):
        if args.busybox is not None:
            self.virtme_param["busybox"] = "--busybox " + args.busybox
        else:
            self.virtme_param["busybox"] = ""

    def _get_virtme_qemu(self, args):
        if args.qemu is not None:
            self.virtme_param["qemu"] = "--qemu-bin " + args.qemu
        else:
            self.virtme_param["qemu"] = ""

    def _get_virtme_cpus(self, args):
        if args.cpus is None:
            cpus = self.cpus
        else:
            cpus = args.cpus
        self.virtme_param["cpus"] = f"--cpus {cpus}"

    def _get_virtme_qemu_opts(self, args):
        qemu_args = ""
        if args.qemu_opts is not None:
            qemu_args += " ".join(args.qemu_opts)
        if args.debug:
            # Enable vmcoreinfo (required by drgn memory dumps)
            qemu_args += "-device vmcoreinfo "
            # Enable debug mode and QMP (to trigger memory dump via `vng --dump`)
            qemu_args += "-s -qmp tcp:localhost:3636,server,nowait "
        if qemu_args != "":
            self.virtme_param["qemu_opts"] = "--qemu-opts " + qemu_args
        else:
            self.virtme_param["qemu_opts"] = ""

    def run(self, args):
        """Execute a kernel inside virtme-ng."""
        self._get_virtme_name(args)
        self._get_virtme_exec(args)
        self._get_virtme_user(args)
        self._get_virtme_arch(args)
        self._get_virtme_root(args)
        self._get_virtme_rw(args)
        self._get_virtme_rodir(args)
        self._get_virtme_rwdir(args)
        self._get_virtme_overlay_rwdir(args)
        self._get_virtme_cwd(args)
        self._get_virtme_run(args)
        self._get_virtme_dry_run(args)
        self._get_virtme_no_virtme_ng_init(args)
        self._get_virtme_mods(args)
        self._get_virtme_network(args)
        self._get_virtme_disk(args)
        self._get_virtme_sound(args)
        self._get_virtme_disable_microvm(args)
        self._get_virtme_disable_kvm(args)
        self._get_virtme_9p(args)
        self._get_virtme_initramfs(args)
        self._get_virtme_graphics(args)
        self._get_virtme_verbose(args)
        self._get_virtme_append(args)
        self._get_virtme_cpus(args)
        self._get_virtme_memory(args)
        self._get_virtme_numa(args)
        self._get_virtme_balloon(args)
        self._get_virtme_gdb(args)
        self._get_virtme_snaps(args)
        self._get_virtme_busybox(args)
        self._get_virtme_qemu(args)
        self._get_virtme_qemu_opts(args)

        # Start VM using virtme-run
        cmd = (
            "virtme-run "
            + f'{self.virtme_param["name"]} '
            + f'{self.virtme_param["exec"]} '
            + f'{self.virtme_param["user"]} '
            + f'{self.virtme_param["arch"]} '
            + f'{self.virtme_param["root"]} '
            + f'{self.virtme_param["rw"]} '
            + f'{self.virtme_param["rodir"]} '
            + f'{self.virtme_param["rwdir"]} '
            + f'{self.virtme_param["overlay_rwdir"]} '
            + f'{self.virtme_param["cwd"]} '
            + f'{self.virtme_param["kdir"]} '
            + f'{self.virtme_param["dry_run"]} '
            + f'{self.virtme_param["no_virtme_ng_init"]} '
            + f'{self.virtme_param["mods"]} '
            + f'{self.virtme_param["network"]} '
            + f'{self.virtme_param["disk"]} '
            + f'{self.virtme_param["sound"]} '
            + f'{self.virtme_param["disable_microvm"]} '
            + f'{self.virtme_param["disable_kvm"]} '
            + f'{self.virtme_param["force_9p"]} '
            + f'{self.virtme_param["force_initramfs"]} '
            + f'{self.virtme_param["graphics"]} '
            + f'{self.virtme_param["verbose"]} '
            + f'{self.virtme_param["append"]} '
            + f'{self.virtme_param["cpus"]} '
            + f'{self.virtme_param["memory"]} '
            + f'{self.virtme_param["numa"]} '
            + f'{self.virtme_param["balloon"]} '
            + f'{self.virtme_param["gdb"]} '
            + f'{self.virtme_param["snaps"]} '
            + f'{self.virtme_param["busybox"]} '
            + f'{self.virtme_param["qemu"]} '
            + f'{self.virtme_param["qemu_opts"]} '
        )
        check_call(cmd, shell=True)

    def dump(self, args):
        """Generate or analyze a crash memory dump."""
        # Use QMP to generate a memory dump
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("localhost", 3636))
        data = sock.recv(1024)
        if not data:
            sys.exit(1)
        if args.verbose:
            sys.stdout.write(data.decode("utf-8"))
        sock.send('{ "execute": "qmp_capabilities" }\r'.encode("utf-8"))
        data = sock.recv(1024)
        if not data:
            sys.exit(1)
        if args.verbose:
            sys.stdout.write(data.decode("utf-8"))
        dump_file = args.dump
        with tempfile.NamedTemporaryFile(delete=dump_file is None) as tmp:
            msg = (
                '{"execute":"dump-guest-memory",'
                '"arguments":{"paging":true,'
                '"protocol":"file:' + tmp.name + '"}}'
                "\r"
            )
            if args.verbose:
                sys.stdout.write(msg + "\n")
            sock.send(msg.encode("utf-8"))
            data = sock.recv(1024)
            if not data:
                sys.exit(1)
            if args.verbose:
                sys.stdout.write(data.decode("utf-8"))
            data = sock.recv(1024)
            if args.verbose:
                sys.stdout.write(data.decode("utf-8"))
            # Save memory dump to target file
            shutil.move(tmp.name, dump_file)

    def clean(self, args):
        """Clean a local or remote git repository."""
        if not os.path.exists(".git"):
            arg_fail("error: must run from a kernel git repository", show_usage=False)
        if args.build_host is None:
            cmd = self._format_cmd("git clean -xdf")
        else:
            cmd = f"ssh {args.build_host} --"
            cmd = self._format_cmd(cmd)
            cmd.append("cd ~/.virtme && git clean -xdf")
        check_call_cmd(cmd, quiet=not args.verbose, dry_run=args.dry_run)


@spinner_decorator(message="📦 checking out kernel")
def checkout(kern_source, args):
    """Checkout kernel."""
    kern_source.checkout(args)
    return True


@spinner_decorator(message="🔧 configuring kernel")
def config(kern_source, args):
    """Configure the kernel."""
    kern_source.config(args)
    return True


@spinner_decorator(message="⚙️c building kernel")
def make(kern_source, args):
    """Build the kernel."""
    kern_source.make(args)
    return True


@spinner_decorator(message="🧹 cleaning kernel")
def clean(kern_source, args):
    """Clean the kernel repo."""
    kern_source.clean(args)
    return True


def run(kern_source, args):
    """Run the kernel."""
    return kern_source.run(args)


@spinner_decorator(message="🐞 generating memory dump")
def dump(kern_source, args):
    """Dump the kernel (if the kernel was running with --debug)."""
    kern_source.dump(args)
    return True


def do_it() -> int:
    """Main body."""
    autocomplete(_ARGPARSER)
    args = _ARGPARSER.parse_args()

    kern_source = KernelSource()
    if kern_source.default_opts:
        for opt in kern_source.default_opts:
            val = kern_source.default_opts[opt]
            setattr(args, opt, val)

    if args.verbose and args.quiet:
        args.verbose = False
    try:
        if args.clean:
            clean(kern_source, args)
        elif args.dump is not None:
            dump(kern_source, args)
        elif args.build or args.kconfig:
            if args.commit:
                checkout(kern_source, args)
            config(kern_source, args)
            if args.kconfig:
                return 0
            make(kern_source, args)
        else:
            try:
                run(kern_source, args)
                return 0
            except CalledProcessError as exc:
                return exc.returncode
    except CalledProcessError as exc:
        raise SilentError() from exc
    return 0


def main() -> int:
    """Main."""
    try:
        return do_it()
    except (KeyboardInterrupt, SilentError):
        return 1


if __name__ == "__main__":
    main()
