"""Hope prices shared by opening validation and roster updates."""

DUAL_PROFESSIONS = {
    "squad_005": {"先锋", "近卫"}, "squad_006": {"重装", "辅助"},
    "squad_007": {"医疗", "狙击"}, "squad_008": {"术师", "特种"},
}


def hope_price(operator, *, squad_id=None, difficulty=15, initial=False, promotion=False, source="normal"):
    if source in {"assistance", "emergency"} or source in {"temporary", "squad_002-temporary"} and not promotion:
        return 0
    rarity = operator.get("rarity")
    if type(rarity) is not int or not 1 <= rarity <= 6:
        raise ValueError("select an operator with a known rarity")
    price = ({4: 1, 5: 1, 6: 3} if promotion else {5: 2, 6: 6}).get(rarity, 0)
    if not initial and not promotion:
        price += int(rarity == 5 and difficulty >= 13) + int(rarity == 6 and difficulty >= 15)
    profession = operator.get("profession")
    if rarity >= 4:
        if profession in DUAL_PROFESSIONS.get(squad_id, set()):
            price -= 1 if promotion else 2
        elif not promotion and (
            squad_id == "squad_009" and profession in {"术师", "狙击", "医疗", "辅助"}
            or squad_id == "squad_010" and profession in {"先锋", "近卫", "重装", "特种"}
        ):
            price -= 2
        if squad_id == "squad_011" and operator.get("subprofession") in {"本源术师", "本源铁卫", "本源近卫", "巫役"}:
            price -= 2
    if operator.get("name") == "机械师":
        price -= 2 if promotion else 4
    return max(0, price)


def initial_roster(rows, *, squad_id, difficulty):
    from .operator_catalog import find_operator
    result = []
    seen = set()
    if len(rows or []) > 3:
        raise ValueError("初始招募最多选择三名干员")
    for row in rows or []:
        if not isinstance(row, dict):
            raise ValueError("invalid initial operator")
        entry = find_operator(row.get("operatorId") or row.get("name"))
        if not entry or (entry["id"] in seen and not entry.get("repeatable")):
            raise ValueError("select distinct operators from the local directory")
        if entry.get("professionEditable"):
            entry = {**entry, "profession": row.get("profession")}
        seen.add(entry["id"])
        source = row.get("source", "normal")
        if source not in {"normal", "temporary"}:
            raise ValueError("initial recruitment source must be normal or temporary")
        elite = row.get("elite", 1)
        max_elite = 2 if entry["rarity"] >= 4 else (1 if entry["rarity"] == 3 else 0)
        if type(elite) is not int or not 0 <= elite <= max_elite:
            raise ValueError("invalid initial elite stage")
        if squad_id == "squad_002" and entry["name"] == "机械师":
            raise ValueError("special operations already grants Mechanist; use its promotion option")
        result.append({"name": entry["name"], "profession": entry["profession"], "rarity": entry["rarity"],
                       "elite": elite, "source": source,
                       "hopeCost": hope_price(entry, squad_id=squad_id, difficulty=difficulty, initial=True, source=source)})
    return result
