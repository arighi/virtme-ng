# -*- mode: python -*-
# Copyright 2023 Andrea Righi

"""virtme-ng: configuration path."""

from pathlib import Path

CONF_PATH = Path(Path.home(), ".config", "virtme-ng")
CONF_FILE = Path(CONF_PATH, "virtme-ng.conf")
