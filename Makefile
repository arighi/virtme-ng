INSTALL_ARGS :=	# todo: add --break-system-packages if ubuntu

# Get git version information for make install
GIT_DESCRIBE := $(shell git describe --always --long --dirty)

.PHONY: all init clean install install_from_source install_only_top

all: init

virtme/guest/bin/virtme-ng-init: virtme_ng_init/src/*.rs
	BUILD_VIRTME_NG_INIT=1 python3 setup.py build

init: virtme/guest/bin/virtme-ng-init
	@echo "Version: $(GIT_DESCRIBE)"

clean:
	BUILD_VIRTME_NG_INIT=1 python3 setup.py clean
	rm -f virtme/guest/bin/virtme-ng-init

# see README.md '* Install from source'
install: install_from_source
install_from_source:
	@echo "Version: $(GIT_DESCRIBE)"
	BUILD_VIRTME_NG_INIT=1 pip3 install --verbose $(INSTALL_ARGS) .

install_only_top:
	@echo "Version: $(GIT_DESCRIBE)"
	BUILD_VIRTME_NG_INIT=0 pip3 install --verbose $(INSTALL_ARGS) .
