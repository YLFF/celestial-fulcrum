"""Read-only background computations bound to a specific Playtime revision."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from threading import Event, RLock
import time
from uuid import uuid4

from ..goals import goal_summary, node_goal_annotations
from ..playtime_route import route_inputs
from ..playtime_state import AREA_SPECS, active_instance
from ..route_planner import RoutePlanner
from .store import atomic_json


from ..diagnostics import localize_result, public_error, message


class JobCancelled(RuntimeError):
    pass


class JobManager:
    def __init__(self, root, store, assets):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store, self.assets = store, assets
        self.lock = RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fulcrum")
        self.records, self.events = {}, {}
        for path in self.root.glob("*.json"):
            if not re.fullmatch(r"[a-f0-9]{32}", path.stem):
                continue
            path = self.path(path.stem)
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(row, dict) or row.get("jobId") != path.stem:
                    raise ValueError("invalid saved job record")
            except (OSError, ValueError) as error:
                logging.getLogger(__name__).warning("忽略损坏的历史任务文件 %s：%s", path, error)
                continue
            if row.get("status") in {"queued", "running"}:
                row.update(status="interrupted", error=message("service restarted; submit against the current snapshot"))
                atomic_json(path, row)

    def path(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("invalid job ID")
        path = (self.root / (job_id + ".json")).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("job escapes storage")
        return path

    def _save(self, row):
        atomic_json(self.path(row["jobId"]), row)

    def get(self, job_id):
        with self.lock:
            if job_id in self.records:
                row = deepcopy(self.records[job_id])
            else:
                path = self.path(job_id)
                if not path.is_file():
                    raise FileNotFoundError("job not found")
                row = json.loads(path.read_text(encoding="utf-8"))
        try:
            revision = self.store.get_revision(row["runId"])
        except FileNotFoundError:
            revision = None
        row["currentRevision"] = revision
        row["stale"] = revision != row["sourceRevision"]
        row = localize_result(row)
        if isinstance(row.get("error"), str):
            original = row["error"]
            row["error"] = public_error(RuntimeError(original))
            if row["error"] != original:
                row.setdefault("diagnosticDetail", original)
        return row

    def submit(self, kind, loaded, options):
        if kind not in {"recognize", "recognize-relics", "score", "plan"}:
            raise ValueError("unsupported job kind")
        if kind in {"recognize", "recognize-relics"}:
            self.assets.load(options["assetId"])
        area_key = options.get("areaKey") or loaded["state"].get("currentAreaKey")
        if area_key is not None and area_key not in AREA_SPECS:
            raise ValueError("invalid area key")
        if kind in {"score", "plan"}:
            route_inputs(loaded["state"], area_key, pursuit=options.get("pursuit", False),
                         planning_goal_ids=options.get("planningGoalIds"), use_item_ids=options.get("useItemIds"))
            if kind == "plan":
                from ..ending_prediction import require_planning_valid
                require_planning_valid(loaded["state"], active_instance(loaded["state"], area_key))
        with self.lock:
            if sum(row["status"] in {"queued", "running"} for row in self.records.values()) >= 8:
                raise ValueError("too many active jobs; wait or cancel")
            job_id = uuid4().hex
            row = {"jobId": job_id, "kind": kind, "runId": loaded["runId"],
                   "sourceRevision": loaded["revision"], "options": deepcopy(options),
                   "status": "queued", "createdAt": datetime.now(timezone.utc).isoformat(), "progress": {}}
            self.records[job_id] = row
            self.events[job_id] = Event()
            self._save(row)
            self.pool.submit(self._execute, job_id, deepcopy(loaded["state"]))
        return self.get(job_id)

    def cancel(self, job_id):
        self.get(job_id)
        with self.lock:
            current = self.records.get(job_id)
            event = self.events.get(job_id)
            if current and event and current["status"] in {"queued", "running"}:
                event.set()
                current["cancelRequested"] = True
        return self.get(job_id)

    def _execute(self, job_id, state):
        started = time.perf_counter()
        event = self.events[job_id]
        def check():
            if event.is_set():
                raise JobCancelled("computation cancelled")
        try:
            check()
            with self.lock:
                row = self.records[job_id]
                row["status"] = "running"
                self._save(row)
                kind, options = row["kind"], row["options"]
            if kind == "recognize-relics":
                from ..vision_relics import RelicRecognizer
                result = RelicRecognizer().recognize(self.assets.path(options["assetId"]))
                result["assetId"] = options["assetId"]
            elif kind == "recognize":
                from ..vision_pipeline import MapRecognizer
                from ..vision_resources import HudRecognizer
                asset = self.assets.path(options["assetId"])
                if options.get("resourcesOnly"):
                    import cv2
                    result = {"success": False, "resourceObservation": HudRecognizer().recognize_image(cv2.imread(str(asset))),
                              "warnings": ["本次仅识别资源，不生成地图候选。"]}
                else:
                    area_key = options.get("areaKey")
                    area, floor = AREA_SPECS[area_key] if area_key else (None, None)
                    result = MapRecognizer().recognize(asset, area=area, floor=floor,
                        template_override=options.get("templateId"), include_resources=options.get("includeResources", True),
                        difficulty=state["opening"]["difficulty"]).to_dict()
                    if result.get("success") and options.get("includeRelics", True):
                        check()
                        from ..vision_relics import RelicRecognizer
                        try:
                            result["relicObservation"] = RelicRecognizer().recognize(asset)
                        except Exception:
                            logging.getLogger(__name__).exception("地图已匹配，但同步识别收藏品栏失败")
                            result["relicObservation"] = {"success": False, "slots": [], "acceptedRelicIds": [],
                                "reason": "收藏品栏识别未完成，本次未同步藏品；地图结果仍可确认。"}
                result["assetId"] = options["assetId"]
            else:
                geometry, route_state = route_inputs(state, options.get("areaKey"),
                    pursuit=options.get("pursuit", False), top_n=options.get("topN", 5),
                    planning_goal_ids=options.get("planningGoalIds"), use_item_ids=options.get("useItemIds"))
                if kind == "score":
                    result = RoutePlanner(geometry).score_snapshot(route_state)
                else:
                    route_state["maxStates"] = options.get("maxStates", 50000)
                    count = 0
                    def progress(_):
                        nonlocal count
                        check()
                        count += 1
                        if count % 100 == 0:
                            with self.lock:
                                self.records[job_id]["progress"] = {"expandedStates": count}
                    if options.get("mode", "global") == "advice":
                        from ..decision_advisor import advise
                        result = advise(geometry, route_state, on_expand=progress)
                    else:
                        result = RoutePlanner(geometry).plan(route_state, on_expand=progress)
                        result["mode"] = "global"
                instance = active_instance(state, options.get("areaKey") or state["currentAreaKey"])
                result["goalSummary"] = goal_summary(state)
                result["nodeGoalAnnotations"] = node_goal_annotations(state, instance)
            check()
            finished = {"status": "completed", "result": localize_result(result)}
        except JobCancelled as error:
            finished = {"status": "cancelled", "error": "任务已取消"}
        except Exception as error:
            finished = {"status": "failed", "error": public_error(error), "diagnosticDetail": str(error), "errorType": type(error).__name__}
        finally:
            with self.lock:
                self.records[job_id].update(finished)
                self.records[job_id]["elapsedSeconds"] = round(time.perf_counter() - started, 3)
                self._save(self.records[job_id])
                self.events.pop(job_id, None)
                # Old results stay on disk; keep a bounded in-memory working set.
                for old_id in list(self.records):
                    if len(self.records) <= 64:
                        break
                    if self.records[old_id]["status"] not in {"queued", "running"} and old_id != job_id:
                        del self.records[old_id]

    def close(self):
        with self.lock:
            for event in self.events.values():
                event.set()
        self.pool.shutdown(wait=True, cancel_futures=False)
