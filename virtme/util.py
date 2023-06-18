# -*- mode: python -*-
# util.py: Misc helpers
# Copyright © 2014-2019 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

from typing import Optional, Sequence

import os
import shutil
import getpass
import itertools

uname = os.uname()


class SilentError(Exception):
    pass


def get_username():
    """Reliably get current username."""
    try:
        username = getpass.getuser()
    except OSError:
        # If getpass.getuser() fails, try alternative methods
        username = os.getenv("USER") or os.getenv("LOGNAME")
    return username


def check_kernel_repo():
    if not os.path.isfile("scripts/kconfig/merge_config.sh") and not os.path.isfile(
        "source/scripts/kconfig/merge_config.sh"
    ):
        return False
    return True


def find_binary(
    names: Sequence[str], root: str = "/", use_path: bool = True
) -> Optional[str]:
    dirs = [
        os.path.join(*i)
        for i in itertools.product(["usr/local", "usr", ""], ["bin", "sbin"])
    ]

    for n in names:
        if use_path:
            # Search PATH first
            path = shutil.which(n)
            if path is not None:
                return path

        for d in dirs:
            path = os.path.join(root, d, n)
            if os.path.isfile(path):
                return path

    # We give up.
    return None


def find_binary_or_raise(
    names: Sequence[str], root: str = "/", use_path: bool = True
) -> str:
    ret = find_binary(names, root=root, use_path=use_path)
    if ret is None:
        raise RuntimeError("Could not find %r" % names)
    return ret
