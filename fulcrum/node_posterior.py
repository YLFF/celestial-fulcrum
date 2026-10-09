"""Apply the count-prior beta only where its ordinary-family model is supported."""

from collections import Counter
from copy import deepcopy
from functools import lru_cache

from .node_prediction_beta import FamilyModel, Slot, max_entropy
from .node_predictor import (
    CATEGORY_TO_TYPE, FEROCITY_TYPES, MYSTERY_TYPES, TYPE_TO_CATEGORY,
    _catalogs, _count_bounds, predict_instance,
)


@lru_cache(maxsize=32)
def _model(slots_key, priors_key):
    return FamilyModel([Slot(key, dict(weights)) for key, weights in slots_key],
                       {key: dict(rows) for key, rows in priors_key}, state_limit=100_000)


def _family_posterior(instance, family, *, placements=None):
    data, _, templates = _catalogs()
    template = templates.get(instance["templateId"])
    if template is None or {tuple(node["slot"]) for node in instance["nodes"].values()} != {
            tuple(slot) for slot in template["occupiedSlots"]}:
        raise ValueError("地图实例未覆盖完整模板，保留兼容估算")
    area = instance["areaKey"]
    sample_index = "remembrance" if area == "IV-remembrance" else str(("I", "II", "III", "IV", "V").index(area))
    index = data["floors"].index("IV追忆" if area == "IV-remembrance" else area)
    samples = data["distanceSamples"].get("start", {}).get(sample_index, {})
    map_count = sum(samples.values())
    if not map_count:
        raise ValueError("该层缺少用于估计节点数量的完整对局样本")
    ordinary = (*MYSTERY_TYPES, "danger-path") if family == "unknown_mystery" else (*FEROCITY_TYPES, "settlement")
    categories = {TYPE_TO_CATEGORY[name] for name in ordinary}
    skeleton, known, ids = deepcopy(instance), {}, []
    for node_id, node in skeleton["nodes"].items():
        category = node.get("resolvedCategoryId") or node.get("observedCategoryId")
        if category not in categories and category != family:
            continue
        ids.append(node_id)
        if category in categories:
            known[node_id] = CATEGORY_TO_TYPE[category]
        node["resolvedCategoryId"] = None
        node["observedCategoryId"] = family
    prediction = predict_instance(skeleton)
    candidates = {key: prediction["unknownNodes"].get(key, {}).get("candidates", []) for key in ids}
    names = sorted({row["nodeType"] for rows in candidates.values() for row in rows} | set(known.values()))
    priors, summaries = {}, {}
    for name in names:
        bounds = _count_bounds(data["countRanges"][name][index])
        if bounds is None:
            raise ValueError(f"{name} 缺少数量范围")
        counts = data["distanceSamples"].get(name, {}).get(sample_index, {})
        if not counts:
            raise ValueError(f"{name} 缺少数量统计样本")
        mean = sum(counts.values()) / map_count
        priors[name] = max_entropy(*bounds, mean)
        summaries[name] = {"mean": mean, "minimum": bounds[0], "maximum": bounds[1]}
    eligible = Counter((row["nodeType"], prediction["unknownNodes"][key]["distanceFromStart"])
                       for key, rows in candidates.items() for row in rows)
    slots = []
    for key, rows in candidates.items():
        distance = prediction["unknownNodes"][key]["distanceFromStart"]
        weights = {row["nodeType"]: row["distanceFrequency"] / eligible[(row["nodeType"], distance)]
                   for row in rows if row["distanceFrequency"] is not None and row["distanceFrequency"] > 0}
        slots.append((key, tuple(sorted(weights.items()))))
    if not slots:
        raise ValueError("没有可用的节点家族位置")
    model = _model(tuple(slots), tuple((key, tuple(rows.items())) for key, rows in priors.items()))
    requests = {}
    for goal_id, placement in (placements or {}).items():
        if not placement.get("eligible") or placement.get("locatedNodeIds"):
            continue
        name = CATEGORY_TO_TYPE[placement["categoryId"]]
        if name not in model.index:
            continue
        if goal_id == "ending3_trade":
            excluded = [key for key in known if instance["nodes"][key].get("completion") == "completed"]
        else:
            excluded = list(known)
        competing = sum(row["eligible"] and not row["locatedNodeIds"] and row["categoryId"] == placement["categoryId"]
                        for row in (placements or {}).values())
        requests[goal_id] = {"type": name, "excludedIds": excluded, "competingMarkers": competing}
    result = model.predict(known, marker_requests=requests)
    return result, {"mapSampleCount": map_count, "countMeans": summaries}


def attach_node_posterior(instance, prediction):
    """Keep raw source frequencies; publish normalized beta or explicit legacy fallback."""
    families = {}
    for family in ("unknown_mystery", "unknown_ferocity"):
        unknown = {key: row for key, row in prediction.get("unknownNodes", {}).items()
                   if row["unknownFamily"] == family}
        if not unknown:
            continue
        try:
            if prediction.get("status") == "not_applicable":
                raise ValueError("该层尚无完整的数量统计模型")
            if any(node.get("needsCategoryReview") or (
                    not node.get("resolvedCategoryId") and node.get("observedCategoryId") is None)
                   for node in instance["nodes"].values()):
                raise ValueError("存在未确认的图像类别，无法建立完整节点家族")
            from .ending_prediction import PLACEMENTS
            placements = {key: row for key, row in prediction.get("endingPlacements", {}).items()
                          if PLACEMENTS[key]["family"] == family}
            result, summary = _family_posterior(instance, family, placements=placements)
            families[family] = {"status": "ok", **summary,
                                **{key: value for key, value in result.items() if key not in {"probabilities", "seconds", "markerProbabilities"}}}
            for goal_id, positions in result.get("markerProbabilities", {}).items():
                placement = placements[goal_id]
                placement["positionProbabilities"] = {key: value for key, value in positions.items() if value > 0}
                placement["basis"] = "conditional_on_beta_categories"
                placement["ordinaryMarkerProbabilities"] = positions
            if result.get("markerProbabilities"):
                families[family]["endingIntegration"] = "conditional_marker_dp_categories_unchanged"
            for key, row in unknown.items():
                row["ordinaryProbabilities"] = {TYPE_TO_CATEGORY[name]: value
                                                for name, value in result["probabilities"][key].items()}
                row["probabilityBasis"] = "count_prior_beta_exact_dp"
                row["endingOccupancyBasis"] = "conditional_on_beta_categories"
        except (ValueError, RuntimeError) as error:
            reason = {
                "sample mean is outside allowed count bounds": "统计平均数量与本地数量上下限冲突",
                "a family slot has no positive-weight candidate": "有位置缺少非零统计候选",
                "no count prior is compatible with the family skeleton": "节点家族数量与统计先验不相容",
                "known category count exceeds the floor maximum": "已确认同类节点超过本层数量上限",
                "observations are impossible under the declared model": "当前已确认节点与统计模型不相容",
                "exact DP state limit reached; no approximate result returned": "精确预测达到状态上限，保留兼容估算",
            }.get(str(error), "当前观测与数量先验模型不相容，已回退兼容估算")
            families[family] = {"status": "fallback", "reason": reason, "diagnosticDetail": str(error)}
            label = "未知诡秘" if family == "unknown_mystery" else "未知凶戾"
            prediction["warnings"].append(f"节点预测 beta：{label}：{reason}")
            for row in unknown.values():
                weights = {item["categoryId"]: item.get("distanceFrequency") or 0 for item in row["candidates"]}
                total = sum(weights.values())
                row["ordinaryProbabilities"] = {key: value / total if total else 0 for key, value in weights.items()}
                row["probabilityBasis"] = "normalized_lubiao_distance_frequency_not_calibrated_posterior"
        for row in unknown.values():
            row["categoryProbabilities"] = dict(row["ordinaryProbabilities"])
    prediction["posteriorBeta"] = {"enabled": True, "families": families,
                                  "assumption": "independent_max_entropy_count_priors_and_distance_preferences"}
    from .ending_prediction import attach_conditional_ending_prediction
    attach_conditional_ending_prediction(instance, prediction)
