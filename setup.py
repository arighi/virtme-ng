#!/usr/bin/env python3
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup
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
    scripts=[
        'bin/virtme-init',
        'bin/virtme-loadmods',
        'bin/virtme-mkinitramfs',
        'bin/virtme-run',
        'bin/virtme-udhcpc-script',
    ],
    classifiers=['Environment :: Console']
)
