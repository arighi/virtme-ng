#!/bin/bash
#
# Automatically create a deb from the git repository
#
# Requirements:
#  - apt install git-buildpackage

gbp buildpackage --git-ignore-branch
