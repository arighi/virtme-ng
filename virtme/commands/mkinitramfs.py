# -*- mode: python -*-
# virtme-mkinitramfs: Generate an initramfs image for virtme
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

import argparse
import modfinder
import virtmods
import mkinitramfs

_ARGPARSER = argparse.ArgumentParser(
    description='Generate initramfs image for virtme',
)
_ARGPARSER.add_argument('--mod-kversion', action='store', default=None)
_ARGPARSER.add_argument('--rw', action='store_true', default=False)

def main():
    import sys

    args = _ARGPARSER.parse_args()

    config = mkinitramfs.Config()

    if args.mod_kversion is not None:
        config.modfiles = modfinder.find_modules_from_install(
            virtmods.MODALIASES, kver=args.mod_kversion)

    if args.rw:
        config.access = 'rw'

    mkinitramfs.mkinitramfs(sys.stdout.buffer, config)

    return 0

if __name__ == '__main__':
    exit(main())
