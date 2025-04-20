# -*- mode: python -*-
# Copyright 2023 Andrea Righi

"""virtme-ng: configuration path."""

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


def spinner_decorator(message):
    def decorator(func):
        def wrapper(*args, **kwargs):
            with Spinner(message=message):
                result = func(*args, **kwargs)
                return result

        return wrapper

    return decorator
