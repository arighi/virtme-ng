# -*- mode: python -*-
# virtme-run: The main command-line virtme frontend
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

from typing import Any, Optional, List, NoReturn, Dict, Tuple

import atexit
import argparse
import tempfile
import os
import errno
import fcntl
import sys
import shlex
import re
import itertools
import subprocess
import signal
from shutil import which
from time import sleep
from .. import virtmods
from .. import modfinder
from .. import mkinitramfs
from .. import qemu_helpers
from .. import architectures
from .. import resources
from ..util import SilentError, uname

def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Virtualize your system (or another) under a kernel image',
    )

    g: Any

    g = parser.add_argument_group(title='Selection of kernel and modules').add_mutually_exclusive_group()
    g.add_argument('--installed-kernel', action='store', nargs='?',
                   const=uname.release, default=None, metavar='VERSION',
                   help='[Deprecated] use --kimg instead.')

    g.add_argument('--kimg', action='store', nargs='?',
                   const=uname.release, default=None,
                   help='Use specified kernel image or  an installed kernel version. If no argument is specified the running kernel will be used.')

    g.add_argument('--kdir', action='store', metavar='KDIR',
                   help='Use a compiled kernel source directory')

    g = parser.add_argument_group(title='Kernel options')
    g.add_argument('--mods', action='store', choices=['none', 'use', 'auto'], default='use',
                   help='Setup loadable kernel modules inside a compiled kernel source directory (used in conjunction with --kdir); none: ignore kernel modules, use: asks user to refresh virtme\'s kernel modules directory, auto: automatically refreshes virtme\'s kernel modules directory')

    g.add_argument('-a', '--kopt', action='append', default=[],
                   help='Add a kernel option.  You can specify this more than once.')

    g.add_argument('--xen', action='store',
                   help='Boot Xen using the specified uncompressed hypervisor.')

    g = parser.add_argument_group(title='Common guest options')
    g.add_argument('--root', action='store', default='/',
                   help='Local path to use as guest root')
    g.add_argument('--rw', action='store_true',
                   help='Give the guest read-write access to its root filesystem')
    g.add_argument('--graphics', action='store_true',
                   help='Show graphical output instead of using a console.')
    g.add_argument('--quiet', action='store_true',
                   help='Reduce console output verbosity.')
    g.add_argument('--net', action='store', const='user', nargs='?',
                   choices=['user', 'bridge'],
                   help='Enable basic network access.')
    g.add_argument('--balloon', action='store_true',
                   help='Allow the host to ask the guest to release memory.')
    g.add_argument('--disk', action='append', default=[], metavar='NAME=PATH',
                   help='Add a read/write virtio-scsi disk.  The device node will be /dev/disk/by-id/scsi-0virtme_disk_NAME.')
    g.add_argument('--blk-disk', action='append', default=[], metavar='NAME=PATH',
                   help='Add a read/write virtio-blk disk.  The device nodes will be /dev/disk/by-id/virtio-virtme_disk_blk_NAME.')
    g.add_argument('--memory', action='store', default=None,
                   help='Set guest memory and qemu -m flag.')
    g.add_argument('--cpus', action='store', default=None,
                   help='Set guest cpu and qemu -smp flag.')
    g.add_argument('--name', action='store', default=None,
                   help='Set guest hostname and qemu -name flag.')
    g.add_argument('--user', action='store',
                   help='Change guest user')

    g = parser.add_argument_group(
        title='Scripting',
        description="Using any of the scripting options will run a script in the guest.  The script's stdin will be attached to virtme-run's stdin and the script's stdout and stderr will both be attached to virtme-run's stdout.  Kernel logs will go to stderr.  This behaves oddly if stdin is a terminal; try using 'cat |virtme-run' if you have trouble with script mode.")
    g.add_argument('--script-sh', action='store', metavar='SHELL_COMMAND',
                   help='Run a one-line shell script in the guest.')
    g.add_argument('--script-exec', action='store', metavar='BINARY',
                   help='Run the specified binary in the guest.')

    g = parser.add_argument_group(
        title='Architecture',
        description="Options related to architecture selection")
    g.add_argument('--arch', action='store', metavar='ARCHITECTURE',
                   default=uname.machine,
                   help='Guest architecture')
    g.add_argument('--busybox', action='store', metavar='PATH_TO_BUSYBOX',
                   help='Use the specified busybox binary.')

    g = parser.add_argument_group(title='Virtualizer settings')
    g.add_argument('--qemu-bin', action='store', default=None,
                   help="Use specified QEMU binary.")
    g.add_argument('-q', '--qemu-opt', action='append', default=[],
                   help="Add a single QEMU argument.  Use this when --qemu-opts's greedy behavior is problematic.'")
    g.add_argument('--qemu-opts', action='store', nargs=argparse.REMAINDER,
                   metavar='OPTS...', help='Additional arguments for QEMU.  This will consume all remaining arguments, so it must be specified last.  Avoid using -append; use --kopt instead.')

    g = parser.add_argument_group(title='Debugging/testing')
    g.add_argument('--force-initramfs', action='store_true',
                   help='Use an initramfs even if unnecessary')
    g.add_argument('--force-9p', action='store_true',
                   help='Use legacy 9p filesystem as rootfs')
    g.add_argument('--dry-run', action='store_true',
                   help="Initialize everything but don't run the guest")
    g.add_argument('--show-command', action='store_true',
                   help='Show the VM command line')
    g.add_argument('--save-initramfs', action='store',
                   help='Save the generated initramfs to the specified path')
    g.add_argument('--show-boot-console', action='store_true',
                   help='Show the boot console when running scripts')

    g = parser.add_argument_group(title='Guest userspace configuration').add_mutually_exclusive_group()
    g.add_argument('--pwd', action='store_true',
                   help='Propagate current working directory to the guest')
    g.add_argument('--cwd', action='store',
                   help='Change guest working directory')

    g = parser.add_argument_group(title='Sharing resources with guest')
    g.add_argument('--rwdir', action='append', default=[],
                   help="Supply a read/write directory to the guest.  Use --rwdir=path or --rwdir=guestpath=hostpath.")
    g.add_argument('--rodir', action='append', default=[],
                   help="Supply a read-only directory to the guest.  Use --rodir=path or --rodir=guestpath=hostpath.")

    g.add_argument('--overlay-rwdir', action='append', default=[],
                   help="Supply a directory that is r/w to the guest but read-only in the host.  Use --overlay-rwdir=path.")

    return parser

_ARGPARSER = make_parser()

def arg_fail(message, show_usage=True) -> NoReturn:
    sys.stderr.write(message + "\n")
    if show_usage:
        _ARGPARSER.print_usage()
    sys.exit(1)

def is_file_more_recent(a, b) -> bool:
    return os.stat(a).st_mtime > os.stat(b).st_mtime

def has_memory_suffix(string):
    pattern = r'\d+[MGK]$'
    return re.match(pattern, string) is not None

class Kernel:
    __slots__ = ['kimg', 'dtb', 'modfiles', 'moddir', 'use_root_mods', 'config']

    kimg: str
    dtb: Optional[str]
    modfiles: List[str]
    moddir: Optional[str]
    use_root_mods: bool
    config: Optional[Dict[str, str]]

    def load_config(self, kdir: str) -> None:
        cfgfile = os.path.join(kdir, '.config')
        if os.path.isfile(cfgfile):
            self.config = {}
            regex = re.compile('^(CONFIG_[A-Z0-9_]+)=([ymn])$')
            for line in open(cfgfile, 'r'):
                m = regex.match(line.strip())
                if m:
                    self.config[m.group(1)] = m.group(2)

def get_rootfs_from_kernel_path(path):
    while path != '/' and not os.path.exists(path + '/lib/modules'):
        path, _ = os.path.split(path)
    return os.path.abspath(path)

def get_kernel_version(path):
    if not os.path.exists(path):
        arg_fail("kernel file %s does not exist, try --build to build the kernel" % path,
                 show_usage=False)
    if not os.access(path, os.R_OK):
        arg_fail("unable to access %s (check for read permissions)" % path, show_usage=False)
    result = subprocess.run(['file', path], capture_output=True, text=True)
    for item in result.stdout.split(', '):
        match = re.search(r'^[vV]ersion (\S+)', item)
        if match:
            kernel_version = match.group(1)
            return kernel_version
    # 'file' failed to get kernel version, try with 'strings'.
    result = subprocess.run(['strings', path], capture_output=True, text=True)
    match = re.search(r"Linux version (\S+)", result.stdout)
    if match:
        kernel_version = match.group(1)
        return kernel_version
    return None

def find_kernel_and_mods(arch, args) -> Kernel:
    kernel = Kernel()

    kernel.use_root_mods = False
    if args.installed_kernel is not None:
        sys.stderr.write("Warning: --installed-kernel is deprecated. Use --kimg instead.\n")
        args.kimg = args.installed_kernel

    if args.kimg is not None:
        # If a locally built kernel image / dir is provided just fallback to
        # the --kdir case.
        kdir = None
        if os.path.exists(args.kimg):
            if os.path.isdir(args.kimg):
                kdir = args.kimg
            elif args.kimg.endswith(arch.kimg_path()):
                if args.kimg == arch.kimg_path():
                    kdir = '.'
                else:
                    kdir = args.kimg.split(arch.kimg_path())[0]
            if kdir is not None and os.path.exists(kdir + '/.config'):
                args.kdir = kdir
                args.kimg = None

    if args.kimg is not None:
        # Try to resolve kimg as a kernel version first, then check if a file
        # is provided.
        kimg = '/usr/lib/modules/%s/vmlinuz' % args.kimg
        if not os.path.exists(kimg):
            kimg = '/boot/vmlinuz-%s' % args.kimg
            if not os.path.exists(kimg):
                kimg = args.kimg
                if not os.path.exists(kimg):
                    arg_fail("%s does not exist" % args.kimg)
        kver = get_kernel_version(kimg)
        if kver is None:
            arg_fail("%s does not seem to be a valid kernel file / directory" % kimg, show_usage=False)
        kernel.kimg = kimg
        if args.mods == 'none':
            kernel.modfiles = []
            kernel.moddir = None
        else:
            # Try to automatically detect modules' path
            root_dir = get_rootfs_from_kernel_path(kernel.kimg)
            if root_dir == '/':
                kernel.use_root_mods = True
            elif root_dir.startswith('/tmp'):
                sys.stderr.write("\nWarning: /tmp is hidden inside the guest, kernel modules won't be supported at runtime unless you move them somewhere else.\n\n")
            kernel.moddir = f'{root_dir}/lib/modules/{kver}'
            if not os.path.exists(kernel.moddir):
                kernel.modfiles = []
                kernel.moddir = None
            else:
                mod_file = os.path.join(kernel.moddir, 'modules.dep')
                if not os.path.exists(mod_file):
                    # Try to refresh modules directory. Some packages (e.g., debs)
                    # don't ship all the required modules information, so we
                    # need to refresh the modules directory using depmod.
                    subprocess.call(['depmod', '-a', '-b', root_dir, kver],
                                    stderr=subprocess.DEVNULL)
                kernel.modfiles = modfinder.find_modules_from_install(
                                    virtmods.MODALIASES, root=root_dir, kver=kver)
        kernel.dtb = None  # For now
    elif args.kdir is not None:
        kimg = os.path.join(args.kdir, arch.kimg_path())
        kver = get_kernel_version(kimg)
        if kver is None:
            arg_fail("%s does not seem to be a valid kernel file / directory" % kimg, show_usage=False)
        kernel.kimg = kimg
        virtme_mods = os.path.join(args.kdir, '.virtme_mods')
        mod_file = os.path.join(args.kdir, 'modules.order')
        virtme_mod_file = os.path.join(virtme_mods, 'lib/modules/0.0.0/modules.dep')
        kernel.load_config(args.kdir)

        # Kernel modules support
        kver = None
        kernel.moddir = None
        kernel.modfiles = []

        modmode = args.mods
        if kernel.config is not None and kernel.config.get('CONFIG_MODULES', 'n') != 'y':
            modmode = 'none'

        if modmode == 'none':
            pass
        elif modmode == 'use' or modmode == 'auto':
            # Check if modules.order exists, otherwise fallback to mods=none
            if os.path.exists(mod_file):
                # Check if virtme's kernel modules directory needs to be updated
                if not os.path.exists(virtme_mods) or \
                   is_file_more_recent(mod_file, virtme_mod_file):
                    if modmode == 'use':
                        # Inform user to manually refresh virtme's kernel modules
                        # directory
                        arg_fail("please run virtme-prep-kdir-mods to update virtme's kernel modules directory or use --mods=auto", show_usage=False)
                    else:
                        # Auto-refresh virtme's kernel modules directory
                        try:
                            resources.run_script('virtme-prep-kdir-mods',
                                                 cwd=args.kdir)
                        except subprocess.CalledProcessError:
                            raise SilentError()
                kernel.moddir = os.path.join(virtme_mods, 'lib/modules', '0.0.0')
                kernel.modfiles = modfinder.find_modules_from_install(
                                   virtmods.MODALIASES, root=virtme_mods, kver='0.0.0')
            else:
                sys.stderr.write('\n%s not found: kernel modules not enabled or kernel not compiled properly, kernel modules disabled\n\n' % mod_file)
        else:
            arg_fail("invalid argument '%s', please use --mods=none|use|auto" % args.mods)

        dtb_path = arch.dtb_path()
        if dtb_path is None:
            kernel.dtb = None
        else:
            kernel.dtb = os.path.join(args.kdir, dtb_path)
    else:
        arg_fail('You must specify a kernel to use.')

    return kernel

# virtio-fs temporary files
virtiofsd_sock = None
virtiofsd_pid  = None

def cleanup_virtiofs_temp_files():
    # Make sure to kill virtiofsd instances that are still potentially running
    if virtiofsd_pid is not None:
        try:
            with open(virtiofsd_pid) as fd:
                pid = int(fd.read().strip())
                os.kill(pid, signal.SIGTERM)
        except (FileNotFoundError, ValueError, OSError):
            pass
    # Clean up temp files
    temp_files = [virtiofsd_sock, virtiofsd_pid]
    for file_path in temp_files:
        try:
            os.remove(file_path)
        except OSError:
            pass

def get_virtiofsd_path():
    # Define the possible virtiofsd paths.
    #
    # NOTE: do not use the C implemention of qemu's virtiofsd, because it
    # doesn't support unprivileged-mode execution and it would be totally
    # unsafe to export the whole rootfs of the host running as root.
    #
    # Instead, always rely on the Rust implementation of virtio-fs:
    # https://gitlab.com/virtio-fs/virtiofsd
    #
    # This project is receiving the most attention for new feature development
    # and the daemon is able to export the entire root filesystem of the host
    # as non-privileged user.
    #
    # Starting with version 8.0, qemu will not ship the C implementation of
    # virtiofsd anymore, allowing to use the Rust daemon installed in the the
    # same path (/usr/lib/qemu/virtiofsd), so also consider this one in the
    # list of possible paths.
    #
    # We can detect if the qemu implementation is installed in /usr/lib/qemu,
    # simply by running the command with --version as non-root. If it returns
    # an error it means that we are using the qemu daemon and we just skip it.
    possible_paths = (
        which('virtiofsd'),
        '/usr/libexec/virtiofsd',
        '/usr/lib/qemu/virtiofsd',
    )
    for path in possible_paths:
        if path and os.path.exists(path) and os.access(path, os.X_OK):
            try:
                subprocess.check_call([path, '--version'],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
                return path
            except:
                pass
    return None

def start_virtiofsd(path, verbose=True):
    global virtiofsd_sock
    global virtiofsd_pid

    virtiofsd_path = get_virtiofsd_path()
    if virtiofsd_path is None:
        return False

    # virtiofsd located, try to start the daemon as non-privileged user.
    _, virtiofsd_sock = tempfile.mkstemp(prefix='virtme')
    virtiofsd_pid = virtiofsd_sock + '.pid'

    # Make sure to clean up temp files before starting the daemon and at exit.
    cleanup_virtiofs_temp_files()
    atexit.register(cleanup_virtiofs_temp_files)

    # Export the whole root fs of the host, do not enable sandbox, otherwise we
    # would get permission errors.
    os.system(f"{virtiofsd_path} --syslog --socket-path {virtiofsd_sock} --shared-dir {path} --sandbox none &")
    max_attempts = 5
    check_duration = 0.1
    for attempt in range(max_attempts):
        if os.path.exists(virtiofsd_pid):
            break
        if verbose:
            sys.stderr.write('virtme: waiting for virtiofsd to start\n')
        sleep(check_duration)
        check_duration *= 2;
    else:
        print('virtme-run: failed to start virtiofsd, fallback to 9p')
        return False
    return True

def export_virtiofs(qemu: qemu_helpers.Qemu, arch: architectures.Arch,
                    qemuargs: List[str], path: str,
                    mount_tag: str, security_model='none', memory=None,
                    readonly=True, verbose=False) -> None:

    if not arch.virtiofs_support():
        return False

    # Try to start virtiofsd deamon
    ret = start_virtiofsd(path, verbose)
    if not ret:
        return False

    # Adjust qemu options to use virtiofsd
    fsid = 'virtfs%d' % len(qemuargs)
    if memory is None:
        memory = '128M'
    vhost_dev_type = arch.vhost_dev_type()
    qemuargs.extend(['-chardev', f'socket,id=char{fsid},path={virtiofsd_sock}'])
    qemuargs.extend(['-device', f'{vhost_dev_type},chardev=char{fsid},tag={mount_tag}'])
    qemuargs.extend(['-object', f'memory-backend-memfd,id=mem,size={memory},share=on'])
    qemuargs.extend(['-numa', f'node,memdev=mem'])

    return True

def export_virtfs(qemu: qemu_helpers.Qemu, arch: architectures.Arch,
                  qemuargs: List[str], path: str,
                  mount_tag: str, security_model='none', readonly=True) -> None:
    # NB: We can't use -virtfs for this, because it can't handle a mount_tag
    # that isn't a valid QEMU identifier.
    fsid = 'virtfs%d' % len(qemuargs)
    qemuargs.extend(['-fsdev', 'local,id=%s,path=%s,security_model=%s%s%s' %
                     (fsid, qemu.quote_optarg(path),
                      security_model, ',readonly=on' if readonly else '',
                      ',multidevs=remap' if qemu.has_multidevs else '')])
    qemuargs.extend(['-device', '%s,fsdev=%s,mount_tag=%s' % (arch.virtio_dev_type('9p'), fsid, qemu.quote_optarg(mount_tag))])

def quote_karg(arg: str) -> str:
    if '"' in arg:
        raise ValueError("cannot quote '\"' in kernel args")

    if ' ' in arg:
        return '"%s"' % arg
    else:
        return arg

# Validate name=path arguments from --disk and --blk-disk
def sanitize_disk_args(func: str, arg: str) -> Tuple[str, str]:
    namefile = arg.split('=', 1)
    if len(namefile) != 2:
        arg_fail('invalid argument to %s' % func)
    name, fn = namefile
    if '=' in fn or ',' in fn:
        arg_fail("%s filenames cannot contain '=' or ','" % (func))
    if '=' in name or ',' in name:
        arg_fail("%s device names cannot contain '=' or ','" % (func))

    return name, fn

# Allowed characters in mount paths.  We can extend this over time if needed.
_SAFE_PATH_PATTERN = '[a-zA-Z0-9_+ /.-]+'
_RWDIR_RE = re.compile('^(%s)(?:=(%s))?$' %
                       (_SAFE_PATH_PATTERN, _SAFE_PATH_PATTERN))

def do_it() -> int:
    args = _ARGPARSER.parse_args()

    arch = architectures.get(args.arch)
    is_native = (args.arch == uname.machine)

    qemu = qemu_helpers.Qemu(args.qemu_bin, arch.qemuname)
    qemu.probe()

    need_initramfs = args.force_initramfs or qemu.cannot_overmount_virtfs

    config = mkinitramfs.Config()

    if len(args.overlay_rwdir) > 0:
        virtmods.MODALIASES.append('overlay')

    kernel = find_kernel_and_mods(arch, args)
    config.modfiles = kernel.modfiles
    if config.modfiles:
        need_initramfs = True

    qemuargs: List[str] = [qemu.qemubin]
    kernelargs = []
    xenargs = []

    # Put the '-name' flag first so it's easily visible in ps, top, etc.
    if args.name:
        qemuargs.extend(['-name', args.name])
        kernelargs.append('virtme_hostname=%s' % args.name)

    if args.memory:
        # If no memory suffix is specified, assume it's MB.
        if not has_memory_suffix(args.memory):
            args.memory += 'M'
        qemuargs.extend(['-m', args.memory])

    # Try to use virtio-fs first, in case of failure fallback to 9p, unless 9p
    # is forced.
    if args.force_9p:
        use_virtiofs = False
    else:
        # Try to switch to 'microvm' on x86_64, but only if virtio-fs can be
        # used for now.
        if not args.graphics and args.arch == 'x86_64':
            virt_arch = architectures.get('microvm')
        else:
            virt_arch = arch
        verbose = not (args.quiet or args.script_sh or args.script_exec)
        use_virtiofs = export_virtiofs(qemu, virt_arch, qemuargs, args.root, 'ROOTFS', memory=args.memory, \
                                       readonly=(not args.rw), verbose=verbose)
        if use_virtiofs:
            arch = virt_arch
    if not use_virtiofs:
        export_virtfs(qemu, arch, qemuargs, args.root, '/dev/root', readonly=(not args.rw))

    guest_tools_path = resources.find_guest_tools()
    if guest_tools_path is None:
        raise ValueError("couldn't find guest tools -- virtme is installed incorrectly")

    if args.root == '/':
        initcmds = [
            f'exec {guest_tools_path}/virtme-init'
        ]
    else:
        export_virtfs(qemu, arch, qemuargs, guest_tools_path, 'virtme.guesttools')
        initcmds = [
            'mkdir -p /run/virtme/guesttools',
            '/bin/mount -n -t 9p -o ro,version=9p2000.L,trans=virtio,access=any ' +
                    'virtme.guesttools /run/virtme/guesttools',
            'exec /run/virtme/guesttools/virtme-init',
        ]

    # Arrange for modules to end up in the right place
    if kernel.moddir is not None:
        if kernel.use_root_mods:
            # Tell virtme-init to use the root /lib/modules
            kernelargs.append("virtme_root_mods=1")
        else:
            # We're grabbing modules from somewhere other than /lib/modules.
            # Rather than mounting it separately, symlink it in the guest.
            # This allows symlinks within the module directory to resolve
            # correctly in the guest.
            kernelargs.append("virtme_link_mods=/%s" % qemu.quote_optarg(os.path.relpath(kernel.moddir, args.root)))
    else:
        # No modules are available.  virtme-init will hide /lib/modules/KVER
        pass

    # Set up mounts
    mount_index = 0
    for dirtype, dirarg in itertools.chain((('rwdir', i) for i in args.rwdir),
                                           (('rodir', i) for i in args.rodir)):
        m = _RWDIR_RE.match(dirarg)
        if not m:
            arg_fail('invalid --%s parameter %r' % (dirtype, dirarg))
        if m.group(2) is not None:
            guestpath = m.group(1)
            hostpath = m.group(2)
        else:
            hostpath = m.group(1)
            guestpath = os.path.relpath(hostpath, args.root)
            if guestpath.startswith('..'):
                arg_fail('%r is not inside the root' % hostpath)

        idx = mount_index
        mount_index += 1
        tag = 'virtme.initmount%d' % idx
        export_virtfs(qemu, arch, qemuargs, hostpath, tag, readonly=(dirtype != 'rwdir'))
        kernelargs.append('virtme_initmount%d=%s' % (idx, guestpath))

    for i, d in enumerate(args.overlay_rwdir):
        kernelargs.append('virtme_rw_overlay%d=%s' % (i, d))

    # Turn on KVM if available
    if is_native:
        qemuargs.extend(['-machine', 'accel=kvm:tcg'])

    # Add architecture-specific options
    qemuargs.extend(arch.qemuargs(is_native))

    # Set up / override baseline devices
    qemuargs.extend(['-parallel', 'none'])
    qemuargs.extend(['-net', 'none'])

    if not args.graphics and not args.script_sh and not args.script_exec:
        # It would be nice to use virtconsole, but it's terminally broken
        # in current kernels.  Nonetheless, I'm configuring the console
        # manually to make it easier to tweak in the future.
        qemuargs.extend(['-echr', '1'])
        qemuargs.extend(['-serial', 'none'])
        qemuargs.extend(['-chardev', 'stdio,id=console,signal=off,mux=on'])

        qemuargs.extend(arch.qemu_serial_console_args())

        qemuargs.extend(['-mon', 'chardev=console'])

        if not args.quiet:
            kernelargs.extend(arch.earlyconsole_args())
        qemuargs.extend(arch.qemu_nodisplay_args())

        if not args.xen:
            kernelargs.extend(arch.serial_console_args())
        else:
            # Horrible special case
            xenargs.extend(['console=com1'])
            kernelargs.extend(['xencons=hvc', 'console=hvc0'])

        # PS/2 probing is slow; give the kernel a hint to speed it up.
        kernelargs.extend(['psmouse.proto=exps'])

        # Fix the terminal defaults (and set iutf8 because that's a better
        # default nowadays).  I don't know of any way to keep this up to date
        # after startup, though.
        try:
                terminal_size = os.get_terminal_size()
                kernelargs.extend(['virtme_stty_con=rows %d cols %d iutf8' %
                                   (terminal_size.lines, terminal_size.columns)])
        except OSError as e:
                # don't die if running with a non-TTY stdout
                if e.errno != errno.ENOTTY:
                        raise

        # Propagate the terminal type
        if 'TERM' in os.environ:
            kernelargs.extend(['TERM=%s' % os.environ['TERM']])

    if args.balloon:
        qemuargs.extend(['-balloon', 'virtio'])

    if args.cpus:
        qemuargs.extend(['-smp', args.cpus])

    if args.blk_disk:
        for i,d in enumerate(args.blk_disk):
            driveid = 'blk-disk%d' % i
            name, fn = sanitize_disk_args('--blk-disk', d)
            qemuargs.extend(['-drive', 'if=none,id=%s,file=%s' % (driveid, fn),
                             '-device', '%s,drive=%s,serial=%s' % (arch.virtio_dev_type('blk'), driveid, name)])

    if args.disk:
        qemuargs.extend(['-device', '%s,id=scsi' % arch.virtio_dev_type('scsi')])

        for i,d in enumerate(args.disk):
            driveid = 'disk%d' % i
            name, fn = sanitize_disk_args('--disk', d)
            qemuargs.extend(['-drive', 'if=none,id=%s,file=%s' % (driveid, fn),
                             '-device', 'scsi-hd,drive=%s,vendor=virtme,product=disk,serial=%s' % (driveid, name)])

    has_script = False

    def do_script(shellcmd: str, use_exec=False, show_boot_console=False) -> None:
        if args.graphics:
            arg_fail('scripts and --graphics are mutually exclusive')

        nonlocal has_script
        nonlocal need_initramfs
        if has_script:
            arg_fail('conflicting script options')
        has_script = True
        need_initramfs = True  # TODO: Fix this

        # Turn off default I/O
        qemuargs.extend(arch.qemu_nodisplay_args())

        # Configure kernel console output
        if show_boot_console:
            output = '/proc/self/fd/2'
            console_args = ()
        else:
            output = '/dev/null'
            console_args = ['quiet', 'loglevel=0']
        qemuargs.extend(arch.qemu_serial_console_args())
        qemuargs.extend(['-chardev', f'file,id=console,path={output}'])

        kernelargs.extend(arch.serial_console_args())
        kernelargs.extend(arch.earlyconsole_args())
        kernelargs.extend(console_args)

        # Set up a virtserialport for script I/O
        #
        # NOTE: we need two additional I/O ports for /dev/stdout and
        # /dev/stderr in the guest.
        #
        # This is needed because virtio serial ports are designed to support a
        # single writer at a time, so any attempt to write directly to
        # /dev/stdout or /dev/stderr in the guest will result in an -EBUSY
        # error.
        qemuargs.extend(['-chardev', 'stdio,id=stdin,signal=on,mux=off'])
        qemuargs.extend(['-device', arch.virtio_dev_type('serial')])
        qemuargs.extend(['-device', 'virtserialport,name=virtme.stdin,chardev=stdin'])

        qemuargs.extend(['-chardev', 'file,id=stdout,path=/proc/self/fd/1'])
        qemuargs.extend(['-device', arch.virtio_dev_type('serial')])
        qemuargs.extend(['-device', 'virtserialport,name=virtme.stdout,chardev=stdout'])

        qemuargs.extend(['-chardev', 'file,id=stderr,path=/proc/self/fd/2'])
        qemuargs.extend(['-device', arch.virtio_dev_type('serial')])
        qemuargs.extend(['-device', 'virtserialport,name=virtme.stderr,chardev=stderr'])

        qemuargs.extend(['-chardev', 'file,id=dev_stdout,path=/proc/self/fd/1'])
        qemuargs.extend(['-device', arch.virtio_dev_type('serial')])
        qemuargs.extend(['-device', 'virtserialport,name=virtme.dev_stdout,chardev=dev_stdout'])

        qemuargs.extend(['-chardev', 'file,id=dev_stderr,path=/proc/self/fd/2'])
        qemuargs.extend(['-device', arch.virtio_dev_type('serial')])
        qemuargs.extend(['-device', 'virtserialport,name=virtme.dev_stderr,chardev=dev_stderr'])

        # Scripts shouldn't reboot
        qemuargs.extend(['-no-reboot'])

        # Ask virtme-init to run the script
        config.virtme_data[b'script'] = """#!/bin/sh

        {prefix}{shellcmd}
        """.format(shellcmd=shellcmd, prefix="exec " if use_exec else "").encode('ascii')

        # Nasty issue: QEMU will set O_NONBLOCK on fds 0, 1, and 2.
        # This isn't inherently bad, but it can cause a problem if
        # another process is reading from 1 or writing to 0, which is
        # exactly what happens if you're using a terminal and you
        # redirect some, but not all, of the tty fds.  Work around it
        # by giving QEMU private copies of the open object if either
        # of them is a terminal.
        for oldfd,mode in ((0,os.O_RDONLY), (1,os.O_WRONLY), (2,os.O_WRONLY)):
            if os.isatty(oldfd):
                try:
                    newfd = os.open('/proc/self/fd/%d' % oldfd, mode)
                except OSError:
                    pass
                else:
                    os.dup2(newfd, oldfd)
                    os.close(newfd)

    if args.script_sh is not None:
        do_script(args.script_sh, show_boot_console=args.show_boot_console)

    if args.script_exec is not None:
        do_script(shlex.quote(args.script_exec), use_exec=True, show_boot_console=args.show_boot_console)

    if args.net:
        qemuargs.extend(['-device', '%s,netdev=n0' % arch.virtio_dev_type('net')])
        if args.net == 'user':
            qemuargs.extend(['-netdev', 'user,id=n0'])
        elif args.net == 'bridge':
            qemuargs.extend(['-netdev', 'bridge,id=n0,br=virbr0'])
        else:
            assert False
        kernelargs.extend(['virtme.dhcp'])

    if args.pwd:
        rel_pwd = os.path.relpath(os.getcwd(), args.root)
        if rel_pwd.startswith('..'):
            print('current working directory is not contained in the root')
            return 1
        kernelargs.append('virtme_chdir=%s' % rel_pwd)

    if args.cwd is not None:
        if args.pwd:
            arg_fail('--pwd and --cwd are mutually exclusive')
        rel_cwd = os.path.relpath(args.cwd, args.root)
        if rel_cwd.startswith('..'):
            print('specified working directory is not contained in the root')
            return 1
        kernelargs.append('virtme_chdir=%s' % rel_cwd)

    if args.user:
        kernelargs.append('virtme_user=%s' % args.user)

    initrdpath: Optional[str]

    if need_initramfs:
        if args.busybox is not None:
            config.busybox = args.busybox
        else:
            busybox = mkinitramfs.find_busybox(args.root, is_native)
            if busybox is None:
                print('virtme-run: initramfs is needed, and no busybox was found',
                      file=sys.stderr)
                return 1
            config.busybox = busybox

        if args.rw:
            config.access = 'rw'

        # Set up the initramfs (warning: hack ahead)
        if args.save_initramfs is not None:
            initramfsfile = open(args.save_initramfs, 'xb')
            initramfsfd = initramfsfile.fileno()
        else:
            initramfsfd,tmpname = tempfile.mkstemp('irfs')
            os.unlink(tmpname)
            initramfsfile = os.fdopen(initramfsfd, 'r+b')
        mkinitramfs.mkinitramfs(initramfsfile, config)
        initramfsfile.flush()
        if args.save_initramfs is not None:
            initrdpath = args.save_initramfs
        else:
            fcntl.fcntl(initramfsfd, fcntl.F_SETFD, 0)
            initrdpath = '/proc/self/fd/%d' % initramfsfd
    else:
        if args.save_initramfs is not None:
            print('--save_initramfs specified but initramfs is not used',
                  file=sys.stderr)
            return 1

        # No initramfs!  Warning: this is slower than using an initramfs
        # because the kernel will wait for device probing to finish.
        # Sigh.
        if use_virtiofs:
            kernelargs.extend([
                'rootfstype=virtiofs',
                'root=ROOTFS',
            ])
        else:
            kernelargs.extend([
                'rootfstype=9p',
                'rootflags=version=9p2000.L,trans=virtio,access=any',
            ])
        kernelargs.extend([
            'raid=noautodetect',
            'rw' if args.rw else 'ro',
        ])
        initrdpath = None
        initcmds.insert(0, 'mount -t tmpfs run /run')

    if args.quiet:
        kernelargs.append('quiet')
        kernelargs.append('loglevel=0')

    # Now that we're done setting up kernelargs, append user-specified args
    # and then initargs
    kernelargs.extend(args.kopt)

    # Unknown options get turned into arguments to init, which is annoying
    # because we're explicitly passing '--' to set the arguments directly.
    # Fortunately, 'init=' will clear any arguments parsed so far, so make
    # sure that 'init=' appears directly before '--'.
    kernelargs.append('init=/bin/sh')
    kernelargs.append('--')
    kernelargs.extend(['-c', ';'.join(initcmds)])

    if args.xen is None:
        # Load a normal kernel
        qemuargs.extend(['-kernel', kernel.kimg])
        if kernelargs:
            qemuargs.extend(['-append',
                             ' '.join(quote_karg(a) for a in kernelargs)])
        if initrdpath is not None:
            qemuargs.extend(['-initrd', initrdpath])
        if kernel.dtb is not None:
            qemuargs.extend(['-dtb', kernel.dtb])

        if xenargs:
            raise ValueError("Can't pass Xen any arguments if we're not using Xen")
    else:
        # Use multiboot syntax to load Xen
        qemuargs.extend(['-kernel', args.xen])
        if xenargs:
            qemuargs.extend(['-append',
                             ' '.join(quote_karg(a) for a in xenargs)])
        qemuargs.extend(['-initrd', '%s %s%s' % (
            kernel.kimg,
            ' '.join(quote_karg(a).replace(',', ',,') for a in kernelargs),
            (',%s' % initrdpath) if initrdpath is not None else '')])

    # Handle --qemu-opt(s)
    qemuargs.extend(args.qemu_opt)
    if args.qemu_opts is not None:
        qemuargs.extend(args.qemu_opts)

    if args.show_command:
        print(' '.join(shlex.quote(a) for a in qemuargs))

    # Go!
    if not args.dry_run:
        pid = os.fork()
        if pid:
            pid, status = os.waitpid(pid, 0)
            return status
        else:
            os.execv(qemu.qemubin, qemuargs)
    return 0

def main() -> int:
    try:
        return do_it()
    except SilentError:
        return 1

if __name__ == '__main__':
    try:
        exit(main())
    except SilentError:
        exit(1)
