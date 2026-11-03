"""virtme-ng: virtiofsd daemon management and virtio-fs QEMU export arguments."""

import atexit
import os
import signal
import subprocess
import sys
import tempfile
from shutil import which
from time import monotonic, sleep

from virtme import architectures

_VIRTIOFSD_READONLY_SUPPORT: dict[str, bool | None] = {"value": None}


class VirtioFS:
    def __init__(self, guest_tools_path):
        self.sock = None
        self.pid = None
        self.guest_tools_path = guest_tools_path

    def _cleanup_virtiofs_temp_files(self):
        # Make sure to kill virtiofsd instances that are still potentially running
        if self.pid is not None:
            try:
                with open(self.pid, encoding="utf-8") as fd:
                    pid = int(fd.read().strip())
                    os.kill(pid, signal.SIGTERM)
            except (FileNotFoundError, ValueError, OSError):
                pass
        # Clean up temp files
        temp_files = [self.sock, self.pid]
        for file_path in temp_files:
            try:
                os.remove(file_path)
            except OSError:
                pass

    def _get_virtiofsd_path(self):
        # Define the possible virtiofsd paths.
        #
        # NOTE: do not use the C implementation of qemu's virtiofsd, because it
        # doesn't support unprivileged-mode execution and it would be totally
        # unsafe to export the whole rootfs of the host running as root.
        #
        # Instead, always rely on the Rust implementation of virtio-fs:
        # https://gitlab.com/virtio-fs/virtiofsd
        #
        # This project is receiving the most attention for new feature development
        # and the daemon is able to export the entire root filesystem of the host
        # as non-privileged user.
        #
        # Starting with version 8.0, qemu will not ship the C implementation of
        # virtiofsd anymore, allowing to use the Rust daemon installed in the the
        # same path (/usr/lib/qemu/virtiofsd), so also consider this one in the
        # list of possible paths.
        #
        # We can detect if the qemu implementation is installed in /usr/lib/qemu,
        # simply by running the command with --version as non-root. If it returns
        # an error it means that we are using the qemu daemon and we just skip it.
        possible_paths = (
            f"{self.guest_tools_path}/bin/virtiofsd",
            which("virtiofsd"),
            "/usr/libexec/virtiofsd",
            "/usr/lib/virtiofsd/virtiofsd",
            "/usr/lib/virtiofsd",
            "/usr/lib/qemu/virtiofsd",
        )
        for path in possible_paths:
            if path and os.path.exists(path) and os.access(path, os.X_OK):
                try:
                    subprocess.check_call(
                        [path, "--version"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return path
                except subprocess.CalledProcessError:
                    pass
        return None

    @staticmethod
    def _supports_readonly(path):
        if _VIRTIOFSD_READONLY_SUPPORT["value"] is not None:
            return _VIRTIOFSD_READONLY_SUPPORT["value"]

        try:
            result = subprocess.run(
                [path, "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        except OSError:
            supported = False
        else:
            supported = result.returncode == 0 and "--readonly" in result.stdout

        _VIRTIOFSD_READONLY_SUPPORT["value"] = supported
        return supported

    def start(
        self, path, verbose=True, cache="always", posix_acl=False, readonly=False
    ):
        virtiofsd_path = self._get_virtiofsd_path()
        if virtiofsd_path is None:
            return False

        # virtiofsd located, try to start the daemon as non-privileged user.
        _, self.sock = tempfile.mkstemp(prefix="virtme")
        self.pid = self.sock + ".pid"

        # Make sure to clean up temp files before starting the daemon and at exit.
        self._cleanup_virtiofs_temp_files()
        atexit.register(self._cleanup_virtiofs_temp_files)

        # Export the whole root fs of the host, do not enable sandbox, otherwise we
        # would get permission errors.
        if not verbose:
            stderr = "2>/dev/null"
        else:
            stderr = ""
        # Only enable --posix-acl when using an external root filesystem.
        # When sharing the host root (/), --posix-acl breaks UID/GID translation
        # which causes authentication failures (e.g., unix_chkpwd cannot obtain
        # user info).
        acl_opt = "--posix-acl " if posix_acl else ""
        readonly_opt = (
            "--readonly "
            if readonly and self._supports_readonly(virtiofsd_path)
            else ""
        )
        os.system(
            f"{virtiofsd_path} --syslog --no-announce-submounts {acl_opt}{readonly_opt}"
            + f"--socket-path {self.sock} --shared-dir {path} "
            + f"--sandbox none --cache {cache} {stderr} &"
        )
        # Keep the previous timeout (0.1 + 0.2 + 0.4 + 0.8 + 1.6 seconds),
        # but avoid adding a full 100ms delay when the daemon starts quickly.
        deadline = monotonic() + 3.1
        waiting_logged = False
        while not os.path.exists(self.pid):
            remaining = deadline - monotonic()
            if remaining <= 0:
                if verbose:
                    sys.stderr.write(
                        "virtme-run: failed to start virtiofsd, fallback to 9p"
                    )
                return False
            if verbose and not waiting_logged:
                sys.stderr.write("virtme: waiting for virtiofsd to start\n")
                waiting_logged = True
            sleep(min(0.01, remaining))
        return True


class VirtioFSConfig:
    def __init__(
        self,
        path: str,
        mount_tag: str,
        rw=False,
        posix_acl=False,
    ):
        self.path = path
        self.mount_tag = mount_tag
        self.rw = rw
        self.posix_acl = posix_acl
        self.readonly = not rw


class VirtioFSState:
    def __init__(self, guest_tools_path, memory=None, memory_configured=False):
        self.guest_tools_path = guest_tools_path
        self.memory = memory
        self.memory_configured = memory_configured


def ensure_virtiofs_memory(
    arch: architectures.Arch,
    qemuargs: list[str],
    state: VirtioFSState,
) -> None:
    if state.memory_configured:
        return

    memory = state.memory if state.memory is not None else "128M"
    qemuargs.extend(["-object", f"memory-backend-memfd,id=mem,size={memory},share=on"])
    if arch.numa_support():
        qemuargs.extend(["-numa", "node,memdev=mem"])
    else:
        qemuargs.extend(["-machine", "memory-backend=mem"])
    state.memory_configured = True


def export_virtiofs(
    arch: architectures.Arch,
    qemuargs: list[str],
    state: VirtioFSState,
    config: VirtioFSConfig,
    verbose=False,
) -> bool:
    if not arch.virtiofs_support():
        return False

    cache = "auto" if config.rw else "always"

    # Try to start virtiofsd daemon
    virtio_fs = VirtioFS(state.guest_tools_path)
    ret = virtio_fs.start(
        config.path,
        verbose,
        cache,
        config.posix_acl,
        config.readonly,
    )
    if not ret:
        return False

    # Adjust qemu options to use virtiofsd
    fsid = f"virtfs{len(qemuargs)}"
    vhost_dev_type = arch.vhost_dev_type("user-fs")

    qemuargs.extend(["-chardev", f"socket,id=char{fsid},path={virtio_fs.sock}"])
    qemuargs.extend(
        ["-device", f"{vhost_dev_type},chardev=char{fsid},tag={config.mount_tag}"]
    )

    ensure_virtiofs_memory(arch, qemuargs, state)
    return True
