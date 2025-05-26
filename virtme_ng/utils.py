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

# NOTE: this must stay in sync with README.md
CONF_DEFAULT = {
    "default_opts": {},
    "systemd": {
        "masks": [
            # disable getty@, since we're forcing the use of serial-getty@
            "getty@"
        ]
    },
}


def spinner_decorator(message):
    def decorator(func):
        def wrapper(*args, **kwargs):
            with Spinner(message=message):
                result = func(*args, **kwargs)
                return result

        return wrapper

    return decorator


def get_conf_obj():
    """Return virtme-ng main configuration, returning the default if not found."""

    # First check if there is a config file in the user's home config
    # directory, then check for a single config file in ~/.virtme-ng.conf and
    # finally check for /etc/virtme-ng.conf. If none of them exist, return the
    # default configuration.
    conf_paths = (
        CONF_FILE,
        Path(Path.home(), ".virtme-ng.conf"),
        Path("/etc", "virtme-ng.conf"),
    )
    for conf_path in conf_paths:
        if conf_path.exists():
            with open(conf_path, encoding="utf-8") as conf_fd:
                conf = json.loads(conf_fd.read())
                return conf
    return CONF_DEFAULT


def get_conf(key_path):
    """Return a configured value for a key_path, which might be nested

    >>> get_conf("default_opts")
    {}
    >>> get_conf("systemd")
    {'masks': ["getty@"]}
    >>> get_conf("systemd.masks")
    ["getty@"]
    """
    keys = key_path.split(".")
    conf = get_conf_obj()
    try:
        for key in keys:
            conf = conf[key]
        return conf
    except (KeyError, TypeError):
        conf = CONF_DEFAULT
        for key in keys:
            conf = conf[key]
        return conf
