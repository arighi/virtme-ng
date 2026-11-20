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

_VIRTIOFSD_PATH: dict[tuple[str, str | None], str | None] = {}
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
        # Without the parent-death signal, the daemon would survive a
        # SIGKILLed virtme-run: do not exec it then. prctl() returns -1 on
        # error.
        if prctl(_PR_SET_PDEATHSIG, signal.SIGTERM) != 0:
            os._exit(1)
        # The parent may have died before the prctl() call took effect.
        if os.getppid() != parent_pid:
            os._exit(1)

    return preexec


class VirtioFSConfig:
    def __init__(
        self,
        path: str,
        mount_tag: str,
        *,
        rw: bool = False,
        posix_acl: bool = False,
        translate_uid: int | None = None,
        translate_gid: int | None = None,
    ):
        self.path = path
        self.mount_tag = mount_tag
        self.rw = rw
        self.posix_acl = posix_acl
        # A non-None id means "translate the guest root to it": 0 would be
        # the identity (the guest root already has root's uid/gid), so it
        # is normalized away and carries no instruction.
        self.translate_uid = translate_uid if translate_uid != 0 else None
        self.translate_gid = translate_gid if translate_gid != 0 else None

    @property
    def readonly(self) -> bool:
        # The readonly export mode is just the absence of rw.
        return not self.rw


class VirtioFSState:
    def __init__(
        self,
        guest_tools_path,
        memory=None,
        memory_configured=False,
        virtiofsd_path=None,
    ):
        self.guest_tools_path = guest_tools_path
        self.memory = memory
        self.memory_configured = memory_configured
        self.virtiofsd_path = virtiofsd_path


class VirtioFS:
    def __init__(self, guest_tools_path, virtiofsd_path=None):
        self.sock = None
        self.proc = None
        self.guest_tools_path = guest_tools_path
        self.virtiofsd_path = virtiofsd_path

    def shutdown(self):
        # Make sure to stop virtiofsd instances that are still potentially
        # running: ask for a graceful shutdown first (SIGTERM), then kill.
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Graceful shutdown timed out: fall back to SIGKILL. Even
                # that may fail (an unreapable daemon, a missing permission);
                # shutting down must never abort the VM launch/exit path.
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=5)
                except (subprocess.TimeoutExpired, PermissionError):
                    pass
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

    def is_virtiofsd_available(self) -> bool:
        """Tell whether a usable virtiofsd binary is installed.

        start() returns False for both missing binaries and daemon launch
        failures; this helper checks binary availability upfront without
        attempting to start the daemon.
        """
        return self._get_virtiofsd_path() is not None

    def _get_virtiofsd_path(self):
        cache_key = (self.guest_tools_path, self.virtiofsd_path)
        if cache_key in _VIRTIOFSD_PATH:
            return _VIRTIOFSD_PATH[cache_key]

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
        #
        # An explicitly requested daemon is the only candidate: silently
        # using a different one would be surprising.
        if self.virtiofsd_path is not None:
            possible_paths = (self.virtiofsd_path,)
        else:
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
                    _VIRTIOFSD_PATH[cache_key] = path
                    return path
                except (subprocess.CalledProcessError, OSError):
                    pass
        if self.virtiofsd_path is not None:
            sys.stderr.write(
                f"virtme-run: '{self.virtiofsd_path}' is not a usable virtiofsd\n"
            )
        _VIRTIOFSD_PATH[cache_key] = None
        return None

    @staticmethod
    def _is_socket(path):
        # The owner is checked as well: the path is visible in /proc/*/cmdline,
        # so a local user could read it there and bind a socket of their own
        # at it, in the window between the removal of the temp file and the
        # daemon's bind(). The daemon would fail to bind, while QEMU was
        # connected to the imposter.
        try:
            st = os.stat(path)
            return stat.S_ISSOCK(st.st_mode) and st.st_uid == os.geteuid()
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

    @staticmethod
    def may_translate_owner(owner: tuple[int, int]) -> bool:
        """Return True if the current user is allowed to translate to OWNER.

        This is a permission check: an unprivileged virtiofsd can only act
        as the invoking user, so the uid has to be the invoking user's and
        the gid one of the invoking user's groups, its primary one or a
        supplementary one (a 0 component is not translated at all).
        Running as root (e.g. through sudo), the privileged virtiofsd can
        act as any user.
        """
        if os.getuid() == 0:
            return True
        owner_uid, owner_gid = owner
        if owner_uid not in (0, os.getuid()):
            return False
        # The daemon can act as any group the invoking user belongs to,
        # also as a supplementary one.
        return owner_gid in (0, os.getgid(), *os.getgroups())

    def _report_9p_fallback(self, verbose, uid_mapped=False):
        # A lost UID mapping changes what the guest sees, so it is announced
        # unconditionally.
        if verbose or uid_mapped:
            sys.stderr.write("virtme-run: failed to start virtiofsd, fallback to 9p\n")
        if uid_mapped:
            sys.stderr.write(
                "virtme-run: the guest root is not mapped to the rootfs owner\n"
            )

    def start(self, config: VirtioFSConfig, verbose=True):
        translate_opt = []
        has_translation = (
            config.translate_uid is not None or config.translate_gid is not None
        )

        virtiofsd_path = self._get_virtiofsd_path()
        if virtiofsd_path is None:
            self._report_9p_fallback(verbose, uid_mapped=has_translation)
            return False

        # virtiofsd located, try to start the daemon as non-privileged user.
        sock_fd, self.sock = tempfile.mkstemp(prefix="virtme", suffix=".sock")
        os.close(sock_fd)

        # Make sure to clean up before starting the daemon and at exit.
        self.shutdown()
        atexit.register(self.shutdown)

        # Export the whole root fs of the host, do not enable sandbox, otherwise we
        # would get permission errors.
        if verbose:
            stdout = stderr = None
        else:
            stdout = stderr = subprocess.DEVNULL
        # Only enable --posix-acl when using an external root filesystem.
        # When sharing the host root (/), --posix-acl breaks UID/GID translation
        # which causes authentication failures (e.g., unix_chkpwd cannot obtain
        # user info).
        acl_opt = ["--posix-acl"] if config.posix_acl else []
        if has_translation:
            wanted = []
            if config.translate_uid is not None:
                wanted.append(("--translate-uid", config.translate_uid))
            if config.translate_gid is not None:
                wanted.append(("--translate-gid", config.translate_gid))

            if not all(self._supports_flag(virtiofsd_path, flag) for flag, _ in wanted):
                missing = "/".join(
                    flag
                    for flag, _ in wanted
                    if not self._supports_flag(virtiofsd_path, flag)
                )
                sys.stderr.write(
                    f"virtme-run: virtiofsd does not support {missing}; "
                    "the guest root is not mapped to the rootfs owner\n"
                )
            else:
                # UID/GID translation cannot be combined with POSIX ACLs:
                # drop them in this case.
                if acl_opt:
                    sys.stderr.write(
                        "virtme-run: disabling POSIX ACLs for UID/GID translation\n"
                    )
                    acl_opt = []
                translate_opt = [f"{flag}=map:0:{target}:1" for flag, target in wanted]
                parts = []
                if config.translate_uid is not None:
                    parts.append(f"uid {config.translate_uid}")
                if config.translate_gid is not None:
                    parts.append(f"gid {config.translate_gid}")
                sys.stderr.write(
                    f"virtme-run: mapping guest root to the owner of the "
                    f"rootfs ({', '.join(parts)})\n"
                )
        readonly_opt = (
            ["--readonly"]
            if config.readonly and self._supports_readonly(virtiofsd_path)
            else []
        )
        virtiofsd_cmd = [
            virtiofsd_path,
            "--syslog",
            "--no-announce-submounts",
            *acl_opt,
            *translate_opt,
            *readonly_opt,
            f"--socket-path={self.sock}",
            f"--shared-dir={config.path}",
            "--sandbox=none",
            f"--cache={'auto' if config.rw else 'always'}",
        ]
        try:
            # Do not let the daemon share the terminal's stdin and foreground
            # process group: an interactive Ctrl-C meant for QEMU must not kill
            # virtiofsd before the guest shuts down cleanly. Keep it in the
            # same session (no setsid) and make it die with virtme-run, even
            # when virtme-run is killed and cannot run its exit handlers.
            # preexec_fn is safe
            # here: no other thread runs yet, and _die_with_parent() only
            # calls prctl() and getppid() in the child.
            self.proc = subprocess.Popen(  # pylint: disable=W1509
                virtiofsd_cmd,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                process_group=0,
                preexec_fn=_die_with_parent(),
            )
        except OSError:
            # The caller expects a graceful fallback to 9p, not an
            # exception (e.g. a fork failure under a low process limit).
            self._report_9p_fallback(verbose, bool(translate_opt))
            return False
        # Poll for the socket every 10ms, up to a total of 3.1 seconds
        deadline = monotonic() + 3.1
        waiting_logged = False
        while not self._is_socket(self.sock):
            remaining = deadline - monotonic()
            if remaining <= 0 or self.proc.poll() is not None:
                self._report_9p_fallback(verbose, bool(translate_opt))
                return False
            if verbose and not waiting_logged:
                sys.stderr.write("virtme: waiting for virtiofsd to start\n")
                waiting_logged = True
            sleep(min(0.01, remaining))
        # The socket path shows up at bind() time: a daemon that exits right
        # after creating it must not be mistaken for a ready one.
        if self.proc.poll() is not None:
            self._report_9p_fallback(verbose, bool(translate_opt))
            return False
        return True


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
        # start() is never reached without virtiofs support, so a lost
        # mapping has to be announced here.
        if config.translate_uid is not None or config.translate_gid is not None:
            sys.stderr.write(
                "virtme-run: no virtiofs support on this architecture: "
                "the guest root is not mapped to the rootfs owner\n"
            )
        return False

    # Try to start virtiofsd daemon
    virtio_fs = VirtioFS(state.guest_tools_path, state.virtiofsd_path)
    ret = virtio_fs.start(config, verbose=verbose)
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
