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

class Qemu(object):
    def __init__(self, arch):
        self.arch = arch

        self.qemubin = shutil.which('qemu-system-%s' % arch)
        if self.qemubin is None and arch == os.uname().machine:
            self.qemubin = shutil.which('qemu-kvm')
        if self.qemubin is None:
            raise ValueError('cannot find qemu for %s' % arch)

        self.version = None

    def probe(self):
        if self.version is None:
            self.version = subprocess.check_output([self.qemubin, '--version'])\
                                     .decode('utf-8')
            self.cannot_overmount_virtfs = (
                re.search(r'version 1\.[012345]', self.version) is not None)

    def quote_optarg(self, a):
        """Quote an argument to an option."""
        return a.replace(',', ',,')

