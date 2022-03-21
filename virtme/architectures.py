# -*- mode: python -*-
# qemu_helpers: Helpers to find QEMU and handle its quirks
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

import os
from typing import List, Optional

class Arch(object):
    def __init__(self, name) -> None:
        self.virtmename = name
        self.qemuname = name
        self.linuxname = name
        self.gccname = name

    defconfig_target = 'defconfig'

    @staticmethod
    def serial_dev_name(index) -> str:
        return 'ttyS%d' % index

    @staticmethod
    def qemuargs(is_native) -> List[str]:
        return []

    @staticmethod
    def virtio_dev_type(virtiotype) -> str:
        # Return a full name for a virtio device.  It would be
        # nice if QEMU abstracted this away, but it doesn't.
        return 'virtio-%s-pci' % virtiotype

    @staticmethod
    def earlyconsole_args() -> List[str]:
        return []

    @staticmethod
    def serial_console_args() -> List[str]:
        return []

    @staticmethod
    def qemu_nodisplay_args() -> List[str]:
        return ['-vga', 'none', '-display', 'none']

    @staticmethod
    def qemu_serial_console_args() -> List[str]:
        # We should be using the new-style -device serialdev,chardev=xyz,
        # but many architecture-specific serial devices don't support that.
        return ['-serial', 'chardev:console']

    @staticmethod
    def config_base() -> List[str]:
        return []

    def kimg_path(self) -> str:
        return 'arch/%s/boot/bzImage' % self.linuxname

    @staticmethod
    def dtb_path() -> Optional[str]:
        return None

class Arch_unknown(Arch):
    @staticmethod
    def qemuargs(is_native):
        return Arch.qemuargs(is_native)

class Arch_x86(Arch):
    def __init__(self, name):
        Arch.__init__(self, name)

        self.linuxname = 'x86'
        self.defconfig_target = '%s_defconfig' % name

    @staticmethod
    def qemuargs(is_native):
        ret = Arch.qemuargs(is_native)

        # Add a watchdog.  This is useful for testing.
        ret.extend(['-watchdog', 'i6300esb'])

        if is_native and os.access('/dev/kvm', os.R_OK):
            # If we're likely to use KVM, request a full-featured CPU.
            # (NB: if KVM fails, this will cause problems.  We should probe.)
            ret.extend(['-cpu', 'host'])  # We can't migrate regardless.

        return ret

    @staticmethod
    def earlyconsole_args():
        return ['earlyprintk=serial,ttyS0,115200']

    @staticmethod
    def serial_console_args():
        return ['console=ttyS0']

    @staticmethod
    def config_base():
        return ['CONFIG_SERIO=y',
                'CONFIG_PCI=y',
                'CONFIG_INPUT=y',
                'CONFIG_INPUT_KEYBOARD=y',
                'CONFIG_KEYBOARD_ATKBD=y',
                'CONFIG_SERIAL_8250=y',
                'CONFIG_SERIAL_8250_CONSOLE=y',
                'CONFIG_X86_VERBOSE_BOOTUP=y',
                'CONFIG_VGA_CONSOLE=y',
                'CONFIG_FB=y',
                'CONFIG_FB_VESA=y',
                'CONFIG_FRAMEBUFFER_CONSOLE=y',
                'CONFIG_RTC_CLASS=y',
                'CONFIG_RTC_HCTOSYS=y',
                'CONFIG_RTC_DRV_CMOS=y',
                'CONFIG_HYPERVISOR_GUEST=y',
                'CONFIG_PARAVIRT=y',
                'CONFIG_KVM_GUEST=y',

                # Depending on the host kernel, virtme can nest!
                'CONFIG_KVM=y',
                'CONFIG_KVM_INTEL=y',
                'CONFIG_KVM_AMD=y',
            ]

class Arch_arm(Arch):
    def __init__(self):
        Arch.__init__(self, 'arm')

        self.defconfig_target = 'vexpress_defconfig'

    @staticmethod
    def qemuargs(is_native):
        ret = Arch.qemuargs(is_native)

        # Emulate a vexpress-a15.
        ret.extend(['-M', 'vexpress-a15'])

        # TODO: consider adding a PCI bus (and figuring out how)

        # TODO: This won't boot unless -dtb is set, but we need to figure
        # out how to find the dtb file.

        return ret

    @staticmethod
    def virtio_dev_type(virtiotype):
        return 'virtio-%s-device' % virtiotype

    @staticmethod
    def earlyconsole_args():
        return ['earlyprintk=serial,ttyAMA0,115200']

    @staticmethod
    def serial_console_args():
        return ['console=ttyAMA0']

    def kimg_path(self):
        return 'arch/arm/boot/zImage'

    def dtb_path(self):
        return 'arch/arm/boot/dts/vexpress-v2p-ca15-tc1.dtb'

class Arch_aarch64(Arch):
    def __init__(self):
        Arch.__init__(self, 'aarch64')

        self.qemuname = 'aarch64'
        self.linuxname = 'arm64'
        self.gccname = 'aarch64'

    @staticmethod
    def qemuargs(is_native):
        ret = Arch.qemuargs(is_native)

        if is_native:
            ret.extend(['-M', 'virt,gic-version=host'])
            ret.extend(['-cpu', 'host'])
        else:
            # Emulate a fully virtual system.
            ret.extend(['-M', 'virt'])

            # Despite being called qemu-system-aarch64, QEMU defaults to
            # emulating a 32-bit CPU.  Override it.
            ret.extend(['-cpu', 'cortex-a57'])


        return ret

    @staticmethod
    def virtio_dev_type(virtiotype):
        return 'virtio-%s-device' % virtiotype

    @staticmethod
    def earlyconsole_args():
        return ['earlyprintk=serial,ttyAMA0,115200']

    @staticmethod
    def serial_console_args():
        return ['console=ttyAMA0']

    def kimg_path(self):
        return 'arch/arm64/boot/Image'

class Arch_ppc64(Arch):
    def __init__(self):
        Arch.__init__(self, 'ppc64')

        self.defconfig_target = 'ppc64_defconfig'
        self.qemuname = 'ppc64'
        self.linuxname = 'powerpc'
        self.gccname = 'ppc64'

    def qemuargs(self, is_native):
        ret = Arch.qemuargs(is_native)

        ret.extend(['-M', 'pseries'])

        return ret

    def kimg_path(self):
        # Apparently SLOF (QEMU's bundled firmware?) can't boot a zImage.
        return 'vmlinux'

class Arch_riscv64(Arch):
    def __init__(self):
        Arch.__init__(self, 'riscv64')

        self.defconfig_target = 'defconfig'
        self.qemuname = 'riscv64'
        self.linuxname = 'riscv'
        self.gccname = 'riscv64'

    def qemuargs(self, is_native):
        ret = Arch.qemuargs(is_native)

        ret.extend(['-machine', 'virt'])
        ret.extend(['-bios', 'default'])

        return ret

    @staticmethod
    def serial_console_args():
        return ['console=ttyS0']

    def kimg_path(self):
        return 'arch/riscv/boot/Image'

class Arch_sparc64(Arch):
    def __init__(self):
        Arch.__init__(self, 'sparc64')

        self.defconfig_target = 'sparc64_defconfig'
        self.qemuname = 'sparc64'
        self.linuxname = 'sparc'
        self.gccname = 'sparc64'

    def qemuargs(self, is_native):
        ret = Arch.qemuargs(is_native)

        return ret

    def kimg_path(self):
        return 'arch/sparc/boot/image'

    def qemu_nodisplay_args(self):
        # qemu-system-sparc fails to boot if -display none is set.
        return ['-nographic', '-vga', 'none']

class Arch_s390x(Arch):
    def __init__(self):
        Arch.__init__(self, 's390x')

        self.qemuname = 's390x'
        self.linuxname = 's390'
        self.gccname = 's390x'

    @staticmethod
    def virtio_dev_type(virtiotype):
        return 'virtio-%s-ccw' % virtiotype

    def qemuargs(self, is_native):
        ret = Arch.qemuargs(is_native)

        # Ask for the latest version of s390-ccw
        ret.extend(['-M', 's390-ccw-virtio'])

        # To be able to configure a console, we need to get rid of the
        # default console
        ret.extend(['-nodefaults'])

        return ret

    @staticmethod
    def config_base():
        return ['CONFIG_MARCH_Z900=y']

    @staticmethod
    def qemu_serial_console_args():
        return ['-device', 'sclpconsole,chardev=console']

ARCHES = {arch.virtmename: arch for arch in [
    Arch_x86('x86_64'),
    Arch_x86('i386'),
    Arch_arm(),
    Arch_aarch64(),
    Arch_ppc64(),
    Arch_riscv64(),
    Arch_sparc64(),
    Arch_s390x(),
]}

def get(arch: str) -> Arch:
    if arch in ARCHES:
        return ARCHES[arch]
    else:
        return Arch_unknown(arch)
