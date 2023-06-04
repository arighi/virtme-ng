#!/bin/bash
#
# Automatically create a deb from the git repository
#
# Requirements:
#  - apt install git-buildpackage

if [ ! -d .git ]; then
    echo "error: must be ran from a git repository"
    exit 1
fi

# Include Rust vendor dependencies in the package (external builders usually
# don't allow to download external packages during the build process).
#
# This is required to build virmte-ng-init.
cd virtme_ng_init
cargo vendor
mkdir .cargo
cat << EOF > .cargo/config.toml
[source.crates-io]
replace-with = "vendored-sources"

[source.vendored-sources]
directory = "vendor"
EOF
cd -

git add virtme_ng_init
git commit -a -m "include vendor dependencies"

# Create upsteam tag
deb_tag=$(dpkg-parsechangelog -S version | cut -d- -f1)
git tag upstream/${deb_tag}

gbp buildpackage --git-ignore-branch $*

# Undo packaging changes and restore original git repo
git tag -d upstream/${deb_tag}
git reset --hard HEAD~1
