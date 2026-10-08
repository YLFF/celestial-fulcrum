"""Resolve combat resources independently of route utility and player bonuses."""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
from typing import Iterable


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "blackflow_battle_rewards.json"
MODES = {"normal", "emergency", "boss", "bossPursuit", "pursuit", "specialNormal", "specialEmergency"}


class BattleRewardCatalog:
    def __init__(self, path: Path = DATA_PATH) -> None:
        self.data = json.loads(path.read_text(encoding="utf-8"))

    def resolve(
        self, *, area_key: str, mode: str, stage_name: str | None = None,
        experience_multipliers: Iterable[str | int | Fraction] | None = None,
    ) -> dict:
        if mode not in MODES:
            raise ValueError(f"Unsupported battle mode: {mode}")
        region = area_key.replace("-remembrance", "")
        if mode.startswith("special"):
            variant = "emergency" if mode == "specialEmergency" else "normal"
            matches = [row for row in self.data["specialBattles"]
                       if stage_name in row["stages"] and row["variant"] == variant]
            if len(matches) != 1:
                raise ValueError("Special battle requires an unambiguous stage and variant")
            row = matches[0]
            selected = {key: row[key] for key in ("experience", "originiumIngot")}
            if stage_name == "无效验尸":
                from .node_rewards import RULES_PATH

                provisional = json.loads(RULES_PATH.read_text(encoding="utf-8"))["battles"]["invalid_autopsy"]
                selected = {**selected, "originiumIngot": {"kind": "fixed", "value": provisional["ingots"]},
                            "rewardReference": provisional["rewardReference"], "provisional": True,
                            "relicCount": provisional["relicCount"], "componentCount": provisional["componentCount"],
                            "ticketCount": provisional["ticketCount"]}
        elif mode == "pursuit":
            if "-treehole" in area_key or region not in ("I", "II", "IV"):
                raise ValueError("Ordinary pursuit is not defined for this area")
            selected = self.data["ordinaryPursuit"]
        else:
            if "-treehole" in area_key:
                if area_key not in ("III-treehole", "IV-treehole", "V-treehole"):
                    raise ValueError("Unsupported treehole area")
                if mode not in ("normal", "emergency"):
                    raise ValueError("Treehole battle must be ordinary or explicitly special")
                region = self.data["stageRegions"].get(stage_name)
                if region is None:
                    raise ValueError("Treehole rewards require the actual stage; do not use the entry floor")
            if region not in self.data["regionRewards"]:
                raise ValueError(f"Unknown stage region: {region}")
            if mode in ("normal", "emergency") and stage_name is not None:
                if self.data["stageRegions"].get(stage_name) != region:
                    raise ValueError("Stage does not belong to the selected reward region")
            selected = self.data["regionRewards"][region][mode]
            if selected is None:
                raise ValueError("No reward is defined for this battle/region")
        result = deepcopy(selected)
        multipliers = (self.data["experienceCalculation"]["fullTechnologyMultipliers"]
                       if experience_multipliers is None else experience_multipliers)
        value = Fraction(result["experience"]["base"])
        for multiplier in multipliers:
            factor = Fraction(str(multiplier))
            if factor < 0:
                raise ValueError("Experience multipliers cannot be negative")
            value *= factor
        result["experienceAward"] = value.numerator // value.denominator
        result["resolvedRegion"] = region if not mode.startswith("special") else None
        return result
