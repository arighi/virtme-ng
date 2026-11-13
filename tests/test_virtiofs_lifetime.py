"""Tests that virtiofsd does not outlive vng, however vng goes away.

vng runs as the session leader of a pty, like in an ssh login session, with a
real virtiofsd. Skipped when no usable virtiofsd is installed.
"""

import collections
import os
import pty
import select
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUEST_TOOLS = str(ROOT / "virtme" / "guest")

# Upper bounds, in seconds, for a healthy run: they only matter when a test
# fails, as the tests do not wait any longer than necessary.
START_TIMEOUT = 10
EXIT_TIMEOUT = 5

# Stands in for vng: run.main() installs the real signal handling, but do_it()
# only exports a directory with virtiofsd and then waits instead of launching
# QEMU. It reports the socket of the daemon.
SESSION_LAUNCHER = """
import fcntl, sys, tempfile, termios, time
from unittest.mock import patch
from virtme.commands import run
from virtme_ng.virtiofs import (
    VirtioFS,
    VirtioFSConfig,
    VirtioFSState,
    export_virtiofs,
)


class Arch:
    def virtiofs_support(self):
        return True

    def vhost_dev_type(self, _dev_type):
        return "vhost-user-fs-pci"

    def numa_support(self):
        return False


# Take the pty (stdin) as controlling terminal as a login session would.
fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def do_it():
    with tempfile.TemporaryDirectory() as shared:
        qemuargs = []
        config = VirtioFSConfig(path=shared, mount_tag="TEST")
        # Only a missing binary is a reason to skip: a daemon that is installed
        # but does not start is a failure.
        if VirtioFS(sys.argv[1])._get_virtiofsd_path() is None:
            print("NO_VIRTIOFSD", flush=True)
            return 1
        if not export_virtiofs(Arch(), qemuargs, VirtioFSState(sys.argv[1]), config):
            print("START_FAILED", flush=True)
            return 1
        # The socket of the daemon is what QEMU gets as its vhost-user chardev.
        sock = next(a for a in qemuargs if a.startswith("socket,"))
        print(sock.split("path=", 1)[1], flush=True)
        time.sleep(60)
    return 0


with patch.object(run, "do_it", do_it):
    sys.exit(run.main())
"""

# How vng went away, and what is left of it.
Outcome = collections.namedtuple("Outcome", "returncode stderr daemon_gone files_left")


def _proc_stat(pid):
    """Return the fields of /proc/PID/stat after the command name, or None."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fd:
            # The command name is parenthesized and may contain anything.
            return fd.read().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None


def _pid_alive(pid):
    fields = _proc_stat(pid)
    # The state is the first field; a zombie is already dead, it just awaits
    # reaping.
    return fields is not None and fields[0] != "Z"


def _start_time(pid):
    # Field 22 of /proc/PID/stat (the 20th after the command name): it tells
    # a process apart from a later one that got the same PID.
    fields = _proc_stat(pid)
    return fields[19] if fields is not None else None


def _is_same_process(pid, start_time):
    """Return whether PID is still the process that started at START_TIME.

    Tells the process apart from an unrelated one that got the same PID after
    it exited.
    """
    return _pid_alive(pid) and _start_time(pid) == start_time


def _wait_until(condition, timeout):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.05)
    return condition()


def _read_daemon_pid(pid_file, vng):
    # virtiofsd itself writes its PID to "<socket>.pid" once it is running.
    # Give up early when vng is gone: the PID will never show up.
    def read():
        try:
            return int(Path(pid_file).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    _wait_until(lambda: read() is not None or vng.poll() is not None, START_TIMEOUT)
    return read()


class VirtiofsdLifetimeTests(unittest.TestCase):
    """virtiofsd must not outlive vng."""

    def run_vng(self, disrupt):
        """Start vng, call DISRUPT(vng, pty_fds) and report what is left."""
        pty_fd, tty_fd = pty.openpty()
        pty_fds = [pty_fd]
        self.addCleanup(lambda: [os.close(fd) for fd in pty_fds])
        try:
            vng = subprocess.Popen(
                [sys.executable, "-c", SESSION_LAUNCHER, GUEST_TOOLS],
                cwd=ROOT,
                stdin=tty_fd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        finally:
            os.close(tty_fd)
        with vng:
            daemon_pid = None
            daemon_start = None
            sock = None
            try:
                ready, _, _ = select.select([vng.stdout], [], [], START_TIMEOUT)
                self.assertTrue(ready, "vng did not start virtiofsd in time")
                line = vng.stdout.readline().decode().strip()
                if not line:
                    # EOF: the launcher died before reporting the daemon.
                    vng.kill()
                    vng.wait()
                    self.fail(f"vng died during startup: {vng.stderr.read().decode()}")
                if line == "NO_VIRTIOFSD":
                    self.skipTest("virtiofsd not available")
                if line == "START_FAILED":
                    self.fail("virtiofsd is installed but vng failed to start it")
                sock = line
                daemon_pid = _read_daemon_pid(f"{sock}.pid", vng)
                self.assertIsNotNone(daemon_pid, "virtiofsd did not start")
                daemon_start = _start_time(daemon_pid)
                self.assertIsNotNone(daemon_start, "virtiofsd is gone already")
                self.assertTrue(_pid_alive(daemon_pid))

                disrupt(vng, pty_fds)
                returncode = vng.wait(timeout=EXIT_TIMEOUT)
                stderr = vng.stderr.read().decode()
                daemon_gone = _wait_until(
                    lambda: not _is_same_process(daemon_pid, daemon_start),
                    EXIT_TIMEOUT,
                )
                files_left = [
                    path for path in (sock, f"{sock}.pid") if os.path.exists(path)
                ]
                return Outcome(returncode, stderr, daemon_gone, files_left)
            finally:
                vng.kill()
                # Never kill a process that merely reuses the daemon's PID.
                if daemon_pid is not None and _is_same_process(
                    daemon_pid, daemon_start
                ):
                    try:
                        os.kill(daemon_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        # It exited since the check above: fine.
                        pass
                for path in (sock, f"{sock}.pid") if sock else ():
                    try:
                        os.remove(path)
                    except OSError:
                        pass

    def test_sigterm_stops_daemon_and_removes_temp_files(self):
        outcome = self.run_vng(lambda vng, _pty_fds: vng.terminate())
        self.assertEqual(outcome.returncode, 1, outcome.stderr)
        self.assertTrue(outcome.daemon_gone, "virtiofsd outlived vng")
        self.assertEqual(outcome.files_left, [])

    def test_ctrl_c_stops_daemon_and_removes_temp_files(self):
        # Ctrl-C: the terminal sends SIGINT to the whole foreground process
        # group, which the daemon is a part of.
        outcome = self.run_vng(lambda vng, _pty_fds: os.killpg(vng.pid, signal.SIGINT))
        self.assertTrue(outcome.daemon_gone, "virtiofsd outlived vng")
        self.assertEqual(outcome.files_left, [])

    def test_ssh_disconnect_stops_daemon(self):
        # The ssh connection drops: the pty is hung up and the kernel sends
        # SIGHUP to the session leader.
        outcome = self.run_vng(lambda _vng, pty_fds: os.close(pty_fds.pop()))
        self.assertTrue(outcome.daemon_gone, "virtiofsd outlived vng")

    # Known bug: SIGHUP is not handled, so vng is killed by it without running
    # its exit handlers and leaves its temporary files behind.
    @unittest.expectedFailure
    def test_ssh_disconnect_shuts_vng_down_cleanly(self):
        # SIGHUP must be handled like SIGTERM, so that the exit handlers run:
        # vng does not die with a traceback because the terminal is gone and
        # it removes the temporary files.
        outcome = self.run_vng(lambda _vng, pty_fds: os.close(pty_fds.pop()))
        self.assertEqual(outcome.returncode, 1, outcome.stderr)
        self.assertNotIn("Traceback", outcome.stderr)
        self.assertEqual(outcome.files_left, [])

    def test_sigkill_stops_daemon(self):
        # SIGKILL runs no exit handler: only the kernel can stop the daemon.
        outcome = self.run_vng(lambda vng, _pty_fds: vng.kill())
        self.assertEqual(outcome.returncode, -signal.SIGKILL, outcome.stderr)
        self.assertTrue(outcome.daemon_gone, "virtiofsd outlived vng")


if __name__ == "__main__":
    unittest.main()
