Contributing to virtme-ng
=========================

Patches are submitted as GitHub pull requests against
<https://github.com/arighi/virtme-ng>.

Developer's Certificate of Origin
---------------------------------

Every commit must carry a `Signed-off-by:` line (`git commit --signoff`). By
adding it you agree to the terms in [DCO-1.1.txt](DCO-1.1.txt).

Commit messages
---------------

 - The subject is prefixed with the component it touches, e.g.
   `virtiofsd: Terminate the daemon gracefully before killing it`,
   `virtme-ng-init: Fix user in the script console fallback` or
   `README: troubleshoot: ...`. See `git log` for the existing prefixes.
 - The body explains *why* the change is needed, not only what it does.
 - A new or changed command-line option must be documented in the README (and
   in the `--help` text).

Repository layout
-----------------

| Path                        | Purpose                                                    |
|-----------------------------|------------------------------------------------------------|
| `vng`, `virtme_ng/`         | The `vng` front-end: build, configure and run the kernel   |
| `virtme/`                   | The `virtme-run`, `virtme-configkernel` and                |
|                             | `virtme-mkinitramfs` back-ends that `vng` drives           |
| `virtme/guest/`             | Scripts that run inside the guest (e.g. `virtme-init`)     |
| `virtme_ng_init/`           | Rust implementation of the guest init (`virtme-ng-init`)   |
| `tests/`                    | Python unit and integration tests                          |
| `tools/`                    | Auxiliary material (e.g. Nix tools disk)                   |

Development setup
-----------------

Run from the source tree, without installing:

```console
$ make          # optional: build virtme-ng-init into virtme/guest/bin/
$ ./vng --help
```

Enable the formatting and linting checks as git hooks:

```console
$ pre-commit install
```

Checks that CI runs, and that you should run before submitting:

```console
$ pre-commit run --all-files                          # ruff, shellcheck, shfmt, cargo clippy/fmt/check
$ pylint vng '**/*.py'; find . -name '*.py' | xargs flake8
$ (cd virtme_ng_init && cargo test)
$ VIRTME_TEST_KERNEL=/path/to/bzImage python3 -m unittest discover -s tests -v
```

Non-obvious pitfalls
--------------------

The topics are ordered by priority, from pitfalls that can silently break
whole setups for users down to conventions and niche cases.

### Cross-architecture, cross-endianness and cross-distro support

virtme-ng boots guests of many architectures — x86_64, i386, arm, aarch64,
ppc64/ppc64le, riscv64, s390x and sparc64 (`virtme/architectures.py`) — and
runs on a wide range of host distributions. A change must not silently break
any of them:

 - Guest-side code must not assume the host architecture. A foreign `--arch`
   guest runs under TCG emulation, uses `virtme-ng-init` only if it was built
   for that architecture (see *The two guest inits must behave the same*),
   and `--root-disk` with a foreign `--arch` requires an explicit `--busybox`
   for it. Arch-specific QEMU arguments, kernel image paths, consoles and
   config fragments belong in the per-arch class in
   `virtme/architectures.py`, not hard-coded at the call site.
 - Do not assume the guest has the same endianness as the host: s390x and
   sparc64 guests are big-endian. When parsing binary formats such as kernel
   images, decode fields with an explicit byte order instead of relying on
   the native one (see the little-endian PE/COFF and EFI zboot parsing in
   `virtme/kernel_image.py`).
 - Host-side code must not assume a particular distribution or a recent tool
   version: package names differ (`busybox-static` vs `busybox`), and QEMU,
   coreutils and friends vary between distros. Scripts running in the guest
   initramfs are executed by busybox, not GNU coreutils, and must stay
   busybox-compatible.

### Inspect external tools before depending on them

virtme-ng drives external tools — QEMU, virtiofsd, busybox, `qemu-img`,
`socat`, ... — whose features differ between versions, implementations and
distro packaging. Before building a new feature on one of them:

 - Check that the tool provides what you need in the versions available on
   the supported distributions, not only on your machine, and record the
   minimum required version in the "Requirements" section of the README.
 - Probe for the feature at runtime and degrade gracefully instead of
   assuming support. Existing examples: `Qemu.probe()` in
   `virtme/qemu_helpers.py` gates QEMU features on the probed version
   (`-object monitor-*` needs QEMU 11.1, `multidevs=` needs 4.2), virtiofsd
   is probed with `--version` and `--help` (which also rejects the C
   implementation, since it cannot run unprivileged, and detects `--readonly`
   support), and a failing `qemu-img info` falls back to a raw disk image.
 - Do not assume a fixed install path: distros install virtiofsd in several
   different directories (see `_get_virtiofsd_path()` in
   `virtme/commands/run.py`).

### The two guest inits must behave the same

The guest is initialized either by the Bash script `virtme/guest/virtme-init`
or by the Rust binary `virtme_ng_init/` (installed as
`virtme/guest/bin/virtme-ng-init`). The Rust init is used whenever the binary
exists for the guest architecture, otherwise virtme-ng silently falls back to
the Bash one (see also `--no-virtme-ng-init`).

 - A change to guest behavior (mounts, devices, networking, script I/O, ...)
   almost always has to be made in **both** implementations.
 - If you run from source without having run `make`, you are testing the
   Bash init only. Conversely, a stale `virtme-ng-init` binary hides your
   Rust changes: rebuild it with `make`.
 - The tests should be run against both inits; CI does this.

### Options are defined in two places

`vng` (`virtme_ng/run.py`) parses its own options and translates them into
`virtme-run` options (`virtme/commands/run.py`). A new user-visible option
usually needs to be added to both parsers, and the translation between them
must be wired up (compare how `--no-virtme-ng-init` is handled in both files).

### Docker containers must keep working

Running `vng` inside a (privileged) Docker container is a supported setup, see
the Docker example and troubleshooting entry in the README. Keep it working
when you change host-side code:

 - Do not assume systemd, a running `udev` daemon, a login session or a
   particular init on the host.
 - Do not assume `/dev/kvm` is present or accessible.
 - A new hard host dependency must be added to the package list in the README
   Docker example and to the dependency installation in
   `.github/workflows/run.yml`.
 - stdin/stdout/stderr are often not TTYs in a container. Redirection issues
   are the usual failure mode (see `tests/test_script_io.py`).

### Tests

 - The integration tests boot a guest and need QEMU. They are **skipped**
   when `VIRTME_TEST_KERNEL` is unset, so a green local run without it does
   not prove much. Point it at a bootable kernel image, e.g. one downloaded
   by `vng -r v6.6` to `~/.cache/virtme-ng/`.
 - Without KVM the tests run under emulation and are much slower. CI enables
   `/dev/kvm` for all users with a udev rule.
 - On Ubuntu with Rust coreutils, `/usr/bin/env` may refuse to run from
   virtiofs; CI works around it by linking `/usr/bin/env` to `gnuenv` (see
   the README troubleshooting section).

### `virtme-ng-init` must be statically linked

It runs before the root filesystem is available and is reused across different
root filesystems (`--root DIR`). Static linking (`-C target-feature=+crt-static`)
is configured in `virtme_ng_init/.cargo/config.toml`, and `build.rs` fails the
build if it is missing.

 - A `RUSTFLAGS` environment variable **replaces** the flags from
   `.cargo/config.toml` instead of being merged with them. `make` and
   `setup.py` re-add `+crt-static` for you; plain `cargo build` does not, so
   append it yourself when you export `RUSTFLAGS`.
 - Use `cargo install --profile release --locked` (as the `Makefile` does)
   rather than copying binaries out of `target/`: `CARGO_TARGET_DIR` may
   redirect the output.
 - Guests of another architecture use `virtme/guest/bin/virtme-ng-init-<arch>`.
   Build it with `rustup target add <triple>` and `make init-<arch>` (for
   example `make init-riscv64`). The arch name is the one passed to
   `vng --arch`, not the Rust triple.
 - On macOS the init is cross-compiled to a Linux musl target automatically.

### Python and tooling constraints

 - Supported Python versions are 3.11 to 3.15 (see `requires-python` and the
   CI matrix). Do not use newer language or standard library features.
 - CI runs `pylint` and `flake8` on top of `ruff`; passing `ruff` alone is not
   enough.
 - Shell scripts are checked with `shellcheck` and formatted with `shfmt`
   (4 spaces, see `.editorconfig`). Scripts need a shebang and the executable
   bit, and the guest scripts use `#!/usr/bin/env bash`, so `/usr/bin/env` must
   exist in the guest root.
 - The cargo pre-commit hooks are skipped on pre-commit.ci and run by the Rust
   workflow instead; run them locally. `cargo clippy` runs with
   `--deny warnings`.

### Prefer long options

When running commands — from Python code, shell scripts, tests or
documentation examples — use the long option form (`--output=json`, not
`-j`): it is self-documenting and stable across implementations. The only
exception is a pretty new option: older tool versions installed on supported
distributions may not know its long form yet, so use the short form there.

### Generated and ignored files

`virtme/guest/bin/`, `virtme_ng_init/target/`, `virtme-ng-prompt`,
`vng-prompt`, `vng.1`, `build/` and `*.egg-info` are build products and are
git-ignored. Do not commit them. The shell completion files and the man page
are generated from `virtme_ng.run.make_parser` when building the package, so
the option definitions and their help text are the single source of truth.

### Version string

`virtme_ng/version.py` derives the version from `git describe --long --dirty`
when run from a git checkout, and falls back to the hard-coded `PKG_VERSION`
otherwise (e.g. in a tarball). A shallow clone or a checkout without tags
therefore reports a misleading version. `VNG_PACKAGE=1` forces `PKG_VERSION`
for distribution packages.

### Nix support

`tools/` contains a Nix recipe that builds an EROFS image of a Nix store
(`/nix/store/tools/bin`), which is attached to the guest with `--disk` (see the
README example and [`tools/README.md`](tools/README.md)). It gives tests a
reproducible set of tools independent of the host.

 - New tools are added in `tools/package.nix`, not in the guest init.
 - The image is mounted by the user at `/nix/store` in the guest, so the guest
   needs that directory: the README example runs `mkdir -p /nix/store` on the
   host first, because the host filesystem is the guest root.
 - `tools/flake.lock` pins `nixpkgs`; `tools/default.nix` is only a shim for the
   non-flake `nix-build` commands. Keep both working when editing the recipe.
 - CI does not build or test the Nix image, so verify it by hand with
   `nix build --extra-experimental-features nix-command -f tools`.
