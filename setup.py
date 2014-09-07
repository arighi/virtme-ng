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

setup(
    name='virtme',
    version='0.0.1',
    author='Andy Lutomirski',
    author_email='luto@amacapital.net',
    description='Virtualize the running distro or a simple hostfs',
    url='https://git.kernel.org/cgit/utils/kernel/virtme/virtme.git',
    license='GPLv2',
    long_description=open(os.path.join(os.path.dirname(__file__),
                                       'README.md'), 'r').read(),
    packages=['virtme', 'virtme.commands'],
    install_requires=[],
    entry_points = {
        'console_scripts': [
            'virtme-run = virtme.commands.run:main',
        ]
    },
    data_files = [
        ('share/virtme-guest-0',
         ['virtme/guest/virtme-init',
          'virtme/guest/virtme-udhcpc-script',
          'virtme/guest/virtme-loadmods',
         ]),
    ],
    classifiers=['Environment :: Console']
)
