"""vng stdin/stdout/stderr redirection tests using a user-supplied kernel image.

Run from the repository root:
    VIRTME_TEST_KERNEL=/path/to/bzImage python -m unittest discover -s tests -p test_script_io.py -v

The tests do not build a kernel or automatically select the host's kernel.
The image must match the host CPU architecture and support virtiofs or 9p.
Requires QEMU. Tests are skipped when VIRTME_TEST_KERNEL is unset.
"""

import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from virtme_ng.utils import STDERR_FILENO, STDIN_FILENO, STDOUT_FILENO

ROOT = Path(__file__).resolve().parents[1]
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
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            with subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL if input_data is None else subprocess.PIPE,
                stdout=out if files else subprocess.PIPE,
                stderr=subprocess.STDOUT
                if merged
                else (err if files else subprocess.PIPE),
                start_new_session=True,
            ) as process:
                try:
                    stdout, stderr = process.communicate(input=input_data, timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = process.communicate()
                    self.fail(f"script I/O hung:\n{stdout!r}\n{stderr!r}")
                if files:
                    out.seek(0)
                    err.seek(0)
                    stdout, stderr = out.read(), err.read()
                self.assertEqual(process.returncode, 7, (stdout, stderr))
        return stdout, stderr or b""

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

    def test_normal_file_and_merged_redirection(self):
        for shell_init in (False, True):
            for files, merged in ((True, False), (False, True)):
                with self.subTest(shell_init=shell_init, files=files, merged=merged):
                    stdout, stderr = self.run_guest(
                        shell_init=shell_init,
                        files=files,
                        merged=merged,
                    )
                    if merged:
                        # QEMU drains the stdout and stderr virtio ports
                        # independently; their merged arrival order can vary.
                        self.assertCountEqual(
                            stdout.splitlines(keepends=True),
                            [b"SCRIPT_STDOUT\n", b"SCRIPT_STDERR\n"],
                        )
                    else:
                        self.assertEqual(stdout, b"SCRIPT_STDOUT\n")
                    self.assertEqual(stderr, b"" if merged else b"SCRIPT_STDERR\n")

    def test_normal_direct_dev_writes(self):
        for shell_init in (False, True):
            with self.subTest(shell_init=shell_init):
                stdout, stderr = self.run_guest(
                    shell_init=shell_init,
                    script="printf 'DIRECT_OUT\\n' >/dev/stdout; printf 'DIRECT_ERR\\n' >/dev/stderr; "
                    + SCRIPT,
                )
                # Direct /dev/stdout and /dev/stderr writes use additional
                # virtio ports, so they can also arrive in either order.
                self.assertCountEqual(
                    stdout.splitlines(keepends=True),
                    [b"DIRECT_OUT\n", b"SCRIPT_STDOUT\n"],
                )
                self.assertCountEqual(
                    stderr.splitlines(keepends=True),
                    [b"DIRECT_ERR\n", b"SCRIPT_STDERR\n"],
                )


if __name__ == "__main__":
    unittest.main()
