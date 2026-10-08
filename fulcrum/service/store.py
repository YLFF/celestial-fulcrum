"""Atomic JSON snapshots with revision checks and one undo snapshot per run."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4

from ..goals import new_goals
from ..playtime_state import new_playtime, rebuild_derived
from ..playtime_view import replace_runtime_sections, render_standalone
from .updates import validate_application_state, seed_owned_milestones

ROOT = Path(__file__).resolve().parents[2]


class RevisionConflict(ValueError):
    pass


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("invalid run ID")
    if value.upper() in {"CON", "PRN", "AUX", "NUL", *(f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10))}:
        raise ValueError("reserved Windows run ID")
    return value


def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class RunStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def path(self, run_id):
        path = (self.root / safe_id(run_id)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("run directory escapes application storage")
        return self.checked_file(path / "playtime.json")

    def checked_file(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("file escapes application storage")
        return path

    def load(self, run_id):
        with self.lock:
            path = self.path(run_id)
            if not path.is_file():
                raise FileNotFoundError("run not found")
            state = json.loads(path.read_text(encoding="utf-8"))
            self.validate(state)
            rebuild_derived(state)
            if state["runId"] != run_id:
                raise ValueError("stored run ID does not match directory")
            revision = state.get("_serviceRevision", 0)
            if type(revision) is not int or revision < 0:
                raise ValueError("invalid saved revision")
            return {"runId": run_id, "revision": revision, "state": state}

    def list(self):
        rows = []
        for path in sorted(self.root.glob("*/playtime.json")):
            try:
                loaded = self.load(path.parent.name)
                state = loaded["state"]
                rows.append({"runId": loaded["runId"], "revision": loaded["revision"],
                             "currentAreaKey": state.get("currentAreaKey"), "updatedAt": state.get("updatedAt"), "valid": True})
            except (ValueError, KeyError, TypeError):
                rows.append({"runId": path.parent.name, "valid": False})
        return rows

    def create(self, run_id=None, **opening):
        run_id = safe_id(run_id or uuid4().hex)
        return self.restore(new_playtime(run_id, **opening), run_id=run_id)

    def restore(self, source, *, run_id=None):
        with self.lock:
            if not isinstance(source, dict):
                raise ValueError("Playtime must be an object")
            state = deepcopy(source)
            run_id = safe_id(run_id or state.get("runId"))
            state["runId"] = run_id
            state.setdefault("goals", new_goals())
            try:
                seed_owned_milestones(state)
                rebuild_derived(state)
                self.validate(state)
            except (KeyError, TypeError, AttributeError) as error:
                raise ValueError("malformed Playtime snapshot") from error
            path = self.path(run_id)
            if path.exists():
                raise RevisionConflict("run already exists; open it or import under a new ID")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._save(path, state, 1)
            return self.load(run_id)

    def _save(self, path, state, revision):
        state["_serviceRevision"] = revision
        state["updatedAt"] = datetime.now(timezone.utc).isoformat()
        atomic_json(path, state)

    @staticmethod
    def validate(state):
        try:
            validate_application_state(state)
            json.dumps(state, allow_nan=False)
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("malformed Playtime snapshot") from error

    def update(self, run_id, revision, mutate):
        with self.lock:
            loaded = self.load(run_id)
            if type(revision) is not int or revision != loaded["revision"]:
                raise RevisionConflict("snapshot changed; reload before confirming")
            draft = deepcopy(loaded["state"])
            try:
                mutate(draft)
                self.validate(draft)
            except (KeyError, TypeError, AttributeError) as error:
                raise ValueError("invalid snapshot update") from error
            path = self.path(run_id)
            atomic_json(self.checked_file(path.with_name("previous.json")), loaded["state"])
            self._save(path, draft, revision + 1)
            return self.load(run_id)

    def undo(self, run_id, revision):
        with self.lock:
            path = self.checked_file(self.path(run_id).with_name("previous.json"))
            if not path.is_file():
                raise FileNotFoundError("no previous snapshot")
            previous = json.loads(path.read_text(encoding="utf-8"))
            def restore(draft):
                draft.clear()
                draft.update(deepcopy(previous))
            return self.update(run_id, revision, restore)

    def markdown(self, run_id):
        state = self.load(run_id)["state"]
        template_path = ROOT / "BLACKFLOW_PLAYTIME_TEMPLATE.md"
        result = replace_runtime_sections(template_path.read_text(encoding="utf-8"), state) if template_path.is_file() else render_standalone(state)
        if state.get("memo"):
            result += "\n\n## 本局备忘\n\n" + state["memo"] + "\n"
        return result
