INSTALL_ARGS :=	# todo: add --break-system-packages if ubuntu

CARGO ?= cargo
INIT_DIR := virtme_ng_init
GUEST_DIR := virtme/guest
INIT_BIN := $(GUEST_DIR)/bin/virtme-ng-init

# Get git version information for make install
GIT_DESCRIBE := $(shell git describe --always --long --dirty)

# Static linking, stripping and linker settings live in
# $(INIT_DIR)/.cargo/config.toml and $(INIT_DIR)/Cargo.toml. Note that
# `cargo install` has no `--release` flag; its explicit form is
# `--profile release` (it is also the default).
CARGO_INSTALL_ARGS := --profile release --locked

# On macOS, cross-compile to a Linux musl target.
ifeq ($(shell uname -s),Darwin)
CARGO_INSTALL_ARGS += --target $(patsubst arm64,aarch64,$(shell uname -m))-unknown-linux-musl
endif

# Staging root for the `cargo install` run of `make init-<arch>`: `cargo
# install` always names the binary after the crate's [[bin]] and cannot
# rename it, so it cannot install it as virtme-ng-init-<arch> directly
# (installing into $(GUEST_DIR) and renaming from there would clobber the
# native init). Absolute, because cargo is invoked from $(INIT_DIR), and
# under target/ so that it is covered by the virtme_ng_init/target gitignore
# entry.
INIT_INSTALL_ROOT := $(abspath $(INIT_DIR)/target/install)

# Rust target triples for `make init-<arch>`, keyed by the arch name passed
# to `vng --arch` (run `rustup target add <target>` first). Archs not listed
# here default to <arch>-unknown-linux-musl. s390x has no official musl
# target, so it uses gnu. Override with RUST_TARGET=<target>.
RUST_TARGET_arm     := arm-unknown-linux-musleabihf
RUST_TARGET_arm64   := aarch64-unknown-linux-musl
RUST_TARGET_i386    := i686-unknown-linux-musl
RUST_TARGET_ppc64   := powerpc64-unknown-linux-musl
RUST_TARGET_ppc64le := powerpc64le-unknown-linux-musl
RUST_TARGET_riscv64 := riscv64gc-unknown-linux-musl
RUST_TARGET_s390x   := s390x-unknown-linux-gnu

.DEFAULT_GOAL := all
.PHONY: all init clean install install_from_source install_only_top

all: init

# Install the init directly into $(GUEST_DIR)/bin, like setup.py does. Use
# `cargo install` instead of `cargo build` + copying from a hardcoded output
# directory, so that cargo itself locates the built binary, also when
# CARGO_TARGET_DIR redirects the output directory.
init:
	cd $(INIT_DIR) && $(CARGO) install --path . --root ../$(GUEST_DIR) --force $(CARGO_INSTALL_ARGS)
	@echo "Version: $(GIT_DESCRIBE)"

# Cross-build the init for a non-native guest, e.g. `make init-riscv64`.
init-%: RUST_TARGET = $(or $(RUST_TARGET_$*),$*-unknown-linux-musl)
init-%:
	cd $(INIT_DIR) && $(CARGO) install --path . --root $(INIT_INSTALL_ROOT) --force $(CARGO_INSTALL_ARGS) --target $(RUST_TARGET)
	mv $(INIT_INSTALL_ROOT)/bin/virtme-ng-init $(INIT_BIN)-$*
	@echo "Version: $(GIT_DESCRIBE)"

clean:
	python3 setup.py clean
	cd $(INIT_DIR) && $(CARGO) clean
	$(RM) -r $(INIT_INSTALL_ROOT)
	$(RM) $(INIT_BIN) $(INIT_BIN)-* $(GUEST_DIR)/.crates*

# see README.md '* Install from source'
install: install_from_source
install_from_source:
	@echo "Version: $(GIT_DESCRIBE)"
	BUILD_VIRTME_NG_INIT=1 pip3 install --verbose $(INSTALL_ARGS) .

install_only_top:
	@echo "Version: $(GIT_DESCRIBE)"
	BUILD_VIRTME_NG_INIT=0 pip3 install --verbose $(INSTALL_ARGS) .
