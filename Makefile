INSTALL_ARGS :=	# todo: add --break-system-packages if ubuntu

.PHONY: init
init:
	cd virtme_ng_init && cargo install --path . --root ../virtme/guest

# see README.md '* Install from source'
install: install_from_source
install_from_source:
	BUILD_VIRTME_NG_INIT=1 pip3 install --verbose -r requirements.txt $(INSTALL_ARGS) .
