"""Read pre-rename settings without moving or replacing player data."""

import os
from pathlib import Path

from .product import PROJECT
LEGACY_TOKEN_HEADER = "X-Blackflow-Token"


def configured_app_data(environ=None):
    values = os.environ if environ is None else environ
    return values.get("CFARA_APP_DATA") or values.get("FULCRUM_APP_DATA") or values.get("BLACKFLOW_APP_DATA")


def default_data_directory(base):
    base = Path(base)
    return base / PROJECT["dataDirectoryName"]
