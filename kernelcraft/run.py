import argparse
import os
import sys
import socket
import shutil
import json
import tempfile
from subprocess import call, check_call, check_output, DEVNULL
from pathlib import Path
from argcomplete import autocomplete

from kernelcraft.utils import VERSION, CONF_FILE

def make_parser():
    parser = argparse.ArgumentParser(
        description='Build and run specific kernels inside a virtualized snapshot of your live system',
    )
    parser.add_argument('--version', '-v', action='version', version=f'%(prog)s {VERSION}')

    ga = parser.add_argument_group(title='Action').add_mutually_exclusive_group()

    ga.add_argument('--init', '-i', action='store_true',
            help='Initialize a git repository to be used with virtme-ng')

    ga.add_argument('--release', '-r', action='store',
            help='Use a kernel from a specific Ubuntu release or upstream')

    ga.add_argument('--clean', '-x', action='store_true',
            help='Clean the kernel repository (local or remote if used with --build-host)')

    ga.add_argument('--dump', '-d', action='store_true',
            help='Generate a memory dump of the running kernel and inspect it')

    ga.add_argument('--skip-build', '-s', action='store_true',
            help='Start the previously compiled kernel without trying to rebuild it')

    parser.add_argument('--kconfig', '-k', action='store_true',
            help='Only generate the kernel .config without building/running anything')

    parser.add_argument('--dump-file', action='store',
            help='Generate a memory dump of the running kernel to a target file')

    parser.add_argument('--skip-modules', '-S', action='store_true',
            help='Run a really fast build by skipping external modules (no external modules support)')

    parser.add_argument('--commit', '-c', action='store',
            help='Use a kernel identified by a specific commit id, tag or branch')

    parser.add_argument('--config', '-f', action='append',
            help='Use one (or more) specific kernel .config snippet to override default config settings')
    parser.add_argument('--compiler', action='store',
            help='Compiler to be used as CC when building the kernel')

    parser.add_argument('--cpus', '-p', action='store',
        help='Set guest CPU count (qemu -smp flag)')

    parser.add_argument('--memory', '-m', action='store',
            help='Set guest memory size (qemu -m flag)')

    parser.add_argument('--network', '-n', action='store',
            metavar='user|bridge', help='Enable network access')

    parser.add_argument('--disk', '-D', action='append',
            metavar='PATH', help='Add a file as virtio-scsi disk (can be used multiple times)')

    parser.add_argument('--exec', '-e', action='store',
            help='Execute a command inside the kernel and exit')

    parser.add_argument('--append', '-a', action='append',
            help='Additional kernel boot options (can be used multiple times)')

    parser.add_argument('--opts', '-o', action='append',
            help='Additional options passed to virtme-run (can be used multiple times)')

    parser.add_argument('--build-host', '-b', action='store',
            help='Perform kernel build on a remote server (ssh access required)')

    parser.add_argument('--build-host-exec-prefix', action='store',
            help='Prepend a command (e.g., chroot) to the make command executed on the remote build host')

    parser.add_argument('--build-host-vmlinux', action='store_true',
            help='Copy vmlinux back from the build host')

    parser.add_argument('--arch', action='store',
            help='Generate and test a kernel for a specific architecture (default is host architecture)')

    parser.add_argument('--root', action='store',
            help='Pass a specific chroot to use inside the virtualized kernel (useful with --arch)')

    parser.add_argument('--force', action='store_true',
            help='Force reset git repository to target branch or commit (warning: this may drop uncommitted changes)')

    parser.add_argument('envs', metavar='envs', type=str, nargs='*',
                        help='Additional Makefile variables')
    return parser

_ARGPARSER = make_parser()

def arg_fail(message, show_usage=True):
    print(message)
    if (show_usage):
        _ARGPARSER.print_usage()
    exit(1)

ARCH_MAPPING = {
    'arm64': {
        'qemu_name': 'aarch64',
        'linux_name': 'arm64',
        'cross_compile': 'aarch64-linux-gnu-',
        'kernel_target': 'Image',
        'kernel_image': 'Image',
    },
    'armhf': {
        'qemu_name': 'arm',
        'linux_name': 'arm',
        'cross_compile': 'arm-linux-gnueabihf-',
        'kernel_target': '',
        'kernel_image': 'zImage',
        'max-cpus': 4,
    },
    'ppc64el': {
        'qemu_name': 'ppc64',
        'linux_name': 'powerpc',
        'cross_compile': 'powerpc64le-linux-gnu-',
        'kernel_target': 'vmlinux',
        'kernel_image': 'vmlinux',
    },
    's390x': {
        'qemu_name': 's390x',
        'linux_name': 's390',
        'cross_compile': 's390x-linux-gnu-',
        'kernel_target': 'bzImage',
        'kernel_image': 'bzImage',
    },
    'riscv64': {
        'qemu_name': 'riscv64',
        'linux_name': 'riscv',
        'cross_compile': 'riscv64-linux-gnu-',
        'kernel_target': 'Image',
        'kernel_image': 'Image',
    },
}

MAKE_COMMAND = "make LOCALVERSION=-virtme"

REMOTE_BUILD_SCRIPT = '''#!/bin/bash
cd ~/.virtme
git reset --hard __virtme__
[ -f debian/rules ] && fakeroot debian/rules clean
{} {}
'''

def create_root(destdir, arch):
    if os.path.exists(destdir):
        return
    # Use Ubuntu's cloud images to create a rootfs, these images are fairly
    # small and they provide a nice environment to test kernels.
    release = check_output('lsb_release -s -c', shell=True).decode(sys.stdout.encoding).rstrip()
    url = f'https://cloud-images.ubuntu.com/{release}/current/{release}-server-cloudimg-{arch}-root.tar.xz'
    prevdir = os.getcwd()
    os.system(f'sudo mkdir -p {destdir}')
    os.chdir(destdir)
    os.system(f'curl -s {url} | sudo tar xvJ')
    os.chdir(prevdir)

class KernelSource:
    def __init__(self, do_init=False):
        if do_init:
            check_call(['git', 'init', '-q'], stdout=sys.stderr, stdin=DEVNULL)
        if not os.path.isdir('.git'):
            arg_fail('error: must run from a kernel git repository', show_usage=False)
        # Initialize known kernels
        conf_path = self.get_conf_file_path()
        with open(conf_path) as fd:
            conf_data = json.loads(fd.read())
            if 'repo' in conf_data:
                self.kernel_release = conf_data['repo']
                self.default_opts = conf_data['default_opts']
            else:
                self.kernel_release = conf_data
        self.cpus = str(os.cpu_count())

    # First check if there is a config file in the user's home config
    # directory, then check for a single config file in ~/.virtme-ng.conf and
    # finally check for /etc/virtme-ng.conf. If none of them exist, report an
    # error and exit.
    def get_conf_file_path(self):
        configs = (CONF_FILE,
                   Path(Path.home(), '.virtme-ng.conf'),
                   Path('/etc', 'virtme-ng.conf'))
        for conf in configs:
            if conf.exists():
                return conf
        sys.stderr.write("ERROR: missing configuration file\n")
        sys.exit(1)

    def _format_cmd(self, cmd):
        return list(filter(None, cmd.split(' ')))

    def _is_dirty_repo(self):
        cmd = 'git --no-optional-locks status -uno --porcelain'
        if check_output(self._format_cmd(cmd), stderr=DEVNULL, stdin=DEVNULL):
            return True
        else:
            return False

    def checkout(self, release=None, commit=None, build_host=None, force=False):
        if release is not None:
            if not release in self.kernel_release:
                sys.stderr.write(f"ERROR: unknown release {release}\n")
                sys.exit(1)
            if call(['git', 'remote', 'get-url', release], stderr=DEVNULL, stdout=sys.stderr, stdin=DEVNULL):
                repo_url = self.kernel_release[release]['repo']
                check_call(['git', 'remote', 'add', release, repo_url], stdout=sys.stderr, stdin=DEVNULL)
            check_call(['git', 'fetch', release], stdout=sys.stderr, stdin=DEVNULL)
            target = commit or (release + '/' + self.kernel_release[release]['branch'])
        else:
            target = commit or 'HEAD'
        if build_host is not None or target != 'HEAD':
            if not force and self._is_dirty_repo():
                arg_fail("error: you have uncommitted changes in your git repository, use --force to drop them", show_usage=False)
            check_call(['git', 'reset', '--hard', target], stdout=sys.stderr, stdin=DEVNULL)

    def config(self, arch=None, config=None, envs=()):
        cmd = 'virtme-configkernel --defconfig'
        if arch is not None:
            if arch not in ARCH_MAPPING:
                arg_fail(f'unsupported architecture: {arch}')
            arch = ARCH_MAPPING[arch]['qemu_name']
            cmd += f' --arch {arch}'
        user_config = str(Path.home()) + '/.config/virtme-ng/kernel.config'
        if config:
            for c in config:
                cmd += f' --custom {c}'
        if os.path.exists(user_config):
            cmd += f' --custom {user_config}'
        # Propagate additional Makefile variables
        for var in envs:
            cmd += f' {var} '
        check_call(self._format_cmd(cmd), stdout=sys.stderr, stdin=DEVNULL)

    def make(self, arch=None, build_host=None, build_host_exec_prefix=None, build_host_vmlinux=False, skip_modules=False, compiler=None, envs=()):
        if arch is not None:
            if arch not in ARCH_MAPPING:
                arg_fail(f'unsupported architecture: {arch}')
            target = ARCH_MAPPING[arch]['kernel_target']
            kernel_image = ARCH_MAPPING[arch]['kernel_image']
            cross_compile = ARCH_MAPPING[arch]['cross_compile']
            cross_arch = ARCH_MAPPING[arch]['linux_name']
        else:
            target = 'bzImage'
            kernel_image = 'bzImage'
            cross_compile = None
            cross_arch = None
        make_command = MAKE_COMMAND
        if compiler:
            make_command += f' CC={compiler}'
        if skip_modules:
            make_command += f' {target}'
        if cross_compile and cross_arch:
            make_command += f' CROSS_COMPILE={cross_compile} ARCH={cross_arch}'
        # Propagate additional Makefile variables
        for var in envs:
            make_command += f' {var} '
        if build_host is None:
            check_call(self._format_cmd(make_command + ' -j' + self.cpus), stdout=sys.stderr, stdin=DEVNULL)
            return
        check_call(['ssh', build_host,
                    'mkdir -p ~/.virtme'], stdout=sys.stderr, stdin=DEVNULL)
        check_call(['ssh', build_host,
                    'git init ~/.virtme'], stdout=sys.stderr, stdin=DEVNULL)
        check_call(['git', 'push', '--force', f"{build_host}:~/.virtme",
                    'HEAD:__virtme__', ], stdout=sys.stderr, stdin=DEVNULL)
        cmd = f'rsync .config {build_host}:.virtme/.config'
        check_call(self._format_cmd(cmd), stdout=sys.stderr, stdin=DEVNULL)
        # Create remote build script
        with tempfile.NamedTemporaryFile(mode='w+t') as tmp:
            tmp.write(REMOTE_BUILD_SCRIPT.format(build_host_exec_prefix or '', make_command + ' -j$(nproc --all)'))
            tmp.flush()
            cmd = f'rsync {tmp.name} {build_host}:.virtme/.kc-build'
            check_call(self._format_cmd(cmd), stdout=sys.stderr, stdin=DEVNULL)
        # Execute remote build script
        check_call(['ssh', build_host, 'bash', '.virtme/.kc-build'], stdout=sys.stderr, stdin=DEVNULL)
        # Copy artifacts back to the running host
        with tempfile.NamedTemporaryFile(mode='w+t') as tmp:
            if build_host_vmlinux or arch == 'ppc64el':
                vmlinux = '--include=vmlinux'
            else:
                vmlinux = ''
            if skip_modules:
                cmd = f'rsync -azS --progress --exclude=.config --exclude=.git/ --include=*/ --include={kernel_image} {vmlinux} --include=*.dtb --exclude="*" {build_host}:.virtme/ ./'
            else:
                cmd = f'rsync -azS --progress --exclude=.config --exclude=.git/ --include=*/ --include="*.ko" --include=".dwo" --include=bzImage --include=zImage --include=Image {vmlinux} --include=.config --include=modules.* --include=System.map --include=Module.symvers --include=module.lds --include=*.dtb --include="**/generated/**" --exclude="*" {build_host}:.virtme/ ./'
            tmp.write(cmd)
            tmp.flush()
            check_call(['bash', tmp.name], stdout=sys.stderr, stdin=DEVNULL)
        if not skip_modules:
            if os.path.exists('./debian/rules'):
                check_call(['fakeroot', 'debian/rules', 'clean'], stdout=sys.stderr, stdin=DEVNULL)
            check_call(self._format_cmd(make_command + f' -j {self.cpus}' + ' modules_prepare'), stdout=sys.stderr, stdin=DEVNULL)

    def run(self, arch=None, root=None, cpus=None, memory=None, network=None, disk=None, append=None, execute=None, opts=None, skip_modules=False):
        hostname = socket.gethostname()
        if root is not None:
            create_root(root, arch)
            root = f'--root {root}'
            username = ''
            pwd = ''
        else:
            root = ''
            username = '--user ' + os.getlogin()
            pwd = '--pwd'
        if arch is not None:
            if arch not in ARCH_MAPPING:
                arg_fail(f'unsupported architecture: {arch}')
            if arch == 'riscv64':
                print('\n!!! WARNING !!!\n')
                print('Kernel boot parameters may be limited on riscv, if you are using an old kernel.')
                print('Make sure to increase COMMAND_LINE_SIZE to at least 1024')
                print('See: https://lore.kernel.org/lkml/e90289af-f557-58f2-f4c8-f79feab4f185@ghiti.fr/T/#t')
                print('\n')
            if 'max-cpus' in ARCH_MAPPING[arch]:
                self.cpus = ARCH_MAPPING[arch]['max-cpus']
            arch = '--arch ' + ARCH_MAPPING[arch]['qemu_name']
        else:
            arch = ''
        if skip_modules:
            mods = '--mods none'
        else:
            mods = '--mods auto'
        if cpus is None:
            cpus = self.cpus
        if memory is None:
            memory = 4096
        if execute is not None:
            execute = f'--script-sh "{execute}"'
        else:
            execute = ''
        if network is not None:
            network = f'--net {network}'
        else:
            network = ''
        if disk is not None:
            disk_str = ''
            for d in disk:
                disk_str += f'--disk {d}={d} '
            disk = disk_str
        else:
            disk = ''
        if append is not None:
            # Split spaces into additional items in the append list
            append = ' '.join(['-a ' + item for _l in [item.split() for item in append] for item in _l])
        else:
            append = ''
        if opts is not None:
            opts = ' '.join(opts)
        else:
            opts = ''
        # Start VM using virtme-run
        rw_dirs = ' '.join(f'--overlay-rwdir {d}' for d in ('/boot', '/etc', '/home', '/opt', '/srv', '/usr', '/var'))
        cmd = f'virtme-run {arch} --name {hostname} --kdir ./ {mods} {rw_dirs} {pwd} {username} {root} {execute} {network} {disk} {append} {opts} --qemu-opts -m {memory} -smp {cpus} -s -qmp tcp:localhost:3636,server,nowait'
        check_call(cmd, shell=True)

    def dump(self, dump_file):
        if not os.path.isfile('vmlinux'):
            arg_fail('vmlinux not found, try to recompile the kernel with --build-host-vmlinux (if --build-host was used)')
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
                check_call(['crash', tmp.name, './vmlinux'])

    def clean(self, build_host=None):
        if build_host is None:
            cmd = self._format_cmd("git clean -xdf")
        else:
            cmd = f'ssh {build_host} --'
            cmd = self._format_cmd(cmd)
            cmd.append('cd ~/.virtme && git clean -xdf')
        check_call(cmd)

def main():
    autocomplete(_ARGPARSER)
    args = _ARGPARSER.parse_args()

    ks = KernelSource(args.init)
    if ks.default_opts:
        for opt in ks.default_opts:
            val = ks.default_opts[opt]
            setattr(args, opt, val)
    if args.init:
        print('virtme-ng git repository initialized')
    elif args.clean:
        ks.clean(build_host=args.build_host)
    elif args.dump:
        ks.dump(args.dump_file)
    else:
        if not args.skip_build:
            ks.checkout(release=args.release, commit=args.commit, \
                        build_host=args.build_host, force=args.force)
            ks.config(arch=args.arch, config=args.config, envs=args.envs)
            if args.kconfig:
                return
            ks.make(arch=args.arch, build_host=args.build_host, \
                    build_host_exec_prefix=args.build_host_exec_prefix, \
                    build_host_vmlinux=args.build_host_vmlinux, \
                    skip_modules=args.skip_modules, compiler=args.compiler, envs=args.envs)
        ks.run(arch=args.arch, root=args.root, \
               cpus=args.cpus, memory=args.memory, network=args.network, disk=args.disk,
               append=args.append, execute=args.exec, opts=args.opts, \
               skip_modules=args.skip_modules)

if __name__ == '__main__':
    exit(main())
