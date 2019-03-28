# -*- mode: python -*-
# virtme-run: The main command-line virtme frontend
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

import argparse
import tempfile
import shutil
import os
import errno
import fcntl
import sys
import shlex
import re
import itertools
from .. import virtmods
from .. import modfinder
from .. import mkinitramfs
from .. import qemu_helpers
from .. import architectures
from .. import guest_tools

uname = os.uname()

def make_parser():
    parser = argparse.ArgumentParser(
        description='Virtualize your system (or another) under a kernel image',
    )

    g = parser.add_argument_group(title='Selection of kernel and modules').add_mutually_exclusive_group()
    g.add_argument('--installed-kernel', action='store', nargs='?',
                   const=uname.release, default=None, metavar='VERSION',
                   help='Use an installed kernel and its associated modules.  If no version is specified, the running kernel will be used.')

    g.add_argument('--kimg', action='store',
                   help='Use specified kernel image with no modules.')

    g.add_argument('--kdir', action='store', metavar='KDIR',
                   help='Use a compiled kernel source directory')

    g = parser.add_argument_group(title='Kernel options')
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
    g.add_argument('--net', action='store_true',
                   help='Enable basic network access.')
    g.add_argument('--balloon', action='store_true',
                   help='Allow the host to ask the guest to release memory.')
    g.add_argument('--disk', action='append', default=[], metavar='NAME=PATH',
                   help='Add a read/write virtio-scsi disk.  The device node will be /dev/disk/by-id/scsi-0virtme_disk_NAME.')
    g.add_argument('--memory', action='store', default=None,
                   help='Set guest memory and qemu -m flag.')
    g.add_argument('--name', action='store', default=None,
                   help='Set guest hostname and qemu -name flag.')

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
    g.add_argument('-q', '--qemu-opt', action='append', default=[],
                   help="Add a single QEMU argument.  Use this when --qemu-opts's greedy behavior is problematic.'")
    g.add_argument('--qemu-opts', action='store', nargs=argparse.REMAINDER,
                   metavar='OPTS...', help='Additional arguments for QEMU.  This will consume all remaining arguments, so it must be specified last.  Avoid using -append; use --kopt instead.')

    g = parser.add_argument_group(title='Debugging/testing')
    g.add_argument('--force-initramfs', action='store_true',
                   help='Use an initramfs even if unnecessary')
    g.add_argument('--dry-run', action='store_true',
                   help="Initialize everything but don't run the guest")
    g.add_argument('--show-command', action='store_true',
                   help='Show the VM command line')

    g = parser.add_argument_group(title='Guest userspace configuration')
    g.add_argument('--pwd', action='store_true',
                   help='Propagate current working directory to the guest')

    g = parser.add_argument_group(title='Sharing resources with guest')
    g.add_argument('--rwdir', action='append', default=[],
                   help="Supply a read/write directory to the guest.  Use --rwdir=path or --rwdir=guestpath=hostpath.")
    g.add_argument('--rodir', action='append', default=[],
                   help="Supply a read-only directory to the guest.  Use --rodir=path or --rodir=guestpath=hostpath.")

    return parser

_ARGPARSER = make_parser()

def arg_fail(message):
    print(message)
    _ARGPARSER.print_usage()
    sys.exit(1)

def find_kernel_and_mods(arch, args):
    if args.installed_kernel is not None:
        kver = args.installed_kernel
        modfiles = modfinder.find_modules_from_install(
            virtmods.MODALIASES, kver=kver)
        moddir = os.path.join('/lib/modules', kver)
        kimg = '/usr/lib/modules/%s/vmlinuz' % kver
        if not os.path.exists(kimg):
            kimg = '/boot/vmlinuz-%s' % kver
        dtb = None  # For now
    elif args.kdir is not None:
        kimg = os.path.join(args.kdir, arch.kimg_path())
        modfiles = []
        moddir = None

        # Once kmod gets fixed (if ever), we can do something like:
        # modfiles = modfinder.find_modules_from_install(
        #     virtmods.MODALIASES,
        #     moddir=os.path.join(args.kernel_build_dir, '.tmp_moddir'))

        dtb_path = arch.dtb_path()
        if dtb_path is None:
            dtb = None
        else:
            dtb = os.path.join(args.kdir, dtb_path)
    elif args.kimg is not None:
        kimg = args.kimg
        modfiles = []
        moddir = None
        dtb = None # TODO: fix this
    else:
        arg_fail('You must specify a kernel to use.')

    return kimg,dtb,modfiles,moddir

def export_virtfs(qemu, arch, qemuargs, path, mount_tag, security_model='none', readonly=True):
    # NB: We can't use -virtfs for this, because it can't handle a mount_tag
    # that isn't a valid QEMU identifier.
    fsid = 'virtfs%d' % len(qemuargs)
    qemuargs.extend(['-fsdev', 'local,id=%s,path=%s,security_model=%s%s' %
                     (fsid, qemu.quote_optarg(path),
                      security_model, ',readonly' if readonly else '')])
    qemuargs.extend(['-device', '%s,fsdev=%s,mount_tag=%s' % (arch.virtio_dev_type('9p'), fsid, qemu.quote_optarg(mount_tag))])

def quote_karg(arg):
    if '"' in arg:
        raise ValueError("cannot quote '\"' in kernel args")

    if ' ' in arg:
        return '"%s"' % arg
    else:
        return arg

# Allowed characters in mount paths.  We can extend this over time if needed.
_SAFE_PATH_PATTERN = '[a-zA-Z0-9_+ /.-]+'
_RWDIR_RE = re.compile('^(%s)(?:=(%s))?$' %
                       (_SAFE_PATH_PATTERN, _SAFE_PATH_PATTERN))

def main():
    args = _ARGPARSER.parse_args()

    arch = architectures.get(args.arch)
    is_native = (args.arch == uname.machine)

    qemu = qemu_helpers.Qemu(arch.qemuname)
    qemu.probe()

    need_initramfs = args.force_initramfs or qemu.cannot_overmount_virtfs

    config = mkinitramfs.Config()

    kimg,dtb,modfiles,moddir = find_kernel_and_mods(arch, args)
    config.modfiles = modfiles
    if config.modfiles:
        need_initramfs = True

    qemuargs = [qemu.qemubin]
    kernelargs = []

    # Put the '-name' flag first so it's easily visible in ps, top, etc.
    if args.name:
        qemuargs.extend(['-name', args.name])
        kernelargs.append('virtme_hostname=%s' % args.name)

    # Set up virtfs
    export_virtfs(qemu, arch, qemuargs, args.root, '/dev/root', readonly=(not args.rw))

    guest_tools_path = guest_tools.find_guest_tools()
    if guest_tools_path is None:
        raise ValueError("couldn't find guest tools -- virtme is installed incorrectly")

    export_virtfs(qemu, arch, qemuargs, guest_tools_path,
                  'virtme.guesttools')

    initcmds = ['mkdir -p /run/virtme/guesttools',
                '/bin/mount -n -t 9p -o ro,version=9p2000.L,trans=virtio,access=any virtme.guesttools /run/virtme/guesttools',
                'exec /run/virtme/guesttools/virtme-init']

    # Map modules
    if moddir is not None:
        export_virtfs(qemu, arch, qemuargs, moddir, 'virtme.moddir')

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

        # We should be using the new-style -device serialdev,chardev=xyz,
        # but many architecture-specific serial devices don't support that.
        qemuargs.extend(['-serial', 'chardev:console'])

        qemuargs.extend(['-mon', 'chardev=console'])

        kernelargs.extend(arch.earlyconsole_args())
        kernelargs.extend(arch.serial_console_args())
        qemuargs.extend(arch.qemu_nodisplay_args())

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

    if args.memory:
        qemuargs.extend(['-m', args.memory])

    if args.disk:
        qemuargs.extend(['-device', '%s,id=scsi' % arch.virtio_dev_type('scsi')])

        for i,d in enumerate(args.disk):
            namefile = d.split('=', 1)
            if len(namefile) != 2:
                arg_fail('invalid argument to --disk')
            name,fn = namefile
            if '=' in fn or ',' in fn:
                arg_fail("--disk filenames cannot contain '=' or ','")
            if '=' in fn or ',' in name:
                arg_fail("--disk device names cannot contain '=' or ','")
            driveid = 'disk%d' % i
            qemuargs.extend(['-drive', 'if=none,id=%s,file=%s' % (driveid, fn),
                             '-device', 'scsi-hd,drive=%s,vendor=virtme,product=disk,serial=%s' % (driveid, name)])

    has_script = False

    def do_script(shellcmd, use_exec=False):
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

        # Send kernel logs to stderr
        qemuargs.extend(['-serial', 'none'])
        qemuargs.extend(['-chardev', 'file,id=console,path=/proc/self/fd/2'])

        # We should be using the new-style -device serialdev,chardev=xyz,
        # but many architecture-specific serial devices don't support that.
        qemuargs.extend(['-serial', 'chardev:console'])

        # Set up a virtserialport for script I/O
        qemuargs.extend(['-chardev', 'stdio,id=stdio,signal=on,mux=off'])
        qemuargs.extend(['-device', arch.virtio_dev_type('serial')])
        qemuargs.extend(['-device', 'virtserialport,name=virtme.scriptio,chardev=stdio'])

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
        do_script(args.script_sh)

    if args.script_exec is not None:
        do_script(shlex.quote(args.script_exec), use_exec=True)

    if args.net:
        qemuargs.extend(['-net', 'nic,model=virtio'])
        qemuargs.extend(['-net', 'user'])
        kernelargs.extend(['virtme.dhcp'])

    if args.pwd:
        rel_pwd = os.path.relpath(os.getcwd(), args.root)
        if rel_pwd.startswith('..'):
            print('current working directory is not contained in the root')
            return 1
        kernelargs.append('virtme_chdir=%s' % rel_pwd)

    if need_initramfs:
        if args.busybox is not None:
            config.busybox = args.busybox
        else:
            config.busybox = mkinitramfs.find_busybox(args.root, is_native)
            if config.busybox is None:
                print('virtme-run: initramfs is needed, and no busybox was found',
                      file=sys.stderr)
                return 1

        # Set up the initramfs (warning: hack ahead)
        tmpfd,tmpname = tempfile.mkstemp('irfs')
        os.unlink(tmpname)
        tmpfile = os.fdopen(tmpfd, 'r+b')
        mkinitramfs.mkinitramfs(tmpfile, config)
        tmpfile.flush()
        fcntl.fcntl(tmpfd, fcntl.F_SETFD, 0)
        initrdpath = '/proc/self/fd/%d' % tmpfile.fileno()
    else:
        # No initramfs!  Warning: this is slower than using an initramfs
        # because the kernel will wait for device probing to finish.
        # Sigh.
        kernelargs.extend([
            'rootfstype=9p',
            'rootflags=version=9p2000.L,trans=virtio,access=any',
            'raid=noautodetect',
            'rw' if args.rw else 'ro',
        ])
        initrdpath = None
        initcmds.insert(0, 'mount -t tmpfs run /run')

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
        qemuargs.extend(['-kernel', kimg])
        if kernelargs:
            qemuargs.extend(['-append',
                             ' '.join(quote_karg(a) for a in kernelargs)])
        if initrdpath is not None:
            qemuargs.extend(['-initrd', initrdpath])
        if dtb is not None:
            qemuargs.extend(['-dtb', dtb])
    else:
        # Use multiboot syntax to load Xen
        qemuargs.extend(['-kernel', args.xen])
        qemuargs.extend(['-initrd', '%s %s%s' % (
            kimg,
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
        os.execv(qemu.qemubin, qemuargs)

if __name__ == '__main__':
    exit(main())
