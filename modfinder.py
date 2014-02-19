#!/usr/bin/python3
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

import re
import subprocess
import os.path
import itertools

_INSMOD_RE = re.compile('insmod (.*[^ ]) *$')

def resolve_dep(modalias, root=None, kver=None):
    args = ['modprobe', '--show-depends']
    args += ['-C', '/var/empty']
    if root is not None:
        args += ['-d', root]
    if kver is not None:
        args += ['-S', kver]
    args += ['--', modalias]

    deps = []

    script = subprocess.check_output(args).decode('utf-8', errors='replace')
    for line in script.split('\n'):
        m = _INSMOD_RE.match(line)
        if m:
            deps.append(m.group(1))

    return deps

def merge_mods(lists):
    found = set()
    mods = []
    for mod in itertools.chain(*lists):
        if mod not in found:
            found.add(mod)
            mods.append(mod)
    return mods

def find_modules_from_install(aliases, root=None, kver=None):
    return merge_mods(resolve_dep(a, root=root, kver=kver) for a in aliases)

def find_modules_from_kernelbuild(modpaths, kdir):
    ret = []
    for p in modpaths:
        fullpath = os.path.join(kdir, p)
        if os.path.isfile(fullpath):
            ret.append(fullpath)
    return ret

def generate_modpaths(aliases):
    """
    This is a hack that only really works on an allmodconfig kernel.
    """
    kver = os.uname().release
    start = '/lib/modules/%s' % kver
    paths = find_modules_from_install(aliases, kver=kver)
    print('MODPATHS = [')
    for p in paths:
        print('    %r,' % os.path.relpath(p, start))
    print(']')
