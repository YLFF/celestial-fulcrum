"""Validated, application-owned defaults for the future advanced scoring handbook."""

from __future__ import annotations

import json
import math
from pathlib import Path

PROFILE_PATH = Path(__file__).resolve().parents[1] / "data/scoring/blackstream/default.json"


def load_profile(path: Path = PROFILE_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 1:
        raise ValueError("评分配置版本不支持")
    sections = ("resources", "components", "tickets", "events", "merchants", "information", "exits", "overlays", "search", "policies")
    if any(not isinstance(data.get(key), dict) for key in sections):
        raise ValueError("评分配置缺少必要分类")

    def validate(value, key):
        if isinstance(value, dict):
            for field, child in value.items():
                validate(child, f"{key}.{field}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                validate(child, f"{key}[{index}]")
        elif type(value) in (int, float) and not math.isfinite(value):
            raise ValueError(f"评分配置必须为有限数值：{key}")

    validate(data, "profile")
    for section, field in (("components", "fixedPoints"), ("components", "movementPoints"), ("tickets", "weights")):
        values = data[section].get(field)
        if not isinstance(values, dict) or not values or any(
            not isinstance(key, str) or type(value) not in (int, float) or value < 0 for key, value in values.items()
        ):
            raise ValueError(f"评分配置应为非负权重表：{section}.{field}")
    for section, fields in {
        "resources": ("relicPoints", "cashPoints", "completeSixStarPoints", "belowThresholdFactor", "carryAPPoints", "exitHopePointFloor"),
        "merchants": ("yellowPointsPerEconomy", "yellowMaxPoints", "greenLogScale", "greenLogOffset", "defaultReserve", "withdrawalCashPoints"),
        "information": ("revealCoefficient", "pathStepIngotExpectation"),
    }.items():
        for field in fields:
            value = data[section].get(field)
            if type(value) not in (int, float) or value < 0:
                raise ValueError(f"评分配置应为非负数：{section}.{field}")
    if data["resources"]["relicPoints"] <= 0 or data["merchants"]["greenLogOffset"] <= 0:
        raise ValueError("藏品基准分和商店对数偏移必须为正数")
    for values, fields in ((data["events"], ("delayDiscount",)), (data["exits"], ("pathCarryDeficitPenalty",)),
                          (data["merchants"], ("repeatFallbackFactor",))):
        if any(type(values.get(field)) not in (int, float) or not 0 <= values[field] <= 1 for field in fields):
            raise ValueError("折扣和比例必须在0至1之间")
    for field in ("emptyEventPenaltyPoints", "contractLowValuePenaltyPoints"):
        value = data["events"].get(field)
        if value is not None and (type(value) not in (int, float) or value > 0):
            raise ValueError("惩罚分应为空或非正数")
    thresholds = data.get("teamThresholds")
    if not isinstance(thresholds, list) or len(thresholds) != 6 or any(
        not isinstance(row, list) or len(row) != 3 or any(type(n) is not int or n < 0 for n in row)
        or not row[0] <= row[1] <= row[2] for row in thresholds
    ):
        raise ValueError("战力门槛应为六层的进阶六星、全部六星、人数三项")
    search = data["search"]
    if any(type(search.get(key)) is not int or search[key] < 1 for key in ("defaultTopN", "defaultMaxStates", "scoreScale")):
        raise ValueError("搜索数量、上限和分数精度必须为正整数")
    if search["defaultTopN"] > 50 or search["defaultMode"] not in {"target", "reference"} or type(search["allocationDominance"]) is not bool:
        raise ValueError("搜索默认设置不合法")
    probabilities = data["overlays"]["unconfirmedTreeholeBattle"]
    if any(type(p) not in (int, float) or not 0 <= p <= 1 for p in probabilities.values()) or not math.isclose(sum(probabilities.values()), 1):
        raise ValueError("树洞战斗近似概率必须加和为1")
    return data


# Defaults are loaded once. Player-selected templates and hot reload are not enabled.
PROFILE = load_profile()
RESOURCE_POINTS = PROFILE["resources"]
CASH_POINTS = RESOURCE_POINTS["cashPoints"]
