#!/usr/bin/python3
# -*- mode: python -*-
# qemu_helpers: Helpers to find QEMU and handle its quirks
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

import os

class Arch(object):
    @staticmethod
    def serial_dev_name(index):
        return 'ttyS%d' % index

class Arch_unknown(Arch):
    @staticmethod
    def qemuargs(is_native):
        return []

class Arch_x86(Arch):
    @staticmethod
    def qemuargs(is_native):
        ret = []

        if is_native and os.access('/dev/kvm', os.R_OK):
            # If we're likely to use KVM, request a full-featured CPU.
            # (NB: if KVM fails, this will cause problems.  We should probe.)
            ret.extend(['-cpu', 'host'])  # We can't migrate regardless.

        return ret

class Arch_arm(Arch):
    def qemuargs(is_native):
        ret = []

        # Emulate a versatilepb.
        ret.extend(['-M', 'versatilepb'])

        return ret

    @staticmethod
    def serial_dev_name(index):
        return 'ttyAMA%d' % index

ARCHES = {
    'x86_64': Arch_x86,
    'i386': Arch_x86,
    'arm': Arch_arm,
}

def get(arch):
    return ARCHES.get(arch, Arch_unknown)
