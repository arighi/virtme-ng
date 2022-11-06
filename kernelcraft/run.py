import argparse
import os
import sys
import socket
import shutil
import subprocess
from pathlib import Path

KERNEL_DIR = str()

def make_parser():
    parser = argparse.ArgumentParser(
        description='Craft and test a specific kernel',
    )

    parser.add_argument('--release', '-r', action='store', metavar='RELEASE',
            help='Use a kernel from a specific Ubuntu release or upstream')

    parser.add_argument('--commit', '-c', action='store', metavar='COMMIT',
            help='Use a kernel identified by a specific commit id or tag (default is HEAD)')

    parser.add_argument('--opts', '-o', action='store', metavar='OPTS',
            help='Additional options passed to virtme-run')

    parser.add_argument('--local', '-l', action='store_true',
            help='Start the previously generated kernel')

    return parser

_ARGPARSER = make_parser()

def arg_fail(message):
    print(message)
    _ARGPARSER.print_usage()
    exit(1)

UBUNTU_RELEASE = {
    # Upstream kernels
    'mainline': {
        'repo': 'git://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git',
        'branch': 'master',
    },
    'next': {
        'repo': 'git://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git',
        'branch': 'master',
    },
    'stable': {
        'repo': 'git://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git',
        'branch': 'master',
    },

    # Ubuntu kernels
    'ubuntu-unstable': {
        'repo': 'git://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/unstable',
        'branch': 'master',
    },
    'ubuntu-kinetic': {
        'repo': 'git://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/kinetic',
        'branch': 'master-next',
    },
    'ubuntu-jammy': {
        'repo': 'git://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/jammy',
        'branch': 'master-next',
    },
    'ubuntu-focal': {
        'repo': 'git://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/focal',
        'branch': 'master-next',
    },
    'ubuntu-bionic': {
        'repo': 'git://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/bionic',
        'branch': 'master-next',
    },
    'ubuntu-xenial': {
        'repo': 'git://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/xenial',
        'branch': 'master-next',
    },
    'ubuntu-trusty': {
        'repo': 'git://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/trusty',
        'branch': 'master-next',
    },
}

class KernelSource:
    def __init__(self, srcdir):
        if not os.path.exists(srcdir):
           os.makedirs(srcdir)
           os.chdir(srcdir)
           subprocess.check_call(['git', 'init'])
        self.cpus = str(os.cpu_count())
        os.chdir(srcdir)
        self.srcdir = srcdir

    def checkout(self, release, commit=None):
        if not release in UBUNTU_RELEASE:
            sys.stderr.write(f"ERROR: unknown release {release}\n")
        if subprocess.call(['git', 'remote', 'get-url', release], stderr=subprocess.DEVNULL):
            repo_url = UBUNTU_RELEASE[release]['repo']
            subprocess.check_call(['git', 'remote', 'add', release, repo_url])
        subprocess.check_call(['git', 'fetch', release])
        target = commit or (release + '/' + UBUNTU_RELEASE[release]['branch'])
        subprocess.check_call(['git', 'reset', '--hard', target])

    def config(self):
        subprocess.check_call(['virtme-configkernel', '--defconfig'])

    def make(self):
        subprocess.check_call(['make', '-j', self.cpus])

    def run(self):
        hostname = socket.gethostname()
        username = os.getlogin()
        # Disable kaslr because it may break debugging tools
        opts = '-a nokaslr'
        # Start VM using virtme
        cmd = f'virtme-run --name {hostname} --kdir {self.srcdir} --mods auto -a nokaslr --user {username} --qemu-opts -m 4096 -smp {self.cpus} -s -qmp tcp:localhost:3636,server,nowait'
        subprocess.check_call([str(c) for c in cmd.split(' ')])

def main():
    args = _ARGPARSER.parse_args()

    ks = KernelSource(str(Path.home()) + '/.kernelcraft')
    if not args.local:
        ks.checkout(args.release, args.commit)
        ks.config()
    ks.make()
    ks.run()

if __name__ == '__main__':
    exit(main())
