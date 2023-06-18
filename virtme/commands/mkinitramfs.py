# -*- mode: python -*-
# virtme-mkinitramfs: Generate an initramfs image for virtme
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

import sys
import argparse
from .. import modfinder
from .. import virtmods
from .. import mkinitramfs


def make_parser():
    parser = argparse.ArgumentParser(
        description="Generate an initramfs image for virtme",
    )

    parser.add_argument(
        "--mod-kversion",
        action="store",
        default=None,
        help="Find kernel modules related to kernel version set",
    )

    parser.add_argument(
        "--rw",
        action="store_true",
        default=False,
        help="Mount initramfs as rw. Default is ro",
    )

    parser.add_argument(
        "--outfile",
        action="store",
        default=None,
        help="Filename of the resulting initramfs file. Default: send initramfs to stdout",
    )

    return parser


def main():
    args = make_parser().parse_args()

    config = mkinitramfs.Config()

    if args.mod_kversion is not None:
        config.modfiles = modfinder.find_modules_from_install(
            virtmods.MODALIASES, kver=args.mod_kversion
        )

    # search for busybox in the root filesystem
    config.busybox = mkinitramfs.find_busybox(root="/", is_native=True)

    if args.rw:
        config.access = "rw"

    with (
        sys.stdout.buffer if args.outfile is None else open(args.outfile, "w+b")
    ) as buf:
        mkinitramfs.mkinitramfs(buf, config)

    return 0


if __name__ == "__main__":
    sys.exit(main())
