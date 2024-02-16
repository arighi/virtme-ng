# -*- mode: python -*-
# virtmods: Default module configuration
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

MODALIASES = [
    # These are most likely portable across all architectures.
    'fs-9p',
    'fs-virtiofs',
    'virtio:d00000009v00001AF4',  # 9pnet_virtio
    'virtio:d00000003v00001AF4',  # virtio_console

    # These are required by the microvm architecture.
    'virtio_pci',                 # virtio-pci
    'virtio_mmio',                # virtio-mmio

    # For virtio_pci architectures (which are, hopefully, all that we care
    # about), there's really only one required driver, virtio_pci.
    # For completeness, here are both of the instances we care about
    # for basic functionality.
    'pci:v00001AF4d00001009sv00001AF4sd00000009bc00sc02i00',  # 9pnet
    'pci:v00001AF4d00001003sv00001AF4sd00000003bc07sc80i00',  # virtconsole

    # Basic system functionality
    'unix',  # UNIX sockets, needed by udev

    # Basic emulated hardware
    'i8042',
    'atkbd',
]
