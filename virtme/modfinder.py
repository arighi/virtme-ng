# -*- mode: python -*-
# modfinder: A simple tool to resolve required modules
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

"""
This is a poor man's module resolver and loader.  It does not support any
sort of hotplug.  Instead it generates a topological order and loads
everything.  The idea is to require very few modules.
"""

import itertools
import os
import platform
import re
import subprocess

from . import util, virtmods

_INSMOD_RE = re.compile("insmod (.*[^ ]) *$")


def resolve_dep(modalias, root=None, kver=None, moddir=None):
    # /usr/sbin might not be in the path, and modprobe is usually in /usr/sbin
    modprobe = util.find_binary_or_raise(["modprobe"])
    args = [modprobe, "--show-depends"]
    args += ["-C", "/var/empty"]
    if root is not None:
        args += ["-d", root]
    if kver is not None and kver != platform.release():
        # If booting the loaded kernel, skip -S.  This helps certain
        # buggy modprobe versions that don't support -S.
        args += ["-S", kver]
    if moddir is not None:
        args += ["--moddir", moddir]
    args += ["--", modalias]

    deps = []

    try:
        with open("/dev/null", "r+b") as devnull:
            script = subprocess.check_output(args, stderr=devnull.fileno()).decode(
                "utf-8", errors="replace"
            )
        for line in script.split("\n"):
            m = _INSMOD_RE.match(line)
            if m:
                deps.append(m.group(1))
    except subprocess.CalledProcessError:
        pass  # This is most likely because the module is built in.

    return deps


def merge_mods(lists) -> list[str]:
    found: set = set()
    mods = []
    for mod in itertools.chain(*lists):
        if mod not in found:
            found.add(mod)
            mods.append(mod)
    return mods


def find_modules_from_install(aliases, root=None, kver=None, moddir=None):
    return merge_mods(
        resolve_dep(a, root=root, kver=kver, moddir=moddir) for a in aliases
    )


def get_mod_path(path, kver):
    """
    There are cases where the path to the modules dir can conflictn with
    depmod. For example, if root_dir points to /../dir/usr, and the default
    depmod module path is /usr/lib/modules, it won't find the modules path
    to create modules.dep inside /../dir/usr/usr/lib/modules/, and making
    depmod/modprobe to not work properly.

    Execute modprobe, using the first of the virtmods, on the given path until
    it find a working directory.
    """
    modprobe = util.find_binary_or_raise(["modprobe"])

    while path and path != "/":
        try:
            subprocess.run(
                [modprobe, "--show-depends", "-C", "/var/empty", "-d", path, "-S", kver, "--",
                    virtmods.MODALIASES[0]],
                check=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL
            )

            return path

        except subprocess.CalledProcessError:
            pass  # This is most likely because the module is built in.

        path, _ = os.path.split(path)

    return None
