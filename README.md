https://github.com/arighi/virtme-ng/assets/423281/485608ee-0c82-46d1-b311-e1b7af0a4e44

What is virtme-ng?
====================

virtme-ng is a tool that allows to easily and quickly recompile and test a
Linux kernel, starting from the source code.

It allows to recompile the kernel in few minutes (rather than hours), then the
kernel is automatically started in a virtualized environment that is an exact
copy-on-write copy of your live system, which means that any changes made to
the virtualized environment do not affect the host system.

In order to do this a minimal config is produced (with the bare minimum support
to test the kernel inside qemu), then the selected kernel is automatically
built and started inside qemu, using the filesystem of the host as a
copy-on-write snapshot.

This means that you can safely destroy the entire filesystem, crash the kernel,
etc. without affecting the host.

Kernels produced with virtme-ng are lacking lots of features, in order to
reduce the build time to the minimum and still provide you a usable kernel
capable of running your tests and experiments.

virtme-ng is based on virtme, written by Andy Lutomirski <luto@kernel.org>
([web][korg-web] | [git][korg-git]).

Quick start
===========

```
 $ uname -r
 5.19.0-23-generic
 $ git clone git://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git
 $ cd linux
 $ vng --build --commit v6.2-rc4
 ...
 $ vng
           _      _
    __   _(_)_ __| |_ _ __ ___   ___       _ __   __ _
    \ \ / / |  __| __|  _   _ \ / _ \_____|  _ \ / _  |
     \ V /| | |  | |_| | | | | |  __/_____| | | | (_| |
      \_/ |_|_|   \__|_| |_| |_|\___|     |_| |_|\__  |
                                                 |___/
    kernel version: 6.2.0-rc4-virtme x86_64

 $ uname -r
 6.2.0-rc4-virtme
 ^
 |___ Now you have a shell inside a virtualized copy of your entire system,
      that is running the new kernel! \o/

 Then simply type "exit" to return back to the real system.
```

Installation
============

* Debian / Ubuntu

You can install the latest stable version of virtme-ng via:
```
 $ sudo apt install virtme-ng
```

* Ubuntu ppa

If you're using Ubuntu, you can install the latest experimental version of
virtme-ng from ppa:arighi/virtme-ng:
```
 $ sudo add-apt-repository ppa:arighi/virtme-ng
 $ sudo apt install --yes virtme-ng
```

* Install from source

To install virtme-ng from source you can clone this git repository and build a
standalone virtme-ng running the following commands:
```
 $ git clone --recurse-submodules https://github.com/arighi/virtme-ng.git
 $ BUILD_VIRTME_NG_INIT=1 pip3 install --verbose -r requirements.txt .
```

If you are in Debian/Ubuntu you may need to install the following packages to
build virtme-ng from source properly:
```
 $ sudo apt install python3-pip python3-argcomplete flake8 pylint \
   cargo rustc qemu-system-x86
```

In recent versions of pip3 you may need to specify `--break-system-packages` to
properly install virtme-ng in your system from source.

* Run from source

You can also run virtme-ng directly from source, make sure you have all the
requirements installed (optionally you can build `virtme-ng-init` for a faster
boot, by running `make`), then from the source directory simply run any
virtme-ng command, such as:
```
 $ ./vng --help
```

Requirements
============

 * You need Python 3.8 or higher

 * QEMU 1.6 or higher is recommended (QEMU 1.4 and 1.5 are partially supported
   using a rather ugly kludge)
   * You will have a much better experience if KVM is enabled.  That means that
     you should be on bare metal with hardware virtualization (VT-x or SVM)
     enabled or in a VM that supports nested virtualization.  On some Linux
     distributions, you may need to be a member of the "kvm" group.  Using
     VirtualBox or most VPS providers will fall back to emulation. If you are
     using GitHub Actions, KVM support is supported on "larger Linux runners" --
     which is [now](https://github.blog/2024-01-17-github-hosted-runners-double-the-power-for-open-source/)
     the default runner -- but it has to be
     [manually enabled](https://github.blog/changelog/2023-02-23-hardware-accelerated-android-virtualization-on-actions-windows-and-linux-larger-hosted-runners/),
     see how it is used in [our tests](.github/workflows/run.yml) or
     [here](https://github.com/multipath-tcp/mptcp_net-next/commit/677b5ecd223c)
     with Docker.

 * Depending on the options you use, you may need a statically linked `busybox`
   binary somewhere in your path.

 * Optionally, you may need virtiofsd 1.7.0 (or higher) for better filesystem
   performance inside the virtme-ng guests.

Examples
========

 - Build a kernel from a clean local kernel source directory (if a .config is
   not available virtme-ng will automatically create a minimum .config with
   all the required feature to boot the instance):
```
   $ vng -b
```

 - Build tag v6.1-rc3 from a local kernel git repository:
```
   $ vng -b -c v6.1-rc3
```

 - Generate a minimal kernel .config in the current kernel build directory:
```
   $ vng --kconfig
```

 - Run a kernel previously compiled from a local git repository in the current
   working directory:
```
   $ vng
```

 - Run an interactive virtme-ng session using the same kernel as the host:
```
   $ vng -r
```

 - Test installed kernel 6.2.0-21-generic kernel
   (NOTE: /boot/vmlinuz-6.2.0-21-generic needs to be accessible):
```
   $ vng -r 6.2.0-21-generic
```

 - Run a pre-compiled vanilla v6.6 kernel fetched from the Ubuntu mainline
   builds repository (useful to test a specific kernel version directly and
   save a lot of build time):
```
   $ vng -r v6.6
```

 - Download and test kernel 6.2.0-1003-lowlatency from deb packages:
```
   $ mkdir test
   $ cd test
   $ apt download linux-image-6.2.0-1003-lowlatency linux-modules-6.2.0-1003-lowlatency
   $ for d in *.deb; do dpkg -x $d .; done
   $ vng -r ./boot/vmlinuz-6.2.0-1003-lowlatency
```

 - Build the tip of the latest kernel on a remote build host called "builder",
   running make inside a specific build chroot (managed remotely by schroot):
```
   $ vng --build --build-host builder \
     --build-host-exec-prefix "schroot -c chroot:kinetic-amd64 -- "
```

 - Run the previously compiled kernel from the current working directory and
   enable networking:
```
   $ vng --net user
```

 - Run the previously compiled kernel adding an additional virtio-scsi device:
```
   $ qemu-img create -f qcow2 /tmp/disk.img 8G
   $ vng --disk /tmp/disk.img
```

 - Recompile the kernel passing some env variables to enable Rust support
   (using specific versions of the Rust toolchain binaries):
```
   $ vng --build RUSTC=rustc-1.62 BINDGEN=bindgen-0.56 RUSTFMT=rustfmt-1.62
```

 - Build the arm64 kernel (using a separate chroot in /opt/chroot/arm64 as the
   main filesystem):
```
   $ vng --build --arch arm64 --root /opt/chroot/arm64/
```

 - Execute `uname -r` inside a kernel recompiled in the current directory and
   send the output to cowsay on the host:
```
   $ vng -- uname -r | cowsay
    __________________
   < 6.1.0-rc6-virtme >
    ------------------
           \   ^__^
            \  (oo)\_______
               (__)\       )\/\
                   ||----w |
                   ||     ||
```

 - Run a bunch of parallel virtme-ng instances in a pipeline, with different
   kernels installed in the system, passing each other their stdout/stdin and
   return all the generated output back to the host (also measure the total
   elapsed time):
```
   $ time true | \
   > vng -r 5.19.0-38-generic -e "cat && uname -r" | \
   > vng -r 6.2.0-19-generic  -e "cat && uname -r" | \
   > vng -r 6.2.0-20-generic  -e "cat && uname -r" | \
   > vng -r 6.3.0-2-generic   -e "cat && uname -r" | \
   > cowsay -n
    ___________________
   / 5.19.0-38-generic \
   | 6.2.0-19-generic  |
   | 6.2.0-20-generic  |
   \ 6.3.0-2-generic   /
    -------------------
           \   ^__^
            \  (oo)\_______
               (__)\       )\/\
                   ||----w |
                   ||     ||

   real    0m2.737s
   user    0m8.425s
   sys     0m8.806s
```

 - Run the vanilla v6.7-rc5 kernel with an Ubuntu 22.04 rootfs:
```
   $ vng -r v6.7-rc5 --user root --root ./rootfs/22.04 --root-release jammy -- cat /etc/lsb-release /proc/version
   ...
   DISTRIB_ID=Ubuntu
   DISTRIB_RELEASE=22.04
   DISTRIB_CODENAME=jammy
   DISTRIB_DESCRIPTION="Ubuntu 22.04.3 LTS"
   Linux version 6.7.0-060700rc5-generic (kernel@kathleen) (x86_64-linux-gnu-gcc-13 (Ubuntu 13.2.0-7ubuntu1) 13.2.0, GNU ld (GNU Binutils for Ubuntu) 2.41) #202312102332 SMP PREEMPT_DYNAMIC Sun Dec 10 23:41:31 UTC 2023
```

 - Run the current kernel creating a 1GB NUMA node with CPUs 0,1,3 assigned
   and a 3GB NUMA node with CPUs 2,4,5,6,7 assigned:
```
   $ vng -r -m 4G --numa 1G,cpus=0-1,cpus=3 --numa 3G,cpus=2,cpus=4-7 -- numactl -H
   available: 2 nodes (0-1)
   node 0 cpus: 0 1 3
   node 0 size: 1005 MB
   node 0 free: 914 MB
   node 1 cpus: 2 4 5 6 7
   node 1 size: 2916 MB
   node 1 free: 2797 MB
   node distances:
   node   0   1
     0:  10  20
     1:  20  10
```

 - Run `glxgears` inside a kernel recompiled in the current directory:
```
   $ vng -g -- glxgears

   (virtme-ng is started in graphical mode)
```

 - Execute an `awesome` window manager session with kernel
   6.2.0-1003-lowlatency (installed in the system):
```
   $ vng -r 6.2.0-1003-lowlatency -g -- awesome

   (virtme-ng is started in graphical mode)
```

 - Run the `steam` snap (tested in Ubuntu) inside a virtme-ng instance using
   the 6.2.0-1003-lowlatency kernel:
```
   $ vng -r 6.2.0-1003-lowlatency --snaps --net user -g -- /snap/bin/steam

   (virtme-ng is started in graphical mode)
```

 - Generate a memory dump of a running instance and read 'jiffies' from the
   memory dump using the drgn debugger:
```
   # Start the vng instance in debug mode
   $ vng --debug

   # In a separate shell session trigger the memory dump to /tmp/vmcore.img
   $ vng --dump /tmp/vmcore.img

   # Use drgn to read 'jiffies' from the memory dump:
   $ echo "print(prog['jiffies'])" | drgn -q -s vmlinux -c /tmp/vmcore.img
   drgn 0.0.23 (using Python 3.11.6, elfutils 0.189, with libkdumpfile)
   For help, type help(drgn).
   >>> import drgn
   >>> from drgn import NULL, Object, cast, container_of, execscript, offsetof, reinterpret, sizeof
   >>> from drgn.helpers.common import *
   >>> from drgn.helpers.linux import *
   >>> (volatile unsigned long)4294675464
```

 - Attach a gdb session to a running instance started with `--debug`:
```
   # Start the vng instance in debug mode
   $ vng --debug

   # In a separate terminal run the following command to attach the gdb session:
   $ vng --gdb
   kernel version = 6.9.0-virtme
   Reading symbols from vmlinux...
   Remote debugging using localhost:1234
   native_irq_disable () at ./arch/x86/include/asm/irqflags.h:37
   37		asm volatile("cli": : :"memory");
   (gdb)

   # NOTE: a vmlinux must be present in the current working directory in order
   # to resolve symbols, otherwise vng # will automatically search for a
   # vmlinux available in the system.
```

 - Run virtme-ng inside a docker container:
```
   $ docker run -it --privileged ubuntu:23.10 /bin/bash
   # apt update
   # echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections
   # apt install --yes git qemu-kvm udev iproute2 busybox-static \
     coreutils python3-requests libvirt-clients kbd kmod file rsync zstd virtiofsd
   # git clone --recursive https://github.com/arighi/virtme-ng.git
   # ./virtme-ng/vng -r v6.6 -- uname -r
   6.6.0-060600-generic
```
   See also: `.github/workflows/run.yml` as a practical example on how to use
   virtme-ng inside docker.

Implementation details
======================

virtme-ng allows to automatically configure, build and run kernels using the
main command-line interface called `vng`.

A minimal custom `.config` is automatically generated if not already present
when `--build` is specified.

It is possible to specify a set of custom configs (.config chunk) in
`~/.config/virtme-ng/kernel.config`, or using --config chunk-file's
or --configitem CONFIG_FOO=bar's.  These user-specific settings will
successively override the default settings.  The final overrides are
the mandatory config items that are required to boot and test the
kernel inside qemu, using `virtme-run`.

Then the kernel is compiled either locally or on an external build host (if the
`--build-host` option is used); once the build is done only the required files
needed to test the kernel are copied from the remote host if an external build
host is used.

When a remote build host is used (`--build-host`) the target branch is force
pushed to the remote host inside the `~/.virtme` directory.

Then the kernel is executed using the virtme module. This allows to test the
kernel using a safe copy-on-write snapshot of the entire host filesystem.

All the kernels compiled with virtme-ng have a `-virtme` suffix to their kernel
version, this allows to easily determine if you're inside a virtme-ng kernel or
if you're using the real host kernel (simply by checking `uname -r`).

External kernel modules
=======================

It is possible to recompile and test out-of-tree kernel modules inside the
virtme-ng kernel, simply by building them against the local directory of the
kernel git repository that was used to build and run the kernel.

Default options
===============

Typically, if you always use virtme-ng with an external build server (e.g.,
`vng --build --build-host REMOTE_SERVER --build-host-exec-prefix CMD`) you
don't always want to specify these options, so instead, you can simply define
them in `~/.config/virtme-ng/virtme-ng.conf` under `default_opts` and then
simply run `vng --build`.

Example (always use an external build server called 'kathleen' and run make
inside a build chroot called `chroot:lunar-amd64`). To do so, modify the
`default_opts` sections in `~/.config/virtme-ng/virtme-ng.conf` as following:
```
    "default_opts" : {
        "build_host": "kathleen",
        "build_host_exec_prefix": "schroot -c chroot:lunar-amd64 --"
    },
```

Now you can simply run `vng --build` to build your kernel from the current
working directory using the external build host, prepending the exec prefix
command when running make.

Troubleshooting
===============

 - If you get permission denied when starting qemu, make sure that your
   username is assigned to the group `kvm` or `libvirt`:
```
  $ groups | grep "kvm\|libvirt"
```

 - When using `--net bridge` to create a bridged network in the guest you
   may get the following error:
```
  ...
  failed to create tun device: Operation not permitted
```

   This is because `qemu-bridge-helper` requires `CAP_NET_ADMIN` permissions.

   To fix this you need to add `allow all` to `/etc/qemu/bridge.conf` and set
   the `CAP_NET_ADMIN` capability to `qemu-bridge-helper`, as following:
```
  $ sudo filecap /usr/lib/qemu/qemu-bridge-helper net_admin
```

 - If the guest fails to start because the host doesn't have enough memory
   available you can specify a different amount of memory using `--memory MB`,
   (this option is passed directly to qemu via `-m`, default is 1G).

 - If you're testing a kernel for an architecture different than the host, keep
   in mind that you need to use also `--root DIR` to use a specific chroot with
   the binaries compatible with the architecture that you're testing.

   If the chroot doesn't exist in your system virtme-ng will automatically
   create it using the latest daily build Ubuntu cloud image:
```
  $ vng --build --arch riscv64 --root ./tmproot
```

 - If the build on a remote build host is failing unexpectedly you may want to
   try cleaning up the remote git repository, running:
```
  $ vng --clean --build-host HOSTNAME
```

 - Snap support is still experimental and something may not work as expected
   (keep in mind that virtme-ng will try to run snapd in a bare minimum system
   environment without systemd), if some snaps are not running try to disable
   apparmor, adding `--append="apparmor=0"` to the virtme-ng command line.

 - Running virtme-ng instances inside docker: in case of failures/issues,
   especially with stdin/stdout/stderr redirections, make sure that you have
   `udev` installed in your docker image and run the following command before
   using `vng`:
```
  $ udevadm trigger --subsystem-match --action=change
```

 - To mount the legacy cgroup filesystem (v1) layout, add
   `SYSTEMD_CGROUP_ENABLE_LEGACY_FORCE=1` to the kernel boot options:
```
$ vng -r --append "SYSTEMD_CGROUP_ENABLE_LEGACY_FORCE=1" -- 'df -T /sys/fs/cgroup/*'
Filesystem     Type   1K-blocks  Used Available Use% Mounted on
blkio          cgroup         0     0         0    - /sys/fs/cgroup/blkio
cpu            cgroup         0     0         0    - /sys/fs/cgroup/cpu
cpuacct        cgroup         0     0         0    - /sys/fs/cgroup/cpuacct
devices        cgroup         0     0         0    - /sys/fs/cgroup/devices
memory         cgroup         0     0         0    - /sys/fs/cgroup/memory
pids           cgroup         0     0         0    - /sys/fs/cgroup/pids
```

Contributing
============

Please see DCO-1.1.txt.

Additional resources
====================

 - [LWN: Faster kernel testing with virtme-ng (November, 2023)](https://lwn.net/Articles/951313/)
 - [LPC 2023: Speeding up Kernel Testing and Debugging with virtme-ng](https://lpc.events/event/17/contributions/1506/attachments/1143/2441/virtme-ng.pdf)

Credits
=======

virtme-ng is written by Andrea Righi <andrea.righi@canonical.com>

virtme-ng is based on virtme, written by Andy Lutomirski <luto@kernel.org>
([web][korg-web] | [git][korg-git]).

[korg-web]: https://git.kernel.org/cgit/utils/kernel/virtme/virtme.git "virtme on kernel.org"
[korg-git]: git://git.kernel.org/pub/scm/utils/kernel/virtme/virtme.git "git address"
[virtme]: https://github.com/amluto/virtme "virtme"
[virtme-ng-ppa]: https://launchpad.net/~arighi/+archive/ubuntu/virtme-ng "virtme-ng ppa"
