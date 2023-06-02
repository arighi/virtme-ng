# -*- mode: python -*-
# Copyright 2023 Andrea Righi

"""virtme-ng: version and configuration path."""

from pathlib import Path

VERSION = "1.9"
CONF_PATH = Path(Path.home(), ".config", "virtme-ng")
CONF_FILE = Path(CONF_PATH, "virtme-ng.conf")
