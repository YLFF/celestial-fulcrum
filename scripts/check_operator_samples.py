"""Local, read-only checks for the two supplied squad screenshots."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fulcrum.vision_operators import OperatorRecognizer

for path in sys.argv[1:]:
    print(json.dumps({"file": path, **OperatorRecognizer().recognize(path)}, ensure_ascii=False), flush=True)
