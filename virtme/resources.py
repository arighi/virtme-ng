# -*- mode: python -*-
# resources.py: Find virtme's resources
# Copyright © 2014-2019 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

"""Helpers to find virtme's guest tools and host scripts."""

import shutil
import subprocess
from importlib import resources as importlib_resources

import virtme


def find_guest_tools():
    """Return the path of the guest tools installed with the running virtme."""

    if importlib_resources.files(virtme).joinpath("guest").is_dir():
        return str(importlib_resources.files(virtme) / "guest")

    # No luck.  This is somewhat surprising.
    return None


def find_script(name) -> str:
    # If we're running out of a source checkout, we can find scripts in the
    # 'bin' directory.
    fn = importlib_resources.files(virtme) / "../bin" / name
    if fn.is_file():
        return str(fn)

    # Otherwise assume we're actually installed and in PATH.
    guess = shutil.which(name)
    if guess is not None:
        return guess

    # No luck.  This is somewhat surprising.
    raise FileNotFoundError(f"could not find script {name}")


def run_script(name, **kwargs) -> None:
    fn = find_script(name)
    subprocess.check_call(executable=fn, args=[fn], **kwargs)
