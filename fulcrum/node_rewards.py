"""Stable local item bindings and conditional frequencies for node reward pools."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "blackflow_node_reward_pools.json"
RULES_PATH = ROOT / "data" / "blackflow_reward_rules.json"

SHARED_POOL_PREFERENCES = (
    "node_final_scrap", "node_wish_relic", "node_incident_lake_fairy", "node_duel_left",
    "node_battle_recruit", "node_battle_savage_recruit", "node_battle_savage_scrap_left",
)
TWO_CHOICE_CONTEXTS = {
    "node_battle_normal_scrap", "node_battle_elite_scrap", "node_battle_boss_scrap",
    "node_battle_savage_scrap_left", "node_battle_savage_scrap_right",
    "node_wandering_resident_scrap", "node_wandering_resident_convergence_scrap",
    "node_duel_center", "pool_boss",
}
DIRECT_SINGLE_CONTEXTS = {
    "node_final_scrap", "node_evacuate_scrap", "node_incident_goods_from_mouth_concept",
    "node_incident_goods_from_mouth_natural", "node_incident_goods_from_mouth_processing",
    "node_incident_informant_processing",
}


def selection_rule(context_id: str) -> dict | None:
    if context_id in TWO_CHOICE_CONTEXTS:
        return {"kind": "choose", "candidateCount": 2, "takeCount": 1, "when": "rewardAvailable",
                "candidateSampling": None}
    if context_id.startswith("node_wish_relic"):
        return {"kind": "choose", "candidateCount": 2, "takeCount": 1, "when": "rewardAvailable",
                "candidateCountMayVary": True, "candidateSampling": None}
    if context_id in DIRECT_SINGLE_CONTEXTS:
        return {"kind": "grant", "takeCount": 1,
                "when": "leaveLayer" if context_id in {"node_final_scrap", "node_evacuate_scrap"} else "optionSelected"}
    if context_id.startswith("node_sacrifice_"):
        is_input = context_id.endswith("_input") or context_id in {
            "node_sacrifice_normal_relic", "node_sacrifice_rare_relic", "node_sacrifice_super_rare_relic",
        }
        return {"kind": "exchangeInput" if is_input else "exchangeOutput", "takeCount": 1,
                "when": "singleExchange"}
    return None


def normalize_pools(archive: dict, catalog: dict) -> list[dict]:
    if archive.get("schemaVersion") != 2 or catalog.get("schemaVersion") != 2:
        raise ValueError("Unsupported reward source/catalog version")
    local = {row["name"]: row for row in catalog["entries"]}
    items = {row["itemId"]: row for row in archive["classifier"]["items"]}
    extra_items = {row["itemId"]: row for pool in archive["pools"]["pools"] for row in pool.get("memberItems", [])}

    def descriptor(source_id: str) -> dict:
        item = items.get(source_id)
        if item is None:
            item = extra_items.get(source_id)
        if item is None:
            return {"itemId": None, "name": source_id, "sourceItemIds": [source_id],
                    "dataType": "unresolved", "metadataStatus": "missing"}
        name = item.get("baseName") or item["name"]
        matched = local.get(name)
        if matched is None and item.get("dataType") == "藏品":
            variant_base = re.sub(r"-[αβγ]$", "", name)
            matched = local.get(variant_base)
            if matched is not None:
                name = variant_base
        data_type = item.get("dataType") or ({"relic": "藏品", "component": "零件"}.get(matched["category"]) if matched else "招募券")
        return {"itemId": matched["id"] if matched else None, "name": name,
                "sourceItemIds": [source_id], "dataType": data_type}

    def members(source_ids: list[str], distribution: dict | None, pool: dict) -> list[dict]:
        observed = (distribution or {}).get("members", [])
        by_source = {row["itemId"]: row for row in observed}
        if len(by_source) != len(observed):
            raise ValueError(f"Duplicate observations in {pool['id']}")
        grouped = {}
        for source_id in dict.fromkeys(source_ids + list(by_source)):
            item = descriptor(source_id)
            key = item["itemId"] or item["name"]
            if key not in grouped:
                grouped[key] = {**item, "sourceItemIds": [], "occurrenceCount": None,
                                "totalOccurrenceCount": None, "probability": None}
            row = grouped[key]
            row["sourceItemIds"].append(source_id)
            sample = by_source.get(source_id)
            if sample is not None:
                count = sample["occurrenceCount"]
                if type(count) is not int or count < 0:
                    raise ValueError("Occurrence counts must be nonnegative integers")
                row["occurrenceCount"] = (row["occurrenceCount"] or 0) + count
                denominator = sample.get("totalOccurrenceCount")
                if denominator is not None:
                    if type(denominator) is not int or denominator <= 0 or count > denominator:
                        raise ValueError("Observation denominators must be positive integers covering the count")
                    row["totalOccurrenceCount"] = max(row["totalOccurrenceCount"] or 0, denominator)
        rows = list(grouped.values())
        total = sum(row["occurrenceCount"] or 0 for row in rows)
        interpretation = (distribution or {}).get("interpretation")
        for row in rows:
            count = row["occurrenceCount"]
            denominator = row["totalOccurrenceCount"] if interpretation == "observedOccurrenceRate" else total
            if count is not None and denominator and interpretation != "membershipOnly":
                row["probability"] = count / denominator
        return rows

    results = []
    seen = set()
    for pool in archive["pools"]["pools"]:
        pool_id = pool.get("officialCode") or pool["id"]
        if pool_id in seen:
            raise ValueError(f"Duplicate reward pool: {pool_id}")
        seen.add(pool_id)
        distribution = pool.get("observedDistribution")
        statistics = {key: deepcopy(value) for key, value in (distribution or {}).items()
                      if key not in {"members", "subpools"}}
        statistics.setdefault("interpretation", "membershipOnly")
        subpools = []
        for subpool in (distribution or {}).get("subpools", []):
            subpools.append({
                "id": subpool["id"], "name": subpool["name"],
                "statistics": {key: deepcopy(value) for key, value in subpool.items()
                               if key not in {"id", "name", "members"}},
                "members": members(subpool.get("itemIds", []) + [row["itemId"] for row in subpool.get("members", [])], subpool, pool),
            })
        results.append({
            "id": pool_id, "sourcePoolId": pool["id"], "name": pool["name"],
            "displayCategory": pool.get("displayCategory"), "statistics": statistics,
            "members": members(pool["collectibles"], distribution, pool), "subpools": subpools,
            "sourceReferences": deepcopy(pool.get("sourceReferences", [])),
            "frequencyColumns": deepcopy(pool.get("frequencyColumns", {})),
            "observedDistribution": deepcopy(distribution),
        })
    return results


def compact_pools(pools: list[dict]) -> tuple[list[dict], list[dict]]:
    """Share identical member lists without pooling observations from different scopes."""
    signatures = {}
    groups = {}
    for pool in pools:
        for group_id, group in [(pool["id"], pool)] + [
            (f"{pool['id']}__{row['id']}", row) for row in pool["subpools"]
        ]:
            descriptors = [{key: deepcopy(value) for key, value in row.items()
                            if key in {"itemId", "name", "dataType", "metadataStatus"}} for row in group["members"]]
            signature = tuple(sorted(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in descriptors))
            signatures.setdefault(signature, []).append(group_id)
            groups[group_id] = (group.get("name") or pool["name"], descriptors)
    priority = {value: index for index, value in enumerate(SHARED_POOL_PREFERENCES)}
    references = {}
    definitions = []
    for aliases in signatures.values():
        owner = min(aliases, key=lambda value: (priority.get(value, len(priority)), value))
        pool_id = owner
        for alias in aliases:
            references[alias] = pool_id
        name, descriptors = groups[owner]
        definitions.append({"id": pool_id, "name": name, "members": descriptors,
                            "contextIds": sorted(aliases)})

    def compact_group(group_id: str, group: dict) -> dict:
        stored = {key: deepcopy(value) for key, value in group.items() if key != "members"}
        stored["rewardPoolId"] = references[group_id]
        stored["memberObservations"] = [
            {"memberKey": row["itemId"] or row["name"],
             **{key: deepcopy(row[key]) for key in ("sourceItemIds", "occurrenceCount", "totalOccurrenceCount", "probability")}}
            for row in group["members"]
        ]
        return stored

    contexts = []
    for pool in pools:
        stored = compact_group(pool["id"], pool)
        stored["selection"] = selection_rule(pool["id"])
        stored["subpools"] = [compact_group(f"{pool['id']}__{row['id']}", row) for row in pool["subpools"]]
        contexts.append(stored)
    return sorted(definitions, key=lambda row: row["id"]), contexts


def expanded_pools(data: dict) -> list[dict]:
    if data.get("schemaVersion") == 1:
        return deepcopy(data["pools"])
    if data.get("schemaVersion") != 2:
        raise ValueError("Unsupported local reward dataset version")
    definitions = {row["id"]: row for row in data["rewardPools"]}

    def expand(group: dict) -> dict:
        result = deepcopy(group)
        items = {row["itemId"] or row["name"]: row for row in definitions[group["rewardPoolId"]]["members"]}
        result["members"] = []
        for observation in group["memberObservations"]:
            member_key = observation["memberKey"]
            result["members"].append({**deepcopy(items[member_key]),
                                      **{key: deepcopy(value) for key, value in observation.items() if key != "memberKey"}})
        result["subpools"] = [expand(row) for row in group.get("subpools", [])]
        return result

    return [expand(row) for row in data["observationContexts"]]


def observation_context_ids(node: dict) -> list[str]:
    return node.get("observationContextIds", node.get("poolIds", []))


def validate_rendered_pools(pools: list[dict], pages: list[dict]) -> tuple[int, list[dict]]:
    """Check names and rounded probabilities against every collected UI option."""
    by_source = {pool["sourcePoolId"]: pool for pool in pools}
    checked = 0
    differences = []
    for page in pages:
        for panel in page["panels"]:
            for rendered in panel["pools"]:
                pool = by_source[rendered["sourcePoolId"]]
                for group in rendered["groups"]:
                    subgroup = next((row for row in pool["subpools"] if row["name"] == group["name"]), None)
                    normalized = subgroup["members"] if subgroup else pool["members"]
                    by_name = {row["name"]: row for row in normalized}
                    visible_total = sum(by_name[item["name"]]["occurrenceCount"] or 0
                                        for item in group["members"] if item["name"] in by_name)
                    interpretation = (subgroup["statistics"] if subgroup else pool["statistics"]).get("interpretation")
                    for item in group["members"]:
                        row = by_name.get(item["name"])
                        if row is None:
                            raise ValueError(f"Unmapped rendered member: {item['name']} in {pool['id']}")
                        if item["probabilityText"]:
                            probability = (row["probability"] if interpretation == "observedOccurrenceRate"
                                           else row["occurrenceCount"] / visible_total if visible_total else None)
                            display = float(item["probabilityText"].rstrip("%"))
                            if probability is None or abs(display - probability * 100) > 0.00501:
                                raise ValueError(f"Frequency differs from rendered page: {pool['id']} / {item['name']} / "
                                                 f"{group['name']}: {probability} vs {item['probabilityText']}")
                            if row["probability"] is not None and abs(display - row["probability"] * 100) > 0.00501:
                                differences.append({"poolId": pool["id"], "subpool": group["name"],
                                                    "name": item["name"], "displayProbability": item["probabilityText"],
                                                    "fullSubpoolFrequency": row["probability"],
                                                    "visibleCountDenominator": visible_total})
                        checked += 1
    return checked, differences


class NodeRewardPoolCatalog:
    def __init__(self, path: Path = DATA_PATH) -> None:
        self.data = json.loads(path.read_text(encoding="utf-8"))
        if self.data.get("schemaVersion") == 1:
            definitions, contexts = compact_pools(self.data["pools"])
            self.data = {key: value for key, value in self.data.items() if key != "pools"}
            self.data.update(schemaVersion=2, rewardPools=definitions, observationContexts=contexts)
        self.by_id = {row["id"]: row for row in expanded_pools(self.data)}
        self.shared_by_id = {row["id"]: row for row in self.data.get("rewardPools", [])}

    def get(self, pool_id: str) -> dict[str, Any]:
        return deepcopy(self.by_id[pool_id])

    def get_pool(self, shared_pool_id: str) -> dict[str, Any]:
        return deepcopy(self.shared_by_id[shared_pool_id])

    def for_node(self, node_category_id: str) -> list[dict]:
        node = next(row for row in self.data["nodes"] if row["nodeCategoryId"] == node_category_id)
        return [self.get(pool_id) for pool_id in observation_context_ids(node)]

    def shared_for_node(self, node_category_id: str) -> list[dict]:
        contexts = self.for_node(node_category_id)
        pool_ids = sorted({row["rewardPoolId"] for row in contexts})
        return [deepcopy(self.shared_by_id[pool_id]) for pool_id in pool_ids]

    def selections_for_node(self, node_category_id: str) -> list[dict]:
        node = next(row for row in self.data["nodes"] if row["nodeCategoryId"] == node_category_id)
        return deepcopy(node.get("rewardSelections", []))

    def rules_for(self, kind: str, rule_id: str) -> dict:
        if kind not in {"nodes", "events", "battles"}:
            raise ValueError("Unknown reward rule kind")
        rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        return deepcopy(rules[kind][rule_id])

    def battle_observations(self, stage_id: str) -> list[dict]:
        return deepcopy([row for row in self.data.get("battleRewardObservations", [])
                         if row["stageId"] == stage_id])
