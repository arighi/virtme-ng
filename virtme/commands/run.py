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
import fcntl
import sys
import shlex
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

#    Disabled until kmod gets fixed.
#    g.add_argument('--kernel-build-dir', action='store', metavar='KDIR',
#                   help='Use a compiled kernel source directory')

    g = parser.add_argument_group(title='Kernel options')
    g.add_argument('-a', '--kopt', action='append', default=[],
                   help='Add a kernel option.  You can specify this more than once.')

    g.add_argument('--xen', action='store',
                   help='Boot Xen using the specified uncompressed hypervisor.')

    g = parser.add_argument_group(title='Common guest options')
    g.add_argument('--root', action='store', default='/',
                   help='Local path to use as guest root')
    g.add_argument('--graphics', action='store_true',
                   help='Show graphical output instead of using a console.')
    g.add_argument('--net', action='store_true',
                   help='Enable basic network access.')
    g.add_argument('--balloon', action='store_true',
                   help='Allow the host to ask the guest to release memory.')
    g.add_argument('--disk', action='append', default=[], metavar='NAME=PATH',
                   help='Add a read/write virtio-scsi disk.  The device node will be /dev/disk/by-id/scsi-0virtme_disk_NAME.')

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

    return parser

_ARGPARSER = make_parser()

def arg_fail(message):
    print(message)
    _ARGPARSER.print_usage()
    sys.exit(1)

def find_kernel_and_mods(args):
    if args.installed_kernel is not None:
        kver = args.installed_kernel
        modfiles = modfinder.find_modules_from_install(
            virtmods.MODALIASES, kver=kver)
        moddir = os.path.join('/lib/modules', kver)
        kimg = '/boot/vmlinuz-%s' % kver
#    Disabled until kmod gets fixed.
#    elif args.kernel_build_dir is not None:
#        kimg = os.path.join(args.kernel_build_dir, 'arch/x86/boot/bzImage')
#        modfiles = modfinder.find_modules_from_install(
#            virtmods.MODALIASES,
#            moddir=os.path.join(args.kernel_build_dir, '.tmp_moddir'))
    elif args.kimg is not None:
        kimg = args.kimg
        modfiles = []
        moddir = None
    else:
        arg_fail('You must specify a kernel to use.')

    return kimg,modfiles,moddir

def export_virtfs(qemu, arch, qemuargs, path, mount_tag):
    # NB: We can't use -virtfs for this, because it can't handle a mount_tag
    # that isn't a valid QEMU identifier.
    fsid = 'virtfs%d' % len(qemuargs)
    qemuargs.extend(['-fsdev', 'local,id=%s,path=%s,security_model=passthrough,readonly' % (fsid, qemu.quote_optarg(path))])
    qemuargs.extend(['-device', '%s,fsdev=%s,mount_tag=%s' % (arch.virtio_dev_type('9p'), fsid, qemu.quote_optarg(mount_tag))])

def quote_karg(arg):
    if '"' in arg:
        raise ValueError("cannot quote '\"' in kernel args")

    if ' ' in arg:
        return '"%s"' % arg
    else:
        return arg

def main():
    args = _ARGPARSER.parse_args()

    qemu = qemu_helpers.Qemu(args.arch)
    qemu.probe()

    need_initramfs = args.force_initramfs or qemu.cannot_overmount_virtfs

    config = mkinitramfs.Config()

    kimg,modfiles,moddir = find_kernel_and_mods(args)
    config.modfiles = modfiles
    if config.modfiles:
        need_initramfs = True

    arch = architectures.get(args.arch)
    is_native = (args.arch == uname.machine)

    qemuargs = [qemu.qemubin]
    kernelargs = []

    # Set up virtfs
    export_virtfs(qemu, arch, qemuargs, args.root, '/dev/root')

    guest_tools_in_guest, guest_tools_path = \
        guest_tools.find_best_guest_tools(args.root)
    if guest_tools_path is None:
        raise ValueError("couldn't find usable virtme guest tools")

    if guest_tools_in_guest:
        virtme_init = os.path.join(guest_tools_path, 'virtme-init')
    else:
        virtme_init = '/run/virtme/guesttools/virtme-init'
        export_virtfs(qemu, arch, qemuargs, guest_tools_path,
                      'virtme.guesttools')
        need_initramfs = True

    # TODO: This has escaping issues for now
    kernelargs.append('init=%s' % os.path.join('/', virtme_init))

    # Map modules
    if moddir is not None:
        export_virtfs(qemu, arch, qemuargs, moddir, 'virtme.moddir')

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
        qemuargs.extend(['-vga', 'none'])
        qemuargs.extend(['-display', 'none'])

        # PS/2 probing is slow; give the kernel a hint to speed it up.
        kernelargs.extend(['psmouse.proto=exps'])

        # Fix the terminal defaults (and set iutf8 because that's a better
        # default nowadays).  I don't know of any way to keep this up to date
        # after startup, though.
        terminal_size = os.get_terminal_size()
        kernelargs.extend(['virtme_stty_con=rows %d cols %d iutf8' %
                           (terminal_size.lines, terminal_size.columns)])

        # Propagate the terminal type
        if 'TERM' in os.environ:
            kernelargs.extend(['TERM=%s' % os.environ['TERM']])

    if args.balloon:
        qemuargs.extend(['-balloon', 'virtio'])

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

    def do_script(shellcmd):
        if args.graphics:
            arg_fail('scripts and --graphics are mutually exclusive')

        nonlocal has_script
        nonlocal need_initramfs
        if has_script:
            arg_fail('conflicting script options')
        has_script = True
        need_initramfs = True  # TODO: Fix this

        # Turn off default I/O
        qemuargs.extend(['-vga', 'none'])
        qemuargs.extend(['-display', 'none'])

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

        exec {shellcmd}
        """.format(shellcmd=shellcmd).encode('ascii')

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
        do_script(shlex.quote(args.script_exec))

    if args.net:
        qemuargs.extend(['-net', 'nic,model=virtio'])
        qemuargs.extend(['-net', 'user'])
        kernelargs.extend(['virtme.dhcp'])

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
            'rootflags=ro,version=9p2000.L,trans=virtio,access=any',
            'raid=noautodetect',
        ])
        initrdpath = None

    if args.xen is None:
        # Load a normal kernel
        qemuargs.extend(['-kernel', kimg])
        if kernelargs:
            qemuargs.extend(['-append',
                             ' '.join(quote_karg(a) for a
                                      in (kernelargs + args.kopt))])
        if initrdpath is not None:
            qemuargs.extend(['-initrd', initrdpath])
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
