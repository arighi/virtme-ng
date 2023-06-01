# -*- mode: python -*-
# Copyright 2023 Andrea Righi

"""virtme-ng: main command-line frontend."""

import argparse
import os
import sys
import socket
import shutil
import json
import tempfile
import time
import threading
import datetime
from subprocess import check_call, check_output, DEVNULL
from pathlib import Path
from argcomplete import autocomplete
from virtme.util import SilentError, uname

from virtme_ng.utils import VERSION, CONF_FILE

def log_msg(message):
    """Log a message with a timestamp."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sys.stderr.write(f"[{timestamp}] {message}")
    sys.stderr.flush()

def spinner_decorator(show_spinner=False, message=""):
    """Function decorator to show a spinner while the function is running."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            stop_event = threading.Event()
            if show_spinner in kwargs.values():
                log_msg(message + "\n")
                spinner_thread = threading.Thread(target=spinner, args=(stop_event,))
                spinner_thread.start()
            result = None
            try:
                result = func(*args, **kwargs)
            finally:
                if show_spinner in kwargs.values():
                    stop_event.set()
                    spinner_thread.join()
                    if result is not None:
                        log_msg('ok\n')
            return result

        def spinner(stop_event):
            while not stop_event.is_set():
                for char in '|/-\\':
                    sys.stderr.write(f'{char}\b')
                    sys.stderr.flush()
                    time.sleep(0.1)

        return wrapper

    return decorator

def make_parser():
    """Main virtme-ng command line parser."""

    parser = argparse.ArgumentParser(
        description='Build and run kernels inside a virtualized snapshot of your live system',
    )
    parser.add_argument('--version', '-v', action='version', version=f'%(prog)s {VERSION}')

    g_action = parser.add_argument_group(title='Action').add_mutually_exclusive_group()

    g_action.add_argument('--run', '-r', action='store', nargs='?',
            const=uname.release, default=None,
            help='Run specified kernel image or an installed kernel version. '
                 'If no argument is specified the running kernel will be used.')

    g_action.add_argument('--build', '-b', action='store_true',
            help='Build the kernel in the current directory '
                 '(or remotely if used with --build-host)')

    g_action.add_argument('--clean', '-x', action='store_true',
            help='Clean the kernel repository (local or remote if used with --build-host)')

    g_action.add_argument('--dump', '-d', action='store_true',
            help='Generate a memory dump of the running kernel and inspect it '
                 '(instance needs to be started with --debug)')

    parser.add_argument('--skip-config', '-s', action='store_true',
            help='Do not re-generate kernel .config')

    parser.add_argument('--debug', action='store_true',
            help='Start the instance with debugging enabled (allow to generate crash dumps)')

    parser.add_argument('--kconfig', '-k', action='store_true',
            help='Only generate the kernel .config without building/running anything')

    parser.add_argument('--dump-file', action='store',
            help='Generate a memory dump of the running kernel to a target file')

    parser.add_argument('--skip-modules', '-S', action='store_true',
            help='Run a really fast build by skipping external modules '
                 '(no external modules support)')

    parser.add_argument('--commit', '-c', action='store',
            help='Use a kernel identified by a specific commit id, tag or branch')

    parser.add_argument('--config', '-f', action='append',
            help='Use one (or more) specific kernel .config snippet '
                 'to override default config settings')

    parser.add_argument('--compiler', action='store',
            help='Compiler to be used as CC when building the kernel')

    parser.add_argument('--name', action='store',
            help='Set guest hostname and qemu -name flag')

    parser.add_argument('--user', action='store',
            help='Change user inside the guest (default is same user as the host)')

    parser.add_argument('--root', action='store',
            help='Pass a specific chroot to use inside the virtualized kernel ' +
                 '(useful with --arch)')

    parser.add_argument('--rw', action='store_true',
            help='Give the guest read-write access to its root filesystem. '
                 'WARNING: this can be dangerous for the host filesystem!')

    parser.add_argument('--force-9p', action='store_true',
            help='Use legacy 9p filesystem as rootfs')

    parser.add_argument('--cwd', action='store',
            help='Change guest working directory ' +
                 '(default is current working directory when possible)')

    parser.add_argument('--pwd', action='store_true',
            help='[deprecated] --pwd is set implicitly by default')

    parser.add_argument('--rodir', action='append', default=[],
            help='Supply a read-only directory to the guest.' +
                 'Use --rodir=path or --rodir=guestpath=hostpath')

    parser.add_argument('--rwdir', action='append', default=[],
            help='Supply a read/write directory to the guest.' +
                 'Use --rwdir=path or --rwdir=guestpath=hostpath')

    parser.add_argument('--overlay-rwdir', action='append', default=[],
            help='Supply a directory that is r/w to the guest but read-only in the host.' +
                 'Use --overlay-rwdir=path.')

    parser.add_argument('--cpus', '-p', action='store',
        help='Set guest CPU count (qemu -smp flag)')

    parser.add_argument('--memory', '-m', action='store',
            help='Set guest memory size (qemu -m flag)')

    parser.add_argument('--balloon', action='store_true',
            help='Allow the host to ask the guest to release memory')

    parser.add_argument('--network', '-n', action='store',
            metavar='user|bridge', help='Enable network access')

    parser.add_argument('--disk', '-D', action='append',
            metavar='PATH', help='Add a file as virtio-scsi disk (can be used multiple times)')

    parser.add_argument('--exec', '-e', action='store',
            help='Execute a command inside the kernel and exit')

    parser.add_argument('--append', '-a', action='append',
            help='Additional kernel boot options (can be used multiple times)')

    parser.add_argument('--force-initramfs', action='store_true',
            help='Use an initramfs even if unnecessary')

    parser.add_argument('--graphics', '-g', action='store',
            nargs='?', const='', metavar="BINARY",
            help='Show graphical output instead of using a console. ' +
                 'An argument can be optionally specified to start a graphical application.')

    parser.add_argument('--quiet', '-q', action='store_true',
            help='Reduce console output verbosity.')

    parser.add_argument('--opts', '-o', action='append',
            help='Additional options passed to virtme-run (can be used multiple times)')

    parser.add_argument('--build-host', action='store',
            help='Perform kernel build on a remote server (ssh access required)')

    parser.add_argument('--build-host-exec-prefix', action='store',
            help='Prepend a command (e.g., chroot) '
                 'to the make command executed on the remote build host')

    parser.add_argument('--build-host-vmlinux', action='store_true',
            help='Copy vmlinux back from the build host')

    parser.add_argument('--arch', action='store',
            help='Generate and test a kernel for a specific architecture '
                 '(default is host architecture)')

    parser.add_argument('--force', action='store_true',
            help='Force reset git repository to target branch or commit '
                 '(warning: this may drop uncommitted changes)')

    parser.add_argument('envs', metavar='envs', type=str, nargs='*',
                        help='Additional Makefile variables')
    return parser

_ARGPARSER = make_parser()

def arg_fail(message, show_usage=True):
    """Print an error message and exit, optionally showing usage help."""
    sys.stderr.write(message + "\n")
    if show_usage:
        _ARGPARSER.print_usage()
    sys.exit(1)

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
    """Initialize a rootfs directory, populating files/directory if it doesn't exist."""
    if os.path.exists(destdir):
        return
    # Use Ubuntu's cloud images to create a rootfs, these images are fairly
    # small and they provide a nice environment to test kernels.
    release = check_output('lsb_release -s -c', shell=True).decode(sys.stdout.encoding).rstrip()
    url = 'https://cloud-images.ubuntu.com/' + \
          f'{release}/current/{release}-server-cloudimg-{arch}-root.tar.xz'
    prevdir = os.getcwd()
    os.system(f'sudo mkdir -p {destdir}')
    os.chdir(destdir)
    os.system(f'curl -s {url} | sudo tar xvJ')
    os.chdir(prevdir)

def get_username():
    """Reliably get current username."""
    try:
        username = os.getlogin()
    except OSError:
        # If os.getlogin() fails, try alternative methods
        username = os.getenv('USER') or os.getenv('LOGNAME')
    return username

class KernelSource:
    """Main class that implement actions to perform on a kernel source directory."""
    def __init__(self):
        self.virtme_param = {}
        conf_path = self.get_conf_file_path()
        self.default_opts = []
        if conf_path is not None:
            with open(conf_path, 'r', encoding='utf-8') as conf_fd:
                conf_data = json.loads(conf_fd.read())
                if 'default_opts' in conf_data:
                    self.default_opts = conf_data['default_opts']
        self.cpus = str(os.cpu_count())

    def get_conf_file_path(self):
        """Return virtme-ng main configuration file path."""

        # First check if there is a config file in the user's home config
        # directory, then check for a single config file in ~/.virtme-ng.conf and
        # finally check for /etc/virtme-ng.conf. If none of them exist, report an
        # error and exit.
        configs = (CONF_FILE,
                   Path(Path.home(), '.virtme-ng.conf'),
                   Path('/etc', 'virtme-ng.conf'))
        for conf in configs:
            if conf.exists():
                return conf
        return None

    def _format_cmd(self, cmd):
        return list(filter(None, cmd.split(' ')))

    def _is_dirty_repo(self):
        cmd = 'git --no-optional-locks status -uno --porcelain'
        if check_output(self._format_cmd(cmd), stderr=DEVNULL, stdin=DEVNULL):
            return True
        return False

    def checkout(self, args):
        """Perform a git checkout operation on a local kernel git repository."""
        if not os.path.isdir('.git'):
            arg_fail('error: must run from a kernel git repository', show_usage=False)
        target = args.commit or 'HEAD'
        if args.build_host is not None or target != 'HEAD':
            if not args.force and self._is_dirty_repo():
                arg_fail("error: you have uncommitted changes in your git repository, " + \
                         "use --force to drop them", show_usage=False)
            check_call(['git', 'reset', '--hard', target], \
                       stdout=DEVNULL if args.quiet else sys.stderr, stdin=DEVNULL)

    def config(self, args):
        """Perform a make config operation on a kernel source directory."""
        arch = args.arch
        cmd = 'virtme-configkernel --update'
        if arch is not None:
            if arch not in ARCH_MAPPING:
                arg_fail(f'unsupported architecture: {arch}')
            arch = ARCH_MAPPING[arch]['qemu_name']
            cmd += f' --arch {arch}'
        user_config = str(Path.home()) + '/.config/virtme-ng/kernel.config'
        if args.config:
            for conf in args.config:
                cmd += f' --custom {conf}'
        if os.path.exists(user_config):
            cmd += f' --custom {user_config}'
        # Propagate additional Makefile variables
        for var in args.envs:
            cmd += f' {var} '
        check_call(self._format_cmd(cmd), \
                   stdout=DEVNULL if args.quiet else sys.stderr, stdin=DEVNULL)

    def _make_remote(self, args, make_command):
        check_call(['ssh', args.build_host,
                    'mkdir -p ~/.virtme'], \
                    stdout=DEVNULL if args.quiet else sys.stderr, stdin=DEVNULL)
        check_call(['ssh', args.build_host,
                    'git init ~/.virtme'], \
                    stdout=DEVNULL if args.quiet else sys.stderr, stdin=DEVNULL)
        check_call(['git', 'push', '--force', '--porcelain', f"{args.build_host}:~/.virtme",
                    'HEAD:__virtme__', ], \
                    stdout=DEVNULL if args.quiet else sys.stderr, stdin=DEVNULL)
        cmd = f'rsync .config {args.build_host}:.virtme/.config'
        check_call(self._format_cmd(cmd), \
                   stdout=DEVNULL if args.quiet else sys.stderr, stdin=DEVNULL)
        # Create remote build script
        with tempfile.NamedTemporaryFile(mode='w+t') as tmp:
            tmp.write(REMOTE_BUILD_SCRIPT.format(args.build_host_exec_prefix or '', \
                                                 make_command + ' -j$(nproc --all)'))
            tmp.flush()
            cmd = f'rsync {tmp.name} {args.build_host}:.virtme/.kc-build'
            check_call(self._format_cmd(cmd), \
                       stdout=DEVNULL if args.quiet else sys.stderr, stdin=DEVNULL)
        # Execute remote build script
        check_call(['ssh', args.build_host, 'bash', '.virtme/.kc-build'], \
                   stdout=DEVNULL if args.quiet else sys.stderr, stdin=DEVNULL)
        # Copy artifacts back to the running host
        with tempfile.NamedTemporaryFile(mode='w+t') as tmp:
            if args.build_host_vmlinux or args.arch == 'ppc64el':
                vmlinux = '--include=vmlinux'
            else:
                vmlinux = ''
            if args.skip_modules:
                cmd = 'rsync -azS --progress --exclude=.config --exclude=.git/ ' + \
                      '--include=*/ --include=bzImage --include=zImage --include=Image ' + \
                      f'{vmlinux} --include=*.dtb --exclude="*" {args.build_host}:.virtme/ ./'
            else:
                cmd = 'rsync -azS --progress --exclude=.config --exclude=.git/ ' + \
                      '--include=*/ --include="*.ko" --include=".dwo" ' + \
                      f'--include=bzImage --include=zImage --include=Image {vmlinux} ' + \
                      '--include=.config --include=modules.* ' + \
                      '--include=System.map --include=Module.symvers --include=module.lds ' + \
                      '--include=*.dtb --include="**/generated/**" --exclude="*" ' + \
                      f'{args.build_host}:.virtme/ ./'
            tmp.write(cmd)
            tmp.flush()
            check_call(['bash', tmp.name], \
                       stdout=DEVNULL if args.quiet else sys.stderr, stdin=DEVNULL)
        if not args.skip_modules:
            if os.path.exists('./debian/rules'):
                check_call(['fakeroot', 'debian/rules', 'clean'], \
                           stdout=DEVNULL if args.quiet else sys.stderr, stdin=DEVNULL)
            check_call(self._format_cmd(make_command + f' -j {self.cpus}' + ' modules_prepare'), \
                       stdout=DEVNULL if args.quiet else sys.stderr, stdin=DEVNULL)

    def make(self, args):
        """Perform a make operation on a kernel source directory."""
        if not os.path.isdir('.git') and args.build_host is not None:
            arg_fail('error: --build-host can be used only on a kernel git repository',
                     show_usage=False)
        if args.build_host is not None and self._is_dirty_repo():
            arg_fail("error: you have uncommitted changes in your git repository, " + \
                     "commit or drop them before building on a remote host", show_usage=False)
        arch = args.arch
        if arch is not None:
            if arch not in ARCH_MAPPING:
                arg_fail(f'unsupported architecture: {arch}')
            target = ARCH_MAPPING[arch]['kernel_target']
            cross_compile = ARCH_MAPPING[arch]['cross_compile']
            cross_arch = ARCH_MAPPING[arch]['linux_name']
        else:
            target = 'bzImage'
            cross_compile = None
            cross_arch = None
        make_command = MAKE_COMMAND
        if args.compiler:
            make_command += f' CC={args.compiler}'
        if args.skip_modules:
            make_command += f' {target}'
        if cross_compile and cross_arch:
            make_command += f' CROSS_COMPILE={cross_compile} ARCH={cross_arch}'
        # Propagate additional Makefile variables
        for var in args.envs:
            make_command += f' {var} '
        if args.build_host is None:
            # Build the kernel locally
            check_call(self._format_cmd(make_command + ' -j' + self.cpus),
                       stdout=DEVNULL if args.quiet else sys.stderr, stdin=DEVNULL)
        else:
            # Build the kernel on a remote build host
            self._make_remote(args, make_command)

    def _get_virtme_name(self, args):
        if args.name is not None:
            self.virtme_param['name'] = '--name ' + args.name
        else:
            self.virtme_param['name'] = '--name ' + socket.gethostname()

    def _get_virtme_arch(self, args):
        if args.arch is not None:
            if args.arch not in ARCH_MAPPING:
                arg_fail(f'unsupported architecture: {args.arch}')
            if 'max-cpus' in ARCH_MAPPING[args.arch]:
                self.cpus = ARCH_MAPPING[args.arch]['max-cpus']
            self.virtme_param['arch'] = '--arch ' + \
                    ARCH_MAPPING[args.arch]['qemu_name']
        else:
            self.virtme_param['arch'] = ''

    def _get_virtme_user(self, args):
        if args.user is not None:
            self.virtme_param['user'] = '--user ' + args.user
        elif args.root is None:
            self.virtme_param['user'] = '--user ' + get_username()
        else:
            self.virtme_param['user'] = ''

    def _get_virtme_root(self, args):
        if args.root is not None:
            create_root(args.root, args.arch or 'amd64')
            self.virtme_param['root'] = f'--root {args.root}'
        else:
            self.virtme_param['root'] = ''

    def _get_virtme_rw(self, args):
        if args.rw:
            self.virtme_param['rw'] = '--rw'
        else:
            self.virtme_param['rw'] = ''

    def _get_virtme_cwd(self, args):
        if args.cwd is not None:
            if args.pwd:
                arg_fail('--pwd and --cwd are mutually exclusive')
            self.virtme_param['cwd'] = '--cwd ' + args.cwd
        elif args.root is None:
            self.virtme_param['cwd'] = '--pwd'
        else:
            self.virtme_param['cwd'] = ''

    def _get_virtme_rodir(self, args):
        self.virtme_param['rodir'] = ''
        for item in args.rodir:
            self.virtme_param['rodir'] += '--rodir ' + item

    def _get_virtme_rwdir(self, args):
        self.virtme_param['rwdir'] = ''
        for item in args.rwdir:
            self.virtme_param['rwdir'] += '--rwdir ' + item

    def _get_virtme_overlay_rwdir(self, args):
        # Set default overlays if rootfs is mounted in read-only mode.
        if not args.rw:
            self.virtme_param['overlay_rwdir'] = ' '.join(f'--overlay-rwdir {d}' \
                    for d in ('/etc', '/home', '/opt', '/srv', '/usr', '/var'))
        # Add user-specified overlays.
        for item in args.overlay_rwdir:
            self.virtme_param['overlay_rwdir'] += '--overlay-rwdir ' + item

    def _get_virtme_run(self, args):
        if args.run is not None:
            self.virtme_param['kdir'] = '--kimg ' + args.run
        else:
            self.virtme_param['kdir'] = '--kdir ./'

    def _get_virtme_mods(self, args):
        if args.skip_modules:
            self.virtme_param['mods'] = '--mods none'
        else:
            self.virtme_param['mods'] = '--mods auto'

    def _get_virtme_exec(self, args):
        if args.exec is not None:
            self.virtme_param['exec'] = f'--script-sh "{args.exec}"'
        else:
            self.virtme_param['exec'] = ''

    def _get_virtme_network(self, args):
        if args.network is not None:
            self.virtme_param['network'] = f'--net {args.network}'
        else:
            self.virtme_param['network'] = ''

    def _get_virtme_disk(self, args):
        if args.disk is not None:
            disk_str = ''
            for dsk in args.disk:
                disk_str += f'--blk-disk {dsk}={dsk} '
            self.virtme_param['disk'] = disk_str
        else:
            self.virtme_param['disk'] = ''

    def _get_virtme_9p(self, args):
        if args.force_9p:
            self.virtme_param['force_9p'] = '--force-9p'
        else:
            self.virtme_param['force_9p'] = ''

    def _get_virtme_initramfs(self, args):
        if args.force_initramfs:
            self.virtme_param['force_initramfs'] = '--force-initramfs'
        else:
            self.virtme_param['force_initramfs'] = ''

    def _get_virtme_graphics(self, args):
        if args.graphics is not None:
            self.virtme_param['graphics'] = f'--graphics "{args.graphics}"'
        else:
            self.virtme_param['graphics'] = ''

    def _get_virtme_quiet(self, args):
        if args.quiet:
            self.virtme_param['quiet'] = '--quiet'
        else:
            self.virtme_param['quiet'] = ''

    def _get_virtme_append(self, args):
        if args.append is not None:
            append = []
            for item in args.append:
                split_items = item.split()
                for split_item in split_items:
                    append.append('-a ' + split_item)
            self.virtme_param['append'] = ' '.join(append)
        else:
            self.virtme_param['append'] = ''

    def _get_virtme_memory(self, args):
        if args.memory is None:
            self.virtme_param['memory'] = '--memory 1G'
        else:
            self.virtme_param['memory'] = '--memory ' + args.memory

    def _get_virtme_balloon(self, args):
        if args.balloon:
            self.virtme_param['balloon'] = '--balloon'
        else:
            self.virtme_param['balloon'] = ''

    def _get_virtme_opts(self, args):
        if args.opts is not None:
            self.virtme_param['opts'] = ' '.join(args.opts)
        else:
            self.virtme_param['opts'] = ''

    def _get_virtme_cpus(self, args):
        if args.cpus is None:
            cpus = self.cpus
        else:
            cpus = args.cpus
        self.virtme_param['cpus'] = f'--qemu-opts -smp {cpus}'

    def _get_virtme_debug(self, args):
        if args.debug:
            self.virtme_param['debug'] = '-s -qmp tcp:localhost:3636,server,nowait'
        else:
            self.virtme_param['debug'] = ''

    def run(self, args):
        """Execute a kernel inside virtme-ng."""
        self._get_virtme_name(args)
        self._get_virtme_user(args)
        self._get_virtme_arch(args)
        self._get_virtme_root(args)
        self._get_virtme_rw(args)
        self._get_virtme_rodir(args)
        self._get_virtme_rwdir(args)
        self._get_virtme_overlay_rwdir(args)
        self._get_virtme_cwd(args)
        self._get_virtme_run(args)
        self._get_virtme_mods(args)
        self._get_virtme_exec(args)
        self._get_virtme_network(args)
        self._get_virtme_disk(args)
        self._get_virtme_9p(args)
        self._get_virtme_initramfs(args)
        self._get_virtme_graphics(args)
        self._get_virtme_quiet(args)
        self._get_virtme_append(args)
        self._get_virtme_memory(args)
        self._get_virtme_balloon(args)
        self._get_virtme_opts(args)
        self._get_virtme_cpus(args)
        self._get_virtme_debug(args)

        # Start VM using virtme-run
        cmd = ('virtme-run ' +
            f'{self.virtme_param["name"]} ' +
            f'{self.virtme_param["user"]} ' +
            f'{self.virtme_param["arch"]} ' +
            f'{self.virtme_param["root"]} ' +
            f'{self.virtme_param["rw"]} ' +
            f'{self.virtme_param["rodir"]} ' +
            f'{self.virtme_param["rwdir"]} ' +
            f'{self.virtme_param["overlay_rwdir"]} ' +
            f'{self.virtme_param["cwd"]} ' +
            f'{self.virtme_param["kdir"]} ' +
            f'{self.virtme_param["mods"]} ' +
            f'{self.virtme_param["exec"]} ' +
            f'{self.virtme_param["network"]} ' +
            f'{self.virtme_param["disk"]} ' +
            f'{self.virtme_param["force_9p"]} ' +
            f'{self.virtme_param["force_initramfs"]} ' +
            f'{self.virtme_param["graphics"]} ' +
            f'{self.virtme_param["quiet"]} ' +
            f'{self.virtme_param["append"]} ' +
            f'{self.virtme_param["memory"]} ' +
            f'{self.virtme_param["balloon"]} ' +
            f'{self.virtme_param["opts"]} ' +
            f'{self.virtme_param["cpus"]} ' +
            f'{self.virtme_param["debug"]} '
        )
        check_call(cmd, shell=True)

    def dump(self, dump_file):
        """Generate or analyze a crash memory dump."""
        if not os.path.isfile('vmlinux'):
            arg_fail('vmlinux not found, try to recompile the kernel with ' +
                     '--build-host-vmlinux (if --build-host was used)')
        # Use QMP to generate a memory dump
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(('localhost', 3636))
        data = sock.recv(1024)
        if not data:
            sys.exit(1)
        print(data)
        sock.send("{ \"execute\": \"qmp_capabilities\" }\r".encode('utf-8'))
        data = sock.recv(1024)
        if not data:
            sys.exit(1)
        print(data)
        with tempfile.NamedTemporaryFile(delete=dump_file is None) as tmp:
            msg = (
                "{\"execute\":\"dump-guest-memory\","
                "\"arguments\":{\"paging\":false,"
                "\"protocol\":\"file:" + tmp.name + "\"}}"
                "\r"
            )
            print(msg)
            sock.send(msg.encode('utf-8'))
            data = sock.recv(1024)
            if not data:
                sys.exit(1)
            print(data)
            data = sock.recv(1024)
            print(data)
            if dump_file:
                # Save memory dump to target file
                shutil.move(tmp.name, dump_file)
            else:
                # Use crash to inspect the memory dump
                check_call(['crash', tmp.name, './vmlinux'])

    def clean(self, build_host=None):
        """Clean a local or remote git repository."""
        if not os.path.isdir('.git'):
            arg_fail('error: must run from a kernel git repository', show_usage=False)
        if build_host is None:
            cmd = self._format_cmd("git clean -xdf")
        else:
            cmd = f'ssh {build_host} --'
            cmd = self._format_cmd(cmd)
            cmd.append('cd ~/.virtme && git clean -xdf')
        check_call(cmd)

@spinner_decorator(message="configuring kernel")
def config(kern_source, args, show_spinner=False): # pylint: disable=unused-argument
    """Confiugure the kernel."""
    kern_source.config(args)
    return True

@spinner_decorator(message="building kernel")
def make(kern_source, args, show_spinner=False): # pylint: disable=unused-argument
    """Build the kernel."""
    kern_source.make(args)
    return True

def run(kern_source, args):
    """Run the kernel."""
    kern_source.run(args)
    return True

def do_it() -> int:
    """Main body."""
    autocomplete(_ARGPARSER)
    args = _ARGPARSER.parse_args()

    kern_source = KernelSource()
    if kern_source.default_opts:
        for opt in kern_source.default_opts:
            val = kern_source.default_opts[opt]
            setattr(args, opt, val)
    try:
        if args.clean:
            kern_source.clean(build_host=args.build_host)
        elif args.dump:
            kern_source.dump(args.dump_file)
        else:
            if args.build:
                if args.commit:
                    kern_source.checkout(args)
                if not args.skip_config:
                    config(kern_source, args, show_spinner=not args.quiet)
                    if args.kconfig:
                        return
                make(kern_source, args, show_spinner=not args.quiet)
            run(kern_source, args)
    except Exception as exc:
        raise SilentError() from exc

def main() -> int:
    """Main."""
    try:
        return do_it()
    except (KeyboardInterrupt, SilentError):
        return 1

if __name__ == '__main__':
    try:
        sys.exit(main())
    except SilentError:
        sys.exit(1)
