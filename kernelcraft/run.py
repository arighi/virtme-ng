import argparse
import os
import sys
import socket
import shutil
import pkg_resources
import json
import tempfile
from subprocess import call, check_call, DEVNULL
from pathlib import Path
from shutil import copyfile

VERSION = '0.0.1'

def make_parser():
    parser = argparse.ArgumentParser(
        description='Build and run a specific kernel inside a virtualized snapshot of your live system',
    )
    parser.add_argument('--version', '-v', action='version', version=f'%(prog)s {VERSION}')

    ga = parser.add_argument_group(title='Action').add_mutually_exclusive_group()

    ga.add_argument('--release', '-r', action='store',
            help='Use a kernel from a specific Ubuntu release or upstream')

    ga.add_argument('--clean', '-x', action='store_true',
            help='Clean the local kernel repository')

    ga.add_argument('--dump', '-d', action='store_true',
            help='Generate a memory dump of the running kernel and inspect it')

    parser.add_argument('--dump-file', action='store',
            help='Generate a memory dump of the running kernel to a target file')

    ga.add_argument('--skip-build', '-s', action='store_true',
            help='Start the previously compiled kernel without trying to rebuild it')

    parser.add_argument('--commit', '-c', action='store',
            help='Use a kernel identified by a specific commit id, tag or branch')

    parser.add_argument('--config', '-f', action='store',
            help='Use a specific kernel .config snippet to override default config settings')

    parser.add_argument('--opts', '-o', action='store',
            help='Additional options passed to virtme-run')

    parser.add_argument('--build-host', '-b', action='store',
            help='Perform kernel build on a remote server (ssh access required)')

    parser.add_argument('--build-host-exec-prefix', action='store',
            help='Prepend a command (e.g., chroot) to the make command executed on the remote build host')

    parser.add_argument('--build-host-vmlinux', action='store_true',
            help='Copy vmlinux back from the build host')

    return parser

_ARGPARSER = make_parser()

def arg_fail(message):
    print(message)
    _ARGPARSER.print_usage()
    exit(1)

REMOTE_BUILD_SCRIPT = '''#!/bin/bash
cd ~/.kernelcraft
git reset --hard __kernelcraft__
[ -f debian/rules ] && fakeroot debian/rules clean
{} make -j$(nproc --all) LOCALVERSION=-kc
'''

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

    def checkout(self, release, commit=None):
        if release:
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

    def make(self, build_host, build_host_exec_prefix, build_host_vmlinux):
        if not build_host:
            check_call(['make', '-j', self.cpus, 'LOCALVERSION=-kc'])
            return
        check_call(['ssh', build_host,
                    'mkdir -p ~/.kernelcraft'])
        check_call(['ssh', build_host,
                    'git init ~/.kernelcraft'])
        check_call(['git', 'push', '--force', f"{build_host}:~/.kernelcraft",
                    'HEAD:__kernelcraft__', ])
        cmd = f'rsync {self.srcdir}/.config {build_host}:.kernelcraft/.config'
        check_call(self._format_cmd(cmd))
        # Create remote build script
        with tempfile.NamedTemporaryFile(mode='w+t') as tmp:
            tmp.write(REMOTE_BUILD_SCRIPT.format(build_host_exec_prefix or ''))
            tmp.flush()
            cmd = f'rsync {tmp.name} {build_host}:.kernelcraft/.kc-build'
            check_call(self._format_cmd(cmd))
        # Execute remote build script
        check_call(['ssh', build_host, 'bash', '.kernelcraft/.kc-build'])
        # Copy artifacts back to the running host
        with tempfile.NamedTemporaryFile(mode='w+t') as tmp:
            if build_host_vmlinux:
                vmlinux = '--include=vmlinux'
            else:
                vmlinux = ''
            cmd = f'rsync -aS --progress --exclude=.config --exclude=.git/ --include=*/ --include="*.ko" --include=".dwo" --include=bzImage {vmlinux} --include=.config --include=modules.* --include=System.map --include=Module.symvers --include=module.lds --include="**/generated/**" --exclude="*" {build_host}:.kernelcraft/ {self.srcdir}/'
            tmp.write(cmd)
            tmp.flush()
            check_call(['bash', tmp.name])
        if os.path.exists(self.srcdir + '/debian/rules'):
            check_call(['fakeroot', 'debian/rules', 'clean'])
        check_call(['make', '-j', self.cpus, 'modules_prepare', 'LOCALVERSION=-kc'])

    def run(self, opts):
        hostname = socket.gethostname()
        username = os.getlogin()
        opts = opts or ''
        # Start VM using virtme
        rw_dirs = ' '.join(f'--overlay-rwdir {d}' for d in ('/etc', '/home', '/opt', '/srv', '/usr', '/var'))
        cmd = f'virtme-run --name {hostname} --kdir {self.srcdir} --mods auto {rw_dirs} {opts} --user {username} --qemu-opts -m 4096 -smp {self.cpus} -s -qmp tcp:localhost:3636,server,nowait'
        check_call(self._format_cmd(cmd))

    def dump(self, dump_file):
        # Use QMP to generate a memory dump
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(('localhost', 3636))
        data = s.recv(1024)
        if not data:
            exit(1)
        print(data)
        s.send("{ \"execute\": \"qmp_capabilities\" }\r".encode('utf-8'))
        data = s.recv(1024)
        if not data:
            exit(1)
        print(data)
        with tempfile.NamedTemporaryFile(delete=(dump_file is None)) as tmp:
            msg = "{\"execute\":\"dump-guest-memory\",\"arguments\":{\"paging\":false,\"protocol\":\"file:" + tmp.name + "\"}}\r"
            print(msg)
            s.send(msg.encode('utf-8'))
            data = s.recv(1024)
            if not data:
                exit(1)
            print(data)
            data = s.recv(1024)
            print(data)
            if dump_file:
                # Save memory dump to target file
                shutil.move(tmp.name, dump_file)
            else:
                # Use crash to inspect the memory dump
                check_call(['crash', tmp.name, self.srcdir + '/vmlinux'])

    def clean(self):
        check_call(['git', 'clean', '-xdf'])

def main():
    args = _ARGPARSER.parse_args()

    ks = KernelSource(str(Path.home()) + '/.kernelcraft')
    if args.clean:
        ks.clean()
    elif args.dump:
        ks.dump(args.dump_file)
    else:
        if not args.skip_build:
            ks.checkout(args.release, args.commit)
            ks.config(args.config)
            ks.make(args.build_host, args.build_host_exec_prefix, args.build_host_vmlinux)
        ks.run(args.opts)

if __name__ == '__main__':
    exit(main())
