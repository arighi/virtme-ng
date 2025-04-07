#!/usr/bin/env python3

import os
import platform
import subprocess
import sys
import sysconfig

from argcomplete import shell_integration

try:
    from build_manpages import build_manpages, get_build_py_cmd, get_install_cmd
except ModuleNotFoundError:
    build_manpages = None
from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.egg_info import egg_info

from virtme_ng.version import get_version_string

os.environ["__VNG_LOCAL"] = "1"
VERSION = get_version_string()

# Source .config if it exists (where we can potentially defined config/build
# options)
if os.path.exists(".config"):
    with open(".config", encoding="utf-8") as config_file:
        for line in config_file:
            key, value = line.strip().split("=")
            os.environ[key] = value

# Global variables to store custom build options (as env variables)
build_virtme_ng_init = int(os.environ.get("BUILD_VIRTME_NG_INIT", 0))

# Make sure virtme-ng-init submodule has been cloned
if build_virtme_ng_init and not os.path.exists("virtme_ng_init/Cargo.toml"):
    sys.stderr.write(
        "WARNING: virtme-ng-init submodule not available, trying to clone it\n"
    )
    subprocess.check_call("git submodule update --init --recursive", shell=True)

# Always include standard site-packages to PYTHONPATH
os.environ["PYTHONPATH"] = sysconfig.get_paths()["purelib"]

# Produce static Rust binaries.
#
# This is required to use the same virtme-ng-init across different root
# filesystems (when `--root DIR` is used).
os.environ["RUSTFLAGS"] = "-C target-feature=+crt-static " + os.environ.get(
    "RUSTFLAGS", ""
)


class BuildPy(build_py):
    def run(self):
        print(f"BUILD_VIRTME_NG_INIT: {build_virtme_ng_init}")
        # Build virtme-ng-init
        if build_virtme_ng_init:
            cwd = "virtme_ng_init"
            root = "../virtme/guest"
            args = ["cargo", "install", "--path", ".", "--root", root]
            if platform.system() == "Darwin":
                machine = platform.machine()
                if machine == "arm64":
                    machine = "aarch64"
                target = f"{machine}-unknown-linux-musl"
                args.extend(
                    [
                        "--target",
                        target,
                        "--config",
                        f'target.{target}.linker = "rust-lld"',
                    ]
                )
            subprocess.check_call(args, cwd="virtme_ng_init")
            subprocess.check_call(
                ["strip", os.path.join(root, "bin", "virtme-ng-init")],
                cwd=cwd,
            )

        # Generate bash autocompletion scripts
        with open("virtme-ng-prompt", "w", encoding="utf-8") as f:
            f.write(shell_integration.shellcode(["virtme-ng"]))
        with open("vng-prompt", "w", encoding="utf-8") as f:
            f.write(shell_integration.shellcode(["vng"]))

        # Run the rest of virtme-ng build
        build_py.run(self)


class EggInfo(egg_info):
    def run(self):
        # Initialize virtme guest binary directory
        guest_bin_dir = "virtme/guest/bin"
        if not os.path.exists(guest_bin_dir):
            os.mkdir(guest_bin_dir)

        # Install guest binaries
        if build_virtme_ng_init and not os.path.exists(
            "virtme/guest/bin/virtme-ng-init"
        ):
            self.run_command("build")
        egg_info.run(self)


packages = [
    "virtme_ng",
    "virtme",
    "virtme.commands",
    "virtme.guest",
]

package_files = [
    "virtme-init",
    "virtme-udhcpc-script",
    "virtme-sshd-script",
    "virtme-ssh-proxy",
    "virtme-snapd-script",
    "virtme-sound-script",
]

if build_virtme_ng_init:
    package_files.append("bin/virtme-ng-init")
    packages.append("virtme.guest.bin")

data_files = [
    ("/etc", ["cfg/virtme-ng.conf"]),
    ("/usr/share/bash-completion/completions", ["virtme-ng-prompt", "vng-prompt"]),
]
if build_manpages:
    data_files.append(("/usr/share/man/man1", ["man/vng.1"]))

cmdclass = {
    "egg_info": EggInfo,
    "build_py": BuildPy,
}
if build_manpages:
    cmdclass["build_manpages"] = build_manpages
    cmdclass["build_py"] = get_build_py_cmd(BuildPy)
    cmdclass["install"] = get_install_cmd()

setup(
    name="virtme-ng",
    version=VERSION,
    author="Andrea Righi",
    author_email="arighi@nvidia.com",
    description="Build and run a kernel inside a virtualized snapshot of your live system",
    url="https://github.com/arighi/virtme-ng",
    license="GPLv2",
    long_description=open(
        os.path.join(os.path.dirname(__file__), "README.md"), encoding="utf-8"
    ).read(),
    long_description_content_type="text/markdown",
    install_requires=[
        "argcomplete",
        "requests",
        "setuptools",
    ],
    entry_points={
        "console_scripts": [
            "vng = virtme_ng.run:main",
            "virtme-ng = virtme_ng.run:main",
            "virtme-run = virtme.commands.run:main",
            "virtme-configkernel = virtme.commands.configkernel:main",
            "virtme-mkinitramfs = virtme.commands.mkinitramfs:main",
        ]
    },
    cmdclass=cmdclass,
    packages=packages,
    package_data={"virtme.guest": package_files},
    data_files=data_files,
    scripts=[
        "bin/virtme-prep-kdir-mods",
        "bin/virtme-ssh-proxy",
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
