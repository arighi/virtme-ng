#!/usr/bin/env python3

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

import sys
if sys.version_info.major < 3:
    print('virtme requires Python 3 or higher')
    sys.exit(1)

setup(
    name='virtme',
    version='0.0.1',
    author='Andy Lutomirski',
    author_email='luto@amacapital.net',
    description='simple tools for kernel testing in a virtualized host',
    url='https://git.kernel.org/cgit/utils/kernel/virtme/virtme.git',
    license=open('./LICENSE').read(),
    long_description=open('./README.md').read(),
    packages=['virtme'],
    install_requires=[],
    entry_points = {
        'console_scripts': [
            'virtme-run = virtme.commands.run:main',
        ]
    },
    classifiers=['Environment :: Console']
)
