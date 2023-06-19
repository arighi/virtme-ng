#!/bin/bash
#
# Automatically create a deb from the git repository
#
# Requirements:
#  - apt install git-buildpackage
#
# Example usage:
#  $ ./build-deb.sh -S -sa --lintian-opts --no-lintian

MODULES="virtme_ng_init virtiofsd"

if [ ! -d .git ]; then
    echo "error: must be ran from a git repository"
    exit 1
fi

# Include Rust vendor dependencies in the package (external builders usually
# don't allow to download external packages during the build process).
#
# This is required to build virmte-ng-init and virtiofsd.
for mod in $MODULES; do
    cd $mod
    git clean -xdf || true
    cargo vendor
    mkdir .cargo
    cat << EOF > .cargo/config.toml
[source.crates-io]
replace-with = "vendored-sources"

[source.vendored-sources]
directory = "vendor"
EOF
    git add .
    git commit -a -m "include $mod vendor dependencies"
    cd -
done

git add $MODULES
git commit -a -m "resync submodules"

# Create upsteam tag
deb_tag=$(dpkg-parsechangelog -S version | cut -d- -f1)
git tag upstream/${deb_tag}

gbp buildpackage --git-ignore-branch --git-submodules $*

# Undo packaging changes and restore original git repo
git tag -d upstream/${deb_tag}

# Restore original git repo
git clean -xdf || true
for mod in $MODULES; do
    cd $mod
    git reset --hard HEAD~1
    cd -
done
git reset --hard HEAD~1
