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

import contextlib
import itertools
import os
import platform
import re
import subprocess
import tempfile

from . import util

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


@contextlib.contextmanager
def get_mod_path(moddir, kver):
    """
    Context manager yielding a basedir suitable for `depmod -b <basedir>
    <kver>` and `modprobe -d <basedir> -S <kver>` that resolves to
    `moddir`, exposing it under both usr/lib/modules/<kver> and
    lib/modules/<kver> since different kmod builds only search one or the
    other.
    """
    if not kver or os.path.basename(kver) != kver or kver in (".", ".."):
        raise ValueError(f"invalid kernel version: {kver!r}")

    with tempfile.TemporaryDirectory(prefix="virtme-moddir-") as compat_root:
        compat_moduledir = os.path.join(compat_root, "usr", "lib", "modules")
        os.makedirs(compat_moduledir, exist_ok=True)
        os.symlink(os.path.realpath(moddir), os.path.join(compat_moduledir, kver))
        os.symlink(os.path.join("usr", "lib"), os.path.join(compat_root, "lib"))

        yield compat_root
