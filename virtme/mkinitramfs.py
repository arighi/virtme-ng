# -*- mode: python -*-
# virtme-mkinitramfs: Generate an initramfs image for virtme
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

import shutil
import io
import os.path
import shlex
from . import cpiowriter
from . import modfinder
from . import virtmods

def make_base_layout(cw):
    for dir in (b'lib', b'bin', b'var', b'etc', b'newroot', b'dev', b'proc',
                b'tmproot', b'run_virtme', b'run_virtme/data', b'run_virtme/guesttools'):
        cw.mkdir(dir, 0o755)

    cw.symlink(b'bin', b'sbin')
    cw.symlink(b'lib', b'lib64')

def make_dev_nodes(cw):
    cw.mkchardev(b'dev/null', (1, 3), mode=0o666)
    cw.mkchardev(b'dev/kmsg', (1, 11), mode=0o666)
    cw.mkchardev(b'dev/console', (5, 1), mode=0o660)

def install_busybox(cw, config):
    with open(config.busybox, 'rb') as busybox:
        cw.write_file(name=b'bin/busybox', body=busybox, mode=0o755)

    for tool in ('sh', 'mount', 'umount', 'switch_root', 'sleep', 'mkdir',
                 'mknod', 'insmod', 'cp', 'cat'):
        cw.symlink(b'busybox', ('bin/%s' % tool).encode('ascii'))

    cw.mkdir(b'bin/real_progs', mode=0o755)

def install_modprobe(cw):
    cw.write_file(name=b'bin/modprobe', body=b'\n'.join([
        b'#!/bin/sh',
        b'echo "virtme: initramfs does not have module $3" >/dev/console',
    ]), mode=0o755)

_LOGFUNC = """log() {
    if [[ -e /dev/kmsg ]]; then
	echo "<6>virtme initramfs: $*" >/dev/kmsg
    else
	echo "virtme initramfs: $*"
    fi
}
"""

def install_modules(cw, modfiles):
    cw.mkdir(b'modules', 0o755)
    paths = []
    for mod in modfiles:
        with open(mod, 'rb') as f:
            modpath = 'modules/' + os.path.basename(mod)
            paths.append(modpath)
            cw.write_file(name=modpath.encode('ascii'),
                          body=f, mode=0o644)

    script = _LOGFUNC + '\n'.join('log \'loading %s...\'; insmod %s' %
                       (os.path.basename(p), shlex.quote(p)) for p in paths)
    cw.write_file(name=b'modules/load_all.sh',
                  body=script.encode('ascii'), mode=0o644)

_INIT = """#!/bin/sh

{logfunc}

source /modules/load_all.sh

log 'mounting hostfs...'

if ! /bin/mount -n -t 9p -o ro,version=9p2000.L,trans=virtio,access=any /dev/root /newroot/; then
  echo "Failed to switch to real root.  We are stuck."
  sleep 5
  exit 1
fi

# Can we actually use /newroot/ as root?
if ! mount -t proc -o nosuid,noexec,nodev proc /newroot/proc 2>/dev/null; then
  # QEMU 1.5 and below have a bug in virtfs that prevents mounting
  # anything on top of a virtfs mount.
  log "your host's virtfs is broken -- using a fallback tmpfs"

  mount --move /newroot /tmproot
  mount -t tmpfs root_workaround /newroot/
  cd tmproot
  mkdir /newroot/proc /newroot/sys /newroot/dev /newroot/run /newroot/tmp
  for i in *; do
    if [[ -d "$i" && \! -d "/newroot/$i" ]]; then
      mkdir /newroot/"$i"
      mount --bind "$i" /newroot/"$i"
    fi
  done
  mknod /newroot/dev/null c 1 3
  mount -o remount,ro -t tmpfs root_workaround /newroot
  umount -l /tmproot
else
  umount /newroot/proc  # Don't leave garbage behind
fi

mount -t tmpfs run /newroot/run
cp -a /run_virtme /newroot/run/virtme
export virtme_run_mounted=1

# Find init
mount -t proc none /proc
for arg in `cat /proc/cmdline`; do
  if [[ "${{arg%%=*}}" = "init" ]]; then
    init="${{arg#init=}}"
    break
  fi
done
umount /proc

if [[ -z "$init" ]]; then
  log 'no init= option'
  exit 1
fi

if /bin/mount -n -t 9p -o ro,version=9p2000.L,trans=virtio,access=any virtme.guesttools /newroot/run/virtme/guesttools 2>/dev/null; then
  log 'using separate guest tools'
fi

log 'done; switching to real root'
exec /bin/switch_root /newroot "$init" "$@"
"""


def generate_init():
    out = io.StringIO()
    out.write(_INIT.format(
        logfunc=_LOGFUNC))
    return out.getvalue().encode('utf-8')

class Config:
    __slots__ = ['modfiles', 'virtme_data', 'virtme_init_path', 'busybox']
    def __init__(self):
        self.modfiles = []
        self.virtme_data = {}
        self.virtme_init_path = None
        self.busybox = None

def mkinitramfs(out, config):
    cw = cpiowriter.CpioWriter(out)
    make_base_layout(cw)
    make_dev_nodes(cw)
    install_busybox(cw, config)
    install_modprobe(cw)
    if config.modfiles is not None:
        install_modules(cw, config.modfiles)
    for name,contents in config.virtme_data.items():
        cw.write_file(b'/run_virtme/data/' + name, body=contents, mode=0o755)
    cw.write_file(b'init', body=generate_init(),
                  mode=0o755)
    cw.write_trailer()

def find_busybox(root, is_native):
    for path in ('usr/local/bin/busybux', 'usr/local/sbin/busybox',
                 'usr/bin/busybox', 'usr/sbin/busybox',
                 'bin/busybox', 'sbin/busybox'):
        if os.path.isfile(os.path.join(root, path)):
            return os.path.join(root, path)

    if is_native:
        # Try the host's busybox, if any
        return shutil.which('busybox')

    # We give up.
    return None
