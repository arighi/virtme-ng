#!/usr/bin/env python3

import os
import sys
from setuptools import setup
from kernelcraft.run import VERSION

if sys.version_info < (3,3):
    print('kernelcraft requires Python 3.3 or higher')
    sys.exit(1)

setup(
    name='kernelcraft',
    version=VERSION,
    author='Andrea Righi',
    author_email='andrea.righi@canonical.com',
    description='',
    url='https://git.launchpad.net/~arighi/+git/kernelcraft',
    license='GPLv2',
    long_description=open(os.path.join(os.path.dirname(__file__),
                                       'README.md'), 'r').read(),
    long_description_content_type="text/markdown",
    packages=['kernelcraft'],
    install_requires=['virtme'],
    include_package_data=True,
    entry_points = {
        'console_scripts': [
            'kc = kernelcraft.run:main',
        ]
    },
    data_files = [
        ('/etc', ['cfg/kernelcraft.conf']),
    ],
    classifiers=['Environment :: Console',
                 'Intended Audience :: Developers',
                 'Intended Audience :: System Administrators',
                 'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
                 'Operating System :: POSIX :: Linux',
             ],

    zip_safe = False,
)
