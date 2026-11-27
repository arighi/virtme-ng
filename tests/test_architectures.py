"""Tests for architecture names and native guest detection."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from virtme import architectures, qemu_helpers
from virtme.commands import run
from virtme_ng import run as vng_run


def on_host(machine):
    return mock.patch("platform.machine", return_value=machine)


class ArchitectureTests(unittest.TestCase):
    def test_arm64_is_an_alias_of_aarch64(self):
        self.assertIs(architectures.get("arm64"), architectures.get("aarch64"))
        self.assertEqual(architectures.get("arm64").virtmename, "aarch64")

    def test_native_arch(self):
        for host, guest in [
            ("x86_64", "x86_64"),
            ("aarch64", "aarch64"),
            ("aarch64", "arm64"),
            ("arm64", "aarch64"),
            ("arm64", "arm64"),
            ("ppc64le", "ppc64le"),
            ("s390x", "s390x"),
            ("i386", "i386"),
            ("arm", "arm"),
            ("ppc64", "ppc64"),
            ("riscv64", "riscv64"),
            ("sparc64", "sparc64"),
        ]:
            with self.subTest(host=host, guest=guest), on_host(host):
                self.assertTrue(architectures.get(guest).is_native())

    def test_non_native_arch(self):
        for host, guest in [
            ("x86_64", "aarch64"),
            ("aarch64", "x86_64"),
            ("ppc64le", "ppc64"),
            ("s390x", "x86_64"),
            ("x86_64", "s390x"),
            ("x86_64", "i386"),
            ("aarch64", "arm"),
            ("x86_64", "riscv64"),
            ("x86_64", "sparc64"),
        ]:
            with self.subTest(host=host, guest=guest), on_host(host):
                self.assertFalse(architectures.get(guest).is_native())


class HostArchTests(unittest.TestCase):
    def test_get_host_arch(self):
        for host, expected in [
            ("x86_64", "amd64"),
            ("aarch64", "arm64"),
            ("arm64", "arm64"),
            ("foo", None),
        ]:
            with self.subTest(host=host), on_host(host):
                self.assertEqual(vng_run.get_host_arch(), expected)


class MicrovmTests(unittest.TestCase):
    def can_use_microvm(self, host, arch="x86_64"):
        args = SimpleNamespace(disable_microvm=False, numa=None, arch=arch)
        with on_host(host), mock.patch.object(run, "can_use_kvm", return_value=True):
            return run.can_use_microvm(args)

    def test_native_x86_64(self):
        self.assertTrue(self.can_use_microvm("x86_64"))

    def test_non_native_x86_64(self):
        self.assertFalse(self.can_use_microvm("aarch64"))

    def test_other_arch(self):
        self.assertFalse(self.can_use_microvm("aarch64", arch="aarch64"))


class FindVirtmeInitTests(unittest.TestCase):
    def find(self, files, guest, host="x86_64"):
        with tempfile.TemporaryDirectory() as tools, on_host(host):
            (Path(tools) / "bin").mkdir()
            for name in files:
                (Path(tools) / "bin" / name).touch()
            return run.find_virtme_init(tools, architectures.get(guest))

    def test_arch_specific_init_is_preferred(self):
        files = ["virtme-ng-init-x86_64", "virtme-ng-init"]
        self.assertEqual(self.find(files, "x86_64"), "bin/virtme-ng-init-x86_64")

    def test_native_falls_back_to_virtme_ng_init(self):
        self.assertEqual(self.find(["virtme-ng-init"], "x86_64"), "bin/virtme-ng-init")

    def test_alias_finds_the_canonical_init(self):
        self.assertEqual(
            self.find(["virtme-ng-init-aarch64"], "arm64"),
            "bin/virtme-ng-init-aarch64",
        )

    def test_non_native_does_not_fall_back(self):
        self.assertEqual(self.find(["virtme-ng-init"], "aarch64"), "virtme-init")

    def test_no_init(self):
        self.assertEqual(self.find([], "x86_64"), "virtme-init")


class QemuTests(unittest.TestCase):
    def test_kvm_fallback(self):
        which = {"qemu-kvm": "/usr/bin/qemu-kvm"}
        with on_host("arm64"), mock.patch("shutil.which", which.get):
            is_native = architectures.get("aarch64").is_native()
            qemu = qemu_helpers.Qemu(None, "aarch64", is_native)
        self.assertEqual(qemu.qemubin, "/usr/bin/qemu-kvm")

    def test_no_kvm_fallback_for_foreign_arch(self):
        which = {"qemu-kvm": "/usr/bin/qemu-kvm"}
        with on_host("x86_64"), mock.patch("shutil.which", which.get):
            is_native = architectures.get("aarch64").is_native()
            with self.assertRaises(ValueError):
                qemu_helpers.Qemu(None, "aarch64", is_native)


if __name__ == "__main__":
    unittest.main()
