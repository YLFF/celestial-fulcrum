"""Actual HTTP screenshot -> confirmation -> score/route smoke; copies the fixture."""

import argparse
import json
from pathlib import Path
import time
from uuid import uuid4
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fulcrum.playtime_route import route_inputs
from fulcrum.route_planner import RoutePlanner

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    parser.add_argument("--output", default=str(ROOT / "work/service_smoke/report.json"))
    args = parser.parse_args()
    fixture = json.loads((ROOT / "runs/true-run-001/playtime.json").read_text(encoding="utf-8"))
    run_id = "service-smoke-" + uuid4().hex[:12]
    with httpx.Client(base_url=args.url, timeout=15, trust_env=False) as client:
        response = client.get("/api/session")
        response.raise_for_status()
        client.headers["X-Fulcrum-Token"] = response.json()["token"]
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        def wait(job):
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                job = request("GET", f"/api/jobs/{job['jobId']}")
                if job["status"] not in {"queued", "running"}:
                    if job["status"] != "completed":
                        raise RuntimeError(job)
                    return job
                time.sleep(.25)
            raise TimeoutError("job did not finish")
        loaded = request("POST", "/api/runs/restore", json={"state": fixture, "runId": run_id})
        screenshot = ROOT / "samples/true_run_map/run1_floor1_state0.jpg"
        uploaded = request("POST", "/api/images", files={"file": (screenshot.name, screenshot.read_bytes(), "image/jpeg")})
        recognized = wait(request("POST", f"/api/runs/{run_id}/jobs/recognize", json={
            "expectedRevision": loaded["revision"], "assetId": uploaded["assetId"], "areaKey": "I", "includeResources": True}))
        result = recognized["result"]
        assert result["success"], result
        expected_instance = fixture["areas"]["I"]["instances"][0]
        assert result["templateId"] == expected_instance["templateId"], result["templateId"]
        assert request("GET", f"/api/runs/{run_id}")["state"] == loaded["state"]
        confirmed = request("POST", f"/api/runs/{run_id}/confirm-recognition", json={
            "expectedRevision": loaded["revision"], "jobId": recognized["jobId"], "areaKey": "I",
            "commands": [{"type": "resources", "values": {"hope": 0}}]})
        revision = confirmed["revision"]
        map_data = request("GET", f"/api/runs/{run_id}/maps/I")
        score = wait(request("POST", f"/api/runs/{run_id}/jobs/score", json={"expectedRevision": revision}))
        routes = {}
        for pursuit in (False, True):
            job = wait(request("POST", f"/api/runs/{run_id}/jobs/plan", json={
                "expectedRevision": revision, "pursuit": pursuit, "topN": 3, "maxStates": 50000}))
            planning = job["result"]
            geometry, route_state = route_inputs(confirmed["state"], pursuit=pursuit, top_n=3)
            route_state["maxStates"] = 50000
            reference = RoutePlanner(geometry).plan(route_state)
            assert planning["routes"][0]["metrics"]["weightedValue"] == reference["routes"][0]["metrics"]["weightedValue"], (planning["routes"][0], reference["routes"][0])
            routes["pursuit" if pursuit else "no-pursuit"] = {"elapsedSeconds": job["elapsedSeconds"], "expandedStates": planning["expandedStates"],
                "searchComplete": planning["searchComplete"], "topScore": planning["routes"][0]["metrics"]["weightedValue"]}
        assert request("GET", f"/api/runs/{run_id}")["state"] == confirmed["state"]
        report = {"runId": run_id, "revision": revision, "templateId": result["templateId"], "nodeCount": len(result["nodes"]),
                  "recognitionSeconds": recognized["elapsedSeconds"], "resourceObservation": result.get("resourceObservation"),
                  "playerPosition": map_data["instance"]["playerPosition"], "actionPoints": map_data["instance"]["actionPoints"],
                  "scoredNodes": len(score["result"]["nodeValues"]), "routes": routes,
                  "searchDidNotMutatePlaytime": True, "fixtureWasCopied": True,
                  "manualCorrections": {"hope": 0}}
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "resourceObservation"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
