"""Dystopia HUD, source-based coverage, and fertile-soil visual evidence."""

from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from .vision_geometry import Circle
from .vision_icons import IconMatcher, node_patch
from .image_io import read_image

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "assets/vision/dystopia"


@lru_cache(maxsize=1)
def textures():
    return [(path.stem.rsplit("_", 1)[0], read_image(path, cv2.IMREAD_UNCHANGED))
            for path in sorted(SAMPLES.glob("*.png"))]


@lru_cache(maxsize=1)
def clean_textures():
    return [(path.stem.rsplit("_", 1)[0], read_image(path, cv2.IMREAD_UNCHANGED))
            for path in sorted((SAMPLES / "clean").glob("*.png"))]


@lru_cache(maxsize=1)
def soil_textures():
    return [(path.stem.rsplit("_", 1)[0], read_image(path, cv2.IMREAD_UNCHANGED))
            for path in sorted((SAMPLES / "soil").glob("*.png"))]


@lru_cache(maxsize=1)
def _soil_gray_textures():
    return [(kind, np.dstack((cv2.cvtColor(cv2.cvtColor(icon[:, :, :3], cv2.COLOR_BGR2GRAY),
                                         cv2.COLOR_GRAY2BGR), icon[:, :, 3]))) for kind, icon in soil_textures()]


def soil_texture_scores(image, pixel, step, category=None):
    x, y = map(round, pixel)
    radius = max(55, round(step * .6))
    left, top = max(0, x-radius), max(0, y-radius)
    patch = image[top:y+radius, left:x+radius]
    gray = cv2.cvtColor(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    scales = tuple(step/100 * factor for factor in (.8, .9, 1, 1.1, 1.2))
    return [(kind, IconMatcher._score(gray, (x-left, y-top), step, icon, scales, search_fraction=.08))
            for kind, icon in _soil_gray_textures() if category is None or kind == category]


def recognize_header(image):
    height, width = image.shape[:2]
    x0, y0, x1, y1 = round(width*.34), 0, round(width*.54), round(height*.13)
    patch = image[y0:y1, x0:x1]
    candidates = []
    for index in range(1, 11):
        icon = read_image(ROOT / f"assets/lubiao/dystopia/dystopia_{index:03}.png")
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
        return {"status": "absent_or_unresolved", "active": None,
                "headerCandidates": [{"id": f"dystopia_{row[0]:03}", "score": round(row[1], 4)}
                                     for row in candidates[:3]]}
    index, score, center, side = candidates[0]
    policy_scores = []
    anchor = (center[0]+side*.56, center[1]+side*.68)
    for policy in range(11, 15):
        icon = read_image(ROOT / f"assets/lubiao/dystopia/dystopia_{policy:03}.png")
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
    jobs = [(icon, factor) for kind, icon in textures() if kind == "node_type_020" for factor in (.8, 1., 1.2)]
    def locate(job):
        icon, factor = job
        template = cv2.resize(icon, None, fx=factor, fy=factor)
        side = template.shape[0]
        scores = cv2.matchTemplate(patch, template[:,:,:3], cv2.TM_CCOEFF_NORMED, mask=template[:,:,3])
        scores[~np.isfinite(scores)] = -1
        peaks = (scores >= .82) & (scores >= cv2.dilate(scores, np.ones((19, 19), np.uint8)))
        return [Circle(x+side/2+x0, y+side/2+y0, side*.25) for y, x in zip(*np.where(peaks))]
    with ThreadPoolExecutor(max_workers=3) as workers:
        for found in workers.map(locate, jobs):
            for circle in found:
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
    for kind, score in soil_texture_scores(image, pixel, step):
        scores[kind] = max(score, scores.get(kind, -1))
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def crack_evidence(image, pixel, step):
    local = node_patch(image, pixel, step, target_step=100, radius_fraction=.80)
    if local is None:
        return {"radialFraction": 0., "sectors": 0}
    patch, (x, y), spacing = local
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    gx, gy = cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    yy, xx = np.ogrid[:gray.shape[0], :gray.shape[1]]
    dx, dy = xx-x, yy-y
    radius = np.hypot(dx, dy)
    annulus = (radius >= .32*spacing) & (radius <= .67*spacing)
    magnitude = np.hypot(gx, gy)
    if not np.any(annulus):
        return {"radialFraction": 0., "sectors": 0}
    edges = annulus & (magnitude >= max(40., np.percentile(magnitude[annulus], 80)))
    # Crack edges point outwards; concentric ripple edges point around the node.
    normal = np.abs(gx*dx+gy*dy)/np.maximum(1., magnitude*radius)
    radial = edges & (normal < .55)
    sectors = ((np.arctan2(dy, dx)+np.pi)*6/np.pi).astype(int) % 12
    counts = np.bincount(sectors[radial], minlength=12)
    return {"radialFraction": round(float(radial.sum()/max(1, edges.sum())), 3),
            "sectors": int(np.count_nonzero(counts >= 4))}


def source_score(image, pixel, step, *, grayscale=False):
    if grayscale:
        image = cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    scores = []
    for kind, icon in textures():
        if kind != "ideal_source":
            continue
        if grayscale:
            color = cv2.cvtColor(cv2.cvtColor(icon[:, :, :3], cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
            icon = np.dstack((color, icon[:, :, 3]))
        scores.append(IconMatcher._score(image, pixel, step, icon,
            tuple(step/100*factor for factor in (.8, 1., 1.2, 1.4, 1.65)),
            search_fraction=.12, radius_fraction=.95))
    return max(scores, default=-1.)


def recognize_nodes(image, nodes, step, observation, difficulty=15, *, original_image=None, image_scale=1.):
    header_uncertain = not observation.get("active")
    header_hints = observation.get("headerCandidates", [])
    if header_uncertain and (not header_hints or header_hints[0]["score"] < .45
                             or header_hints[0]["id"] == "dystopia_008"):
        return observation
    if observation.get("ideologyId") == "dystopia_008":
        return recognize_visual_nodes(image, nodes, step, observation)
    radius = 3 if difficulty >= 12 else 2
    sources = []
    for node in nodes:
        confirmed = node.category_id in {"node_type_002", "unknown_ferocity"}
        possible = node.category_id is None and any(row["id"] in {"node_type_002", "unknown_ferocity"}
                                                   and row["score"] >= .35 for row in node.category_candidates)
        if not confirmed and not possible:
            continue
        score = source_score(image, node.pixel, step)
        sources.append({"nodeId": node.coord.key, "score": round(score, 4), "categoryConfirmed": confirmed})
    sources.sort(key=lambda row: row["score"], reverse=True)
    source = None
    if (sources and sources[0]["categoryConfirmed"] and not header_uncertain and sources[0]["score"] >= .60
            and (len(sources) == 1 or sources[0]["score"]-sources[1]["score"] >= .08)):
        source = next(node for node in nodes if node.coord.key == sources[0]["nodeId"])
    if source is None and original_image is not None:
        by_id = {node.coord.key: node for node in nodes}
        for row in sources[:3]:
            node = by_id[row["nodeId"]]
            pixel = tuple(value/image_scale for value in node.pixel)
            local = node_patch(original_image, pixel, step/image_scale, radius_fraction=.95)
            if local is None:
                continue
            patch, anchor, spacing = local
            color = source_score(patch, anchor, spacing)
            gray = source_score(patch, anchor, spacing, grayscale=True)
            cracks = crack_evidence(patch, anchor, spacing)
            row.update(originalScore=round(color, 4), grayScore=round(gray, 4), cracks=cracks)
            if cracks["radialFraction"] >= .45 and cracks["sectors"] >= 6:
                row["refinedScore"] = round(max(color, gray), 4)
        refined = sorted(sources, key=lambda row: row.get("refinedScore", -1), reverse=True)
        if refined:
            best = refined[0]
            minimum = .78 if header_uncertain else .72
            second = max((max(row["score"], row.get("refinedScore", -1)) for row in refined[1:]), default=-1)
            if best.get("refinedScore", -1) >= minimum and best["refinedScore"]-second >= .10:
                source = by_id[best["nodeId"]]
    if source and header_uncertain:
        observation = {**observation, "active": True, "status": "candidate", "presenceSource": "ideal_source_cracks"}
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
    evidence = {}
    normal_icons = IconMatcher()
    for node in nodes:
        kind = "node_type_020" if node.category_id == "start" else node.category_id
        scores = soil_texture_scores(image, node.pixel, step, kind)
        best_kind, best_score = max(scores, key=lambda row: row[1], default=(kind, -1))
        scales = (.55, .65, .75, .85, 1, 1.15, 1.3, 1.45, 1.6, 1.8, 2)
        if best_kind == "node_type_020":
            clean_score = normal_icons._empty_score(image, node.pixel, [])
        else:
            clean_score = max((normal_icons._score(image, node.pixel, step, icon, scales)
                               for kind, icon in normal_icons.node_templates if kind == best_kind), default=-1)
            clean_score = max(clean_score, max((normal_icons._score(image, node.pixel, step, icon,
                tuple(step/100 * factor for factor in (.7, .85, 1, 1.15, 1.3)))
                for kind, icon in clean_textures() if kind == best_kind), default=-1))
        affected = True if best_score >= .9 and best_score-clean_score >= .06 else None
        if kind == "node_type_020" and best_score >= .82:
            affected = True
        if affected is not True and scores and clean_score >= .72 and clean_score-best_score >= .015:
            affected = False
        if scores and clean_score >= .65 and best_score < .84:
            affected = False
        if not scores and clean_score >= .90:
            affected = False
        evidence[node.coord.key] = {"affected": affected, "textureScore": round(best_score, 4),
                                    "textureCategoryId": best_kind, "cleanScore": round(clean_score, 4),
                                    "method": "soil_echo_texture"}
    refine_soil_references(image, nodes, step, evidence)
    return {**observation, "affectedNodeIds": [key for key, value in evidence.items() if value["affected"]],
            "nodeEvidence": evidence, "idealSourceCandidates": [], "sourceStatus": "not_applicable",
            "coverageMethod": "soil_echo_texture"}


def soil_boundary_evidence(image, pixel, step):
    angles = np.linspace(0, 2*np.pi, 16, endpoint=False)
    radii = np.linspace(.40, .73, 16)*step
    xs = np.rint(pixel[0]+np.cos(angles)[:, None]*radii).astype(int)
    ys = np.rint(pixel[1]+np.sin(angles)[:, None]*radii).astype(int)
    if xs.min() < 0 or ys.min() < 0 or xs.max() >= image.shape[1] or ys.max() >= image.shape[0]:
        return None
    colors = image[ys, xs]
    hsv = cv2.cvtColor(colors, cv2.COLOR_BGR2HSV)
    values = hsv[:, :, 2].astype(float)
    # A pale, sharp local rim is only a boundary hint, not proof of which side is covered.
    prominence = values[:, 1:-1]-(values[:, :-2]+values[:, 2:])/2
    peaks = (prominence > 14) & (hsv[:, 1:-1, 1] < 100) & (values[:, 1:-1] > 45)
    return int(np.count_nonzero(np.any(peaks, axis=1)))


def refine_soil_references(image, nodes, step, evidence):
    """Use corroborated same-map appearances; never fill across gaps in the shadow."""
    patches, groups = {}, {}
    for node in nodes:
        kind = "node_type_020" if node.category_id == "start" else node.category_id
        row = evidence[node.coord.key]
        row["boundaryRays"] = soil_boundary_evidence(image, node.pixel, step)
        if kind is None:
            continue
        local = node_patch(image, node.pixel, step, target_step=100, radius_fraction=.55)
        if local is None:
            continue
        patch, anchor, spacing = local
        x, y = anchor
        radius = round(spacing*.48)
        left, top = round(x-radius), round(y-radius)
        cut = patch[max(0, top):round(y+radius), max(0, left):round(x+radius)]
        if left < 0 or top < 0 or cut.shape[:2] != (2*radius, 2*radius):
            continue
        gray = cv2.cvtColor(cut, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (80, 80), interpolation=cv2.INTER_AREA)
        patches[node.coord.key] = gray
        reliable = (row["affected"] is True and row["textureScore"] >= .90
                    or row["affected"] is False and row["cleanScore"] >= .85 and row["textureScore"] < .84)
        if reliable:
            groups.setdefault((kind, row["affected"]), []).append(node.coord.key)
    for node in nodes:
        key, kind = node.coord.key, node.category_id
        row = evidence[key]
        if row["affected"] is not None or key not in patches:
            continue
        scores = {}
        for affected in (True, False):
            references = groups.get((kind, affected), [])
            if len(references) < 2:
                continue
            ranked = []
            for reference in references:
                value = float(cv2.matchTemplate(patches[key], patches[reference], cv2.TM_CCOEFF_NORMED)[0, 0])
                if np.isfinite(value):
                    ranked.append((value, reference))
            ranked.sort(reverse=True)
            if len(ranked) >= 2:
                scores[affected] = (ranked[1][0], [item[1] for item in ranked[:2]])
        row["referenceScores"] = {str(affected).lower(): round(value[0], 4) for affected, value in scores.items()}
        if len(scores) != 2:
            continue
        best = max(scores, key=lambda affected: scores[affected][0])
        score = scores[best][0]
        minimum = .95 if (row["boundaryRays"] or 0) >= 4 else .90
        if score >= minimum and score-scores[not best][0] >= .10:
            row.update(affected=best, method="soil_same_map_reference", referenceNodeIds=scores[best][1])
