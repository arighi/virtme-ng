# -*- mode: python -*-
# Copyright 2023 Andrea Righi

"""virtme-ng: configuration path."""

import json
from pathlib import Path

from virtme_ng.spinner import Spinner

CACHE_DIR = Path(Path.home(), ".cache", "virtme-ng")
SSH_DIR = Path(CACHE_DIR, ".ssh")
SSH_CONF_FILE = SSH_DIR.joinpath("virtme-ng-ssh.conf")
VIRTME_SSH_DESTINATION_NAME = "virtme-ng"
VIRTME_SSH_HOSTNAME_CID_SEPARATORS = ("%", "/")
DEFAULT_VIRTME_SSH_HOSTNAME_CID_SEPARATOR = VIRTME_SSH_HOSTNAME_CID_SEPARATORS[0]
CONF_PATH = Path(Path.home(), ".config", "virtme-ng")
CONF_FILE = Path(CONF_PATH, "virtme-ng.conf")
SERIAL_GETTY_FILE = Path(CACHE_DIR, "serial-getty@.service")


def spinner_decorator(message):
    def decorator(func):
        def wrapper(*args, **kwargs):
            with Spinner(message=message):
                result = func(*args, **kwargs)
                return result

        return wrapper

    return decorator


def get_conf_file_path():
    """Return virtme-ng main configuration file path."""

    # First check if there is a config file in the user's home config
    # directory, then check for a single config file in ~/.virtme-ng.conf and
    # finally check for /etc/virtme-ng.conf. If none of them exist, report an
    # error and exit.
    configs = (
        CONF_FILE,
        Path(Path.home(), ".virtme-ng.conf"),
        Path("/etc", "virtme-ng.conf"),
    )
    for conf in configs:
        if conf.exists():
            return conf
    return None


def get_conf(name):
    conf_path = get_conf_file_path()
    if conf_path is not None:
        with open(conf_path, encoding="utf-8") as conf_fd:
            conf_data = json.loads(conf_fd.read())
            if name in conf_data:
                return conf_data[name]
    return []
