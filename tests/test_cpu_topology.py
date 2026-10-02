"""Tests for automatic host CPU topology discovery."""

import tempfile
import unittest
from pathlib import Path

from virtme.cpu_topology import TopologyError, host_cpu_topology


class HostCpuTopologyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.sysfs = Path(self.tempdir.name)

    def add_cpu(self, cpu, package, core, die=None):
        topology = self.sysfs / f"cpu{cpu}" / "topology"
        topology.mkdir(parents=True)
        (topology / "physical_package_id").write_text(str(package), encoding="ascii")
        (topology / "core_id").write_text(str(core), encoding="ascii")
        if die is not None:
            (topology / "die_id").write_text(str(die), encoding="ascii")

    def test_sparse_host_cpu_numbers_keep_siblings_together(self):
        for cpu, package, core in [
            (0, 0, 0),
            (12, 0, 0),
            (1, 0, 1),
            (13, 0, 1),
            (4, 1, 8),
            (16, 1, 8),
            (5, 1, 9),
            (17, 1, 9),
        ]:
            self.add_cpu(cpu, package, core)

        smp, pin, warning = host_cpu_topology(self.sysfs, {0, 1, 4, 5, 12, 13, 16, 17})
        self.assertEqual(smp, "8,sockets=2,cores=2,threads=2")
        self.assertEqual(pin, [0, 12, 1, 13, 4, 16, 5, 17])
        self.assertIsNone(warning)

    def test_allowed_cpu_subset_defines_visible_topology(self):
        self.add_cpu(2, 0, 0)
        self.add_cpu(10, 0, 0)
        self.add_cpu(3, 0, 1)
        self.add_cpu(11, 0, 1)

        smp, pin, warning = host_cpu_topology(self.sysfs, {2, 3})
        self.assertEqual(smp, "2,sockets=1,cores=2,threads=1")
        self.assertEqual(pin, [2, 3])
        self.assertIsNone(warning)

    def test_uneven_allowed_threads_keep_smt(self):
        self.add_cpu(2, 0, 0)
        self.add_cpu(10, 0, 0)
        self.add_cpu(3, 0, 1)

        smp, pin, warning = host_cpu_topology(self.sysfs, {2, 3, 10})
        self.assertEqual(smp, "2,sockets=1,cores=1,threads=2")
        self.assertEqual(pin, [2, 10])
        self.assertIn("host CPUs 3 are not used", warning)

    def test_hybrid_cpu_keeps_smt_cores(self):
        # 2 SMT performance cores + 4 efficiency cores without SMT.
        for cpu, core in [(0, 0), (1, 0), (2, 4), (3, 4)]:
            self.add_cpu(cpu, 0, core)
        for cpu in range(4, 8):
            self.add_cpu(cpu, 0, cpu + 4)

        smp, pin, warning = host_cpu_topology(self.sysfs, set(range(8)))
        self.assertEqual(smp, "4,sockets=1,cores=2,threads=2")
        self.assertEqual(pin, [0, 1, 2, 3])
        self.assertIn("host CPUs 4-7 are not used", warning)

    def test_smt_preferred_over_cpu_count(self):
        # Socket 0 has 2 SMT cores, socket 1 has 1 SMT core + 2 single cores.
        for cpu, package, core in [
            (0, 0, 0),
            (1, 0, 0),
            (2, 0, 1),
            (3, 0, 1),
            (4, 1, 0),
            (5, 1, 0),
            (6, 1, 1),
            (7, 1, 2),
        ]:
            self.add_cpu(cpu, package, core)

        smp, pin, warning = host_cpu_topology(self.sysfs, set(range(8)))
        self.assertEqual(smp, "6,sockets=1,cores=3,threads=2")
        self.assertEqual(pin, list(range(6)))
        self.assertIn("merged into one", warning)
        self.assertIn("host CPUs 6-7 are not used", warning)

    def test_keep_sockets_when_cpu_count_ties(self):
        for cpu, package, core in [(0, 0, 0), (1, 0, 1), (2, 1, 0), (3, 1, 1)]:
            self.add_cpu(cpu, package, core)
        self.add_cpu(4, 1, 2)

        smp, pin, warning = host_cpu_topology(self.sysfs, {0, 1, 2, 3})
        self.assertEqual(smp, "4,sockets=2,cores=2,threads=1")
        self.assertEqual(pin, [0, 1, 2, 3])
        self.assertIsNone(warning)

    def test_uneven_sockets_merge(self):
        self.add_cpu(0, 0, 0)
        self.add_cpu(1, 0, 1)
        self.add_cpu(2, 1, 0)

        smp, pin, warning = host_cpu_topology(self.sysfs, {0, 1, 2})
        self.assertEqual(smp, "3,sockets=1,cores=3,threads=1")
        self.assertEqual(pin, [0, 1, 2])
        self.assertIn("merged into one", warning)

    def test_uneven_sockets_merge_keeps_smt(self):
        # Keeping both sockets would drop an SMT core, so merging them into a
        # single socket wins because it uses every CPU.
        for cpu, package, core in [
            (0, 0, 0),
            (1, 0, 0),
            (2, 0, 1),
            (3, 0, 1),
            (4, 1, 0),
            (5, 1, 0),
        ]:
            self.add_cpu(cpu, package, core)

        smp, pin, warning = host_cpu_topology(self.sysfs, set(range(6)))
        self.assertEqual(smp, "6,sockets=1,cores=3,threads=2")
        self.assertEqual(pin, list(range(6)))
        self.assertIn("merged into one", warning)

    def test_distinct_dies_can_repeat_core_ids(self):
        self.add_cpu(0, 0, 0, die=0)
        self.add_cpu(1, 0, 0, die=1)

        smp, pin, warning = host_cpu_topology(self.sysfs, {0, 1})
        self.assertEqual(smp, "2,sockets=1,cores=2,threads=1")
        self.assertEqual(pin, [0, 1])
        self.assertIsNone(warning)

    def test_missing_topology_fails(self):
        self.add_cpu(0, 0, 0)

        with self.assertRaisesRegex(TopologyError, "missing host CPU topology"):
            host_cpu_topology(self.sysfs, {0, 1})


if __name__ == "__main__":
    unittest.main()
