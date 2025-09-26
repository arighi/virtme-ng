# -*- mode: python -*-
# Copyright 2023 Andrea Righi

"""virtme-ng version"""

import os
from importlib.metadata import PackageNotFoundError, version
from subprocess import DEVNULL, CalledProcessError, check_output

PKG_VERSION = "1.38"


def get_package_version():
    try:
        return version("virtme-ng")
    except PackageNotFoundError:
        return PKG_VERSION


def get_version_string():
    if os.environ.get("VNG_PACKAGE"):
        return PKG_VERSION

    if not os.environ.get("__VNG_LOCAL"):
        return get_package_version()

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
                f"cd {os.path.dirname(__file__)} && [ -e ../.git ] && git describe --long --dirty",
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
        # If git describe fails to determine a version (e.g. building from the
        # source using a tarball), the version from pip cannot be picked because
        # it might be different than the local one being used here. Fall back to
        # the hard-coded package version then.
        return PKG_VERSION


VERSION = get_version_string()

if __name__ == "__main__":
    print(VERSION)
