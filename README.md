What is KernelCraft?
====================

KernelCraft is a tool that allows to setup a lab to experiment different
kernel versions in a safe virtualized environment, re-using the entire
filesystem of the running machine as a safe live-copy, without affecting
the real filesystem of the host.

In order to to this a minimal config is produced (with the bare minimum support
to test the kernel inside kvm), then the selected kernel is automatically built
and started inside kvm, using the filesystem of the host as a copy-on-write
snapshot.

This means that you can safely destroy the entire filesystem, crash the kernel,
etc. without affecting the host.

KernelCraft is meant to be a tool that allows you to easily and quickly test
kernels (e.g., bisecting a regression).

Kernels produced with KernelCraft are lacking lots of features, in order to
reduce the build time to the minimum and still provide you a usable kernel
capable of running your tests and experiments.

Requirements
============

KernelCraft requires a customized version of virtme, available here
[web][arighi-virtme].

You may also need to install `crash` to use the memory dump inspection feature
(see example below).

If you are using Ubuntu you can install all the required packages and dependencies from this ppa:
[web][kernelcraft-ppa].

Examples
========

 - Build and run v6.1-rc3 from the public mainline git repository:
```
   $ kc -r mainline -c v6.1-rc3
```

 - Build and run a kernel 2 commits before the previously compiled kernel:
```
   $ kc --commit HEAD~2
```

 - Test the previously built kernel:
```
   $ kc -s
```

 - Generate and inspect a memory dump of the currently tested kernel (crash
   tool needs to be installed):
```
   $ kc -d
```

 - Save a memory dump of the running kernel to /tmp/vmcore.img
```
   $ kc -d --dump-file /tmp/vmcore.img
```

 - Test the tip of linux-next, building the kernel on a remote build host
   called "builder", including /var/lib/rust-for-linux/bin to the default PATH:
```
   $ kc -r next --build-host arighi@builder \
     --build-host-exec-prefix 'PATH=/var/lib/rust-for-linux/bin:$PATH'
```

 - Test the tip of the latest mainline kernel, building the kernel on a remote
   build host called "builder", running make inside a specific build chroot
   (managed remotely by schroot):
```
   $ kc -r mainline --build-host builder \
     --build-host-exec-prefix "schroot -c chroot:kinetic-amd64 -- "
```

 - Run the previously compiled kernel and enable bridge networking (NOTE: you
   may get permission denied in some Ubuntu releases, I solved by doing a
   `sudo chmod u+s /usr/lib/qemu/qemu-bridge-helper`:
```
   $ kc -s -o '--net bridge'
```

 - Test latest mainline kernel on arm64 (using a separate chroot in
   /opt/chroot/arm64 as the main filesystem):
```
   $ kc -r mainline --arch arm64 --root /opt/chroot/arm64/
```

Implementation details
======================

KernelCraft has a list of known git repositories in ~/.kernelcraft.conf, stored
in a JSON format. It is possible to add custom git repositories by changing
this file.

Repositories are identified by name (specified with the option --release / -r).

When a release (git repository) is specified KernelCraft takes care of adding
the remote branch to the local current git repository. When a remote build host
is used (--build-host) the target branch is force pushed to the remote host
inside the ~/.kernelcraft folder.

Then a minimal custom .config is generated using (a custom version of)
virtme-configkernel.

Then the kernel is compiled either locally or on an external build host (if the
`--build-host` option is used); once the build is done only the required files
needed to test the kernel are copied from the remote host if an external build
host is used.

Then the kernel is executed using virtme. This allows to test the kernel using
a safe copy-on-write snapshot of the entire host filesystem.

All the kernels compiled with KernelCraft have a `-rc` suffix to their kernel
version, this allows to easily determine if you're inside a KernelCraft kernel
or if you're using the real host kernel (simply by checking `uname -r`).

It is also possible to generate and inspect a memory dump of the tested kernel
running `kc -d` from the host, while the test kernel is running.

External kernel modules
=======================

It is possible to recompile and test out-of-tree kernel modules inside the
KernelCraft kernel, simply by building them against the local directory of the
kernel git repository that was used to build and run the kernel.

Credits
=======

KernelCraft is written by Andrea Righi <andrea.righi@canonical.com>

KernelCraft is based on virtme, written by Andy Lutomirski <luto@kernel.org>
([web][korg-web] | [git][korg-git]).

[korg-web]: https://git.kernel.org/cgit/utils/kernel/virtme/virtme.git "virtme on kernel.org"
[korg-git]: git://git.kernel.org/pub/scm/utils/kernel/virtme/virtme.git "git address"
[arighi-virtme]: https://github.com/arighi/virtme "arighi virtme"
[kernelcraft-ppa]: https://launchpad.net/~arighi/+archive/ubuntu/kernelcraft "kernelcraft ppa"
