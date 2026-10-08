"""Dystopia HUD, source-based coverage, and fertile-soil visual evidence."""

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .vision_geometry import Circle
from .vision_icons import IconMatcher

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "assets/vision/dystopia"


@lru_cache(maxsize=1)
def textures():
    return [(path.stem.rsplit("_", 1)[0], cv2.imread(str(path), cv2.IMREAD_UNCHANGED))
            for path in sorted(SAMPLES.glob("*.png"))]


@lru_cache(maxsize=1)
def clean_textures():
    return [(path.stem.rsplit("_", 1)[0], cv2.imread(str(path), cv2.IMREAD_UNCHANGED))
            for path in sorted((SAMPLES / "clean").glob("*.png"))]


def recognize_header(image):
    height, width = image.shape[:2]
    x0, y0, x1, y1 = round(width*.34), 0, round(width*.54), round(height*.13)
    patch = image[y0:y1, x0:x1]
    candidates = []
    for index in range(1, 11):
        icon = cv2.imread(str(ROOT / f"assets/lubiao/dystopia/dystopia_{index:03}.png"))
        if icon is None:
            continue
        best = (-1, None, None)
        for side in sorted({max(12, round(size*width/1280)) for size in range(24, 51, 2)}):
            template = cv2.resize(icon, (side, side))
            scores = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(scores)
            if score > best[0]:
                best = score, (x0+location[0]+side/2, location[1]+side/2), side
        candidates.append((index, *best))
    candidates.sort(key=lambda item: item[1], reverse=True)
    if not candidates or candidates[0][1] < .60 or candidates[0][1]-candidates[1][1] < .06:
        return {"status": "absent_or_unresolved", "active": None}
    index, score, center, side = candidates[0]
    policy_scores = []
    anchor = (center[0]+side*.56, center[1]+side*.68)
    for policy in range(11, 15):
        icon = cv2.imread(str(ROOT / f"assets/lubiao/dystopia/dystopia_{policy:03}.png"))
        value = IconMatcher._score(image, anchor, side, icon,
                                  tuple(size*width/1280/max(icon.shape[:2]) for size in range(12, 29, 2)),
                                  search_fraction=.22, radius_fraction=.6)
        policy_scores.append((policy, value))
    policy_scores.sort(key=lambda item: item[1], reverse=True)
    policy = policy_scores[0][0] if (policy_scores[0][1] >= .60 and
                                  policy_scores[0][1]-policy_scores[1][1] >= .06) else None
    return {"status": "candidate", "active": True, "ideologyId": f"dystopia_{index:03}",
            "policyId": f"dystopia_{policy:03}" if policy else None,
            "score": round(score, 4), "policyScore": round(policy_scores[0][1], 4),
            "headerPixel": list(center), "affectedNodeIds": [], "idealSourceNodeId": None,
            "nodeEvidence": {}, "sourceStatus": "not_applicable" if index == 8 else "unresolved"}


def connector_evidence(image, viewport):
    x0, y0, x1, y1 = viewport
    patch = image[y0:y1, x0:x1]
    circles = []
    for kind, icon in textures():
        if kind != "node_type_020":
            continue
        for factor in (.8, 1.0, 1.2):
            template = cv2.resize(icon, None, fx=factor, fy=factor)
            side = template.shape[0]
            scores = cv2.matchTemplate(patch, template[:,:,:3], cv2.TM_CCOEFF_NORMED, mask=template[:,:,3])
            scores[~np.isfinite(scores)] = -1
            peaks = (scores >= .82) & (scores >= cv2.dilate(scores, np.ones((19, 19), np.uint8)))
            for y, x in zip(*np.where(peaks)):
                circle = Circle(x+side/2+x0, y+side/2+y0, side*.25)
                if all(np.hypot(circle.x-old.x, circle.y-old.y) >= 12 for old in circles):
                    circles.append(circle)
    return circles


def classify_texture(image, pixel, step):
    scores = {}
    for kind, icon in textures():
        if kind == "ideal_source":
            continue
        scales = tuple(step/100 * relative for relative in (.7, .85, 1, 1.15, 1.3))
        score = IconMatcher._score(image, pixel, step, icon, scales, search_fraction=.09)
        scores[kind] = max(score, scores.get(kind, -1))
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def recognize_nodes(image, nodes, step, observation, difficulty=15):
    if not observation.get("active"):
        return observation
    if observation.get("ideologyId") == "dystopia_008":
        return recognize_visual_nodes(image, nodes, step, observation)
    radius = 3 if difficulty >= 12 else 2
    sources = []
    for node in nodes:
        if node.category_id not in {"node_type_002", "unknown_ferocity"}:
            continue
        score = max((IconMatcher._score(image, node.pixel, step, icon,
                    tuple(step/100 * factor for factor in (.8, 1, 1.2, 1.4, 1.65)),
                    search_fraction=.12, radius_fraction=.95)
                    for kind, icon in textures() if kind == "ideal_source"), default=-1)
        sources.append({"nodeId": node.coord.key, "score": round(score, 4)})
    sources.sort(key=lambda row: row["score"], reverse=True)
    source = None
    if sources and sources[0]["score"] >= .60 and (len(sources) == 1 or sources[0]["score"]-sources[1]["score"] >= .08):
        source = next(node for node in nodes if node.coord.key == sources[0]["nodeId"])
    evidence = {}
    for node in nodes:
        distance = abs(node.coord.x-source.coord.x)+abs(node.coord.y-source.coord.y) if source else None
        evidence[node.coord.key] = {"affected": distance <= radius if distance is not None else None,
                                   "sourceDistance": distance, "method": "source_manhattan_rule"}
    return {**observation, "nodeEvidence": evidence,
            "affectedNodeIds": [key for key, row in evidence.items() if row["affected"]],
            "idealSourceCandidates": sources, "idealSourceNodeId": source.coord.key if source else None,
            "sourceStatus": "candidate" if source else "unresolved", "coverageRadius": radius,
            "coverageMethod": "source_manhattan_rule", "difficulty": difficulty}


def recognize_visual_nodes(image, nodes, step, observation):
    if not observation.get("active"):
        return observation
    evidence, sources = {}, []
    normal_icons = IconMatcher()
    for node in nodes:
        ranked = classify_texture(image, node.pixel, step)
        best_kind, best_score = ranked[0]
        scales = (.55, .65, .75, .85, 1, 1.15, 1.3, 1.45, 1.6, 1.8, 2)
        if best_kind == "node_type_020":
            clean_score = normal_icons._empty_score(image, node.pixel, [])
        else:
            clean_score = max((normal_icons._score(image, node.pixel, step, icon, scales)
                               for kind, icon in normal_icons.node_templates if kind == best_kind), default=-1)
            clean_score = max(clean_score, max((normal_icons._score(image, node.pixel, step, icon,
                tuple(step/100 * factor for factor in (.7, .85, 1, 1.15, 1.3)))
                for kind, icon in clean_textures() if kind == best_kind), default=-1))
        affected = True if best_score >= .86 and best_score-clean_score >= .025 else None
        if clean_score >= .72 and clean_score-best_score >= .015:
            affected = False
        if node.category_id not in {"start", best_kind}:
            observed_clean = max((normal_icons._score(image, node.pixel, step, icon, scales)
                                 for kind, icon in normal_icons.node_templates if kind == node.category_id), default=-1)
            observed_clean = max(observed_clean, max((normal_icons._score(image, node.pixel, step, icon,
                tuple(step/100 * factor for factor in (.7, .85, 1, 1.15, 1.3)))
                for kind, icon in clean_textures() if kind == node.category_id), default=-1))
            if observed_clean >= .80 and observed_clean-best_score >= .04:
                affected = False
        evidence[node.coord.key] = {"affected": affected, "textureScore": round(best_score, 4),
                                    "textureCategoryId": best_kind, "cleanScore": round(clean_score, 4)}
        if observation["ideologyId"] == "dystopia_008" or node.category_id not in {"node_type_002", "unknown_ferocity"}:
            continue
        score = max(IconMatcher._score(image, node.pixel, step, icon,
                    tuple(step/100 * factor for factor in (.8, 1, 1.2, 1.4, 1.65)),
                    search_fraction=.12, radius_fraction=.95)
                    for kind, icon in textures() if kind == "ideal_source")
        sources.append({"nodeId": node.coord.key, "score": round(score, 4)})
    sources.sort(key=lambda item: item["score"], reverse=True)
    result = {**observation, "affectedNodeIds": [key for key, value in evidence.items() if value["affected"]],
              "nodeEvidence": evidence, "idealSourceCandidates": sources}
    if sources and sources[0]["score"] >= .60 and (len(sources) == 1 or sources[0]["score"]-sources[1]["score"] >= .08):
        result.update(idealSourceNodeId=sources[0]["nodeId"], sourceStatus="candidate")
        if sources[0]["nodeId"] not in result["affectedNodeIds"]:
            result["affectedNodeIds"].append(sources[0]["nodeId"])
        evidence[sources[0]["nodeId"]]["affected"] = True
    return result
