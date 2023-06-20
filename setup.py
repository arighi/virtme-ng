#!/usr/bin/env python3

import os
import sys
from glob import glob
from subprocess import check_call, CalledProcessError
from setuptools import setup, Command
from setuptools.command.build_py import build_py
from setuptools.command.egg_info import egg_info
from virtme_ng.version import VERSION


class LintCommand(Command):
    description = "Run coding style checks"
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        try:
            sys.stderr.write("checking python coding style\n")
            for cmd in ("flake8", "pylint"):
                command = [cmd]
                for pattern in (
                    "*.py",
                    "virtme/*.py",
                    "virtme/*/*.py",
                    "virtme_ng/*.py",
                ):
                    command += glob(pattern)
                check_call(command)
            sys.stderr.write("python: ok\n")
            sys.stderr.write("checking Rust coding style\n")
            check_call(
                ["cargo", "fmt", "--", "--check"], cwd="virtme_ng_init"
            )
            sys.stderr.write("Rust: ok\n")
        except CalledProcessError:
            sys.exit(1)


class BuildPy(build_py):
    def run(self):
        check_call(
            ["cargo", "install", "--path", ".", "--root", "../virtme/guest"],
            cwd="virtme_ng_init",
        )
        check_call(
            ["strip", "-s", "../virtme/guest/bin/virtme-ng-init"],
            cwd="virtme_ng_init",
        )
        build_py.run(self)


class EggInfo(egg_info):
    def run(self):
        if not os.path.exists("virtme/guest/bin/virtme-ng-init"):
            self.run_command("build")
        egg_info.run(self)


if sys.version_info < (3, 8):
    print("virtme-ng requires Python 3.8 or higher")
    sys.exit(1)

setup(
    name="virtme-ng",
    version=VERSION,
    author="Andrea Righi",
    author_email="andrea.righi@canonical.com",
    description="Build and run a kernel inside a virtualized snapshot of your live system",
    url="https://git.launchpad.net/~arighi/+git/virtme-ng",
    license="GPLv2",
    long_description=open(
        os.path.join(os.path.dirname(__file__), "README.md"), "r", encoding="utf-8"
    ).read(),
    long_description_content_type="text/markdown",
    packages=[
        "virtme_ng",
        "virtme",
        "virtme.commands",
        "virtme.guest",
        "virtme.guest.bin",
    ],
    install_requires=["argcomplete"],
    entry_points={
        "console_scripts": [
            "vng = virtme_ng.run:main",
            "virtme-ng = virtme_ng.run:main",
            "virtme-run = virtme.commands.run:main",
            "virtme-configkernel = virtme.commands.configkernel:main",
            "virtme-mkinitramfs = virtme.commands.mkinitramfs:main",
        ]
    },
    cmdclass={
        "build_py": BuildPy,
        "egg_info": EggInfo,
        "lint": LintCommand,
    },
    data_files=[("/etc", ["cfg/virtme-ng.conf"])],
    scripts=[
        "bin/virtme-prep-kdir-mods",
    ],
    package_data={
        "virtme.guest": [
            "bin/virtme-ng-init",
            "virtme-init",
            "virtme-udhcpc-script",
            "virtme-snapd-script",
            "virtme-sound-script",
        ],
    },
    include_package_data=True,
    classifiers=[
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
        "Operating System :: POSIX :: Linux",
    ],
    zip_safe=False,
)
