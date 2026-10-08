"""Public product identity, independent of theme-specific module names."""

import json

from .runtime import ROOT

PROJECT = json.loads((ROOT / "data/project_info.json").read_text(encoding="utf-8"))
