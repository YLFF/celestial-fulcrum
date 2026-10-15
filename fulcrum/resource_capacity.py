"""Permanent carry-slot grants, separate from current held combat effects."""

from functools import lru_cache


@lru_cache(maxsize=1)
def carry_relic_grants():
    from .relic_effects import load_definitions
    return {key: sum(effect["value"] for effect in definition["effects"]
                     if effect["target"].get("metric") == "squad_capacity"
                     and effect["operation"] in {"grant", "flat_delta"})
            for key, definition in load_definitions().items()}


def reconcile_carry_slots(state, past=()):
    resources = state.get("resources", {})
    level = resources.get("level")
    slots = resources.get("carrySlots")
    if type(level) is not int or type(slots) is not int:
        return
    grants = carry_relic_grants()
    held = {row["id"]: row.get("count", 1) for row in state.get("relics", []) if grants.get(row["id"])}
    runtime = state.setdefault("resourceRuntime", {})
    ledger = runtime.get("carrySlots")
    if ledger is None:
        # Legacy saves may already include manual corrections: only restore a known minimum.
        maximum_level = max([level, *(snapshot.get("resources", {}).get("level") or 1 for snapshot in past)])
        known = dict(held)
        for snapshot in past:
            for row in snapshot.get("relics", []):
                if grants.get(row["id"]):
                    known[row["id"]] = max(known.get(row["id"], 0), row.get("count", 1))
        base = 9 if state.get("opening", {}).get("squadId") == "squad_002" else 7
        slots = max(slots, min(13, base + maximum_level // 2 + sum(grants[key] * count for key, count in known.items())))
    else:
        maximum_level = max(level, ledger["level"])
        slots += max(0, maximum_level // 2 - ledger["level"] // 2)
        slots += sum(grants[key] * max(0, count - ledger["held"].get(key, 0)) for key, count in held.items())
    resources["carrySlots"] = min(13, slots)
    runtime["carrySlots"] = {"level": maximum_level, "held": held}
