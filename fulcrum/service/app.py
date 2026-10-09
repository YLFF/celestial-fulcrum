"""Loopback HTTP boundary for existing Python business modules."""

from contextlib import asynccontextmanager
from copy import deepcopy
import os
from pathlib import Path
import sys
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..goals import goal_summary, node_goal_annotations
from ..ending_prediction import planning_check, require_planning_valid
from ..playtime_state import AREA_SPECS, active_instance, merge_map_observation, merge_resource_observation, merge_action_observation
from ..window_capture import CaptureUnavailable, capture_window, list_windows, select_window
from ..diagnostics import public_error
from ..scoring_profile import PROFILE
from .access import AccessPolicy, local_client
from .assets import AssetStore, MAX_UPLOAD_BYTES
from .catalog import editor_catalog, image_path
from .jobs import JobManager
from .store import ROOT, RevisionConflict, RunStore
from .updates import apply_commands

RESOURCE_OBSERVATION_FIELDS = {"life", "shield", "level", "experience", "hope", "originium_ingot", "action_points"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NewRun(StrictModel):
    runId: str | None = None
    difficulty: int = Field(default=15, ge=0, le=20)
    squadId: str | None = None
    cocoons: dict[str, int] | None = None
    technologyCombatBonuses: dict[str, float | int] | None = None
    lookoutSplitUnlocked: bool = True
    initialOperators: list[dict[str, Any]] | None = None
    initialSupports: list[str] = Field(default_factory=list)
    initialTickets: list[str] = Field(default_factory=list)
    promoteInitialMechanist: bool = False
    investmentBalance: int = Field(default=99, ge=0)
    goals: dict[str, Any] | None = None


class ImportRun(StrictModel):
    state: dict[str, Any]
    runId: str | None = None


class RevisionRequest(StrictModel):
    expectedRevision: int = Field(ge=0)


class PatchRun(RevisionRequest):
    commands: list[dict[str, Any]] = Field(min_length=1, max_length=200)


class RecognizeRequest(RevisionRequest):
    assetId: str
    areaKey: str | None = None
    templateId: str | None = None
    includeResources: bool = True
    resourcesOnly: bool = False


class RelicRecognizeRequest(RevisionRequest):
    assetId: str


class ConfirmRelics(RevisionRequest):
    jobId: str
    relicIds: list[str] = Field(default_factory=list, max_length=100)


class PlanRequest(RevisionRequest):
    areaKey: str | None = None
    pursuit: bool = False
    topN: int = Field(default=PROFILE["search"]["defaultTopN"], ge=1, le=50)
    maxStates: int = Field(default=PROFILE["search"]["defaultMaxStates"], ge=1, le=500000)
    planningGoalIds: list[str] | None = None
    useItemIds: list[str] | None = None


class ConfirmRecognition(RevisionRequest):
    jobId: str
    areaKey: str | None = None
    confirmMap: bool = True
    resourceFields: list[str] = Field(default_factory=lambda: sorted(RESOURCE_OBSERVATION_FIELDS))
    newInstance: bool = False
    initialAreaEntry: bool = False
    entrySandboxRelicIds: list[str] | None = None
    commands: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class CaptureRequest(StrictModel):
    pid: int = Field(ge=1)
    windowId: str
    method: Literal["graphics", "printwindow", "screen"] = "graphics"
    crop: list[int] | None = None
    authorizationId: str


class CaptureAuthorization(StrictModel):
    pid: int = Field(ge=1)
    windowId: str
    consent: bool


class ExampleRequest(StrictModel):
    runId: str | None = None


def create_app(storage_root=None, *, allowed_origins=None):
    from ..compat import configured_app_data, LEGACY_TOKEN_HEADER
    root = Path(storage_root or configured_app_data() or ROOT / "work/app_data").resolve()
    store, assets = RunStore(root / "runs"), AssetStore(root / "images")
    access = AccessPolicy()
    token = access.token
    origins = allowed_origins or ["http://127.0.0.1:8766", "http://localhost:8766", "http://127.0.0.1:5173", "http://localhost:5173"]

    @asynccontextmanager
    async def lifespan(app):
        app.state.jobs = JobManager(root / "jobs", store, assets)
        try:
            yield
        finally:
            app.state.jobs.close()

    from ..product import PROJECT
    app = FastAPI(title=PROJECT["name"], version=PROJECT["version"], lifespan=lifespan,
                  description=f"{PROJECT['englishName']}。本地接口供桌面窗口及开发页面使用。")
    app.state.store, app.state.assets = store, assets
    app.state.access = access
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
                       allow_headers=["Content-Type", "X-Fulcrum-Token", LEGACY_TOKEN_HEADER], expose_headers=["Content-Disposition"])

    @app.middleware("http")
    async def local_boundary(request, call_next):
        host = request.url.hostname
        if not access.valid_host(host) or not local_client(request):
            return JSONResponse({"detail": "服务仅允许本机访问"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin not in origins:
            return JSONResponse({"detail": "当前页面来源未获授权"}, status_code=403)
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) < 0 or int(length) > MAX_UPLOAD_BYTES + 1024 * 1024:
                    return JSONResponse({"detail": "上传内容过大，请缩小图片或文件"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "请求的内容长度不合法"}, status_code=400)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    security = APIKeyHeader(name="X-Fulcrum-Token", auto_error=False)
    def authorize(request: Request, value=Depends(security)):
        if value is None:
            value = request.headers.get(LEGACY_TOKEN_HEADER)
        return access.authorize(request, value)

    def authorize_local(request: Request, scope=Depends(authorize)):
        if scope != "local" or not local_client(request):
            raise HTTPException(403, "native capture requires the local computer")

    auth = [Depends(authorize)]
    local_auth = [Depends(authorize_local)]

    @app.exception_handler(RevisionConflict)
    async def conflict(_, error):
        return JSONResponse({"detail": "对局状态已更新，请刷新页面后重新计算或确认", "diagnosticDetail": str(error)}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def request_invalid(_, error):
        fields = [".".join(str(part) for part in row["loc"] if part != "body") for row in error.errors()]
        return JSONResponse({"detail": "输入格式或数值范围不合法，请检查：" + "、".join(fields),
                             "validationFields": fields}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_, error):
        defaults = {401: "访问授权已失效，请刷新页面重新连接服务",
                    403: "没有此操作的授权，请确认本机访问或截图授权", 404: "找不到所需资源",
                    405: "此接口不支持当前请求方式",
                    503: "当前功能不可用，请检查服务和前端构建状态"}
        detail = error.detail if isinstance(error.detail, str) and any("\u4e00" <= char <= "\u9fff" for char in error.detail) else defaults.get(error.status_code, "请求未完成，请重试")
        return JSONResponse({"detail": detail, "diagnosticDetail": str(error.detail)}, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(ValueError)
    async def invalid(_, error):
        return JSONResponse({"detail": public_error(error), "diagnosticDetail": str(error)}, status_code=422)

    @app.exception_handler(FileNotFoundError)
    async def missing(_, error):
        return JSONResponse({"detail": public_error(error), "diagnosticDetail": str(error)}, status_code=404)

    @app.exception_handler(CaptureUnavailable)
    async def capture_unavailable(_, error):
        return JSONResponse({"detail": public_error(error), "diagnosticDetail": str(error)}, status_code=503)

    def loaded_at_revision(run_id, revision):
        loaded = store.load(run_id)
        if loaded["revision"] != revision:
            raise RevisionConflict("snapshot changed; reload before computing or confirming")
        return loaded

    @app.get("/", include_in_schema=False)
    def index():
        index = ROOT / "frontend/dist/index.html"
        if not index.is_file():
            raise HTTPException(503, "frontend is not built; see /docs")
        return FileResponse(index, media_type="text/html")

    app.mount("/ui-assets", StaticFiles(directory=ROOT / "frontend/dist/ui-assets", check_dir=False), name="ui-assets")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "serviceVersion": PROJECT["version"], "project": dict(PROJECT)}

    @app.get("/api/session")
    def session(request: Request):
        return {"token": token, "header": "X-Fulcrum-Token", "scope": "local"}

    @app.get("/api/capabilities", dependencies=auth)
    def capabilities(request: Request):
        from ..runtime import ocr_available
        return {"snapshotEditing": True, "mapRecognition": True, "resourceOCR": ocr_available(),
                "nodePrediction": True, "routePlanning": True, "scoreBreakdown": True,
                "endingGoalRecording": True, "endingGoalOptionScoring": True, "endingGoalRanking": True, "relicEffectAggregation": False,
                "windowCapture": sys.platform == "win32" and local_client(request), "utopiaRangeRecognition": True,
                "imageUpload": True, "relicRecognition": True,
                "exampleRun": (ROOT / "runs/true-run-001/playtime.json").is_file(),
                "ocrReviewRequired": True, "screenshotIsIntermediate": True}

    @app.get("/api/catalog", dependencies=auth)
    def catalog():
        return editor_catalog()

    @app.get("/api/catalog/{entry_id}/image", dependencies=auth)
    def catalog_image(entry_id: str):
        return FileResponse(image_path(entry_id))

    @app.get("/api/vision-icons/{kind}", dependencies=auth)
    def vision_icon(kind: str):
        if kind not in {"unknown_mystery", "unknown_ferocity"}:
            raise HTTPException(404, "icon not available")
        return FileResponse(ROOT / "assets/vision" / f"{kind}_01.png")

    @app.get("/api/runs", dependencies=auth)
    def runs():
        return {"runs": store.list()}

    def opening_arguments(body):
        from ..opening import SQUAD_NAMES
        from ..recruitment import initial_roster
        if body.squadId not in SQUAD_NAMES:
            raise ValueError("请选择分队")
        if body.promoteInitialMechanist and len(body.initialOperators or []) > 2:
            raise ValueError("初始进阶占用一张招募券，最多再招募两名干员")
        return dict(difficulty=body.difficulty, squad_id=body.squadId, cocoons=body.cocoons,
                    technology_combat_bonuses=body.technologyCombatBonuses,
                    lookout_split_unlocked=body.lookoutSplitUnlocked,
                    initial_operators=initial_roster(body.initialOperators, squad_id=body.squadId, difficulty=body.difficulty),
                    investment_balance=body.investmentBalance, initial_supports=body.initialSupports,
                    initial_tickets=body.initialTickets, promote_initial_mechanist=body.promoteInitialMechanist)

    @app.post("/api/opening/preview", dependencies=auth)
    def opening_preview(body: NewRun):
        from ..opening import build_opening
        args = opening_arguments(body)
        rows = args["initial_operators"]
        base = build_opening(**{**args, "initial_operators": [], "promote_initial_mechanist": False})
        cost = sum(row["hopeCost"] for row in rows) + (2 if body.promoteInitialMechanist else 0)
        if body.promoteInitialMechanist and (body.squadId != "squad_002" or "重装招募券" not in body.initialTickets):
            raise ValueError("初始进阶机械师需要特勤分队和重装招募券")
        return {"operators": rows, "initialHope": base["resources"]["hope"], "hopeCost": cost,
                "remainingHope": base["resources"]["hope"] - cost, "affordable": base["resources"]["hope"] >= cost,
                "resources": base["resources"], "capacity": base["componentBox"]["capacity"]}

    @app.post("/api/runs", dependencies=auth, status_code=201)
    def new_run(body: NewRun):
        from ..playtime_state import new_playtime
        from ..goals import validate_goals
        from uuid import uuid4
        state = new_playtime(body.runId or uuid4().hex, **opening_arguments(body))
        if body.goals is not None:
            validate_goals(body.goals)
            state["goals"].update(body.goals)
        return store.restore(state)

    @app.post("/api/runs/restore", dependencies=auth, status_code=201)
    def restore(body: ImportRun):
        return store.restore(body.state, run_id=body.runId)

    @app.get("/api/examples", dependencies=auth)
    def examples():
        return [{"id": "true-run-001", "name": "N15 多边贸易 · 一层实测"}] if (ROOT / "runs/true-run-001/playtime.json").is_file() else []

    @app.post("/api/examples/{example_id}/restore", dependencies=auth, status_code=201)
    def restore_example(example_id: str, body: ExampleRequest):
        if example_id != "true-run-001":
            raise FileNotFoundError("example not found")
        import json
        from uuid import uuid4
        state = json.loads((ROOT / "runs/true-run-001/playtime.json").read_text(encoding="utf-8"))
        return store.restore(state, run_id=body.runId or f"true-run-ui-{uuid4().hex[:8]}")

    @app.get("/api/runs/{run_id}", dependencies=auth)
    def get_run(run_id: str):
        loaded = store.load(run_id)
        from ..team_status import team_status
        state = loaded["state"]
        thresholds = {}
        for area_key, slot in state["areas"].items():
            instance = next((row for row in slot["instances"] if row["instanceId"] == slot["activeInstanceId"]), None)
            floor = ("I", "II", "III", "IV", "V", "VI").index(area_key.split("-")[0]) + 1
            thresholds[area_key] = team_status(state["operators"], floor, state["opening"].get("squadId"),
                instance.get("strategy", {}).get("scoringOptions", {}) if instance else {})
        return {**loaded, "goalSummary": goal_summary(state), "teamThresholds": thresholds}

    @app.patch("/api/runs/{run_id}", dependencies=auth)
    def patch_run(run_id: str, body: PatchRun):
        movement = any(command.get("type") in {"position", "currentArea"} for command in body.commands)
        return store.update(run_id, body.expectedRevision, lambda draft: apply_commands(draft, body.commands), map_update=movement)

    @app.post("/api/runs/{run_id}/undo", dependencies=auth)
    def undo(run_id: str, body: RevisionRequest):
        return store.undo(run_id, body.expectedRevision)

    @app.post("/api/runs/{run_id}/redo", dependencies=auth)
    def redo(run_id: str, body: RevisionRequest):
        return store.redo(run_id, body.expectedRevision)

    @app.get("/api/runs/{run_id}/markdown", dependencies=auth)
    def markdown(run_id: str):
        return PlainTextResponse(store.markdown(run_id), media_type="text/markdown")

    @app.get("/api/runs/{run_id}/maps/{area_key}", dependencies=auth)
    def current_map(run_id: str, area_key: str):
        loaded = store.load(run_id)
        instance = active_instance(loaded["state"], area_key)
        return {"runId": run_id, "revision": loaded["revision"], "instance": instance,
                "encounterPool": loaded["state"]["areas"][area_key]["encounterPool"],
                "goalAnnotations": node_goal_annotations(loaded["state"], instance)}

    @app.post("/api/images", dependencies=auth, status_code=201)
    async def upload(file: UploadFile = File(...)):
        try:
            payload = await file.read(MAX_UPLOAD_BYTES + 1)
        finally:
            await file.close()
        return assets.save(payload, source={"kind": "upload", "filename": Path(file.filename or "screenshot").name})

    @app.get("/api/images/{asset_id}", dependencies=auth)
    def image(asset_id: str):
        assets.load(asset_id)
        return FileResponse(assets.path(asset_id), media_type="image/png")

    @app.get("/api/capture/windows", dependencies=local_auth)
    def windows(pid: int | None = None):
        return {"windows": list_windows(pid)}

    @app.post("/api/capture/authorize", dependencies=local_auth)
    def authorize_capture(body: CaptureAuthorization):
        if not body.consent:
            raise HTTPException(403, "explicit capture consent is required")
        select_window(body.pid, body.windowId)
        return access.grant_capture(body.pid, body.windowId)

    @app.post("/api/capture/revoke", dependencies=local_auth)
    def revoke_capture(body: dict[str, str]):
        access.revoke_capture(body.get("authorizationId"))
        return {"revoked": True}

    @app.post("/api/capture", dependencies=local_auth, status_code=201)
    def capture(body: CaptureRequest):
        access.check_capture(body.authorizationId, body.pid, body.windowId)
        result = capture_window(body.pid, body.windowId, method=body.method, crop=body.crop)
        return assets.save(result["image"], source={"kind": "window", "window": result["window"],
                            "method": result["method"], "crop": body.crop, "warnings": result["warnings"]})

    @app.post("/api/runs/{run_id}/jobs/recognize", dependencies=auth, status_code=202)
    def recognize(run_id: str, body: RecognizeRequest):
        return app.state.jobs.submit("recognize", loaded_at_revision(run_id, body.expectedRevision),
                                     body.model_dump(exclude={"expectedRevision"}))

    @app.post("/api/runs/{run_id}/jobs/recognize-relics", dependencies=auth, status_code=202)
    def recognize_relics(run_id: str, body: RelicRecognizeRequest):
        return app.state.jobs.submit("recognize-relics", loaded_at_revision(run_id, body.expectedRevision),
                                     body.model_dump(exclude={"expectedRevision"}))

    @app.post("/api/runs/{run_id}/confirm-relics", dependencies=auth)
    def confirm_relics(run_id: str, body: ConfirmRelics):
        job = app.state.jobs.get(body.jobId)
        if job["runId"] != run_id or job["kind"] != "recognize-relics" or job["status"] != "completed":
            raise ValueError("select a completed relic recognition job for this run")
        if job["sourceRevision"] != body.expectedRevision or job["stale"]:
            raise RevisionConflict("relic recognition is stale; recognize again")
        if not job["result"].get("success"):
            raise ValueError("relic row was not located")
        candidates = {row["id"] for slot in job["result"]["slots"] for row in slot["candidates"]}
        if not set(body.relicIds) <= candidates:
            raise ValueError("selected relic is not a recognition candidate")

        def merge(draft):
            rows = deepcopy(draft["relics"])
            held = {row["id"] for row in rows}
            for relic_id in body.relicIds:
                if relic_id not in held:
                    rows.append({"id": relic_id, "count": 1})
                    held.add(relic_id)
            apply_commands(draft, [{"type": "relics", "items": rows}])

        return store.update(run_id, body.expectedRevision, merge)

    @app.post("/api/runs/{run_id}/jobs/plan", dependencies=auth, status_code=202)
    def plan(run_id: str, body: PlanRequest):
        loaded = loaded_at_revision(run_id, body.expectedRevision)
        require_planning_valid(loaded["state"], active_instance(loaded["state"], body.areaKey or loaded["state"]["currentAreaKey"]))
        return app.state.jobs.submit("plan", loaded,
                                     body.model_dump(exclude={"expectedRevision"}))

    @app.post("/api/runs/{run_id}/planning-check", dependencies=auth)
    def check_plan(run_id: str, body: PlanRequest):
        loaded = loaded_at_revision(run_id, body.expectedRevision)
        return planning_check(loaded["state"], active_instance(loaded["state"], body.areaKey or loaded["state"]["currentAreaKey"]))

    @app.post("/api/runs/{run_id}/jobs/score", dependencies=auth, status_code=202)
    def score(run_id: str, body: PlanRequest):
        return app.state.jobs.submit("score", loaded_at_revision(run_id, body.expectedRevision),
                                     body.model_dump(exclude={"expectedRevision"}))

    @app.get("/api/jobs/{job_id}", dependencies=auth)
    def job(job_id: str):
        return app.state.jobs.get(job_id)

    @app.post("/api/jobs/{job_id}/cancel", dependencies=auth)
    def cancel(job_id: str):
        return app.state.jobs.cancel(job_id)

    @app.post("/api/runs/{run_id}/confirm-recognition", dependencies=auth)
    def confirm(run_id: str, body: ConfirmRecognition):
        job = app.state.jobs.get(body.jobId)
        if job["runId"] != run_id or job["kind"] != "recognize" or job["status"] != "completed":
            raise ValueError("select a completed recognition job for this run")
        if job["sourceRevision"] != body.expectedRevision or job["stale"]:
            raise RevisionConflict("recognition was computed on an older snapshot; recognize again")
        observation = deepcopy(job["result"])
        if any(command.get("type") == "dystopia" for command in body.commands):
            # Apply the user's reviewed coverage once, not the unreviewed candidate first.
            observation.pop("dystopiaObservation", None)
        area_key = body.areaKey or job["options"].get("areaKey")
        if not area_key and observation.get("floor") and observation.get("area") != "treehole":
            area_key = list(AREA_SPECS)[0] if observation["floor"] == 1 else {2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI"}[observation["floor"]]
        requested = job["options"].get("areaKey")
        if requested and area_key != requested:
            raise ValueError("confirmed area must match recognition request")
        if body.confirmMap and not observation.get("success"):
            raise ValueError("map recognition is unresolved; review template or confirm resources only")
        if body.confirmMap and area_key not in AREA_SPECS:
            raise ValueError("choose an area key, including the treehole parent floor")
        if set(body.resourceFields) - RESOURCE_OBSERVATION_FIELDS:
            raise ValueError("unsupported resource observation field")
        resource = deepcopy(observation.get("resourceObservation") or {})
        resource["fields"] = {key: value for key, value in resource.get("fields", {}).items() if key in body.resourceFields}
        observation["resourceObservation"] = None
        def mutate(draft):
            instance = None
            if body.confirmMap:
                instance = merge_map_observation(draft, area_key, observation, new_instance=body.newInstance,
                    initial_area_entry=body.initialAreaEntry, entry_sandbox_relic_ids=body.entrySandboxRelicIds)
                instance["sourceScreenshot"] = str(assets.path(job["options"]["assetId"]))
                instance["sourceAssetId"] = job["options"]["assetId"]
            merge_resource_observation(draft, resource)
            if not body.initialAreaEntry and area_key:
                instance = instance or active_instance(draft, area_key)
                merge_action_observation(instance, resource)
            if body.commands:
                apply_commands(draft, body.commands)
            else:
                from ..playtime_state import rebuild_derived
                rebuild_derived(draft)
        return store.update(run_id, body.expectedRevision, mutate, map_update=body.confirmMap)

    return app
