"""Tests for virtiofsd daemon management and virtio-fs QEMU export arguments."""

# The unit tests in this file exercise the internal helpers of VirtioFS
# directly; that is what they are for.
# pylint: disable=protected-access

import os
import signal
import socket
import subprocess
import tempfile
import unittest
from unittest import mock

from virtme_ng.virtiofs import (
    _VIRTIOFSD_READONLY_SUPPORT,
    VirtioFS,
    VirtioFSConfig,
    VirtioFSState,
    ensure_virtiofs_memory,
    export_virtiofs,
)


class FakeArch:
    def __init__(self, virtiofs=True, numa=True):
        self._virtiofs = virtiofs
        self._numa = numa

    def virtiofs_support(self):
        return self._virtiofs

    def vhost_dev_type(self, _dev_type):
        return "virtiofs-device"

    def numa_support(self):
        return self._numa


class DaemonPatchMixin:
    """Patch virtiofsd discovery and startup so that start() succeeds.

    Creates a real (fake) executable at <tempdir>/bin/virtiofsd so that
    _get_virtiofsd_path() finds it as the first candidate, and patches
    os.system to simulate the daemon by binding a unix socket at the
    socket path, which is what the readiness poll waits for.
    """

    def setUp(self):
        super().setUp()
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        _VIRTIOFSD_READONLY_SUPPORT["value"] = None
        self.addCleanup(self._reset_readonly_cache)

        self.daemon = os.path.join(self.tempdir.name, "bin", "virtiofsd")
        os.makedirs(os.path.dirname(self.daemon), exist_ok=True)
        with open(self.daemon, "w", encoding="utf-8") as fd:
            fd.write("#!/bin/sh\n")
        os.chmod(self.daemon, 0o755)

        self.sock = os.path.join(self.tempdir.name, "virtme.sock")
        self.system_calls = []

        def system_side_effect(cmd):
            self.system_calls.append(cmd)
            if self.create_socket:
                daemon_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                daemon_sock.bind(self.sock)
                daemon_sock.close()
            return 0

        self.create_socket = True
        patches = [
            mock.patch("virtme_ng.virtiofs.subprocess.check_call"),
            # _supports_readonly() must never spawn a real virtiofsd; default
            # to no --readonly support.
            mock.patch(
                "virtme_ng.virtiofs.subprocess.run",
                return_value=mock.MagicMock(returncode=0, stdout="usage: virtiofsd"),
            ),
            mock.patch("virtme_ng.virtiofs.os.system", side_effect=system_side_effect),
            mock.patch(
                "virtme_ng.virtiofs.tempfile.mkstemp", return_value=(0, self.sock)
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _reset_readonly_cache(self):
        _VIRTIOFSD_READONLY_SUPPORT["value"] = None


class VirtioFSConfigTests(unittest.TestCase):
    def test_readonly_is_negated_rw(self):
        config = VirtioFSConfig(path="/", mount_tag="ROOTFS")
        self.assertFalse(config.rw)
        self.assertTrue(config.readonly)
        self.assertFalse(config.posix_acl)

        config = VirtioFSConfig(path="/", mount_tag="ROOTFS", rw=True)
        self.assertTrue(config.rw)
        self.assertFalse(config.readonly)

    def test_state_defaults(self):
        state = VirtioFSState("/opt/guest-tools")
        self.assertEqual(state.guest_tools_path, "/opt/guest-tools")
        self.assertIsNone(state.memory)
        self.assertFalse(state.memory_configured)


class EnsureVirtiofsMemoryTests(unittest.TestCase):
    def test_numa_appends_numa_node(self):
        qemuargs = []
        state = VirtioFSState("/opt/guest-tools")
        ensure_virtiofs_memory(FakeArch(numa=True), qemuargs, state)
        self.assertEqual(
            qemuargs,
            [
                "-object",
                "memory-backend-memfd,id=mem,size=128M,share=on",
                "-numa",
                "node,memdev=mem",
            ],
        )
        self.assertTrue(state.memory_configured)

    def test_without_numa_uses_machine_option(self):
        qemuargs = []
        state = VirtioFSState("/opt/guest-tools")
        ensure_virtiofs_memory(FakeArch(numa=False), qemuargs, state)
        self.assertEqual(
            qemuargs,
            [
                "-object",
                "memory-backend-memfd,id=mem,size=128M,share=on",
                "-machine",
                "memory-backend=mem",
            ],
        )

    def test_already_configured_is_noop(self):
        qemuargs = []
        state = VirtioFSState("/opt/guest-tools", memory_configured=True)
        ensure_virtiofs_memory(FakeArch(), qemuargs, state)
        self.assertEqual(qemuargs, [])

    def test_custom_memory_size(self):
        qemuargs = []
        state = VirtioFSState("/opt/guest-tools", memory="256M")
        ensure_virtiofs_memory(FakeArch(), qemuargs, state)
        self.assertIn("memory-backend-memfd,id=mem,size=256M,share=on", qemuargs)


class ExportVirtiofsTests(DaemonPatchMixin, unittest.TestCase):
    def test_unsupported_arch_returns_false(self):
        with mock.patch("virtme_ng.virtiofs.os.system") as system:
            state = VirtioFSState(self.tempdir.name)
            config = VirtioFSConfig(path="/", mount_tag="ROOTFS")
            self.assertFalse(
                export_virtiofs(FakeArch(virtiofs=False), [], state, config)
            )
            system.assert_not_called()

    def test_daemon_unavailable_returns_false(self):
        qemuargs = []
        with (
            mock.patch("virtme_ng.virtiofs.which", return_value=None),
            mock.patch(
                "virtme_ng.virtiofs.subprocess.check_call",
                side_effect=subprocess.CalledProcessError(1, "virtiofsd"),
            ),
        ):
            state = VirtioFSState("/nonexistent")
            config = VirtioFSConfig(path="/", mount_tag="ROOTFS")
            self.assertFalse(export_virtiofs(FakeArch(), qemuargs, state, config))
        self.assertEqual(qemuargs, [])
        self.assertEqual(self.system_calls, [])

    def test_appends_chardev_device_and_memory(self):
        qemuargs = []
        state = VirtioFSState(self.tempdir.name)
        config = VirtioFSConfig(path="/", mount_tag="ROOTFS")
        self.assertTrue(export_virtiofs(FakeArch(), qemuargs, state, config))
        self.assertIn("-chardev", qemuargs)
        self.assertIn(f"socket,id=charvirtfs0,path={self.sock}", qemuargs)
        self.assertIn("-device", qemuargs)
        self.assertIn("virtiofs-device,chardev=charvirtfs0,tag=ROOTFS", qemuargs)
        self.assertIn("memory-backend-memfd,id=mem,size=128M,share=on", qemuargs)
        self.assertIn("-numa", qemuargs)
        self.assertTrue(state.memory_configured)

    def test_cache_auto_for_rw_and_always_for_ro(self):
        state = VirtioFSState(self.tempdir.name)
        config = VirtioFSConfig(path="/", mount_tag="ROOTFS", rw=True)
        self.assertTrue(export_virtiofs(FakeArch(), [], state, config))
        self.assertIn("--cache auto", self.system_calls[0])
        self.assertNotIn("--cache always", self.system_calls[0])

        state = VirtioFSState(self.tempdir.name)
        config = VirtioFSConfig(path="/", mount_tag="ROOTFS")
        self.assertTrue(export_virtiofs(FakeArch(), [], state, config))
        self.assertIn("--cache always", self.system_calls[1])
        self.assertNotIn("--cache auto", self.system_calls[1])


class GetVirtiofsdPathTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        # Determinism: any candidate probe that actually runs must fail, so
        # that fixed paths like /usr/libexec/virtiofsd (which may exist on the
        # test machine) never make a test pass by accident.
        self.check_call_patch = mock.patch(
            "virtme_ng.virtiofs.subprocess.check_call",
            side_effect=subprocess.CalledProcessError(1, "virtiofsd"),
        )
        self.check_call_patch.start()
        self.addCleanup(self.check_call_patch.stop)

    def _make_executable(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fd:
            fd.write("#!/bin/sh\n")
        os.chmod(path, 0o755)

    def test_prefers_guest_tools_binary(self):
        guest_binary = os.path.join(self.tempdir.name, "bin", "virtiofsd")
        self._make_executable(guest_binary)
        with mock.patch("virtme_ng.virtiofs.subprocess.check_call") as check_call:
            self.assertEqual(
                VirtioFS(self.tempdir.name)._get_virtiofsd_path(), guest_binary
            )
            check_call.assert_called_once_with(
                [guest_binary, "--version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def test_falls_back_to_which(self):
        which_binary = os.path.join(self.tempdir.name, "virtiofsd")
        self._make_executable(which_binary)
        with (
            mock.patch("virtme_ng.virtiofs.which", return_value=which_binary),
            mock.patch("virtme_ng.virtiofs.subprocess.check_call") as check_call,
        ):
            self.assertEqual(
                VirtioFS("/nonexistent")._get_virtiofsd_path(), which_binary
            )
            check_call.assert_called_once()

    def test_returns_none_when_not_found(self):
        with mock.patch("virtme_ng.virtiofs.which", return_value=None):
            self.assertIsNone(VirtioFS("/nonexistent")._get_virtiofsd_path())

    def test_skips_failing_candidate(self):
        guest_binary = os.path.join(self.tempdir.name, "bin", "virtiofsd")
        self._make_executable(guest_binary)
        with mock.patch("virtme_ng.virtiofs.which", return_value=None):
            # check_call raises for every candidate (setUp default).
            self.assertIsNone(VirtioFS(self.tempdir.name)._get_virtiofsd_path())


class SupportsReadonlyTests(unittest.TestCase):
    def setUp(self):
        _VIRTIOFSD_READONLY_SUPPORT["value"] = None
        self.addCleanup(self._reset_cache)

    def _reset_cache(self):
        _VIRTIOFSD_READONLY_SUPPORT["value"] = None

    def test_detects_flag_in_help_output(self):
        result = mock.MagicMock(returncode=0, stdout="--readonly\nusage: virtiofsd")
        with mock.patch("virtme_ng.virtiofs.subprocess.run", return_value=result):
            self.assertTrue(VirtioFS._supports_readonly("/usr/bin/virtiofsd"))

    def test_false_on_nonzero_returncode(self):
        result = mock.MagicMock(returncode=1, stdout="--readonly")
        with mock.patch("virtme_ng.virtiofs.subprocess.run", return_value=result):
            self.assertFalse(VirtioFS._supports_readonly("/usr/bin/virtiofsd"))

    def test_false_when_flag_missing(self):
        result = mock.MagicMock(returncode=0, stdout="usage: virtiofsd")
        with mock.patch("virtme_ng.virtiofs.subprocess.run", return_value=result):
            self.assertFalse(VirtioFS._supports_readonly("/usr/bin/virtiofsd"))

    def test_false_on_oserror(self):
        with mock.patch(
            "virtme_ng.virtiofs.subprocess.run", side_effect=OSError("no such file")
        ):
            self.assertFalse(VirtioFS._supports_readonly("/usr/bin/virtiofsd"))

    def test_result_is_cached(self):
        result = mock.MagicMock(returncode=0, stdout="--readonly")
        with mock.patch(
            "virtme_ng.virtiofs.subprocess.run", return_value=result
        ) as run:
            self.assertTrue(VirtioFS._supports_readonly("/usr/bin/virtiofsd"))
            self.assertTrue(VirtioFS._supports_readonly("/another/virtiofsd"))
            run.assert_called_once()


class VirtioFSStartTests(DaemonPatchMixin, unittest.TestCase):
    def test_returns_false_without_daemon(self):
        with (
            mock.patch("virtme_ng.virtiofs.which", return_value=None),
            mock.patch(
                "virtme_ng.virtiofs.subprocess.check_call",
                side_effect=subprocess.CalledProcessError(1, "virtiofsd"),
            ),
            mock.patch("virtme_ng.virtiofs.tempfile.mkstemp") as mkstemp,
        ):
            self.assertFalse(VirtioFS("/nonexistent").start("/"))
            mkstemp.assert_not_called()

    def test_spawns_daemon_via_shell_command(self):
        self.assertTrue(VirtioFS(self.tempdir.name).start("/", verbose=False))

        self.assertEqual(len(self.system_calls), 1)
        cmd = self.system_calls[0]
        self.assertTrue(cmd.startswith(self.daemon))
        self.assertIn("--syslog", cmd)
        self.assertIn("--no-announce-submounts", cmd)
        self.assertIn(f"--socket-path {self.sock}", cmd)
        self.assertIn("--shared-dir /", cmd)
        self.assertIn("--sandbox none", cmd)
        self.assertIn("--cache always", cmd)
        self.assertIn("2>/dev/null", cmd)
        self.assertTrue(cmd.endswith("&"))
        self.assertNotIn("--posix-acl", cmd)
        self.assertNotIn("--readonly", cmd)

    def test_verbose_keeps_stderr_inherited(self):
        self.assertTrue(VirtioFS(self.tempdir.name).start("/", verbose=True))
        self.assertNotIn("2>/dev/null", self.system_calls[0])

    def test_timeout_returns_false(self):
        self.create_socket = False
        with (
            mock.patch("virtme_ng.virtiofs.monotonic", side_effect=[0.0, 100.0]),
            mock.patch("virtme_ng.virtiofs.sys.stderr") as stderr,
        ):
            self.assertFalse(VirtioFS(self.tempdir.name).start("/", verbose=True))
        self.assertEqual(len(self.system_calls), 1)
        messages = [call.args[0] for call in stderr.write.call_args_list]
        self.assertTrue(any("failed to start virtiofsd" in msg for msg in messages))

    def test_passes_acl_and_readonly_flags(self):
        result = mock.MagicMock(returncode=0, stdout="--readonly\nusage: virtiofsd")
        with mock.patch("virtme_ng.virtiofs.subprocess.run", return_value=result):
            self.assertTrue(
                VirtioFS(self.tempdir.name).start(
                    "/", posix_acl=True, readonly=True, verbose=False
                )
            )
        cmd = self.system_calls[0]
        self.assertIn("--posix-acl", cmd)
        self.assertIn("--readonly", cmd)


class IsSocketTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

    def test_true_for_unix_socket(self):
        path = os.path.join(self.tempdir.name, "sock")
        daemon_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        daemon_sock.bind(path)
        daemon_sock.close()
        self.assertTrue(VirtioFS._is_socket(path))

    def test_false_for_regular_file(self):
        path = os.path.join(self.tempdir.name, "file")
        with open(path, "w", encoding="utf-8") as fd:
            fd.write("")
        self.assertFalse(VirtioFS._is_socket(path))

    def test_false_for_missing_path(self):
        path = os.path.join(self.tempdir.name, "nonexistent")
        self.assertFalse(VirtioFS._is_socket(path))


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

    def test_kills_daemon_and_removes_temp_files(self):
        virtio_fs = VirtioFS("/nonexistent")
        virtio_fs.sock = os.path.join(self.tempdir.name, "virtme.sock")
        virtio_fs.pid = virtio_fs.sock + ".pid"
        with open(virtio_fs.sock, "w", encoding="utf-8") as fd:
            fd.write("")
        with open(virtio_fs.pid, "w", encoding="utf-8") as fd:
            fd.write("4242")

        with mock.patch("virtme_ng.virtiofs.os.kill") as kill:
            virtio_fs._cleanup_virtiofs_temp_files()

        kill.assert_called_once_with(4242, signal.SIGTERM)
        self.assertFalse(os.path.exists(virtio_fs.sock))
        self.assertFalse(os.path.exists(virtio_fs.pid))


if __name__ == "__main__":
    unittest.main()
