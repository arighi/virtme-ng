# -*- mode: python -*-
# Copyright 2023 Andrea Righi

"""virtme-ng version"""

import os
from subprocess import check_output, DEVNULL, CalledProcessError

PKG_VERSION = "1.25"


def get_version_string():
    try:
        # Get the version from `git describe`.
        #
        # Make sure to get the proper git repository by using the directory
        # that contains this file and also make sure that the parent is a
        # virtme-ng repository.
        #
        # Otherwise fallback to the static version defined in PKG_VERSION.
        version = (
            check_output(
                "cd %s && [ -e ../.git ] && git describe --always --long --dirty" % os.path.dirname(__file__),
                shell=True,
                stderr=DEVNULL,
            )
            .decode("utf-8")
            .strip()
        )

        # Remove the 'v' prefix if present
        if version.startswith("v"):
            version = version[1:]

        # Replace hyphens with plus sign for build metadata
        version_pep440 = version.replace("-", "+", 1).replace("-", ".")

        return version_pep440
    except CalledProcessError:
        # Default version if git describe fails (e.g., when building virtme-ng
        # from a source package.
        return PKG_VERSION


VERSION = get_version_string()

if __name__ == "__main__":
    print(VERSION)
