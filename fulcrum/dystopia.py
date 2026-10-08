"""Editable, per-node dystopia snapshot, independent of treehole utopias."""

from copy import deepcopy

IDEOLOGY_IDS = {f"dystopia_{index:03}" for index in range(1, 11)}
POLICY_IDS = {f"dystopia_{index:03}" for index in range(11, 15)}
FIELDS = {"active", "ideologyId", "policyId", "affectedNodeIds", "uncertainNodeIds", "idealSourceNodeId"}


def empty_dystopia():
    return {"active": False, "ideologyId": None, "policyId": None,
            "affectedNodeIds": [], "uncertainNodeIds": [], "idealSourceNodeId": None}


def validate_dystopia(value, nodes):
    if not isinstance(value, dict) or set(value) != FIELDS or type(value["active"]) is not bool:
        raise ValueError("invalid dystopia snapshot fields")
    if value["ideologyId"] not in IDEOLOGY_IDS | {None} or value["policyId"] not in POLICY_IDS | {None}:
        raise ValueError("invalid dystopia ideology or policy")
    for field in ("affectedNodeIds", "uncertainNodeIds"):
        ids = value[field]
        if (not isinstance(ids, list) or any(not isinstance(key, str) for key in ids)
                or len(ids) != len(set(ids)) or not set(ids) <= set(nodes)):
            raise ValueError("invalid dystopia node coverage")
    if set(value["affectedNodeIds"]) & set(value["uncertainNodeIds"]):
        raise ValueError("dystopia coverage cannot be both confirmed and uncertain")
    source = value["idealSourceNodeId"]
    if source is not None and (not isinstance(source, str) or source not in nodes or source not in value["affectedNodeIds"]):
        raise ValueError("ideal source must be a covered map node")
    if value["ideologyId"] == "dystopia_008" and source is not None:
        raise ValueError("fertile soil has no ideal source")
    if not value["active"] and value != empty_dystopia():
        raise ValueError("inactive dystopia must have no coverage or source")


def set_dystopia(instance, value):
    validate_dystopia(value, instance["nodes"])
    source = value["idealSourceNodeId"]
    previous_source = instance.get("dystopia", {}).get("idealSourceNodeId")
    if source is not None:
        node = instance["nodes"][source]
        retained_source = (source == previous_source and node.get("observedCategoryId") == "node_type_020"
                           and node.get("resolvedCategoryId") == "node_type_002")
        if node.get("observedCategoryId") not in {"node_type_002", "unknown_ferocity", None} and not retained_source:
            raise ValueError("ideal source must be emergency combat or hidden ferocity")
    if previous_source and previous_source != source:
        previous = instance["nodes"][previous_source]
        if (previous.pop("idealSourceInferredCategory", False) and previous.get("observedCategoryId") == "unknown_ferocity"
                and previous.get("completion") != "completed" and previous.get("resolvedCategoryId") == "node_type_002"):
            previous["resolvedCategoryId"] = None
    if source is not None:
        node = instance["nodes"][source]
        # The source rule resolves its type without claiming the game has revealed it.
        node["resolvedCategoryId"] = "node_type_002"
        if node.get("observedCategoryId") == "unknown_ferocity":
            node["idealSourceInferredCategory"] = True
    instance["dystopia"] = deepcopy(value)


def merge_dystopia_observation(instance, observation):
    if not observation or not observation.get("active"):
        return
    previous = instance.get("dystopia", empty_dystopia())
    same = previous.get("active") and previous.get("ideologyId") == observation.get("ideologyId")
    affected, uncertain = [], []
    evidence = observation.get("nodeEvidence", {})
    for key in instance["nodes"]:
        status = evidence.get(key, {}).get("affected")
        if status is True or (status is None and same and key in previous["affectedNodeIds"]):
            affected.append(key)
        elif status is None:
            uncertain.append(key)
    source = observation.get("idealSourceNodeId") or (previous["idealSourceNodeId"] if same else None)
    if source and source not in affected:
        affected.append(source)
        uncertain = [key for key in uncertain if key != source]
    if observation.get("ideologyId") == "dystopia_008":
        source = None
    set_dystopia(instance, {"active": True, "ideologyId": observation.get("ideologyId"),
        "policyId": observation.get("policyId") or (previous["policyId"] if same else None),
        "affectedNodeIds": affected, "uncertainNodeIds": uncertain, "idealSourceNodeId": source})
