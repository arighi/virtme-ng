#!/usr/bin/env python3

import os
import sys
from setuptools import setup
from kernelcraft.utils import VERSION, CONF_PATH

if sys.version_info < (3,8):
    print('virtme-ng requires Python 3.8 or higher')
    sys.exit(1)

setup(
    name='virtme-ng',
    version=VERSION,
    author='Andrea Righi',
    author_email='andrea.righi@canonical.com',
    description='Build and run a kernel inside a virtualized snapshot of your live system',
    url='https://git.launchpad.net/~arighi/+git/virtme-ng',
    license='GPLv2',
    long_description=open(os.path.join(os.path.dirname(__file__),
                                       'README.md'), 'r').read(),
    long_description_content_type="text/markdown",
    packages=['kernelcraft', 'virtme', 'virtme.commands', 'virtme.guest'],
    install_requires=['argcomplete'],
    entry_points = {
        'console_scripts': [
            'virtme-ng = kernelcraft.run:main',
            'virtme-run = virtme.commands.run:main',
            'virtme-configkernel = virtme.commands.configkernel:main',
            'virtme-mkinitramfs = virtme.commands.mkinitramfs:main',
        ]
    },
    data_files = [
        (str(CONF_PATH), ['cfg/virtme-ng.conf']),
    ],
    scripts = [
        'bin/virtme-prep-kdir-mods',
        ],
    package_data = {
        'virtme.guest': [
            'virtme-init',
            'virtme-udhcpc-script',
        ],
    },
    include_package_data=True,
    classifiers=['Environment :: Console',
                 'Intended Audience :: Developers',
                 'Intended Audience :: System Administrators',
                 'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
                 'Operating System :: POSIX :: Linux',
             ],

    zip_safe = False,
)
