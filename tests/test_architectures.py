"""Tests for architecture names and native guest detection."""

import unittest
from types import SimpleNamespace
from unittest import mock

from virtme import architectures
from virtme.commands import run


def on_host(machine):
    return mock.patch("platform.machine", return_value=machine)


class ArchitectureTests(unittest.TestCase):
    @unittest.expectedFailure
    def test_arm64_is_an_alias_of_aarch64(self):
        self.assertIs(architectures.get("arm64"), architectures.get("aarch64"))
        self.assertEqual(architectures.get("arm64").virtmename, "aarch64")


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
