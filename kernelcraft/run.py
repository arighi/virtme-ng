import argparse
import os
import sys
import socket
import pkg_resources
import json
from subprocess import call, check_call, DEVNULL
from pathlib import Path
from shutil import copyfile

VERSION = '0.0.1'

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

    ga.add_argument('--clean', '-x', action='store_true',
            help='Clean the local kernel repository')

    ga.add_argument('--skip-build', '-s', action='store_true',
            help='Start the previously compiled kernel without trying to rebuild it')

    parser.add_argument('--commit', '-c', action='store',
            help='Use a kernel identified by a specific commit id, tag or branch')

    parser.add_argument('--config', '-f', action='store',
            help='Use a specific kernel .config snippet to override default config settings')

    parser.add_argument('--opts', '-o', action='store',
            help='Additional options passed to virtme-run')

    return parser

_ARGPARSER = make_parser()

def arg_fail(message):
    print(message)
    _ARGPARSER.print_usage()
    exit(1)

class KernelSource:
    def __init__(self, srcdir):
        # Initialize known kernels
        conf = str(Path.home()) + '/.kernelcraft.conf'
        if not Path(conf).exists():
            default_conf = pkg_resources.resource_filename('kernelcraft', 'kernelcraft.conf')
            copyfile(default_conf, conf)
        with open(conf) as fd:
            self.kernel_release = json.loads(fd.read())

        # Initialize kernel source repo
        if not os.path.exists(srcdir):
           os.makedirs(srcdir)
           os.chdir(srcdir)
           check_call(['git', 'init'])
        self.cpus = str(os.cpu_count())
        os.chdir(srcdir)
        self.srcdir = srcdir

    def _format_cmd(self, cmd):
        return list(filter(None, cmd.split(' ')))

    def checkout(self, release, commit=None, local=None):
        if not local:
            if not release in self.kernel_release:
                sys.stderr.write(f"ERROR: unknown release {release}\n")
                sys.exit(1)
            if call(['git', 'remote', 'get-url', release], stderr=DEVNULL):
                repo_url = self.kernel_release[release]['repo']
                check_call(['git', 'remote', 'add', release, repo_url])
            check_call(['git', 'fetch', release])
            target = commit or (release + '/' + self.kernel_release[release]['branch'])
        else:
            target = commit or 'HEAD'
        check_call(['git', 'reset', '--hard', target])

    def config(self, config):
        cmd = 'virtme-configkernel --defconfig'
        if config:
            cmd += f' --custom {config}'
        check_call(self._format_cmd(cmd))

    def make(self):
        check_call(['make', '-j', self.cpus])

    def run(self, opts):
        hostname = socket.gethostname()
        username = os.getlogin()
        opts = opts or ''
        # Start VM using virtme
        rw_dirs = ' '.join(f'--overlay-rwdir {d}' for d in ('/etc', '/home', '/opt', '/srv', '/usr', '/var'))
        cmd = f'virtme-run --name {hostname} --kdir {self.srcdir} --mods auto {rw_dirs} {opts} --user {username} --qemu-opts -m 4096 -smp {self.cpus} -s -qmp tcp:localhost:3636,server,nowait'
        check_call(self._format_cmd(cmd))

    def clean(self):
        check_call(['git', 'clean', '-xdf'])

def main():
    args = _ARGPARSER.parse_args()

    ks = KernelSource(str(Path.home()) + '/.kernelcraft')
    if args.clean:
        ks.clean()
    else:
        if not args.skip_build:
            ks.checkout(args.release, args.commit, args.local)
            ks.config(args.config)
            ks.make()
        ks.run(args.opts)

if __name__ == '__main__':
    exit(main())
