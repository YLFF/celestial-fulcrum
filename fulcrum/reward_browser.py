"""Read-only reward candidates; observation probabilities stay in the source data."""

from functools import lru_cache
import json

from .node_rewards import NodeRewardPoolCatalog, ROOT, observation_context_ids


def secret_trader_members(source, all_items):
    node = next(row for row in source.data["nodes"] if row["nodeCategoryId"] == "node_type_013")
    by_name = {row["name"]: row for row in all_items.values() if row["category"] == "component"}
    groups = {"regular": {}, "firstFloor": {}}
    for panel in node["statisticsPanels"]:
        group = groups["firstFloor" if panel["option"].startswith("一层特殊型 / ") else "regular"]
        for table in panel["tables"]:
            if table["title"] != "零件频次":
                continue
            for name, _kind, _frequency in table["rows"][1:]:
                item = by_name[name]
                group[item["id"]] = {"itemId": item["id"], "dataType": "零件"}
    # Only merge membership: each shop/phase observation keeps its original denominator.
    return {key: list(group.values()) for key, group in groups.items()}


@lru_cache(maxsize=1)
def browser_catalog():
    links = json.loads((ROOT / "data/reward_pool_links.json").read_text(encoding="utf-8"))
    source = NodeRewardPoolCatalog()
    pools = {}

    def add(key, row, label=None):
        members = row["members"]
        for kind, data_type in (("relic", "藏品"), ("component", "零件")):
            item_ids = list(dict.fromkeys(item["itemId"] for item in members
                                         if item.get("itemId") and item["dataType"] == data_type))
            if item_ids:
                pool_key = f"{key}:{kind}"
                pools[pool_key] = {"id": pool_key, "contextId": key, "kind": kind,
                    "label": label or links["labels"].get(key, row["name"]), "itemIds": item_ids}

    for key, row in source.by_id.items():
        if (row.get("selection") or {}).get("kind") == "exchangeInput":
            continue
        if row["subpools"]:
            for subpool in row["subpools"]:
                add(f"{key}__{subpool['id']}", subpool, f"{links['labels'].get(key, row['name'])} · {subpool['name']}")
        else:
            add(key, row)

    from .service.catalog import entries
    all_items = entries()
    shelves = secret_trader_members(source, all_items)
    for key, group, label in (("secret_trader_shelves", "regular", "秘境行商 · 售卖零件汇总"),
                              ("secret_trader_shelves_f1", "firstFloor", "秘境行商 · 一层特殊货架")):
        add(key, {"name": label, "members": shelves[group]}, label)
    for key, row in links["fixedPools"].items():
        add(key, {"name": row["label"], "members": [{"itemId": item_id,
            "dataType": "藏品" if all_items[item_id]["category"] == "relic" else "零件"}
            for item_id in row["itemIds"]]})

    def resolve(contexts):
        return [key for key, pool in pools.items() if pool["contextId"] in contexts
                or any(pool["contextId"].startswith(f"{context}__") for context in contexts)]

    nodes = {row["nodeCategoryId"]: resolve(observation_context_ids(row)) for row in source.data["nodes"]}
    nodes["node_type_006"] = []  # Encounter pools belong to individual event rows.
    nodes["node_type_013"] = resolve(["secret_trader_shelves", "secret_trader_shelves_f1"])
    nodes["node_type_009"] += resolve(["ending_beacon"])
    nodes["node_type_008"] += resolve(["ending_civilization"])
    return {"pools": pools, "nodes": nodes,
            "events": {key: resolve(contexts) for key, contexts in links["events"].items()},
            "marks": {key: resolve(contexts) for key, contexts in links["marks"].items()},
            "special": {"ending3_autopsy": resolve(["node_battle_normal_invalid_autopsy", "node_battle_boss_scrap", "ending_autopsy"])},
            "missing": links["missing"]}
