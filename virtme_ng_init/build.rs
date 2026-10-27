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
    let target_os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();

    // Whether static linking is enabled. Cargo reports the enabled target
    // features in CARGO_CFG_TARGET_FEATURE for every flag source (including
    // RUSTFLAGS), which, unlike matching the rustflags strings themselves,
    // cannot be fooled by combinations such as "-C
    // target-feature=+sse2,+crt-static". Disabled features do not show up
    // there, so crt-static must be enabled explicitly for every target, even
    // where it is the default (musl).
    let crt_static = has_feature(
        &std::env::var("CARGO_CFG_TARGET_FEATURE").unwrap_or_default(),
        "crt-static",
    );

    if target_os == "linux" && !crt_static {
        panic!(
            "virtme-ng-init must be statically linked, but crt-static is not \
             enabled: a RUSTFLAGS environment variable overrides the flags \
             in .cargo/config.toml entirely, or crt-static was disabled \
             explicitly. Append to it instead of replacing it: \
             RUSTFLAGS=\"-C target-feature=+crt-static $RUSTFLAGS\""
        );
    }
}

// Whether the comma-separated list of target features `features` contains
// `feature`. Splitting on the commas matters: a combination like
// "-C target-feature=+sse2,+crt-static" hides "crt-static" from naive
// substring matching.
fn has_feature(features: &str, feature: &str) -> bool {
    features.split(',').any(|entry| entry.trim() == feature)
}
