import argparse
import os
import sys
import socket
import shutil
from subprocess import call, check_call, DEVNULL
from pathlib import Path

VERSION = '0.0.1'
KERNEL_DIR = str()

def make_parser():
    parser = argparse.ArgumentParser(
        description='Craft and test a specific kernel',
    )
    parser.add_argument('--version', '-v', action='version', version=f'%(prog)s {VERSION}')

    ga = parser.add_argument_group(title='Action').add_mutually_exclusive_group(required=True)

    ga.add_argument('--release', '-r', action='store',
            help='Use a kernel from a specific Ubuntu release or upstream')

    ga.add_argument('--local', '-l', action='store_true',
            help='Use a local branch/tag/commit of a previously generated kernel')

    parser.add_argument('--commit', '-c', action='store',
            nargs='?', default='HEAD', const='HEAD',
            help='Use a kernel identified by a specific commit id, tag or branch (default is HEAD)')

    parser.add_argument('--opts', '-o', action='store',
            help='Additional options passed to virtme-run')

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
           check_call(['git', 'init'])
        self.cpus = str(os.cpu_count())
        os.chdir(srcdir)
        self.srcdir = srcdir

    def checkout(self, release, commit=None, local=None):
        if not local:
            if not release in UBUNTU_RELEASE:
                sys.stderr.write(f"ERROR: unknown release {release}\n")
            if call(['git', 'remote', 'get-url', release], stderr=DEVNULL):
                repo_url = UBUNTU_RELEASE[release]['repo']
                check_call(['git', 'remote', 'add', release, repo_url])
            check_call(['git', 'fetch', release])
            target = commit or (release + '/' + UBUNTU_RELEASE[release]['branch'])
        else:
            target = commit
        check_call(['git', 'reset', '--hard', target])

    def config(self):
        check_call(['virtme-configkernel', '--defconfig'])

    def make(self):
        check_call(['make', '-j', self.cpus])

    def run(self, opts):
        hostname = socket.gethostname()
        username = os.getlogin()
        opts = opts or ''
        # Start VM using virtme
        cmd = f'virtme-run --name {hostname} --kdir {self.srcdir} --mods auto {opts} --user {username} --qemu-opts -m 4096 -smp {self.cpus} -s -qmp tcp:localhost:3636,server,nowait'
        check_call(list(filter(None, cmd.split(' '))))

def main():
    args = _ARGPARSER.parse_args()

    ks = KernelSource(str(Path.home()) + '/.kernelcraft')
    ks.checkout(args.release, args.commit, args.local)
    ks.config()
    ks.make()
    ks.run(args.opts)

if __name__ == '__main__':
    exit(main())
