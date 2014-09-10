# -*- mode: python -*-
# resources.py: Find virtme's resources
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

"""Helpers to find virtme's guest tools."""

import os
import pkg_resources

def find_dist_guest_tools():
    """Return the path of the guest tools installed with the running virtme.

    This is much more complicated than it deserves to be.
    """

    # First try: look for an ordinary resource.  This will succeed when
    # running from the source tree, but it is unlikely to succeed
    # if we're running out of any sort of installation.
    if pkg_resources.resource_isdir(__name__, 'guest'):
        return pkg_resources.resource_filename(__name__, 'guest')

    # Second try: look for a distribution resource.
    provider = pkg_resources.get_provider(__name__)
    if provider.egg_info is not None:
        dist = pkg_resources.Distribution.from_filename(provider.egg_root)
        req = dist.as_requirement()
        if pkg_resources.resource_isdir(req, 'share/virtme-guest-0'):
            return pkg_resources.resource_filename(req, 'share/virtme-guest-0')

    # No luck.  This is somewhat surprising.
    return None

def find_installed_guest_tools(root):
    def has_dir(path):
        # Don't use os.path.join: we want to treat absolute paths
        # as relative.
        return os.path.isdir(root + '/' + path)

    if has_dir('usr/local/share/virtme-guest-0'):
        return '/usr/local/share/virtme-guest-0'
    elif has_dir('usr/share/virtme-guest-0'):
        return 'usr/share/virtme-guest-0'
    else:
        return None

def find_best_guest_tools(root):
    """Returns the path to the best choice of guest tools.

    This returns a tuple (in_guest, relative_path).  If in_guest is true,
    then relative_path is guaranteed to be relative.
    """

    # Always prefer the installed guest tools.  This way blocking access
    # to /home is more likely to work.
    path = find_installed_guest_tools(root)
    if path is not None:
        return (True, path)

    # Now try the host's copy.  This is here to keep root != '/' as consistent
    # as possible
    if root != '/':
        path = find_installed_guest_tools('/')
        if path is not None:
            return (False, path)

    # Now try the dist copy.
    path = find_dist_guest_tools()
    if path is not None:
        return (root == '/', os.path.relpath(path, '/'))

    return (None, None)
