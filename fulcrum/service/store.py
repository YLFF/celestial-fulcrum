"""Atomic run snapshots and map-update checkpoints for undo/redo."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4

from ..goals import new_goals
from ..acquisition_facts import seed_acquisition_facts
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
            history = state.pop("_serviceHistory", None)
            if history is None:
                history = self._legacy_history(run_id, state)
            self._validate_history(history)
            self.validate(state)
            seed_acquisition_facts(state, history["past"])
            rebuild_derived(state)
            if state["runId"] != run_id:
                raise ValueError("stored run ID does not match directory")
            revision = state.get("_serviceRevision", 0)
            if type(revision) is not int or revision < 0:
                raise ValueError("invalid saved revision")
            return {"runId": run_id, "revision": revision, "state": state,
                    "history": {"canUndo": bool(history["past"]), "canRedo": bool(history["future"]),
                                "undoCount": len(history["past"]), "redoCount": len(history["future"])}}

    def get_revision(self, run_id):
        """Read freshness metadata without rebuilding predictions or loading legacy history."""
        with self.lock:
            path = self.path(run_id)
            if not path.is_file():
                raise FileNotFoundError("run not found")
            saved = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict) or saved.get("runId") != run_id:
                raise ValueError("stored run ID does not match directory")
            revision = saved.get("_serviceRevision", 0)
            if type(revision) is not int or revision < 0:
                raise ValueError("invalid saved revision")
            return revision

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
            history = state.pop("_serviceHistory", None)
            if history is None:
                history = {"past": [], "future": []}
            self._validate_history(history)
            source_id = state.get("runId")
            run_id = safe_id(run_id or state.get("runId"))
            try:
                seed_acquisition_facts(state, history["past"])
                for snapshot in [state, *history["past"], *history["future"]]:
                    if snapshot.get("runId") != source_id:
                        raise ValueError("history run ID does not match imported snapshot")
                    snapshot["runId"] = run_id
                    snapshot.setdefault("goals", new_goals())
                    seed_owned_milestones(snapshot)
                    rebuild_derived(snapshot)
                    self.validate(snapshot)
            except (KeyError, TypeError, AttributeError) as error:
                raise ValueError("malformed Playtime snapshot") from error
            path = self.path(run_id)
            if path.exists():
                raise RevisionConflict("run already exists; open it or import under a new ID")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._save(path, state, 1, history)
            return self.load(run_id)

    def export(self, run_id):
        with self.lock:
            state = self.load(run_id)["state"]
            state["_serviceHistory"] = self._history(run_id)
            return state

    def _save(self, path, state, revision, history=None):
        state["_serviceRevision"] = revision
        state["updatedAt"] = datetime.now(timezone.utc).isoformat()
        saved = deepcopy(state)
        saved["_serviceHistory"] = history or {"past": [], "future": []}
        atomic_json(path, saved)

    @staticmethod
    def _validate_history(history):
        if not isinstance(history, dict) or set(history) != {"past", "future"} or any(
            not isinstance(history[key], list) or any(not isinstance(row, dict) or "_serviceHistory" in row
                                                      for row in history[key]) for key in ("past", "future")
        ):
            raise ValueError("invalid exploration history")

    def _history(self, run_id):
        saved = json.loads(self.path(run_id).read_text(encoding="utf-8"))
        history = saved.get("_serviceHistory")
        if history is None:
            history = self._legacy_history(run_id, saved)
        self._validate_history(history)
        return history

    def _legacy_history(self, run_id, state):
        history = {"past": [], "future": []}
        path = self.checked_file(self.path(run_id).with_name("previous.json"))
        if not path.is_file():
            return history
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            self.validate(previous)
            if previous.get("runId") != run_id:
                return history
            def map_fingerprint(snapshot):
                return (snapshot.get("currentAreaKey"), {
                    key: (slot.get("activeInstanceId"), [(row.get("instanceId"), row.get("playerPosition"),
                        row.get("sourceAssetId"), row.get("sourceScreenshot")) for row in slot.get("instances", [])])
                    for key, slot in snapshot["areas"].items()
                })
            # Old releases retained only one edit; reuse it only if it was a map transition.
            if map_fingerprint(previous) != map_fingerprint(state):
                previous.pop("_serviceHistory", None)
                history["past"].append(previous)
        except (ValueError, KeyError, TypeError):
            pass
        return history

    @staticmethod
    def _check_revision(loaded, revision):
        if type(revision) is not int or revision != loaded["revision"]:
            raise RevisionConflict("snapshot changed; reload before confirming")

    @staticmethod
    def validate(state):
        try:
            validate_application_state(state)
            json.dumps(state, allow_nan=False)
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("malformed Playtime snapshot") from error

    def update(self, run_id, revision, mutate, *, map_update=False):
        with self.lock:
            loaded = self.load(run_id)
            self._check_revision(loaded, revision)
            draft = deepcopy(loaded["state"])
            try:
                mutate(draft)
                self.validate(draft)
            except (KeyError, TypeError, AttributeError) as error:
                raise ValueError("invalid snapshot update") from error
            path = self.path(run_id)
            history = self._history(run_id)
            if map_update:
                history["past"].append(loaded["state"])
            history["future"] = []
            self._save(path, draft, revision + 1, history)
            return self.load(run_id)

    def undo(self, run_id, revision):
        return self._travel(run_id, revision, "past", "future")

    def redo(self, run_id, revision):
        return self._travel(run_id, revision, "future", "past")

    def _travel(self, run_id, revision, source, destination):
        with self.lock:
            loaded = self.load(run_id)
            self._check_revision(loaded, revision)
            history = self._history(run_id)
            if not history[source]:
                raise ValueError("没有可撤销的地图更新" if source == "past" else "没有可重做的地图更新")
            restored = history[source].pop()
            if restored.get("runId") != run_id:
                raise ValueError("history run ID does not match directory")
            self.validate(restored)
            history[destination].append(loaded["state"])
            self._save(self.path(run_id), restored, revision + 1, history)
            return self.load(run_id)

    def markdown(self, run_id):
        state = self.load(run_id)["state"]
        template_path = ROOT / "BLACKFLOW_PLAYTIME_TEMPLATE.md"
        result = replace_runtime_sections(template_path.read_text(encoding="utf-8"), state) if template_path.is_file() else render_standalone(state)
        if state.get("memo"):
            result += "\n\n## 本局备忘\n\n" + state["memo"] + "\n"
        return result
