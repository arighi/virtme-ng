"""Tests that virtiofsd does not outlive virtme-run, however it goes away.

virtme-run is the process that owns virtiofsd: a stand-in process runs its
main() as the session leader of a pty, like in an ssh login session, with a
real virtiofsd, instead of launching QEMU. The real vng (virtme_ng/run.py)
launches virtme-run via a shell and neither handles nor forwards signals of
its own, so what is exercised here is virtme-run's own lifetime behavior:
only the disruptions that signal the whole foreground process group (Ctrl-C
and the ssh disconnect) reach virtme-run in the real topology as well, while
a signal aimed at the vng parent alone is not covered. Each scenario also
checks its own cleanup: whatever its outcome, no process and no open file
descriptor may be left behind. Skipped when no
usable virtiofsd is installed.
"""

import collections
import os
import pty
import select
import shutil
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

# Stands in for the virtme-run process of a vng session: run.main() installs
# the real signal handling, but do_it() only exports a directory with
# virtiofsd and then waits instead of launching QEMU. It reports the socket
# of the daemon and the shared directory, which the test has to remove
# itself when the stand-in is killed without running any cleanup.
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
        # but does not start is a failure. Tell the two apart only after a
        # failed start, so that the happy path runs the availability probe
        # (virtiofsd --version) just once.
        if not export_virtiofs(Arch(), qemuargs, VirtioFSState(sys.argv[1]), config):
            if not VirtioFS(sys.argv[1]).is_virtiofsd_available():
                print("NO_VIRTIOFSD", flush=True)
            else:
                print("START_FAILED", flush=True)
            return 1
        # The socket of the daemon is what QEMU gets as its vhost-user
        # chardev; the shared directory is reported along with it, so that
        # the test can remove it when the stand-in is killed.
        sock = next(a for a in qemuargs if a.startswith("socket,"))
        print(f"{sock.split('path=', 1)[1]} {shared}", flush=True)
        time.sleep(60)
    return 0


with patch.object(run, "do_it", do_it):
    sys.exit(run.main())
"""

# How virtme-run went away, and what is left of it.
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


def _open_fds():
    """Return the set of the file descriptors open in this process."""
    dir_fd = os.open("/proc/self/fd", os.O_RDONLY)
    try:
        # The listing contains the directory fd itself.
        return {int(fd) for fd in os.listdir(dir_fd)} - {dir_fd}
    finally:
        os.close(dir_fd)


def _pids_referencing(path):
    """Return the PIDs of the processes whose command line contains PATH."""
    pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as fd:
                if path.encode() in fd.read():
                    pids.append(int(entry))
        except OSError:
            continue
    return pids


def _read_daemon_pid(pid_file, virtme_run):
    # virtiofsd itself writes its PID to "<socket>.pid" once it is running.
    # Give up early when virtme-run is gone: the PID will never show up.
    def read():
        try:
            return int(Path(pid_file).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    _wait_until(
        lambda: read() is not None or virtme_run.poll() is not None, START_TIMEOUT
    )
    return read()


class VirtiofsdLifetimeTests(unittest.TestCase):
    """virtiofsd must not outlive virtme-run."""

    def run_virtme_run(self, disrupt):
        """Start the virtme-run stand-in, call DISRUPT(virtme_run, pty_fds) and
        report what is left."""
        # Nothing of the scenario may be left behind, whatever its outcome:
        # no process, no open file descriptor. The snapshot is taken before
        # anything is opened, and the check is registered as the first
        # cleanup so that it runs as the last one -- after the pty has been
        # closed and the stand-in has been waited for -- so that it also
        # holds when the scenario itself fails.
        fds_before = _open_fds()
        virtme_run = None
        sock = None
        shared_dir = None
        self.addCleanup(
            self._assert_no_leaks, fds_before, lambda: (virtme_run, sock, shared_dir)
        )
        pty_fd, tty_fd = pty.openpty()
        pty_fds = [pty_fd]
        self.addCleanup(lambda: [os.close(fd) for fd in pty_fds])
        try:
            virtme_run = subprocess.Popen(
                [sys.executable, "-c", SESSION_LAUNCHER, GUEST_TOOLS],
                cwd=ROOT,
                stdin=tty_fd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        finally:
            os.close(tty_fd)
        with virtme_run:
            daemon_pid = None
            daemon_start = None
            try:
                ready, _, _ = select.select([virtme_run.stdout], [], [], START_TIMEOUT)
                self.assertTrue(ready, "virtme-run did not start virtiofsd in time")
                line = virtme_run.stdout.readline().decode().strip()
                if not line:
                    # EOF: the launcher died before reporting the daemon.
                    virtme_run.kill()
                    virtme_run.wait()
                    self.fail(
                        f"virtme-run died during startup: {virtme_run.stderr.read().decode()}"
                    )
                if line == "NO_VIRTIOFSD":
                    self.skipTest("virtiofsd not available")
                if line == "START_FAILED":
                    self.fail(
                        "virtiofsd is installed but virtme-run failed to start it"
                    )
                sock, shared_dir = line.split()
                daemon_pid = _read_daemon_pid(f"{sock}.pid", virtme_run)
                if daemon_pid is None:
                    # The launcher reported a socket, but no pid file showed
                    # up: it may have died in between, which the EOF branch
                    # above only catches before the report.
                    virtme_run.kill()
                    returncode = virtme_run.wait()
                    self.fail(
                        "virtiofsd did not write its pid file; virtme-run exit"
                        f"status: {returncode}, stderr: "
                        f"{virtme_run.stderr.read().decode()}"
                    )
                daemon_start = _start_time(daemon_pid)
                self.assertIsNotNone(daemon_start, "virtiofsd is gone already")
                self.assertTrue(_pid_alive(daemon_pid))

                # The daemon must be alive when the disruption hits: one
                # that crashed on its own before it would make every check
                # below pass without the signal delivery ever being
                # exercised. The check has to happen before the disruption:
                # the Ctrl-C and ssh-disconnect disruptors signal the whole
                # foreground process group, which reaches the daemon as
                # long as it shares virtme-run's.
                self.assertTrue(
                    _is_same_process(daemon_pid, daemon_start),
                    "virtiofsd was gone before virtme-run went away",
                )
                disrupt(virtme_run, pty_fds)
                try:
                    returncode = virtme_run.wait(timeout=EXIT_TIMEOUT)
                except subprocess.TimeoutExpired:
                    # A virtme-run that hangs instead of exiting is a failure mode
                    # of its own (e.g. an unhandled signal): report it as a
                    # test failure, not as an uncaught exception. A SIGKILLed
                    # child is always reapable, so the final wait() needs no
                    # timeout of its own.
                    virtme_run.kill()
                    returncode = virtme_run.wait()
                    self.fail(
                        f"virtme-run did not exit within {EXIT_TIMEOUT}s after going "
                        f"away; virtme-run exitstatus: {returncode}, stderr: "
                        f"{virtme_run.stderr.read().decode()}"
                    )
                stderr = virtme_run.stderr.read().decode()
                daemon_gone = _wait_until(
                    lambda: not _is_same_process(daemon_pid, daemon_start),
                    EXIT_TIMEOUT,
                )
                files_left = [
                    path for path in (sock, f"{sock}.pid") if os.path.exists(path)
                ]
                return Outcome(returncode, stderr, daemon_gone, files_left)
            finally:
                virtme_run.kill()
                if daemon_pid is None:
                    # The daemon's PID is unknown (virtme-run went away before
                    # reporting it, or it never wrote its pid file), but it
                    # may still be running: it shares virtme-run's process group,
                    # so take the whole group down instead of orphaning it.
                    try:
                        os.killpg(virtme_run.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        # The group is gone already: fine.
                        pass
                # Never kill a process that merely reuses the daemon's PID.
                elif _is_same_process(daemon_pid, daemon_start):
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
                if shared_dir is not None:
                    # A stand-in that was SIGKILLed (or killed by an unhandled
                    # signal) cannot clean up the shared directory itself.
                    shutil.rmtree(shared_dir, ignore_errors=True)
                # Close the stand-in's pipes instead of leaving that to the
                # garbage collector: the traceback of a failing scenario
                # keeps this frame -- and with it the Popen object and its
                # pipes -- alive past the cleanups.
                virtme_run.stdout.close()
                virtme_run.stderr.close()

    def _assert_no_leaks(self, fds_before, get_scenario):
        """Assert that nothing of the scenario is left behind.

        run_virtme_run() registers this as its first cleanup, so it runs as
        the last one, after the pty has been closed and the stand-in has
        been waited for.
        """
        virtme_run, sock, shared_dir = get_scenario()
        if virtme_run is not None:
            # The stand-in has been killed and waited for by now, so a
            # poll() result also means reaped: no virtme-run is left
            # behind, not even as a zombie.
            self.assertIsNotNone(virtme_run.poll(), "virtme-run was not reaped")
        if sock is not None:
            # The daemon is the only process that references the socket in
            # its command line, so this covers it also when its PID is not
            # known (it never wrote its pid file).
            self.assertTrue(
                _wait_until(lambda: not _pids_referencing(sock), EXIT_TIMEOUT),
                f"a process is still using {sock}",
            )
        if shared_dir is not None:
            # Removed by the scenario's own cleanup; only a stand-in that
            # could not run any cleanup (a SIGKILL) leaves it behind.
            self.assertFalse(
                os.path.exists(shared_dir), "the shared directory was left behind"
            )
        self.assertEqual(
            _open_fds() - fds_before, set(), "file descriptors were leaked"
        )

    def test_sigterm_stops_daemon_and_removes_temp_files(self):
        outcome = self.run_virtme_run(
            lambda virtme_run, _pty_fds: virtme_run.terminate()
        )
        self.assertEqual(outcome.returncode, 1, outcome.stderr)
        self.assertTrue(outcome.daemon_gone, "virtiofsd outlived virtme-run")
        self.assertEqual(outcome.files_left, [])

    def test_ctrl_c_stops_daemon_and_removes_temp_files(self):
        # Ctrl-C: the terminal sends SIGINT to the whole foreground process
        # group, which the daemon is a part of.
        outcome = self.run_virtme_run(
            lambda virtme_run, _pty_fds: os.killpg(virtme_run.pid, signal.SIGINT)
        )
        self.assertTrue(outcome.daemon_gone, "virtiofsd outlived virtme-run")
        self.assertEqual(outcome.files_left, [])

    def test_ssh_disconnect_stops_daemon(self):
        # The ssh connection drops: the pty is hung up and the kernel sends
        # SIGHUP to the session leader.
        outcome = self.run_virtme_run(
            lambda _virtme_run, pty_fds: os.close(pty_fds.pop())
        )
        self.assertTrue(outcome.daemon_gone, "virtiofsd outlived virtme-run")

    # Known bug: SIGHUP is not handled, so virtme-run is killed by it without running
    # its exit handlers and leaves its temporary files behind.
    @unittest.expectedFailure
    def test_ssh_disconnect_shuts_virtme_run_down_cleanly(self):
        # SIGHUP must be handled like SIGTERM, so that the exit handlers run:
        # virtme-run does not die with a traceback because the terminal is gone and
        # it removes the temporary files.
        outcome = self.run_virtme_run(
            lambda _virtme_run, pty_fds: os.close(pty_fds.pop())
        )
        self.assertEqual(outcome.returncode, 1, outcome.stderr)
        self.assertNotIn("Traceback", outcome.stderr)
        self.assertEqual(outcome.files_left, [])

    def test_sigkill_stops_daemon(self):
        # SIGKILL runs no exit handler: only the kernel can stop the daemon.
        outcome = self.run_virtme_run(lambda virtme_run, _pty_fds: virtme_run.kill())
        self.assertEqual(outcome.returncode, -signal.SIGKILL, outcome.stderr)
        self.assertTrue(outcome.daemon_gone, "virtiofsd outlived virtme-run")


if __name__ == "__main__":
    unittest.main()
