What is virtme?
===============

Virtme is a set of simple tools to run a virtualized Linux kernel that
uses the host Linux distribution instead of a separate image.

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

That kernel needs to be sane.  Your kernel is probably sane, but allmodconfig and allyesconfig generate insane kernels.  Sanity includes:

    CONFIG_CMDLINE_OVERRIDE=n
    CONFIG_BINFMT_SCRIPT=y

You may also have better luck if you set:

    CONFIG_EMBEDDED=n
    CONFIG_EXPERT=n
    CONFIG_MODULE_SIG_FORCE=n

Your host system will need to satisfy some prerequisites:

* You need a statically linked `busybox` binary somewhere in your path.
* You need Python 3.3.
* QEMU 1.6 or higher is recommended.  QEMU 1.4 and 1.5 are partially supported using a rather ugly kludge.

Once you have such a kernel, run one of:

* virtme-run --kimg PATH_TO_BZIMAGE
* virtme-run --installed-kernel
* virtme-run --installed-kernel VERSION

On x86, you can usually find a bzImage in `arch/x86/boot/bzImage` once you've
compiled your kernel.

Note that the --kimg mode does not support modules.

You can then do things like `cd /home/username` and you will have readonly
access to all your files.

Upcoming features
=================

In the near term, the high-priority features are:

* Support for modular virtfs and 9p for non-installed kernels.
* Some way to configure writable mounts.