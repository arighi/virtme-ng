#!/bin/bash

if (( $# != 1 )); then
    echo "Usage: make-release-tarball VERSION"
    exit 1
fi

ver="$1"

exec git archive --prefix=virtme-$ver/ --format=tar -o /dev/stdout HEAD
