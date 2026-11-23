"""vng stdin/stdout/stderr redirection tests using a user-supplied kernel image.

Run from the repository root:
    VIRTME_TEST_KERNEL=/path/to/bzImage python -m unittest discover -s tests -p test_script_io.py -v

The tests do not build a kernel or automatically select the host's kernel.
The image must match the host CPU architecture and support virtiofs or 9p.
Requires QEMU. Tests are skipped when VIRTME_TEST_KERNEL is unset.
"""

import hashlib
import os
import pwd
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from virtme_ng.utils import STDERR_FILENO, STDIN_FILENO, STDOUT_FILENO

ROOT = Path(__file__).resolve().parents[1]
# OSC and CSI escape sequences, e.g. the terminal integration markers that
# su on Ubuntu wraps the session in (OSC 3008 start/end): they have no
# newline of their own and would glue themselves to output lines.
ANSI_ESCAPES = re.compile(
    rb"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-9;?]*[ -/]*[@-~]|[@-Z\\-_])"
)
# The stdio modes the matrix tests exercise: the plain virtio-serial
# ports, and the console fallback for when the script I/O ports are
# unavailable (host stdin is not accessible).
STDIO_MODES = (
    ("ports", (), None),
    ("console", ("--show-boot-console",), STDIN_FILENO),
)
LAUNCHER = """
import os
import sys
from unittest.mock import patch
from virtme.commands import run

can_access_file = run.can_access_file
def accessible(path):
    if path == '/proc/self/fd/' + os.environ.get('VIRTME_TEST_INACCESSIBLE_FD', ''):
        return False
    return can_access_file(path)

with patch.object(run, 'can_access_file', side_effect=accessible):
    sys.exit(run.main())
"""
SCRIPT = "printf 'SCRIPT_STDOUT\\n'; printf 'SCRIPT_STDERR\\n' >&2; exit 7"
CONSOLE_MARKER = b"VIRTME_TEST_CONSOLE_MARKER"
# Write and drain a controlled console message to test routing independently
# of kernel boot banners, loglevels, and asynchronous printk delivery.
CONSOLE_SCRIPT = (
    "printf 'VIRTME_TEST_CONSOLE_MARKER\\n' >/dev/console; stty -F /dev/console -echo; "
)
# The script-I/O contract, exercised in every stdio mode (see
# test_stdio_modes): terminal presence on stdin/stdout/stderr, stdin
# delivery, stdout/stderr routing, and direct /dev/stdout and /dev/stderr
# writes, which use their own virtio ports because virtio-serial allows a
# single writer per port. Before exiting,
# the script drains the console: poweroff does not wait for it, and output
# still in the UART transmit buffer would be lost (see
# test_fallback_boot_console_options for the same constraint).
DRAIN_CONSOLE = """python3 -c 'import os, termios
try:
    termios.tcdrain(os.open("/dev/console", os.O_WRONLY))
except OSError:
    pass'
"""
MATRIX_SCRIPT = (
    """if test -t 0 && test -t 1 && test -t 2; then printf 'IS_TTY\\n'; else printf 'NO_TTY\\n'; fi
line=NONE
i=0
while [ "$i" -lt 16 ] && [ "$line" != 'payload' ]; do
    i=$((i+1))
    IFS= read -r line || line=EOF
done
printf 'READ:%s\\n' "$line"
printf 'SCRIPT_STDOUT\\n'
printf 'SCRIPT_STDERR\\n' >&2
printf 'DIRECT_OUT\\n' >/dev/stdout
printf 'DIRECT_ERR\\n' >/dev/stderr
"""
    + DRAIN_CONSOLE
    + """exit 7"""
)
# The same contract run as an unprivileged user, plus the terminal ioctls
# such a user must not get away with: TIOCSTI injects input into the
# terminal's input queue (the classic escalation against privileged
# processes on the same terminal), TIOCLINUX (TIOCL_PASTESEL) pastes the
# selection buffer into the console input queue. Host stdin is at EOF:
# the virtio port reports it, while the serial console has no EOF
# notion, so the read there must time out rather than hang or see EOF.
# The whole probe is a single python3 -c to keep the script small: it
# travels base64-encoded in virtme.exec= on the kernel command line,
# which the kernel silently truncates past COMMAND_LINE_SIZE.
# Like DRAIN_CONSOLE, the script drains the console before exiting, but
# through its own stdout: /dev/console is root-owned mode 0600, and this
# runs as the unprivileged user. In console mode the script's stdout is
# the console device itself (the only mode that needs the drain: the
# init implementations chown it to the user), and in ports mode it is a
# virtio port, where tcdrain fails with ENOTTY and no drain is needed.
USER_MATRIX_SCRIPT = """python3 -c 'import fcntl, os, select, sys, termios
def out(m):
    print(m, flush=True)
out("SCRIPT_STDOUT")
print("SCRIPT_STDERR", file=sys.stderr, flush=True)
open("/dev/stdout", "w").write("DIRECT_OUT\\n")
open("/dev/stderr", "w").write("DIRECT_ERR\\n")
out("IS_TTY" if all(os.isatty(f) for f in (0, 1, 2)) else "NO_TTY")
if select.select([sys.stdin], [], [], 3)[0]:
    out("READ:" + (sys.stdin.readline().rstrip("\\n") or "EOF"))
else:
    out("READ:TIMEOUT")
try:
    legacy = open("/proc/sys/dev/tty/legacy_tiocsti").read().strip()
except OSError:
    legacy = "ABSENT"
out("LEGACY_TIOCSTI:" + legacy)
def probe(name, fn):
    try:
        fn()
        out(name + ":SUCCEEDED")
    except OSError as e:
        out(name + ":ERR%d" % e.errno)
probe("TIOCSTI", lambda: fcntl.ioctl(0, 0x5412, b"x"))
probe("TIOCLINUX", lambda: fcntl.ioctl(0, 0x541C, bytearray(b"\\x03\\x00")))
def tty1():
    fd = os.open("/dev/tty1", os.O_RDONLY)
    try:
        fcntl.ioctl(fd, 0x541C, bytearray(b"\\x03\\x00"))
    finally:
        os.close(fd)
probe("TTY1_TIOCLINUX", tty1)
try:
    termios.tcdrain(sys.stdout.fileno())
except OSError:
    pass'
exit 7"""
# Consume all of stdin and print its MD5, so bulk stdin can be checked for
# truncation and corruption (see test_large_input): md5sum reads stdin when
# given no file argument and prints "hash -", of which set -- keeps the
# hash as $1.
LARGE_INPUT_SCRIPT = "set -- $(md5sum); printf 'MD5:%s\\n' \"$1\"; exit 7"


@unittest.skipUnless(os.environ.get("VIRTME_TEST_KERNEL"), "VIRTME_TEST_KERNEL not set")
class ScriptIOTests(unittest.TestCase):
    def run_guest(
        self,
        *,
        flags=(),
        shell_init=False,
        inaccessible=None,
        input_data=None,
        files=False,
        merged=False,
        script=SCRIPT,
        microvm=False,
        input_after=None,
    ):
        command = [
            sys.executable,
            "-c",
            LAUNCHER,
            "--mods",
            "auto",
            "--kimg",
            os.environ["VIRTME_TEST_KERNEL"],
            "--cpus",
            "2",
            "--memory",
            "1G",
            "--script-sh",
            script,
            *flags,
        ]
        if not microvm:
            command.append("--disable-microvm")
        if shell_init:
            command.append("--no-virtme-ng-init")
        env = dict(
            os.environ,
            VIRTME_TEST_INACCESSIBLE_FD=str(inaccessible)
            if inaccessible is not None
            else "",
        )
        if input_after is not None:
            # The gated run handles the streams itself, always as pipes:
            # files and merged would be silently dropped rather than
            # applied to the host-side redirection. A raise, not an
            # assert: the guard must survive python -O.
            if files or merged:
                raise ValueError("gated input cannot combine with files or merged")
            return self._run_with_gated_input(command, env, input_data, input_after)
        # Host stdin: a bytes payload goes through a pipe that
        # communicate() writes; an open binary file is handed to the
        # launcher as its stdin itself (regular-file stdin, read from its
        # current offset); None leaves stdin at /dev/null.
        if input_data is None:
            stdin = subprocess.DEVNULL
        elif isinstance(input_data, bytes):
            stdin = subprocess.PIPE
        else:
            stdin = input_data
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            with subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdin=stdin,
                stdout=out if files else subprocess.PIPE,
                stderr=subprocess.STDOUT
                if merged
                else (err if files else subprocess.PIPE),
                start_new_session=True,
            ) as process:
                try:
                    stdout, stderr = process.communicate(
                        input=input_data if isinstance(input_data, bytes) else None,
                        timeout=30,
                    )
                except subprocess.TimeoutExpired:
                    self._kill_group(process)
                    stdout, stderr = process.communicate()
                    self.fail(f"script I/O hung:\n{stdout!r}\n{stderr!r}")
                if files:
                    out.seek(0)
                    err.seek(0)
                    stdout, stderr = out.read(), err.read()
                self.assertEqual(process.returncode, 7, (stdout, stderr))
        return stdout, stderr or b""

    @staticmethod
    def _kill_group(process):
        # Only call while the child is unreaped: after process.wait() its
        # pid could have been recycled into an unrelated process group.
        # The group may also be gone already in the window between the
        # timeout and the signal; keep the diagnostic either way.
        assert process.returncode is None
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    @staticmethod
    def _exited(process):
        # Whether the launcher has exited, without reaping it: as a zombie
        # it keeps pinning its pid, and with it the process group, so
        # _kill_group stays safe however long the streams take to close.
        return (
            os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            is not None
        )

    def _run_with_gated_input(self, command, env, input_data, marker):
        """Run the guest like run_guest, but hold input_data back until
        MARKER shows up on its stdout: input written before the guest's
        console is up is lost to the UART resets of the early boot.
        stdout and stderr are drained in the same loop, or the guest
        would block on them."""
        # input_data must be a bytes payload - None, or one of the open
        # files run_guest also accepts, would make the gated write below
        # raise a TypeError that escapes the draining loop, skipping the
        # timeout diagnostics. A raise, not an assert: the guard must
        # survive python -O.
        if not isinstance(input_data, bytes):
            raise TypeError("gated input requires a bytes payload")
        with subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ) as process:
            stdout_buf, stderr_buf = bytearray(), bytearray()
            # Each still-open stream maps to the buffer of what it has
            # produced; a stream leaves the map on EOF, but what arrived
            # stays in its buffer.
            streams = {process.stdout: stdout_buf, process.stderr: stderr_buf}
            input_sent = False
            # The guest must exit within the deadline. Once it has, the
            # pipes must still close: a detached child of the launcher
            # (e.g. virtiofsd) can keep them open past its exit, and
            # without EOF there is no way to tell drained output from
            # output still in flight, so bound that wait separately
            # instead of hanging the test run.
            deadline = time.monotonic() + 30
            eof_deadline = None
            # The launcher's exit is polled unreaped (see _exited), so on
            # failure its whole group can still be killed: whatever keeps
            # the streams open past the launcher's exit must not outlive
            # the failure into the later guest boots of the matrix.
            exited = False
            while streams or not exited:
                if not exited and self._exited(process):
                    exited = True
                    eof_deadline = time.monotonic() + 10
                    if not streams:
                        # Both streams are at EOF and the launcher has
                        # exited: skip the final poll slice, which has
                        # nothing left to wait for.
                        break
                timeout = (eof_deadline or deadline) - time.monotonic()
                if timeout <= 0:
                    self._kill_group(process)
                    process.wait()
                    why = (
                        "script I/O hung"
                        if eof_deadline is None
                        else "script I/O streams still open after the guest exited"
                    )
                    self.fail(f"{why}:\n{bytes(stdout_buf)!r}\n{bytes(stderr_buf)!r}")
                # Poll in bounded slices to notice the guest exiting (and
                # with it the switch to the bounded EOF wait) promptly.
                # select() on an empty fd list sleeps out the timeout
                # instead of returning, so waiting for the launcher's exit
                # with both streams at EOF stays a sleep, not a spin.
                readable, _, _ = select.select(
                    [stream.fileno() for stream in streams],
                    [],
                    [],
                    min(timeout, 0.5),
                )
                for stream in list(streams):
                    if stream.fileno() not in readable:
                        continue
                    chunk = os.read(stream.fileno(), 4096)
                    if chunk:
                        streams[stream] += chunk
                    else:
                        stream.close()
                        del streams[stream]
                if not input_sent and marker in stdout_buf:
                    input_sent = True
                    # input_data is well under the pipe capacity, so the
                    # write cannot block the draining loop. Close stdin
                    # even on error: the guest must see EOF rather than
                    # hang until the timeout.
                    try:
                        process.stdin.write(input_data)
                    except OSError:
                        pass
                    finally:
                        try:
                            process.stdin.close()
                        except OSError:
                            pass
            process.wait()
            self.assertEqual(
                process.returncode, 7, (bytes(stdout_buf), bytes(stderr_buf))
            )
            return bytes(stdout_buf), bytes(stderr_buf) or b""

    @staticmethod
    def _text(stream):
        # Normalize output for comparison: strip escape sequences that can
        # glue themselves to output lines, and the CRLF line endings of
        # pty and console output.
        return ANSI_ESCAPES.sub(b"", stream).replace(b"\r\n", b"\n")

    @classmethod
    def _lines(cls, stream):
        return cls._text(stream).splitlines()

    @staticmethod
    def _expected_lines(mode, read):
        """The stdout/stderr line lists of the stdio contract; READ is the
        stdin outcome (READ:payload, READ:EOF or READ:TIMEOUT)."""
        out = [
            b"IS_TTY" if mode == "console" else b"NO_TTY",
            read,
            b"SCRIPT_STDOUT",
        ]
        if mode == "console":
            # Everything, including /dev/stdout and /dev/stderr, is merged
            # on the console.
            return out + [b"SCRIPT_STDERR", b"DIRECT_OUT", b"DIRECT_ERR"], []
        # Direct /dev/stdout and /dev/stderr writes keep their own ports.
        return out + [b"DIRECT_OUT"], [b"SCRIPT_STDERR", b"DIRECT_ERR"]

    def _assert_mode_output(self, mode, stdout, stderr, read, exact=True):
        """Assert the MATRIX_SCRIPT output contract in one stdio mode; READ
        is the stdin outcome (READ:payload, READ:EOF or READ:TIMEOUT).
        With EXACT in the ports mode, stdout and stderr must be exactly
        the expected lines; everything else - the console mode, where
        kernel printk and tty echo can glue themselves to script output
        lines, and the unprivileged matrix script, which prints extra
        probe lines - is matched as substrings instead."""
        expected_out, expected_err = self._expected_lines(mode, read)
        if exact and mode == "ports":
            # stdout and stderr stay separate, on their own ports.
            self.assertCountEqual(self._lines(stdout), expected_out)
            self.assertCountEqual(self._lines(stderr), expected_err)
            return
        # Match as substrings of the unsplit output: on the console,
        # kernel printk or tty echo can glue themselves to script output
        # lines.
        for line in expected_out:
            self.assertIn(line, self._text(stdout))
        err = self._text(stderr)
        for line in expected_err:
            self.assertIn(line, err)
        if mode == "console":
            # Everything, including /dev/stdout and /dev/stderr, is merged
            # on the console: stderr must have nothing of it.
            self.assertNotIn(b"SCRIPT_STDERR", err)
            self.assertNotIn(b"DIRECT_ERR", err)

    def test_fallback_preserves_raw_stdout_with_stdin_eof(self):
        # Host stdin EOF used to disconnect stdout's stdio-backed port.
        # Assert bytes, not text with newline translation: a console fallback
        # would add boot messages and CRLF and incorrectly merge stderr.
        for shell_init in (False, True):
            for flags in ((), ("--verbose",), ("--fast-boot",)):
                for files in (False, True):
                    with self.subTest(shell_init=shell_init, flags=flags, files=files):
                        stdout, stderr = self.run_guest(
                            shell_init=shell_init,
                            flags=flags,
                            files=files,
                            inaccessible=STDIN_FILENO,
                        )
                        self.assertEqual(stdout, b"SCRIPT_STDOUT\n")
                        self.assertIn(b"falling back to limited redirection", stderr)
                        self.assertNotIn(b"SCRIPT_STDERR", stderr)

    def test_fallback_for_each_inaccessible_fd(self):
        for fd in (STDIN_FILENO, STDOUT_FILENO, STDERR_FILENO):
            for input_data in (None, b"unused input\n"):
                with self.subTest(fd=fd, input_data=input_data):
                    stdout, _ = self.run_guest(inaccessible=fd, input_data=input_data)
                    self.assertEqual(stdout, b"SCRIPT_STDOUT\n")

    def test_fallback_large_output(self):
        for files in (False, True):
            with self.subTest(files=files):
                stdout, _ = self.run_guest(
                    inaccessible=STDIN_FILENO,
                    files=files,
                    script="head -c 1048576 /dev/zero; exit 7",
                )
                self.assertEqual(stdout, bytes(1048576))

    def test_microvm_streams(self):
        for shell_init in (False, True):
            for inaccessible in (None, STDIN_FILENO):
                with self.subTest(shell_init=shell_init, inaccessible=inaccessible):
                    stdout, stderr = self.run_guest(
                        microvm=True,
                        shell_init=shell_init,
                        inaccessible=inaccessible,
                    )
                    self.assertEqual(stdout, b"SCRIPT_STDOUT\n")
                    if inaccessible is None:
                        self.assertEqual(stderr, b"SCRIPT_STDERR\n")
                    else:
                        self.assertIn(b"falling back to limited redirection", stderr)

    def test_fallback_boot_console_options(self):
        for shell_init in (False, True):
            for flags in (
                ("--show-boot-console",),
                ("--show-boot-console", "--verbose"),
            ):
                with self.subTest(shell_init=shell_init, flags=flags):
                    stdout, stderr = self.run_guest(
                        shell_init=shell_init,
                        flags=flags,
                        inaccessible=STDIN_FILENO,
                        # Drain the console before poweroff: this checks I/O
                        # routing independently of the existing console
                        # teardown's ability to flush the final output.
                        script=CONSOLE_SCRIPT
                        + SCRIPT.replace("exit 7", "stty -echo; exit 7"),
                    )
                    self.assertIn(b"SCRIPT_STDOUT\r\n", stdout)
                    self.assertIn(b"SCRIPT_STDERR\r\n", stdout)
                    self.assertIn(CONSOLE_MARKER, stdout)
                    self.assertNotIn(CONSOLE_MARKER, stderr)
                    self.assertNotIn(b"SCRIPT_STDERR", stderr)

    def test_normal_streams_and_input(self):
        for shell_init in (False, True):
            for flags in (
                (),
                ("--verbose",),
                ("--show-boot-console",),
                ("--show-boot-console", "--verbose"),
            ):
                for input_data in (None, b"payload\n"):
                    with self.subTest(
                        shell_init=shell_init, flags=flags, input_data=input_data
                    ):
                        script = (
                            CONSOLE_SCRIPT
                            + "IFS= read -r line || line=EOF; printf 'READ:%s\\n' \"$line\"; "
                            + SCRIPT
                        )
                        stdout, stderr = self.run_guest(
                            shell_init=shell_init,
                            flags=flags,
                            input_data=input_data,
                            script=script,
                        )
                        value = b"EOF" if input_data is None else b"payload"
                        self.assertEqual(
                            stdout, b"READ:" + value + b"\nSCRIPT_STDOUT\n"
                        )
                        self.assertIn(b"SCRIPT_STDERR\n", stderr)
                        self.assertNotIn(b"falling back", stderr)
                        self.assertEqual(
                            CONSOLE_MARKER in stderr, "--show-boot-console" in flags
                        )

    def test_stdio_modes(self):
        # The script-I/O contract of every stdio mode, as root:
        # - ports: the plain virtio-serial ports, not terminals; stdout and
        #   stderr stay separate, on their own ports;
        # - console: the script I/O ports are unavailable (host stdin is
        #   not accessible), so the script runs on the serial console and
        #   everything, including /dev/stdout and /dev/stderr, is merged.
        # Completing under the timeout is itself part of the contract.
        for shell_init in (False, True):
            for mode, flags, inaccessible in STDIO_MODES:
                with self.subTest(shell_init=shell_init, mode=mode):
                    stdout, stderr = self.run_guest(
                        script=MATRIX_SCRIPT,
                        flags=flags,
                        inaccessible=inaccessible,
                        input_data=b"payload\n",
                        # The console mode gates the input on the script's
                        # first output line: input written before the
                        # guest's console is up is lost to the UART resets
                        # of the early boot.
                        input_after=b"IS_TTY" if mode == "console" else None,
                        shell_init=shell_init,
                    )
                    self._assert_mode_output(mode, stdout, stderr, b"READ:payload")

    def test_stdio_modes_merged_output(self):
        # Host-side merged redirection: QEMU drains the stdout and stderr
        # virtio ports independently; their merged arrival order can vary.
        for shell_init in (False, True):
            with self.subTest(shell_init=shell_init):
                stdout, stderr = self.run_guest(
                    script=MATRIX_SCRIPT,
                    input_data=b"payload\n",
                    shell_init=shell_init,
                    merged=True,
                )
                expected_out, expected_err = self._expected_lines(
                    "ports", b"READ:payload"
                )
                self.assertCountEqual(self._lines(stdout), expected_out + expected_err)
                self.assertEqual(stderr, b"")

    def test_stdio_modes_file_output(self):
        # Host stdout and stderr as regular files: the direct /dev/stdout
        # and /dev/stderr writes go through chardevs that open the same
        # file as the script's own stdout and stderr.
        for shell_init in (False, True):
            with self.subTest(shell_init=shell_init):
                stdout, stderr = self.run_guest(
                    script=MATRIX_SCRIPT,
                    input_data=b"payload\n",
                    shell_init=shell_init,
                    files=True,
                )
                self._assert_mode_output("ports", stdout, stderr, b"READ:payload")

    def test_stdio_modes_file_input(self):
        # Host stdin as a regular file, with and without payload: the stdio
        # chardev reads it like any other stdin and reports EOF once it is
        # exhausted — an empty file is an immediate EOF, like /dev/null.
        # Console mode has no file-stdin variant: it requires host stdin to
        # be inaccessible (see STDIO_MODES).
        for payload in (b"payload\n", b""):
            for files in (False, True):
                for shell_init in (False, True):
                    with self.subTest(
                        payload=payload, files=files, shell_init=shell_init
                    ):
                        with tempfile.TemporaryFile() as input_file:
                            input_file.write(payload)
                            input_file.seek(0)
                            stdout, stderr = self.run_guest(
                                script=MATRIX_SCRIPT,
                                input_data=input_file,
                                files=files,
                                shell_init=shell_init,
                            )
                        self._assert_mode_output(
                            "ports",
                            stdout,
                            stderr,
                            b"READ:payload" if payload else b"READ:EOF",
                        )

    def test_large_input(self):
        # 1 MiB of stdin through the virtio port, well over the pipe
        # capacity: the host must apply backpressure — communicate() can
        # only keep writing as the guest drains — rather than deadlock or
        # drop data, and the checksum must catch truncation and corruption.
        # Ports only: console mode cannot carry ungated input (early bytes
        # are lost to the boot UART resets), and gated input assumes input
        # well under the pipe capacity.
        payload = b"payload\n" * 131072  # 1 MiB
        expected = b"MD5:" + hashlib.md5(payload).hexdigest().encode() + b"\n"
        for files in (False, True):
            for shell_init in (False, True):
                with self.subTest(files=files, shell_init=shell_init):
                    stdout, _ = self.run_guest(
                        script=LARGE_INPUT_SCRIPT,
                        input_data=payload,
                        files=files,
                        shell_init=shell_init,
                    )
                    self.assertEqual(stdout, expected)

    @unittest.skipIf(os.getuid() == 0, "requires an unprivileged invoking user")
    def test_stdio_modes_as_user(self):
        # The guest uses the host rootfs, so the invoking user (with a
        # working login shell, unlike e.g. nobody) is the readily available
        # unprivileged user to run the script as. Resolved lazily: at
        # module level a missing passwd entry would break every test in
        # this module; here it only skips this one.
        try:
            user = pwd.getpwuid(os.getuid()).pw_name
        except KeyError:
            self.skipTest(f"no passwd entry for uid {os.getuid()}")
        # The same modes as an unprivileged user: this covers the su path,
        # the chown of the script I/O ports, and the terminal ioctls the
        # script must not get away with. Host stdin is at EOF: the virtio
        # port reports it, while the serial console has no EOF notion, so
        # the read there must time out rather than hang.
        for shell_init in (False, True):
            for mode, flags, inaccessible in STDIO_MODES:
                with self.subTest(shell_init=shell_init, mode=mode):
                    stdout, stderr = self.run_guest(
                        script=USER_MATRIX_SCRIPT,
                        flags=(*flags, "--user", user),
                        inaccessible=inaccessible,
                        shell_init=shell_init,
                    )
                    self._assert_mode_output(
                        mode,
                        stdout,
                        stderr,
                        b"READ:EOF" if mode == "ports" else b"READ:TIMEOUT",
                        exact=False,
                    )
                    out = self._text(stdout)
                    # The terminal ioctls must not succeed for the
                    # unprivileged script: on the virtio ports they are not
                    # even terminals (ENOTTY), and neither is the pty or
                    # the serial console a VT for TIOCLINUX. With legacy
                    # TIOCSTI disabled (the default since v6.10; older
                    # kernels permit it by design) the kernel must reject
                    # the injection with EIO.
                    self.assertNotIn(b"TIOCLINUX:SUCCEEDED", out)
                    self.assertNotIn(b"TTY1_TIOCLINUX:SUCCEEDED", out)
                    # ENOTTY: the virtio ports are not terminals at
                    # all, and the serial console (like a pty) is no VT
                    # for TIOCLINUX. TIOCSTI on a real terminal is
                    # rejected with EIO instead (asserted below).
                    self.assertIn(b"TIOCLINUX:ERR25", out)
                    if mode == "ports":
                        self.assertIn(b"TIOCSTI:ERR25", out)
                    elif b"LEGACY_TIOCSTI:0" in out:
                        # TIOCSTI injection must fail with EIO.
                        self.assertIn(b"TIOCSTI:ERR5", out)
                        self.assertNotIn(b"TIOCSTI:SUCCEEDED", out)
                    else:
                        # Legacy TIOCSTI is permitted by design here (the
                        # sysctl is enabled, or the kernel predates the
                        # restriction and reports no sysctl at all): the
                        # kernel sanctions the injection into the
                        # script's own terminal, so there is nothing to
                        # enforce. Only make sure the probe concluded, so
                        # this gap stays visible rather than silent. Match
                        # unanchored, like the other assertions: console
                        # noise can glue itself to the result line.
                        self.assertTrue(
                            re.search(rb"TIOCSTI:(SUCCEEDED|ERR\d+)", out),
                            out,
                        )


if __name__ == "__main__":
    unittest.main()
