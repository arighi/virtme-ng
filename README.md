What is virtme?
===============

Virtme is a set of simple tools to run a virtualized Linux kernel that
uses the host Linux distribution or a simple rootfs instead of a whole
disk image.

Virtme is tiny, easy to use, and makes testing kernel changes quite simple.

Some day this might be useful as a sort of sandbox.  Right now it's not
really configurable enough for that.

Virtme is hosted at kernel.org in utils/kernel/virtme/virtme.git ([web][korg-web] | [git][korg-git]).  It's mirrored [on github][github].  Please submit bugs
and PRs via github.  Release tarballs are at [kernel.org in /pub/linux/utils/kernel/virtme][korg-releases].

[korg-web]: https://git.kernel.org/cgit/utils/kernel/virtme/virtme.git "virtme on kernel.org"
[korg-git]: git://git.kernel.org/pub/scm/utils/kernel/virtme/virtme.git "git address"
[korg-releases]: https://mirrors.edge.kernel.org/pub/linux/utils/kernel/virtme/releases/ "virtme releases on kernel.org"
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

An easy, somewhat-reliable way to generate a working config is via
the virtme-configkernel. It needs to be run on a kernel source directory,
like:

    virtme-configkernel --arch=ARCH --defconfig

Your host system will need to satisfy some prerequisites:

* You need Python 3.3 or higher.
* QEMU 1.6 or higher is recommended.  QEMU 1.4 and 1.5 are partially supported using a rather ugly kludge.
  * You will have a much better experience if KVM is enabled.  That means that you should be on bare metal with hardware virtualization (VT-x or SVM) enabled or in a VM that supports nested virtualization.  On some Linux distributions, you may need to be a member of the "kvm" group.  Using VirtualBox or most VPS providers will fall back to emulation.
* Depending on the options you use, you may need a statically linked `busybox` binary somewhere in your path.

Once you have such a kernel, run one of:

* virtme-run --kdir PATH_TO_KERNEL_TREE
* virtme-run --installed-kernel
* virtme-run --installed-kernel VERSION
* virtme-run --kimg PATH_TO_KERNEL_IMAGE

With --installed-kernel or --kdir, modules associated with the kernel will be available in the VM.  With --kdir in particular, you will either need to follow the directions that virtme-run prints or specify --mods=auto to make this work.  With --kimg, modules are not supported.

You can then do things like `cd /home/username` and you will have readonly
access to all your files.

Virtme gives you console input and output by default.  Type ctrl-a x to exit.
Type ctrl-a c to access the QEMU monitor.

For now, the virtme console is a serial console -- virtconsole seems to be unusably buggy.  I don't know of any way to keep the tty state in sync between the host and guest, so resizing the host window after starting the guest may confuse guest libraries like readline.

Graphics
========

If you want graphical output instead of console output, pass --graphics.  Note that this is the opposite of QEMU's default behavior.

Architecture support
====================

By default, virtme will use whatever architecture would be shown by `uname -m`.  You can override this with `--arch`.  Note that you may need to do some poorly documented fiddling for now to get non-native architectures working, and you will almost certainly need to set `--root` to a root that matches the architecture.

In general, the easiest way to configure a working kernel is to run:

    virtme-configkernel --arch=ARCH --defconfig

x86
---

x86 (both x86_64 and i386) is fully supported, although some odd KVM configurations may cause problems.

ARM
---

ARM is supported using qemu's `vexpress-a15` machine.  There is no built-in KVM support for ARM right now, although it might work by accident -- I don't own a real KVM-capable ARM machine to test it on.

If you use any mode other than --kdir, you'll need to manually set QEMU's -dtb option.  I'm not sure why -- I assumed that QEMU would provide its own device tree, but this doesn't seem to be the case.

Aarch64
-------

Aarch64 works out of the box if you have a new enough version of QEMU.

PPC64
-----

PPC64 appears to be reasonably functional.

RISC-V
------

riscv64 works out of the box, but you'll neet at least QEMU-4.1.0 to be
able to run `vmlinux`-style kernels.  riscv32 is not supported because
there are no existing userspace images for it.  Support is provided via
QEMU's `virt` machine with OpenSBI for firmware.

Others
------

Other architectures may or may not work.  Adding support is trivial, so ping me if you need another architecture.  Unrecognized architectures use a set of maybe-acceptable defaults.

Upcoming features
=================

In the near term, the high-priority features are:

* Support for modular virtfs and 9p for non-installed kernels.

Contributing
============

Please see DCO.txt
