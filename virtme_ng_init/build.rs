// SPDX-License-Identifier: GPL-3.0

//! Build script of virtme-ng-init.
//!
//! virtme-ng-init must be a static binary: it is executed before the root
//! filesystem is available and it is reused across different root filesystems
//! (when `--root DIR` is used). The `-C target-feature=+crt-static` flag is
//! configured in .cargo/config.toml, but a RUSTFLAGS environment variable
//! replaces those flags wholesale (Cargo treats the possible rustflags sources
//! as mutually exclusive and never merges them), which would silently produce
//! a dynamically linked binary. Fail the build loudly instead.

fn main() {
    // Re-evaluate the guard whenever the effective rustflags change.
    println!("cargo:rerun-if-env-changed=RUSTFLAGS");
    println!("cargo:rerun-if-env-changed=CARGO_ENCODED_RUSTFLAGS");

    // The effective rustflags of this build as computed by Cargo (from the
    // environment or from .cargo/config.toml), separated by 0x1f.
    let rustflags = std::env::var("CARGO_ENCODED_RUSTFLAGS").unwrap_or_default();
    // The target triple of the artifact being built (build scripts
    // themselves are always compiled for and run on the host).
    let target = std::env::var("TARGET").unwrap_or_default();

    // musl targets enable crt-static by default, so the flag is only
    // strictly required for the other Linux targets (e.g. gnu).
    let crt_static_default = target.ends_with("-musl");
    let crt_static = rustflags.contains("target-feature=+crt-static")
        || (crt_static_default && !rustflags.contains("target-feature=-crt-static"));

    if target.contains("linux") && !crt_static {
        panic!(
            "virtme-ng-init must be statically linked, but crt-static is not \
             enabled for target '{target}': a RUSTFLAGS environment variable \
             overrides the flags in .cargo/config.toml entirely. Append to it \
             instead of replacing it: \
             RUSTFLAGS=\"-C target-feature=+crt-static $RUSTFLAGS\""
        );
    }
}
