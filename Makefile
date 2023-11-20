.PHONY: init
init:
	cd virtme_ng_init && cargo install --path . --root ../virtme/guest
