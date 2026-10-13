"""Current resident overlays, separate from the original node's completion."""

RESIDENT_MARK = "node_mark_001"


def resident_active(node):
    return RESIDENT_MARK in node.get("confirmedMarkIds", []) and not node.get(
        "residentCleared", node.get("completion") == "completed")


def outpost_completed(instance):
    return any(node.get("completion") == "completed" and (
        node.get("completedCategoryId") == "node_type_019" or
        node.get("completedCategoryId") is None and node.get("resolvedCategoryId") == "node_type_019"
        and RESIDENT_MARK not in node.get("confirmedMarkIds", []))
        for node in instance["nodes"].values())


def clear_resident(node):
    node["confirmedMarkIds"] = [mark for mark in node.get("confirmedMarkIds", []) if mark != RESIDENT_MARK]
    node["markCandidates"] = [mark for mark in node.get("markCandidates", []) if mark["id"] != RESIDENT_MARK]
    node["residentCleared"] = True


def clear_outpost_residents(instance):
    if outpost_completed(instance):
        for node in instance["nodes"].values():
            if RESIDENT_MARK in node.get("confirmedMarkIds", []) or any(
                    mark["id"] == RESIDENT_MARK for mark in node.get("markCandidates", [])):
                clear_resident(node)


def merge_resident_marks(node, current):
    previous = set(node.get("confirmedMarkIds", []))
    incoming = set(current["confirmedMarkIds"])
    # Missing/uncertain icons cannot establish absence; readable new nodes can.
    has_candidate = any(mark["id"] == RESIDENT_MARK for mark in current["markCandidates"])
    if current["observedCategoryId"] is not None and not has_candidate:
        previous.discard(RESIDENT_MARK)
    node["confirmedMarkIds"] = sorted(previous | incoming)
    if RESIDENT_MARK in incoming:
        node["residentCleared"] = False


def complete_node(instance, node):
    active_resident = resident_active(node)
    node["completion"] = "completed"
    if not node.get("completedCategoryId"):
        node["completedCategoryId"] = "node_type_021" if active_resident else node.get("resolvedCategoryId")
    if active_resident:
        node["residentCompleted"] = True
        clear_resident(node)
    clear_outpost_residents(instance)
