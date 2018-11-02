# -*- mode: python -*-
# resources.py: Find virtme's resources
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

"""Helpers to find virtme's guest tools."""

import os
import pkg_resources

def find_guest_tools():
    """Return the path of the guest tools installed with the running virtme.
    """

    if pkg_resources.resource_isdir(__name__, 'guest'):
        return pkg_resources.resource_filename(__name__, 'guest')

    # No luck.  This is somewhat surprising.
    return None
