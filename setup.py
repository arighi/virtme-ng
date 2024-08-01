#!/usr/bin/env python3

import os
import sys
import platform
import sysconfig
from glob import glob
from shutil import which
from subprocess import check_call, CalledProcessError
from setuptools import setup, Command
from setuptools.command.build_py import build_py
from setuptools.command.egg_info import egg_info
from virtme_ng.version import get_version_string

os.environ["__VNG_LOCAL"] = "1"
VERSION = get_version_string()

# Source .config if it exists (where we can potentially defined config/build
# options)
if os.path.exists(".config"):
    with open(".config", "r", encoding="utf-8") as config_file:
        for line in config_file:
            key, value = line.strip().split("=")
            os.environ[key] = value

# Global variables to store custom build options (as env variables)
build_virtme_ng_init = int(os.environ.get("BUILD_VIRTME_NG_INIT", 0))

# Make sure virtme-ng-init submodule has been cloned
if build_virtme_ng_init and not os.path.exists("virtme_ng_init/Cargo.toml"):
    sys.stderr.write("WARNING: virtme-ng-init submodule not available, trying to clone it\n")
    check_call("git submodule update --init --recursive", shell=True)

# Always include standard site-packages to PYTHONPATH
os.environ['PYTHONPATH'] = sysconfig.get_paths()['purelib']


def is_arm_32bit():
    arch = platform.machine()
    return arch.startswith("arm") and platform.architecture()[0] == "32bit"


def parse_requirements(filename):
    with open(filename, 'r', encoding="utf-8") as file:
        lines = file.readlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith('#')]


class LintCommand(Command):
    description = "Run coding style checks"
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        try:
            for cmd in ("flake8", "pylint"):
                command = [cmd]
                for pattern in (
                    "vng",
                    "*.py",
                    "virtme/*.py",
                    "virtme/*/*.py",
                    "virtme_ng/*.py",
                ):
                    command += glob(pattern)
                check_call(command)
        except CalledProcessError:
            sys.exit(1)


man_command = f"""
argparse-manpage \
  --pyfile ./virtme_ng/run.py --function make_parser \
  --prog vng --version v{VERSION} \
  --author "virtme-ng is written by Andrea Righi <andrea.righi@canonical.com>" \
  --author "Based on virtme by Andy Lutomirski <luto@kernel.org>" \
  --project-name virtme-ng --manual-title virtme-ng \
  --description "Quickly run kernels inside a virtualized snapshot of your live system" \
  --url https://github.com/arighi/virtme-ng > vng.1
"""


class BuildPy(build_py):
    def run(self):
        print(f"BUILD_VIRTME_NG_INIT: {build_virtme_ng_init}")
        # Build virtme-ng-init
        if build_virtme_ng_init:
            check_call(["make", "init"])
            check_call(
                ["strip", "-s", "../virtme/guest/bin/virtme-ng-init"],
                cwd="virtme_ng_init",
            )
        # Generate manpage
        if which('argparse-manpage'):
            env = os.environ.copy()
            env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
            check_call(man_command, shell=True, env=env)

        # Generate bash autocompletion scripts
        completion_command = ''
        if which("register-python-argcomplete"):
            completion_command = "register-python-argcomplete"
        elif which("register-python-argcomplete3"):
            completion_command = "register-python-argcomplete3"
        else:
            print("ERROR: 'register-python-argcomplete' or 'register-python-argcomplete3' not found.")
            sys.exit(1)
        check_call(completion_command + ' virtme-ng > virtme-ng-prompt', shell=True)
        check_call(completion_command + ' vng > vng-prompt', shell=True)

        # Run the rest of virtme-ng build
        build_py.run(self)


class EggInfo(egg_info):
    def run(self):
        # Initialize virtme guest binary directory
        guest_bin_dir = "virtme/guest/bin"
        if not os.path.exists(guest_bin_dir):
            os.mkdir(guest_bin_dir)

        # Install guest binaries
        if (build_virtme_ng_init and not os.path.exists("virtme/guest/bin/virtme-ng-init")):
            self.run_command("build")
        egg_info.run(self)


if sys.version_info < (3, 8):
    print("virtme-ng requires Python 3.8 or higher")
    sys.exit(1)

packages = [
    "virtme_ng",
    "virtme",
    "virtme.commands",
    "virtme.guest",
]

package_files = [
    "virtme-init",
    "virtme-udhcpc-script",
    "virtme-snapd-script",
    "virtme-sound-script",
]

if build_virtme_ng_init:
    package_files.append("bin/virtme-ng-init")
    packages.append("virtme.guest.bin")

data_files = [
    ("/etc", ["cfg/virtme-ng.conf"]),
    ("/usr/share/bash-completion/completions", ["virtme-ng-prompt"]),
    ("/usr/share/bash-completion/completions", ["vng-prompt"]),
]

if which('argparse-manpage'):
    data_files.append(("/usr/share/man/man1", ["vng.1"]))

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
    install_requires=parse_requirements('requirements.txt'),
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
    packages=packages,
    package_data={"virtme.guest": package_files},
    data_files=data_files,
    scripts=[
        "bin/virtme-prep-kdir-mods",
    ],
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
