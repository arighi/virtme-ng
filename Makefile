INSTALL_ARGS :=	# todo: add --break-system-packages if ubuntu

# Get git version information for make install
GIT_DESCRIBE := $(shell git describe --always --long --dirty)

.PHONY: init
init:
	cd virtme_ng_init && cargo install --path . --root ../virtme/guest

# see README.md '* Install from source'
install: install_from_source
install_from_source:
	@echo "Version: $(GIT_DESCRIBE)"
	BUILD_VIRTME_NG_INIT=1 pip3 install --verbose -r requirements.txt $(INSTALL_ARGS) .

install_only_top:
	@echo "Version: $(GIT_DESCRIBE)"
	BUILD_VIRTME_NG_INIT=0 pip3 install --verbose -r requirements.txt $(INSTALL_ARGS) .
