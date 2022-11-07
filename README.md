What is KernelCraft?
====================

KernelCraft is a tool that allows to setup a lab to experiment different
kernel versions in a safe virtualized environment, re-using the entire
filesystem of the running machine as a safe live-copy, without affecting
the real filesystem of the host.

KernelCraft is meant to be a tool that allows you to easily and quickly setup a
lab to do kernel experiments. Kernels produced with KernelCraft are lacking
lots of features, in order to reduce the build time to the minimum and still
provide you a usable kernel capable of running your tests and experiments.

Credits
=======

KernelCraft is written by Andrea Righi <andrea.righi@canonical.com>

KernelCraft is based on virtme, written by Andy Lutomirski <luto@kernel.org>
([web][korg-web] | [git][korg-git]).

[korg-web]: https://git.kernel.org/cgit/utils/kernel/virtme/virtme.git "virtme on kernel.org"
[korg-git]: git://git.kernel.org/pub/scm/utils/kernel/virtme/virtme.git "git address"
