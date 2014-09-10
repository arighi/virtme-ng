#!/usr/bin/env python3

import os
import sys

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

if sys.version_info.major < 3:
    print('virtme requires Python 3 or higher')
    sys.exit(1)

_VERSION = '0.0.1'

setup(
    name='virtme',
    version=_VERSION,
    author='Andy Lutomirski',
    author_email='luto@amacapital.net',
    description='Virtualize the running distro or a simple rootfs',
    url='https://git.kernel.org/cgit/utils/kernel/virtme/virtme.git',
    download_url='https://www.kernel.org/pub/linux/utils/kernel/virtme/releases/virtme-%s.tar.xz' % _VERSION,
    license='GPLv2',
    long_description=open(os.path.join(os.path.dirname(__file__),
                                       'README.md'), 'r').read(),
    packages=['virtme', 'virtme.commands'],
    install_requires=[],
    entry_points = {
        'console_scripts': [
            'virtme-run = virtme.commands.run:main',
            'virtme-configkernel = virtme.commands.configkernel:main',
        ]
    },
    data_files = [
        ('share/virtme-guest-0',
         ['virtme/guest/virtme-init',
          'virtme/guest/virtme-udhcpc-script',
          'virtme/guest/virtme-loadmods',
         ]),
    ],
    classifiers=['Environment :: Console',
                 'Intended Audience :: Developers',
                 'Intended Audience :: System Administrators',
                 'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
                 'Operating System :: POSIX :: Linux',
             ]
)
