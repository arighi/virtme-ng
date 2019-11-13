# -*- mode: python -*-
# util.py: Misc helpers
# Copyright © 2014-2019 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

from typing import Optional, Sequence

import os
import shutil
import itertools

def find_binary(names: Sequence[str], root: str = '/',
                use_path: bool = True) -> Optional[str]:
    dirs = [os.path.join(*i) for i in itertools.product(
        ['usr/local', 'usr', ''],
        ['bin', 'sbin'])]

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
