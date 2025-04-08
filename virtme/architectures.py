# -*- mode: python -*-
# qemu_helpers: Helpers to find QEMU and handle its quirks
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

import os
from typing import List, Optional


class Arch:
    def __init__(self, name) -> None:
        self.virtmename = name
        self.qemuname = name
        self.linuxname = name
        self.gccname = name

    defconfig_target = "defconfig"

    @staticmethod
    def virtiofs_support() -> bool:
        return False

    @staticmethod
    def numa_support() -> bool:
        return True

    @staticmethod
    def qemuargs(is_native, use_kvm, use_gpu) -> List[str]:
        _ = is_native
        _ = use_kvm
        _ = use_gpu
        return []

    @staticmethod
    def virtio_dev_type(virtiotype) -> str:
        # Return a full name for a virtio device.  It would be
        # nice if QEMU abstracted this away, but it doesn't.
        return f"virtio-{virtiotype}-pci"

    @staticmethod
    def vhost_dev_type(vhosttype) -> str:
        return f"vhost-{vhosttype}-pci"

    @staticmethod
    def earlyconsole_args() -> List[str]:
        return []

    @staticmethod
    def serial_console_args() -> List[str]:
        return []

    @staticmethod
    def qemu_nodisplay_args() -> List[str]:
        return ["-vga", "none", "-display", "none"]

    @staticmethod
    def qemu_nodisplay_nvgpu_args() -> List[str]:
        return ["-display", "none"]

    @staticmethod
    def qemu_display_args() -> List[str]:
        return ["-device", "virtio-gpu-pci"]

    @staticmethod
    def qemu_sound_args() -> List[str]:
        return []

    @staticmethod
    def qemu_vmcoreinfo_args() -> List[str]:
        return ["-device", "vmcoreinfo"]

    @staticmethod
    def qemu_serial_console_args() -> List[str]:
        # We should be using the new-style -device serialdev,chardev=xyz,
        # but many architecture-specific serial devices don't support that.
        return ["-serial", "chardev:console"]

    @staticmethod
    def config_base() -> List[str]:
        return []

    def kimg_path(self) -> str:
        return f"arch/{self.linuxname}/boot/bzImage"

    def img_name(self) -> List[str]:
        return ["vmlinuz"]

    @staticmethod
    def dtb_path() -> Optional[str]:
        return None


class Arch_unknown(Arch):
    @staticmethod
    def qemuargs(is_native, use_kvm, use_gpu):
        return Arch.qemuargs(is_native, use_kvm, use_gpu)


class Arch_x86(Arch):
    def __init__(self, name):
        Arch.__init__(self, name)

        self.linuxname = "x86"
        self.defconfig_target = f"{name}_defconfig"

    @staticmethod
    def virtiofs_support() -> bool:
        return True

    @staticmethod
    def qemuargs(is_native, use_kvm, use_gpu):
        ret = Arch.qemuargs(is_native, use_kvm, use_gpu)

        # Add a watchdog.  This is useful for testing.
        ret.extend(["-device", "i6300esb,id=watchdog0"])

        if is_native and use_kvm:
            # If we're likely to use KVM, request a full-featured CPU.
            # (NB: if KVM fails, this will cause problems.  We should probe.)
            cpu_str = "host"
            if use_gpu:
                cpu_str += ",host-phys-bits-limit=0x28"
            ret.extend(["-cpu", cpu_str])
        else:
            ret.extend(["-machine", "q35"])

        return ret

    @staticmethod
    def qemu_sound_args() -> List[str]:
        return [
            "-audiodev",
            "sdl,id=snd0",
            "-device",
            "intel-hda",
            "-device",
            "hda-output,audiodev=snd0",
        ]

    @staticmethod
    def earlyconsole_args():
        return ["earlyprintk=serial,ttyS0,115200"]

    @staticmethod
    def serial_console_args():
        return ["ttyS0"]

    @staticmethod
    def config_base():
        return [
            "CONFIG_SERIO=y",
            "CONFIG_PCI=y",
            "CONFIG_INPUT=y",
            "CONFIG_INPUT_KEYBOARD=y",
            "CONFIG_KEYBOARD_ATKBD=y",
            "CONFIG_SERIAL_8250=y",
            "CONFIG_SERIAL_8250_CONSOLE=y",
            "CONFIG_X86_VERBOSE_BOOTUP=y",
            "CONFIG_VGA_CONSOLE=y",
            "CONFIG_FB=y",
            "CONFIG_FB_VESA=y",
            "CONFIG_FRAMEBUFFER_CONSOLE=y",
            "CONFIG_RTC_CLASS=y",
            "CONFIG_RTC_HCTOSYS=y",
            "CONFIG_RTC_DRV_CMOS=y",
            "CONFIG_HYPERVISOR_GUEST=y",
            "CONFIG_PARAVIRT=y",
            "CONFIG_KVM_GUEST=y",
            # Depending on the host kernel, virtme can nest!
            "CONFIG_KVM=y",
            "CONFIG_KVM_INTEL=y",
            "CONFIG_KVM_AMD=y",
        ]


class Arch_microvm(Arch_x86):
    @staticmethod
    def virtio_dev_type(virtiotype):
        return f"virtio-{virtiotype}-device"

    @staticmethod
    def vhost_dev_type(vhosttype) -> str:
        return f"vhost-{vhosttype}-device"

    @staticmethod
    def qemu_display_args() -> List[str]:
        return [
            "-device",
            "virtio-keyboard-device",
            "-device",
            "virtio-tablet-device",
            "-device",
            "virtio-gpu-device",
            "-global",
            "virtio-mmio.force-legacy=false",
        ]

    @staticmethod
    def qemuargs(is_native, use_kvm, use_gpu):
        ret = Arch.qemuargs(is_native, use_kvm, use_gpu)

        # Use microvm architecture for faster boot
        ret.extend(["-M", "microvm,accel=kvm,pcie=on,rtc=on"])

        if is_native and use_kvm:
            # If we're likely to use KVM, request a full-featured CPU.
            # (NB: if KVM fails, this will cause problems.  We should probe.)
            ret.extend(["-cpu", "host"])  # We can't migrate regardless.

        return ret


class Arch_arm(Arch):
    def __init__(self):
        Arch.__init__(self, "arm")

        self.defconfig_target = "vexpress_defconfig"

    @staticmethod
    def qemuargs(is_native, use_kvm, use_gpu):
        ret = Arch.qemuargs(is_native, use_kvm, use_gpu)

        # Emulate a vexpress-a15.
        ret.extend(["-M", "vexpress-a15"])

        # NOTE: consider adding a PCI bus (and figuring out how)
        #
        # This won't boot unless -dtb is set, but we need to figure out
        # how to find the dtb file.

        return ret

    @staticmethod
    def qemu_display_args() -> List[str]:
        return ["-device", "virtio-gpu-device"]

    @staticmethod
    def virtio_dev_type(virtiotype):
        return f"virtio-{virtiotype}-device"

    @staticmethod
    def earlyconsole_args():
        return ["earlyprintk=serial,ttyAMA0,115200"]

    @staticmethod
    def serial_console_args():
        return ["ttyAMA0"]

    def kimg_path(self):
        return "arch/arm/boot/zImage"

    @staticmethod
    def dtb_path():
        if os.path.exists("arch/arm/boot/dts/arm/vexpress-v2p-ca15-tc1.dtb"):
            return "arch/arm/boot/dts/arm/vexpress-v2p-ca15-tc1.dtb"
        if os.path.exists("arch/arm/boot/dts/vexpress-v2p-ca15-tc1.dtb"):
            return "arch/arm/boot/dts/vexpress-v2p-ca15-tc1.dtb"
        return None


class Arch_aarch64(Arch):
    def __init__(self, name):
        Arch.__init__(self, name)

        self.qemuname = "aarch64"
        self.linuxname = "arm64"
        self.gccname = "aarch64"

    @staticmethod
    def virtiofs_support() -> bool:
        return True

    @staticmethod
    def qemuargs(is_native, use_kvm, use_gpu):
        ret = Arch.qemuargs(is_native, use_kvm, use_gpu)

        if is_native and use_kvm:
            ret.extend(["-M", "virt,gic-version=host"])
            ret.extend(["-cpu", "host"])
        else:
            # Emulate a fully virtual system.
            ret.extend(["-M", "virt"])

            # Despite being called qemu-system-aarch64, QEMU defaults to
            # emulating a 32-bit CPU.  Override it.
            ret.extend(["-cpu", "cortex-a57"])

        return ret

    @staticmethod
    def virtio_dev_type(virtiotype):
        return f"virtio-{virtiotype}-device"

    @staticmethod
    def earlyconsole_args():
        return ["earlyprintk=serial,ttyAMA0,115200"]

    @staticmethod
    def serial_console_args():
        return ["ttyAMA0"]

    def kimg_path(self):
        return "arch/arm64/boot/Image"


class Arch_ppc(Arch):
    def __init__(self, name):
        Arch.__init__(self, name)

        self.defconfig_target = "pseries_defconfig"
        self.qemuname = "ppc64"
        self.linuxname = "powerpc"
        self.gccname = "powerpc64le"

    @staticmethod
    def qemuargs(is_native, use_kvm, use_gpu):
        ret = Arch.qemuargs(is_native, use_kvm, use_gpu)
        ret.extend(["-M", "pseries"])

        return ret

    @staticmethod
    def config_base():
        return [
            "CONFIG_CPU_LITTLE_ENDIAN=y",
            "CONFIG_PPC_POWERNV=n",
            "CONFIG_PPC_SUBPAGE_PROT=y",
            "CONFIG_KVM_BOOK3S_64=y",
            "CONFIG_ZONE_DEVICE=y",
        ]

    def kimg_path(self):
        # Apparently SLOF (QEMU's bundled firmware?) can't boot a zImage.
        return "vmlinux"

    def img_name(self) -> List[str]:
        return ["vmlinux"]


class Arch_riscv64(Arch):
    def __init__(self):
        Arch.__init__(self, "riscv64")

        self.defconfig_target = "defconfig"
        self.linuxname = "riscv"

    @staticmethod
    def virtiofs_support() -> bool:
        return True

    @staticmethod
    def qemuargs(is_native, use_kvm, use_gpu):
        ret = Arch.qemuargs(is_native, use_kvm, use_gpu)
        ret.extend(["-machine", "virt"])
        ret.extend(["-bios", "default"])

        return ret

    @staticmethod
    def serial_console_args():
        return ["ttyS0"]

    def kimg_path(self):
        return "arch/riscv/boot/Image"


class Arch_sparc64(Arch):
    def __init__(self):
        Arch.__init__(self, "sparc64")

        self.defconfig_target = "sparc64_defconfig"
        self.linuxname = "sparc"

    @staticmethod
    def qemuargs(is_native, use_kvm, use_gpu):
        return Arch.qemuargs(is_native, use_kvm, use_gpu)

    def kimg_path(self):
        return "arch/sparc/boot/image"

    @staticmethod
    def qemu_nodisplay_args():
        # qemu-system-sparc fails to boot if -display none is set.
        return ["-nographic", "-vga", "none"]


class Arch_s390x(Arch):
    def __init__(self):
        Arch.__init__(self, "s390x")

        self.linuxname = "s390"

    @staticmethod
    def virtiofs_support() -> bool:
        return True

    @staticmethod
    def numa_support() -> bool:
        return False

    @staticmethod
    def virtio_dev_type(virtiotype):
        return f"virtio-{virtiotype}-ccw"

    @staticmethod
    def vhost_dev_type(vhosttype) -> str:
        return f"vhost-{vhosttype}-ccw"

    @staticmethod
    def qemuargs(is_native, use_kvm, use_gpu):
        ret = Arch.qemuargs(is_native, use_kvm, use_gpu)

        # Ask for the latest version of s390-ccw
        ret.extend(["-M", "s390-ccw-virtio"])

        if is_native and use_kvm:
            ret.extend(["-cpu", "host"])

        # Add a watchdog. This is useful for testing.
        ret.extend(["-device", "diag288,id=watchdog0"])

        # To be able to configure a console, we need to get rid of the
        # default console
        ret.extend(["-nodefaults"])

        return ret

    @staticmethod
    def qemu_display_args() -> List[str]:
        return ["-device", "virtio-gpu-ccw,devno=fe.0.0101"]

    @staticmethod
    def config_base():
        return ["CONFIG_MARCH_Z900=y", "CONFIG_DIAG288_WATCHDOG=y"]

    @staticmethod
    def serial_console_args() -> List[str]:
        return ["ttysclp0"]

    @staticmethod
    def qemu_serial_console_args():
        return ["-device", "sclpconsole,chardev=console"]

    @staticmethod
    def earlyconsole_args() -> List[str]:
        return ["earlyprintk=sclp"]

    @staticmethod
    def qemu_vmcoreinfo_args() -> List[str]:
        return []

    def img_name(self) -> List[str]:
        return ["vmlinuz", "image"]


ARCHES = {
    arch.virtmename: arch
    for arch in [
        Arch_microvm("microvm"),
        Arch_x86("x86_64"),
        Arch_x86("i386"),
        Arch_arm(),
        Arch_aarch64("aarch64"),
        Arch_aarch64("arm64"),
        Arch_ppc("ppc64"),
        Arch_ppc("ppc64le"),
        Arch_riscv64(),
        Arch_sparc64(),
        Arch_s390x(),
    ]
}


def get(arch: str) -> Arch:
    if arch in ARCHES:
        return ARCHES[arch]
    return Arch_unknown(arch)
