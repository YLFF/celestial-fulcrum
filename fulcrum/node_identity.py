"""Layer context distinguishes the two identical ending-related mark icons."""

def contextual_mark_id(mark_id: str, area: str | None, floor: int | None) -> str | None:
    if mark_id not in {"node_mark_002", "node_mark_003"} or area is None or floor is None:
        return mark_id
    if area != "main":
        return None
    if floor in {2, 3, 4}:
        return "node_mark_002"
    return "node_mark_003" if floor == 5 else None
