mkdir -p virtme_ng_init/.cargo
cat << EOF > virtme_ng_init/.cargo/config.toml
[source]
[source.debian-packages]
directory = "/usr/share/cargo/registry"
[source.crates-io]
replace-with = "debian-packages"
EOF
