# -*- mode: python -*-
# Copyright 2023 Andrea Righi

"""virtme-ng: mainline kernel downloader."""

import os
import re
import sys
import subprocess
from glob import glob
from shutil import which
import requests
from virtme_ng.utils import CACHE_DIR, spinner_decorator

BASE_URL = "https://kernel.ubuntu.com/mainline"

HTTP_CHUNK = 4096
HTTP_TIMEOUT = 30


class KernelDownloader:
    def __init__(self, version, arch="amd64", verbose=False):
        # Fetch and extract precompiled mainline kernel
        self.kernel_dir = f"{CACHE_DIR}/{version}/{arch}"
        self.version = version
        self.arch = arch
        self.verbose = verbose
        self.target = f"{self.kernel_dir}/boot/vmlinuz*generic*"

        if not glob(self.target):
            self._fetch_kernel()

    def _download_file(self, url, destination):
        response = requests.get(url, stream=True, timeout=HTTP_TIMEOUT)
        if response.status_code == 200:
            os.makedirs(self.kernel_dir, exist_ok=True)
            with open(destination, 'wb') as file:
                for chunk in response.iter_content(chunk_size=HTTP_CHUNK):
                    file.write(chunk)
        else:
            raise FileNotFoundError(f"failed to download {url}, error: {response.status_code}")

    @spinner_decorator(message="📥 downloading kernel")
    def _fetch_kernel(self):
        if not which("dpkg"):
            raise FileNotFoundError("dpkg is not available, unable to uncompress kernel deb")

        url = BASE_URL + "/" + self.version + "/" + self.arch
        response = requests.get(url, timeout=HTTP_TIMEOUT)
        if response.status_code != 200:
            url = BASE_URL + "/" + self.version
            response = requests.get(url, timeout=HTTP_TIMEOUT)
        if self.verbose:
            sys.stderr.write(f"use {self.version}/{self.arch} pre-compiled kernel from {url}\n")
        if response.status_code == 200:
            href_pattern = re.compile(r'href=["\']([^\s"\']+.deb)["\']')
            matches = href_pattern.findall(response.text)
            for match in matches:
                # Skip headers packages
                if 'headers' in match:
                    continue
                # Skip packages for different architectures
                if f'{self.arch}.deb' not in match:
                    continue
                # Skip if package is already downloaded
                deb_file = f"{self.kernel_dir}/{match}"
                if os.path.exists(deb_file):
                    continue
                self._download_file(url + "/" + match, deb_file)
                subprocess.check_call(['dpkg', '-x', deb_file, self.kernel_dir])
            if not glob(f"{self.kernel_dir}/*.deb"):
                raise FileNotFoundError(f"could not find kernel packages at {url}")
        else:
            raise FileNotFoundError(f"failed to retrieve content, error: {response.status_code}")
