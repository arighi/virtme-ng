"""Tests for architecture names and native guest detection."""

import unittest
from types import SimpleNamespace
from unittest import mock

from virtme import architectures
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

    @unittest.expectedFailure
    def test_non_native_x86_64(self):
        self.assertFalse(self.can_use_microvm("aarch64"))

    def test_other_arch(self):
        self.assertFalse(self.can_use_microvm("aarch64", arch="aarch64"))


if __name__ == "__main__":
    unittest.main()
