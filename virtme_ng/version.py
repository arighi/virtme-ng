# -*- mode: python -*-
# Copyright 2023 Andrea Righi

"""virtme-ng version"""

from subprocess import check_output, DEVNULL, CalledProcessError

PKG_VERSION = "1.25"


def get_version_string():
    try:
        # Get the version from git describe
        version = (
            check_output(
                "git describe --always --long --dirty",
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
