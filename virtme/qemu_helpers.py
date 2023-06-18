# -*- mode: python -*-
# qemu_helpers: Helpers to find QEMU and handle its quirks
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

import os
import re
import shutil
import subprocess
from typing import Optional


class Qemu:
    qemubin: str
    version: Optional[str]

    def __init__(self, qemubin, arch) -> None:
        self.arch = arch
        self.has_multidevs = None
        self.cannot_overmount_virtfs = None

        if not qemubin:
            qemubin = shutil.which("qemu-system-%s" % arch)
            if qemubin is None and arch == os.uname().machine:
                qemubin = shutil.which("qemu-kvm")
            if qemubin is None:
                raise ValueError("cannot find qemu for %s" % arch)
        else:
            if not os.path.isfile(qemubin):
                raise ValueError('specified qemu binary "%s" does not exist' % qemubin)
            if not os.access(qemubin, os.X_OK):
                raise ValueError(
                    'specified qemu binary "%s" is not executable' % qemubin
                )

        self.qemubin = qemubin
        self.version = None

    def probe(self) -> None:
        if self.version is None:
            self.version = subprocess.check_output([self.qemubin, "--version"]).decode(
                "utf-8"
            )
            self.cannot_overmount_virtfs = (
                re.search(r"version 1\.[012345]", self.version) is not None
            )

            # QEMU 4.2+ supports -fsdev multidevs=remap
            self.has_multidevs = (
                re.search(r"version (?:1\.|2\.|3\.|4\.[01][^\d])", self.version) is None
            )

    def quote_optarg(self, a: str) -> str:
        """Quote an argument to an option."""
        return a.replace(",", ",,")
