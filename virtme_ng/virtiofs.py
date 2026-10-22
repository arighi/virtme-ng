"""virtme-ng: virtiofsd daemon management and virtio-fs QEMU export arguments."""

import atexit
import ctypes
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
from shutil import which
from time import monotonic, sleep

from virtme import architectures

_VIRTIOFSD_HELP: dict[str, str] = {}

_PR_SET_PDEATHSIG = 1


def _die_with_parent():
    """Return a function for Popen(preexec_fn=) to tie a child to its parent.

    The child gets SIGTERM as soon as the parent exits, whatever the reason,
    including a SIGKILL that does not run any exit handler. Note that the
    kernel ties this to the *thread* that spawned the child, so the child
    must be spawned from a thread that lives as long as the process (the
    main thread).
    """
    # Load libc here: the returned function runs between fork and exec, where
    # nothing but already prepared code should be executed.
    prctl = ctypes.CDLL(None).prctl
    parent_pid = os.getpid()

    def preexec():
        # Without the parent-death signal, the daemon would survive a SIGKILLed
        # vng: do not exec it then. prctl() returns -1 on error.
        if prctl(_PR_SET_PDEATHSIG, signal.SIGTERM) != 0:
            os._exit(1)
        # The parent may have died before the prctl() call took effect.
        if os.getppid() != parent_pid:
            os._exit(1)

    return preexec


class VirtioFS:
    def __init__(self, guest_tools_path):
        self.sock = None
        self.proc = None
        self.guest_tools_path = guest_tools_path

    def _cleanup_virtiofs_temp_files(self):
        # Make sure to kill virtiofsd instances that are still potentially running
        if self.proc is not None:
            try:
                self.proc.terminate()
            except PermissionError:
                pass
        # Clean up temp files (virtiofsd creates a pid file next to the socket
        # in --socket-path mode; remove it as well, even though it is unused)
        if self.sock is not None:
            for file_path in (self.sock, f"{self.sock}.pid"):
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
    def _is_socket(path):
        try:
            return stat.S_ISSOCK(os.stat(path).st_mode)
        except OSError:
            return False

    @staticmethod
    def _get_virtiofsd_help(path) -> str:
        # Return the (cached) `--help` output of the virtiofsd at PATH;
        # several feature checks may need it, but it is enough to run each
        # daemon only once. An empty string means the output could not be
        # retrieved.
        if path not in _VIRTIOFSD_HELP:
            try:
                result = subprocess.run(
                    [path, "--help"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
            except OSError:
                help_text = ""
            else:
                help_text = result.stdout if result.returncode == 0 else ""
            _VIRTIOFSD_HELP[path] = help_text
        return _VIRTIOFSD_HELP[path]

    @staticmethod
    def _supports_flag(path, flag) -> bool:
        # Match FLAG as a whole flag: the exact --help formatting (spacing,
        # wrapping) differs across virtiofsd versions and must not silently
        # disable a feature, and a longer flag must not match as its
        # shorter prefix (e.g. --readonly-mode is not --readonly).
        return (
            re.search(
                rf"{re.escape(flag)}(?![\w-])", VirtioFS._get_virtiofsd_help(path)
            )
            is not None
        )

    @staticmethod
    def _supports_readonly(path):
        return VirtioFS._supports_flag(path, "--readonly")

    def _report_9p_fallback(self, verbose):
        if verbose:
            sys.stderr.write("virtme-run: failed to start virtiofsd, fallback to 9p\n")

    def start(
        self, path, verbose=True, cache="always", posix_acl=False, readonly=False
    ):
        virtiofsd_path = self._get_virtiofsd_path()
        if virtiofsd_path is None:
            return False

        # virtiofsd located, try to start the daemon as non-privileged user.
        sock_fd, self.sock = tempfile.mkstemp(prefix="virtme", suffix=".sock")
        os.close(sock_fd)

        # Make sure to clean up temp files before starting the daemon and at exit.
        self._cleanup_virtiofs_temp_files()
        atexit.register(self._cleanup_virtiofs_temp_files)

        # Export the whole root fs of the host, do not enable sandbox, otherwise we
        # would get permission errors.
        if verbose:
            stderr = None
        else:
            stderr = subprocess.DEVNULL
        # Only enable --posix-acl when using an external root filesystem.
        # When sharing the host root (/), --posix-acl breaks UID/GID translation
        # which causes authentication failures (e.g., unix_chkpwd cannot obtain
        # user info).
        acl_opt = ["--posix-acl"] if posix_acl else []
        readonly_opt = (
            ["--readonly"]
            if readonly and self._supports_readonly(virtiofsd_path)
            else []
        )
        virtiofsd_cmd = [
            virtiofsd_path,
            "--syslog",
            "--no-announce-submounts",
            *acl_opt,
            *readonly_opt,
            f"--socket-path={self.sock}",
            f"--shared-dir={path}",
            "--sandbox=none",
            f"--cache={cache}",
        ]
        try:
            # Do not let the daemon share the terminal's stdin and foreground
            # process group: an interactive Ctrl-C meant for QEMU must not kill
            # virtiofsd before the guest shuts down cleanly. Keep it in the
            # same session (no setsid) and make it die with vng, even when vng
            # is killed and cannot run its exit handlers. preexec_fn is safe
            # here: no other thread runs yet, and _die_with_parent() only
            # calls prctl() and getppid() in the child.
            self.proc = subprocess.Popen(  # pylint: disable=W1509
                virtiofsd_cmd,
                stdin=subprocess.DEVNULL,
                stderr=stderr,
                process_group=0,
                preexec_fn=_die_with_parent(),
            )
        except OSError:
            # The caller expects a graceful fallback to 9p, not an
            # exception (e.g. a fork failure under a low process limit).
            self._report_9p_fallback(verbose)
            return False
        # Poll for the socket every 10ms, up to a total of 3.1 seconds
        deadline = monotonic() + 3.1
        waiting_logged = False
        while not self._is_socket(self.sock):
            remaining = deadline - monotonic()
            if remaining <= 0 or self.proc.poll() is not None:
                self._report_9p_fallback(verbose)
                return False
            if verbose and not waiting_logged:
                sys.stderr.write("virtme: waiting for virtiofsd to start\n")
                waiting_logged = True
            sleep(min(0.01, remaining))
        # The socket path shows up at bind() time: a daemon that exits right
        # after creating it must not be mistaken for a ready one.
        if self.proc.poll() is not None:
            self._report_9p_fallback(verbose)
            return False
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
