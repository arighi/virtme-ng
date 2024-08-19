# -*- mode: python -*-
# virtme-configkernel: Configure a kernel for virtme
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

from typing import Optional

import sys
import argparse
import os
import shlex
import shutil
import subprocess
import multiprocessing
from .. import architectures
from ..util import SilentError, uname


def make_parser():
    parser = argparse.ArgumentParser(
        description="Configure a kernel for virtme",
    )

    parser.add_argument(
        "--arch",
        action="store",
        metavar="ARCHITECTURE",
        default=uname.machine,
        help="Target architecture",
    )

    parser.add_argument(
        "--cross-compile",
        action="store",
        metavar="CROSS_COMPILE_PREFIX",
        help="Cross-compile compiler prefix",
    )

    parser.add_argument(
        "--custom",
        action="append",
        metavar="CUSTOM",
        help="Use a custom config snippet file to override specific config options",
    )

    parser.add_argument(
        "--configitem",
        action="append",
        metavar="CONFITEM",
        help="add or alter a (CONFIG_)?FOO=bar item",
    )

    parser.add_argument(
        "--no-update",
        action="store_true",
        help="Skip if the config file already exists",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="get chatty about config assembled",
    )

    g = parser.add_argument_group(title="Mode").add_mutually_exclusive_group()

    g.add_argument(
        "--allnoconfig",
        action="store_true",
        help="Overwrite configuration with a virtme-suitable allnoconfig (unlikely to work)",
    )

    g.add_argument(
        "--defconfig",
        action="store_true",
        help="Overwrite configuration with a virtme-suitable defconfig",
    )

    g.add_argument(
        "--update", action="store_true", help="Update existing config for virtme"
    )

    parser.add_argument(
        "envs",
        metavar="envs",
        type=str,
        nargs="*",
        help="Additional Makefile variables",
    )

    return parser


_ARGPARSER = make_parser()


def arg_fail(message):
    print(message)
    _ARGPARSER.print_usage()
    sys.exit(1)


_GENERIC_CONFIG = [
    "##: Generic",
    "CONFIG_UEVENT_HELPER=n",  # Obsolete and slow
    "CONFIG_VIRTIO=y",
    "CONFIG_VIRTIO_PCI=y",
    "CONFIG_VIRTIO_MMIO=y",
    "CONFIG_VIRTIO_BALLOON=y",
    "CONFIG_NET=y",
    "CONFIG_NET_CORE=y",
    "CONFIG_NETDEVICES=y",
    "CONFIG_NETWORK_FILESYSTEMS=y",
    "CONFIG_INET=y",
    "CONFIG_NET_9P=y",
    "CONFIG_NET_9P_VIRTIO=y",
    "CONFIG_9P_FS=y",
    "CONFIG_VIRTIO_NET=y",
    "CONFIG_CMDLINE_OVERRIDE=n",
    "CONFIG_BINFMT_SCRIPT=y",
    "CONFIG_SHMEM=y",
    "CONFIG_TMPFS=y",
    "CONFIG_UNIX=y",
    "CONFIG_MODULE_SIG_FORCE=n",
    "CONFIG_DEVTMPFS=y",
    "CONFIG_TTY=y",
    "CONFIG_VT=y",
    "CONFIG_UNIX98_PTYS=y",
    "CONFIG_EARLY_PRINTK=y",
    "CONFIG_INOTIFY_USER=y",
    "",
    "##: virtio-scsi support",
    "CONFIG_BLOCK=y",
    "CONFIG_SCSI_LOWLEVEL=y",
    "CONFIG_SCSI=y",
    "CONFIG_SCSI_VIRTIO=y",
    "CONFIG_BLK_DEV_SD=y",
    "",
    "##: virt-serial support",
    "CONFIG_VIRTIO_CONSOLE=y",
    "",
    "##: watchdog (useful for test scripts)",
    "CONFIG_WATCHDOG=y",
    "CONFIG_WATCHDOG_CORE=y",
    "CONFIG_I6300ESB_WDT=y",
    "##: Make sure debuginfo are available",
    "CONFIG_DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT=y",
    "##: Enable overlayfs",
    "CONFIG_OVERLAY_FS=y",
    "##: virtio-fs support",
    "CONFIG_DAX=y",
    "CONFIG_DAX_DRIVER=y",
    "CONFIG_FS_DAX=y",
    "CONFIG_MEMORY_HOTPLUG=y",
    "CONFIG_MEMORY_HOTREMOVE=y",
    "CONFIG_ZONE_DEVICE=y",
    "CONFIG_FUSE_FS=y",
    "CONFIG_VIRTIO_FS=y",
]

_GENERIC_CONFIG_OPTIONAL = [
    "##: initramfs support",
    "CONFIG_BLK_DEV_INITRD=y",
    "##: BPF stuff & useful debugging features",
    "CONFIG_BPF=y",
    "CONFIG_BPF_SYSCALL=y",
    "CONFIG_BPF_JIT=y",
    "CONFIG_HAVE_EBPF_JIT=y",
    "CONFIG_BPF_EVENTS=y",
    "CONFIG_FTRACE_SYSCALLS=y",
    "CONFIG_FUNCTION_TRACER=y",
    "CONFIG_HAVE_DYNAMIC_FTRACE=y",
    "CONFIG_DYNAMIC_FTRACE=y",
    "CONFIG_HAVE_KPROBES=y",
    "CONFIG_KPROBES=y",
    "CONFIG_KPROBE_EVENTS=y",
    "CONFIG_ARCH_SUPPORTS_UPROBES=y",
    "CONFIG_UPROBES=y",
    "CONFIG_UPROBE_EVENTS=y",
    "CONFIG_DEBUG_FS=y",
    "##: Required to generate memory dumps for drgn",
    "CONFIG_FW_CFG_SYSFS=y",
    "CONFIG_FW_CFG_SYSFS_CMDLINE=y",
    "##: Graphics support",
    "CONFIG_DRM=y",
    "CONFIG_DRM_VIRTIO_GPU=y",
    "CONFIG_DRM_VIRTIO_GPU_KMS=y",
    "CONFIG_DRM_BOCHS=y",
    "CONFIG_VIRTIO_IOMMU=y",
    "##: Sound support",
    "CONFIG_SOUND=y",
    "CONFIG_SND=y",
    "CONFIG_SND_SEQUENCER=y",
    "CONFIG_SND_PCI=y",
    "CONFIG_SND_INTEL8X0=y",
    "CONFIG_SND_HDA_CODEC_REALTEK=y",
    "# CONFIG_SND_DRIVERS is not set",
    "# CONFIG_SND_X86 is not set",
    "# CONFIG_SND_PCMCIA is not set",
    "# Required to run snaps",
    "CONFIG_SECURITYFS=y",
    "CONFIG_CGROUP_BPF=y",
    "CONFIG_SQUASHFS=y",
    "CONFIG_SQUASHFS_XZ=y",
    "CONFIG_SQUASHFS_ZSTD=y",
    "CONFIG_FUSE_FS=y",
    "# Unnecessary configs",
    "# CONFIG_LOCALVERSION_AUTO is not set",
    "# CONFIG_TEST_KMOD is not set",
    "# CONFIG_USB is not set",
    "# CONFIG_CAN is not set",
    "# CONFIG_BLUETOOTH is not set",
    "# CONFIG_I2C is not set",
    "# CONFIG_USB_HID is not set",
    "# CONFIG_HID is not set",
    "# CONFIG_TIGON3 is not set",
    "# CONFIG_BNX2X is not set",
    "# CONFIG_CHELSIO_T1 is not set",
    "# CONFIG_BE2NET is not set",
    "# CONFIG_S2IO is not set",
    "# CONFIG_EHEA is not set",
    "# CONFIG_E100 is not set",
    "# CONFIG_IXGB is not set",
    "# CONFIG_IXGBE is not set",
    "# CONFIG_I40E is not set",
    "# CONFIG_MLX4_EN is not set",
    "# CONFIG_MLX5_CORE is not set",
    "# CONFIG_MYRI10GE is not set",
    "# CONFIG_NETXEN_NIC is not set",
    "# CONFIG_NFS_FS is not set",
    "# CONFIG_IPV6 is not set",
    "# CONFIG_AUDIT is not set",
    "# CONFIG_SECURITY is not set",
    "# CONFIG_WIRELESS is not set",
    "# CONFIG_WLAN is not set",
    "# CONFIG_SCHED_MC is not set",
    "# CONFIG_CPU_FREQ is not set",
    "# CONFIG_INFINIBAND is not set",
    "# CONFIG_PPP is not set",
    "# CONFIG_PPPOE is not set",
    "# CONFIG_EXT2_FS is not set",
    "# CONFIG_REISERFS_FS not set",
    "# CONFIG_JFS_FS is not set",
    "# CONFIG_XFS_FS is not set",
    "# CONFIG_BTRFS_FS is not set",
    "# CONFIG_HFS_FS is not set",
    "# CONFIG_HFSPLUS_FS is not set",
    "# CONFIG_SCSI_FC_ATTRS is not set",
    "# CONFIG_SCSI_CXGB3_ISCSI is not set",
    "# CONFIG_SCSI_CXGB4_ISCSI is not set",
    "# CONFIG_SCSI_BNX2_ISCSI is not set",
    "# CONFIG_BE2ISCSI is not set",
    "# CONFIG_SCSI_MPT2SAS is not set",
    "# CONFIG_SCSI_IBMVFC is not set",
    "# CONFIG_SCSI_SYM53C8XX_2 is not set",
    "# CONFIG_SCSI_IPR is not set",
    "# CONFIG_SCSI_QLA_FC is not set",
    "# CONFIG_SCSI_QLA_ISCSI is not set",
    "# CONFIG_SCSI_DH is not set",
    "# CONFIG_FB_MATROX is not set",
    "# CONFIG_FB_RADEON is not set",
    "# CONFIG_FB_IBM_GXT4500 is not set",
    "# CONFIG_FB_VESA is not set",
    "# CONFIG_YENTA is not set",
    "# CONFIG_NETFILTER is not set",
    "# CONFIG_RFKILL is not set",
    "# CONFIG_ETHERNET is not set",
    "# CONFIG_BLK_DEV_SR is not set",
    "# CONFIG_TCP_MD5SIG is not set",
    "# CONFIG_XFRM_USER is not set",
    "# CONFIG_CRYPTO is not set",
    "# CONFIG_EXT4_FS is not set",
    "# CONFIG_VFAT_FS is not set",
    "# CONFIG_FAT_FS is not set",
    "# CONFIG_MSDOS_FS is not set",
    "# CONFIG_AUTOFS4_FS is not set",
    "# CONFIG_AUTOFS_FS is not set",
    "# CONFIG_NVRAM is not set",
]


def do_it():
    args = _ARGPARSER.parse_args()

    arch = architectures.get(args.arch)

    custom_conf = []
    if args.custom:
        for conf_chunk in args.custom:
            with open(conf_chunk, "r", encoding="utf-8") as fd:
                custom_conf += fd.readlines()

    if args.verbose:
        print(f"custom:\n{custom_conf}")

    mod_conf = []
    if args.configitem:
        mod_conf += ["##: final config-item mods"]
        for conf_item in args.configitem:
            if not conf_item.startswith("CONFIG_"):
                conf_item = "CONFIG_" + conf_item
            mod_conf += [conf_item]

    if args.verbose:
        print(f"mods:\n{mod_conf}")

    conf = (
        _GENERIC_CONFIG_OPTIONAL
        + ["##: Arch-specific options"]
        + arch.config_base()
        + custom_conf
        + mod_conf
        + _GENERIC_CONFIG
    )

    if args.verbose:
        print(f"conf:\n{conf}")

    linuxname = shlex.quote(arch.linuxname)
    archargs = [f"ARCH={linuxname}"]

    cross_compile_prefix = f"{arch.gccname}-linux-gnu-"
    if args.cross_compile != "":
        cross_compile_prefix = args.cross_compile

    if shutil.which(f"{cross_compile_prefix}-gcc") and arch.gccname != uname.machine:
        gccname = shlex.quote(f"{cross_compile_prefix}-gcc")
        archargs.append(f"CROSS_COMPILE={gccname}")

    maketarget: Optional[str]

    updatetarget = ""
    if args.allnoconfig:
        maketarget = "allnoconfig"
        updatetarget = "syncconfig"
    elif args.defconfig:
        maketarget = arch.defconfig_target
        updatetarget = "olddefconfig"
    elif args.update:
        if args.no_update:
            arg_fail("--update and --no-update cannot be used together")
        maketarget = None
        updatetarget = "olddefconfig"
    else:
        arg_fail("No mode selected")

    # Propagate additional Makefile variables
    for var in args.envs:
        if var.startswith("O="):
            # Setting "O=..." takes precedence over KBUILD_OUTPUT.
            os.environ["KBUILD_OUTPUT"] = var[2:]

        archargs.append(shlex.quote(var))

    # Determine if an initial config is present
    config = ".config"
    makef = "Makefile"

    # Check if KBUILD_OUTPUT is defined and if it's a directory
    config_dir = os.environ.get("KBUILD_OUTPUT", "")
    if config_dir and os.path.isdir(config_dir):
        config = os.path.join(config_dir, config)
        makef = os.path.join(config_dir, makef)

    if os.path.exists(config):
        if args.no_update:
            print(f"{config} file exists: no modifications have been done")
            return 0
    else:
        if args.update:
            print(f"Error: {config} file is missing")
            return 1

    if maketarget is not None:
        make_args = []
        if not os.path.exists(makef):
            if args.verbose:
                sys.stderr.write(f"missing {makef}, adding -f $src/Makefile\n")
            if os.path.exists("Makefile"):
                # assuming we're in linux srcdir
                make_args = ["-f", str(os.path.abspath("Makefile"))]
                if args.verbose:
                    sys.stderr.write(f"adding make_args: {make_args}\n")
        try:
            subprocess.check_call(["make"] + make_args + archargs + [maketarget])
        except Exception as exc:
            raise SilentError() from exc

    # Append virtme configs
    if args.verbose:
        sys.stderr.write(f"appending to config: {config}\n")
    with open(config, "ab") as conffile:
        conffile.write("\n".join(conf).encode("utf-8"))

    # Run the update target
    try:
        subprocess.check_call(["make"] + archargs + [updatetarget])
    except Exception as exc:
        raise SilentError() from exc

    make_args = " ".join(archargs)
    cpu_count = multiprocessing.cpu_count()
    print(f"Configured.  Build with 'make {make_args} -j{cpu_count}'")

    return 0


def main() -> int:
    try:
        return do_it()
    except SilentError:
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SilentError:
        sys.exit(1)
