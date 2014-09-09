What is virtme?
===============

Virtme is a set of simple tools to run a virtualized Linux kernel that
uses the host Linux distribution or a simple rootfs instead of a whole
disk image.

Virtme is tiny, easy to use, and makes testing kernel changes quite simple.

Some day this might be useful as a sort of sandbox.  Right now it's not
really configurable enough for that.

Virtme is hosted at kernel.org in utils/kernel/virtme/virtme.git ([web][korg-web] | [git][korg-git]).  It's mirrored [on github][github].

[korg-web]: https://git.kernel.org/cgit/utils/kernel/virtme/virtme.git "virtme on kernel.org"
[korg-git]: git://git.kernel.org/pub/scm/utils/kernel/virtme/virtme.git "git address"
[github]: https://github.com/amluto/virtme

How to use virtme
=================

You'll need a Linux kernel that has these options (built-in or as modules)

    CONFIG_VIRTIO
    CONFIG_VIRTIO_PCI
    CONFIG_NET_9P
    CONFIG_NET_9P_VIRTIO
    CONFIG_9P_FS

For networking support, you also need CONFIG_VIRTIO_NET.

For script support, you need CONFIG_VIRTIO_CONSOLE.

For disk support, you need CONFIG_SCSI_VIRTIO.

That kernel needs to be sane.  Your kernel is probably sane, but allmodconfig and allyesconfig generate insane kernels.  Sanity includes:

    CONFIG_CMDLINE_OVERRIDE=n
    CONFIG_BINFMT_SCRIPT=y
    CONFIG_TMPFS=y

You may also have better luck if you set:

    CONFIG_EMBEDDED=n
    CONFIG_EXPERT=n
    CONFIG_MODULE_SIG_FORCE=n
    CONFIG_DEVTMPFS=y

An easy, somewhat-reliable way to generate a working config is to append
the `prereqs.config` file to your .config and then run `make defconfig`.

Your host system will need to satisfy some prerequisites:

* You need Python 3.3 or higher.
* QEMU 1.6 or higher is recommended.  QEMU 1.4 and 1.5 are partially supported using a rather ugly kludge.
  * You will have a much better experience if KVM is enabled.  That means that you should be on bare metal with hardware virtualization (VT-x or SVM) enabled or in a VM that supports nested virtualization.  On some Linux distributions, you may need to be a member of the "kvm" group.  Using VirtualBox or most VPS providers will fall back to emulation.
* Depending on the options you use, you may need a statically linked `busybox` binary somewhere in your path.

Once you have such a kernel, run one of:

* virtme-run --kimg PATH_TO_BZIMAGE
* virtme-run --installed-kernel
* virtme-run --installed-kernel VERSION

On x86, you can usually find a bzImage in `arch/x86/boot/bzImage` once you've
compiled your kernel.

Note that the --kimg mode does not support modules.

You can then do things like `cd /home/username` and you will have readonly
access to all your files.

Console
=======

virtme has usable console support.  Pass --console to virtme-run to use it.
To exit, type ctrl-a x.

For now, the virtme console is a serial console -- virtconsole seems to be unusably buggy.  I don't know of any way to keep the tty state in sync between the host and guest, so resizing the host window after starting the guest may confuse guest libraries like readline.

Architecture support
====================

By default, virtme will use whatever architecture would be shown by `uname -m`.  You can override this with `--arch`.  Note that you may need to do some poorly documented fiddling for now to get non-native architectures working, and you will almost certainly need to set `--root` to a root that matches the architecture.

x86
---

x86 (both x86_64 and i386) is fully supported, although some odd KVM configurations may cause problems.

ARM
---

ARM is supported using qemu's `versatilepb` machine.  This is an unfortunate choice: that's a rather outdated machine, and virtme should be using a different system (`vexpress-a15` or `virt`) that is more modern and does not depend on PCI.  There is no built-in KVM support for ARM right now, although it might work by accident -- I don't own a real KVM-capable ARM machine to test it on.

Aarch64
-------

Aarch64 works out of the box if you have a new enough version of QEMU.

PPC64
-----

PPC64 appears to be reasonably functional.

Others
------

Other architectures may or may not work.  Adding support is trivial, so ping me if you need another architecture.  Unrecognized architectures use a set of maybe-acceptable defaults.

Upcoming features
=================

In the near term, the high-priority features are:

* Support for modular virtfs and 9p for non-installed kernels.
* Some way to configure writable mounts.
* A clean way to run a script in the guest for testing.
