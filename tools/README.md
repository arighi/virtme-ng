# Tools VM disk using Nix

## Context

By default, virtme-ng uses the host file-system, or the one from a rootfs.
That's good for developers who already have all the tools required to launch
some tests, but that can be an issue for new ones, or the ones who exceptionally
need to execute some tests from other subsystems. While at it, this can also be
useful for CIs and other developers, to have a more reproducible environment to
execute these tests.

This is an alternative to using containers or rootfs including a whole
file-system, and being limited to what's in it, e.g. when a specific debugging
tool is required: existing ones on the host cannot be used.

## Description

This will build an EROFS image, similar to [the one in Nixpkgs' `qemu-vm.nix`](https://github.com/NixOS/nixpkgs/blob/fed54261b0f4923235c9bb340b23ec1f4a1e2384/nixos/modules/virtualisation/qemu-vm.nix#L172-L200),
but including a `--transform` to create `/nix/store/tools/` from
`/nix/store/<some-hash>-tools/tools/`.

- `package.nix` is where the actual recipe of the image build is, and where
  new packages can be added.
- `flake.{nix,lock}` is not really necessary, but that's a common way to pin
  `nixpkgs` instead of using whatever is in `$NIX_PATH`.
- `default.nix` is not really necessary, but it's a shim to support the
  traditional `nix` commands (i.e. `nix-build`) instead of only the experimental
  new commands (i.e. `nix build`).

## Build

[Nix](https://nixos.org/download/) is obviously required here. Then, from the
parent directory, launch `nix build`:

```console
$ nix build --extra-experimental-features nix-command -f tools
```

`--extra-experimental-features` is needed to be able to use Flakes. Then the
image can be converted to the QCOW2 format for QEMU, and compressed (`-c`):

```console
$ qemu-img convert -c -f raw -O qcow2 result/nix-store.erofs nix-store.erofs.disk
```

Note that the raw image can also be tested without the need of a VM, e.g.

```console
$ mkdir -p /tmp/vm/nix/store
$ sudo modprobe erofs
$ sudo mount -v result/nix-store.erofs /tmp/vm/nix/store
$ sudo chroot /tmp/vm /nix/store/tools/bin/bash

$ PATH=/nix/store/tools/bin
$ hello
Hello, world!
```
