"""Read rendered Lubiao reward pools; never overwrite manually maintained Markdown."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fulcrum.node_rewards import compact_pools, expanded_pools, normalize_pools, observation_context_ids, validate_rendered_pools


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY_URL = "https://www.lubiao.wiki/nodes/rogue_6"
ARCHIVE_URL = "https://www.lubiao.wiki/data/archives/blackstream.json"
BATTLES_URL = "https://www.lubiao.wiki/data/battles/rogue_6.json"
BATTLE_OBSERVATION_STAGES = ("ro6_n_1_1", "ro6_e_1_1", "ro6_t_5", "ro6_e_t_5")
DEFAULT_SOURCE_DIR = ROOT / "work" / "lubiao_node_rewards"
DEFAULT_OUTPUT = ROOT / "data" / "blackflow_node_reward_pools.json"
PROTECTED = {ROOT / name for name in (
    "BLACKSTREAM_REFERENCE.md", "BLACKSTREAM_RULEBOOK.md", "BLACKFLOW_PLAYTIME_TEMPLATE.md",
)}


def describe(value, depth: int = 2):
    if depth == 0:
        return {"type": type(value).__name__, "size": len(value)} if isinstance(value, (list, dict)) else value
    if isinstance(value, dict):
        return {key: describe(child, depth - 1) for key, child in value.items()}
    if isinstance(value, list):
        return {"size": len(value), "first": describe(value[0], depth - 1) if value else None}
    return value


def inspect_page(page, url: str) -> dict:
    responses = []
    page.on("response", lambda response: responses.append(response))
    response = page.goto(url, wait_until="networkidle", timeout=30000)
    if response is None or response.status != 200:
        raise RuntimeError(f"Failed to load {url}")
    notice = page.get_by_role("button", name="知道了", exact=True)
    if notice.is_visible():
        notice.click()
    modules = []
    for row in responses:
        if row.url.startswith("https://www.lubiao.wiki/_nuxt/") and row.url.endswith(".js"):
            body = row.text()
            for needle in ("node_final_scrap", "node-pool-probability"):
                index = body.find(needle)
                if index >= 0:
                    modules.append({"url": row.url, "needle": needle, "imports": body[:4500],
                                    "excerpt": body[max(0, index - 300):index + 2500]})
    return {
        "url": page.url, "text": page.locator("body").inner_text(),
        "dataUrls": sorted({row.url for row in responses if row.url.startswith("https://www.lubiao.wiki/data/")}),
        "controls": page.locator("button, select").evaluate_all(
            "elements => elements.map(e => ({tag: e.tagName, text: e.innerText, class: e.className}))"
        ),
        "links": page.locator("a[href]").evaluate_all(
            "elements => elements.map(e => ({text: e.innerText, href: e.getAttribute('href')}))"
        ),
        "mainHtml": page.locator("main").evaluate("e => e.outerHTML").strip()[:30000],
        "modules": modules,
    }


def read_json(request, url: str) -> dict:
    response = request.get(url)
    if response.status != 200:
        raise RuntimeError(f"Failed to read {url}")
    return response.json()


def collect_tables(page) -> list[dict]:
    return page.locator(".node-detail-view table").evaluate_all(
        """elements => elements.map(table => {
            const boundary = table.closest('.node-detail-view');
            function nearby(direction, selector) {
                for (let node = table; node && node !== boundary; node = node.parentElement) {
                    for (let sibling = node[direction]; sibling; sibling = sibling[direction]) {
                        if (sibling.matches(selector)) return sibling;
                        if (sibling.matches('table, h2, h3, h4')) break;
                    }
                }
                return null;
            }
            const heading = nearby('previousElementSibling', 'h2, h3, h4');
            const metadata = nearby('nextElementSibling', '.statistics-metadata');
            return {
                title: heading?.innerText ?? table.closest('section')?.querySelector('h2, h3')?.innerText ?? '',
                rows: [...table.rows].map(row => [...row.cells].map(cell => cell.innerText)),
                metadata: metadata?.innerText ?? null
            };
        })"""
    )


def select_statistics_filter(page, group_name: str, label: str) -> None:
    button = page.get_by_role("group", name=group_name, exact=True).get_by_role("button", name=label, exact=True)
    button.click()
    page.wait_for_function(
        "args => [...document.querySelectorAll('[role=group][aria-label]')].find(e => e.getAttribute('aria-label') === args[0])"
        "?.querySelector('button[aria-pressed=true]')?.innerText === args[1]", arg=[group_name, label],
    )


def collect_rogue_shop_statistics(page) -> list[dict]:
    panels = []
    floors = page.get_by_role("group", name="商店层数", exact=True).locator("button").all_inner_texts()
    if not floors:
        raise ValueError("Rogue shop floor filters were not rendered")
    for floor in floors:
        select_statistics_filter(page, "商店层数", floor)
        categories = page.get_by_role("group", name="商品类别", exact=True).locator("button").all_inner_texts()
        if not {"收藏品", "零件", "招募券", "支援道具"}.issubset(categories):
            raise ValueError("Rogue shop category filters were not fully rendered")
        for category in categories:
            select_statistics_filter(page, "商品类别", category)
            tables = collect_tables(page)
            panels.append({"option": f"{floor} / {category}", "pools": [], "tables": tables,
                           "message": page.locator(".shop-statistics").inner_text() if not tables else None})
    return panels


def collect_shop_statistics(page) -> list[dict]:
    panels = []
    types = page.get_by_role("group", name="秘境行商类型", exact=True).locator("button").all_inner_texts()
    if not {"加工品型", "自然物型", "概念体型", "一层特殊型"}.issubset(types):
        raise ValueError("Secret shop type filters were not fully rendered")
    for shop_type in types:
        select_statistics_filter(page, "秘境行商类型", shop_type)
        for phase in ("首次进入", "刷新货架"):
            select_statistics_filter(page, "货架阶段", phase)
            floor_group = page.get_by_role("group", name="店型零件层数", exact=True)
            floors = floor_group.locator("button").all_inner_texts() if floor_group.count() else [None]
            for floor in floors:
                if floor is not None:
                    select_statistics_filter(page, "店型零件层数", floor)
                panels.append({"option": " / ".join(value for value in (shop_type, phase, floor) if value),
                               "pools": [], "tables": collect_tables(page)})
    return panels


def collect_page(page, entry: dict) -> dict:
    if entry["nodeCategoryId"] == "node_type_006":
        entry = {**entry, "directoryEntryUrl": entry["sourceUrl"],
                 "sourceUrl": "https://www.lubiao.wiki/nodes/details/rogue_6/encounter"}
    response = page.goto(entry["sourceUrl"], wait_until="networkidle", timeout=30000)
    if response is None or response.status != 200:
        raise RuntimeError(f"Failed to load {entry['sourceUrl']}")
    page.wait_for_timeout(800)
    notice = page.get_by_role("button", name="知道了", exact=True)
    if notice.is_visible():
        notice.click()
    result = {**entry, "version": page.locator(".version-description").inner_text(), "panels": []}
    if "/nodes/battles/" in page.url:
        result["poolIds"] = []
        return result
    filters = page.locator(".node-pool-filters button")
    labels = filters.all_inner_texts() or [None]
    for index, label in enumerate(labels):
        if label is not None:
            filters.nth(index).click()
            page.wait_for_function(
                "label => document.querySelector('.node-pool-filters button[aria-pressed=true]')?.innerText === label",
                arg=label,
            )
        pools = page.locator(".node-pool-contents").evaluate_all(
            """elements => elements.map(root => ({
                title: root.querySelector('h2').innerText,
                groups: [...root.querySelectorAll(':scope > section')].map(group => ({
                    name: group.querySelector('h3')?.innerText ?? null,
                    metadata: group.querySelector('.statistics-metadata')?.innerText ?? null,
                    members: [...group.querySelectorAll('.node-pool-member')].map(item => ({
                        name: item.querySelector('strong').innerText,
                        href: item.getAttribute('href'),
                        probabilityText: item.querySelector('.node-pool-probability')?.innerText ?? null
                    }))
                }))
            }))"""
        )
        for pool in pools:
            ids = {parse_qs(urlparse(member["href"]).query)["pool"][0]
                   for group in pool["groups"] for member in group["members"] if member["href"]}
            if len(ids) != 1:
                raise ValueError(f"Ambiguous displayed pool: {pool['title']}")
            pool["sourcePoolId"] = ids.pop()
        tables = collect_tables(page)
        result["panels"].append({"option": label, "pools": pools, "tables": tables})
    if entry["nodeCategoryId"] == "node_type_013":
        result["statisticsPanels"] = collect_shop_statistics(page)
    elif entry["nodeCategoryId"] == "node_type_004":
        result["statisticsPanels"] = collect_rogue_shop_statistics(page)
    if "statisticsPanels" in result:
        for panel in result["panels"]:
            panel["tables"] = []
    return result


def collect_sources(browser, catalog: dict, source_dir: Path) -> tuple[dict, dict, list[dict]]:
    context = browser.new_context(viewport={"width": 1440, "height": 1080})
    try:
        context.route("**/rumt-zh.com/**", lambda route: route.abort())
        archive = read_json(context.request, ARCHIVE_URL)
        battles = read_json(context.request, BATTLES_URL)
        page = context.new_page()
        page.goto(DIRECTORY_URL, wait_until="networkidle", timeout=30000)
        entries = page.locator(".compact-node-entry").evaluate_all(
            "elements => elements.map(e => ({name: e.innerText, href: e.getAttribute('href')}))"
        )
        local_nodes = {row["name"]: row["id"] for row in catalog["entries"] if row["category"] == "node_type"}
        if set(row["name"] for row in entries) != set(local_nodes):
            raise ValueError("Online node directory differs from the local ID catalog")
        pages = []
        for item in entries:
            entry = {"name": item["name"], "nodeCategoryId": local_nodes[item["name"]],
                     "sourceUrl": urljoin(DIRECTORY_URL, item["href"])}
            pages.append(collect_page(page, entry))
            print(f"Read {item['name']}: {len(pages[-1]['panels'])} selections", flush=True)
        observations = collect_battle_observations(page)
        source_dir.mkdir(parents=True, exist_ok=True)
        write_json(source_dir / "battle-observations.json", observations)
        for name, content in (("archive.json", archive), ("battles.json", battles), ("pages.json", pages)):
            write_json(source_dir / name, content)
        return archive, battles, pages
    finally:
        context.close()


def normalize_battle_observations(observations: list[dict]) -> list[dict]:
    observations = json.loads(json.dumps(observations))
    for row in observations:
        for group in row["rewardGroups"]:
            description = group.get("description") or ""
            match = re.search(r"([\d,]+)/([\d,]+)\s*场", description)
            prose_match = re.search(r"(\d+)场中(\d+)场", description)
            if match:
                count, total = (int(value.replace(",", "")) for value in match.groups())
            elif prose_match:
                total, count = map(int, prose_match.groups())
            else:
                continue
            if total <= 0 or not 0 <= count <= total:
                raise ValueError("Invalid battle reward observation denominator")
            group.update(occurrenceCount=count, sampleCount=total, probability=count / total)
    return observations


def collect_battle_observations(page) -> list[dict]:
    observations = []
    for stage_id in BATTLE_OBSERVATION_STAGES:
        url = f"https://www.lubiao.wiki/nodes/battle/rogue_6/{stage_id}"
        response = page.goto(url, wait_until="networkidle", timeout=30000)
        if response is None or response.status != 200:
            raise RuntimeError(f"Failed to load {url}")
        groups = page.locator(".battle-loot-row .battle-reward-group").evaluate_all(
            """elements => elements.map(e => ({
                items: [...e.querySelectorAll('.battle-reward-item')].map(i => ({
                    name: i.querySelector('.battle-reward-name').innerText,
                    quantity: Number(i.querySelector('.battle-reward-quantity').firstChild.textContent)
                })),
                probabilityText: e.querySelector('.battle-reward-probability')?.innerText ?? null,
                description: e.getAttribute('title')
            }))"""
        )
        if not groups:
            raise ValueError(f"No rendered battle rewards for {stage_id}")
        for group in groups:
            match = re.search(r"([\d,]+)/([\d,]+)\s*场", group["description"] or "")
            if match:
                count, total = (int(value.replace(",", "")) for value in match.groups())
                group.update(occurrenceCount=count, sampleCount=total, probability=count / total)
            else:
                group["probability"] = (float(group["probabilityText"].rstrip("%")) / 100
                                        if group["probabilityText"] else None)
            group["candidateCount"] = len(group["items"])
            group["takeCount"] = 1
        observations.append({"stageId": stage_id, "sourceUrl": url, "rewardGroups": groups,
                             "metadata": page.locator('.statistics-metadata').all_inner_texts()})
    return normalize_battle_observations(observations)


def build_payload(archive: dict, battles: dict, pages: list[dict], catalog: dict,
                  battle_observations: list[dict] | None = None) -> dict:
    pools = normalize_pools(archive, catalog)
    checked, differences = validate_rendered_pools(pools, pages)
    source_to_id = {row["sourcePoolId"]: row["id"] for row in pools}
    for node_id, prefix in (("node_type_006", "node_incident_"), ("node_type_008", "node_sacrifice_")):
        expected = {pool["sourcePoolId"] for pool in pools if pool["id"].startswith(prefix)}
        node = next(row for row in pages if row["nodeCategoryId"] == node_id)
        captured = {pool["sourcePoolId"] for panel in node["panels"] for pool in panel["pools"]}
        if expected - captured:
            raise ValueError(f"Reward options were not fully rendered for {node['name']}: {expected - captured}")
    reference_nodes = {
        "BATTLE_NORMAL": "node_type_001", "BATTLE_ELITE": "node_type_002",
        "BATTLE_BOSS": "node_type_003", "BATTLE_SAVAGE": "node_type_019",
        "WANDERING_RESIDENT": "node_type_021",
    }
    nodes = []
    for page in pages:
        pool_ids = {source_to_id[pool["sourcePoolId"]] for panel in page["panels"] for pool in panel["pools"]}
        for pool in pools:
            if any(reference_nodes.get(source_id) == page["nodeCategoryId"]
                   for reference in pool["sourceReferences"] for source_id in reference.get("sourceIds", [])):
                pool_ids.add(pool["id"])
        if page["nodeCategoryId"] == "node_type_009":
            pool_ids.add("pool_scrap_3")
        nodes.append({**page, "poolIds": sorted(pool_ids)})
    unresolved = sorted({row["name"] for pool in pools for row in pool["members"]
                         if row["itemId"] is None and row["dataType"] in {"藏品", "零件"}})
    if unresolved:
        raise ValueError(f"Reward members missing local item IDs: {unresolved}")
    definitions, contexts = compact_pools(pools)
    shared_ids = {row["id"]: row["rewardPoolId"] for row in contexts}
    for node in nodes:
        node["observationContextIds"] = node.pop("poolIds")
        node["rewardPoolIds"] = sorted({shared_ids[pool_id] for pool_id in node["observationContextIds"]})
        if node["nodeCategoryId"] == "node_type_019":
            node["rewardSelections"] = [
                {"rewardPoolId": shared_ids[context_id], "observationContextId": context_id,
                 "groupCount": 1, "candidateCount": 2, "takeCountPerGroup": 1,
                 "candidateSampling": None}
                for context_id in ("node_battle_savage_scrap_left", "node_battle_savage_scrap_right")
            ]
    return {
        "schemaVersion": 2, "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {"directoryUrl": DIRECTORY_URL, "archiveUrl": ARCHIVE_URL, "battlesUrl": BATTLES_URL},
        "meaning": "Conditional observed reward frequencies, not event occurrence or server generation weights",
        "renderedMembersChecked": checked, "renderedProbabilityDifferences": differences, "nodes": nodes,
        "rewardPools": definitions, "observationContexts": contexts,
        "stages": battles["stages"],
        "battleRewardObservations": normalize_battle_observations(battle_observations or []),
    }


def write_json(path: Path, value) -> None:
    if path.resolve() in PROTECTED:
        raise ValueError("Manually maintained Markdown cannot be overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def markdown_draft(data: dict) -> str:
    pools = expanded_pools(data)
    lines = ["## 12. 节点奖励候选池与统计分布", "",
             "物品沿用本手册的藏品、零件ID。概率为条件下的观测构成，不是节点或事件出现概率，也不是公开的服务器权重。二选一统计的是候选频次，不代表最后领取比例；没有频次的成员记为未知，不补0或等概率。", "",
             "同一次奖励的二选一共用物品池，记录为同池生成2个候选、领取1件，不拆成两个池。居民据点有两个不同的零件池，每池各二选一一次，共领取2件；不能把两个池取并集。成员清单相同的事件或节点共用一个池定义；奖励数量、候选数和领取数在各场景分别记录。不同统计范围的频次不直接累加，也不因共用清单就假定来源样本互不重叠。", "",
             "不同难度、楼层、来源的样本不擅自合并；统计限制在各池中保留。样本中的二选一数量与最终获得件数分别处理。三/五层领袖奖励数量相同，不代表三层N6统计已经验证五层或N15的抽取分布。", "",
             "商店按层级分别统计，表中使用完整子池的出现次数作为分母。网页把同名物品归入第一个展示分组后，会对该组剩余可见成员重新归一化；例如IV层仅展示两项时的70.73%/29.27%，不是这两项占完整IV层藏品池的比例。两种口径不混用。", "",
             "### 12.1 节点与奖励池对应", "", "| 节点ID | 节点 | 奖励池 |", "| --- | --- | --- |"]
    for node in data["nodes"]:
        pool_text = "、".join(f"`{value}`" for value in node.get("rewardPoolIds", observation_context_ids(node))) or "未列独立物品池；见节点效果"
        lines.append(f"| `{node['nodeCategoryId']}` | {node['name']} | {pool_text} |")
    lines += ["", "### 12.2 奖励池明细", "",
              "失与得输入池只列可投入成员，不视为随机输入奖励；输出池按所投入物品的稀有度分开。表中频次保留出现次数/观测分母，百分比只供阅读。未列出的事件固定奖励与默认策略仍按7、11.6处理，不推断它们没有收益。仅有单物品频次时，不能反推二选一组合的联合概率。", ""]
    shared = {}
    for pool in pools:
        if pool["displayCategory"] != "node" and not any(pool["id"] in observation_context_ids(node) for node in data["nodes"]):
            continue
        shared.setdefault(pool.get("rewardPoolId", pool["id"]), []).append(pool)

    def label(pool):
        node_names = "、".join(node["name"] for node in data["nodes"] if pool["id"] in observation_context_ids(node))
        return f"{node_names} / {pool['name']}" if node_names and node_names != pool["name"] else pool["name"]

    def append_statistics(pool, group):
        stats = group["statistics"]
        lines.append(f"样本：{stats.get('sampleCount', '未记录')}；抽取/候选记录：{stats.get('drawCount', '未记录')}；更新时间：{stats.get('updatedAt', pool['statistics'].get('updatedAt', '未记录'))}。")
        scope = stats.get("scopeLabel")
        if not scope:
            text = " ".join(str(stats.get(key, "")) for key in ("notes", "observationSource"))
            match = re.search(r"N\d+(?:[一二三四五六]层)?", text)
            scope = match.group() if match else "难度/层级未单独限定"
        lines.extend(["", f"统计范围：{scope}。"])
        if stats.get("displayNote"):
            lines.extend(["", stats["displayNote"]])
        if pool["id"] in {"node_battle_boss_recruit", "node_battle_boss_scrap", "pool_boss"}:
            lines.extend(["", "追猎与地图进入合并统计；希望硕果的额外零件单列。"])
        if pool["id"] == "node_battle_extra_scrap":
            lines.extend(["", "普通作战额外直接领取的单件零件，不与常规二选一候选合并。"])
        if pool["id"].startswith("node_wish_relic"):
            lines.extend(["", "包含少量三选一或其他多选项页面，分母为全部候选数，不是事件数或实际领取数。"])
        if group["name"] == "沙盘β冷却":
            lines.extend(["", "前页出现沙盘β后的下一页观测为0/1532；恢复资格后为1457/1554，属于出现率而非池内构成。"])
        selection = pool.get("selection")
        if selection:
            if selection["kind"] == "choose":
                extra = "；加成可能增加候选数" if selection.get("candidateCountMayVary") else ""
                lines.extend(["", f"领取规则：同池{selection['candidateCount']}选{selection['takeCount']}{extra}。"])
            elif selection["kind"] == "grant":
                lines.extend(["", f"领取规则：该选项直接获得{selection['takeCount']}件。"])
            elif selection["kind"].startswith("exchange"):
                verb = "投入" if selection["kind"] == "exchangeInput" else "获得"
                lines.extend(["", f"交换规则：单次{verb}{selection['takeCount']}件；两次交换分别按各自所投物品查池。"])

    def frequency(item):
        count, total = item["occurrenceCount"], item["totalOccurrenceCount"]
        return "未记录" if count is None else f"{count} / {total if total is not None else '未记录'}"

    def probability(item):
        return f"{item['probability'] * 100:.2f}%" if item["probability"] is not None else "未知"

    definitions = {row["id"]: row for row in data.get("rewardPools", [])}
    for shared_id, contexts in shared.items():
        lines += [f"#### {shared_id} " + "；".join(label(pool) for pool in contexts), ""]
        first = contexts[0]
        groups = first["subpools"] or [{"name": None, "statistics": first["statistics"], "members": first["members"]}]
        for group in groups:
            if group["name"]:
                lines += [f"**{group['name']}**", ""]
            for context in contexts:
                if len(contexts) > 1:
                    lines += [f"**{label(context)}**", ""]
                append_statistics(context, group if first["subpools"] else {"name": None, "statistics": context["statistics"]})
                lines += [""]
            header = ["物品ID", "名称"] + (["出现次数 / 观测分母", "条件频次"] if len(contexts) == 1 else [label(pool) for pool in contexts])
            lines += ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
            by_context = [{row["itemId"] or row["name"]: row for row in pool["members"]} for pool in contexts]
            members = definitions[shared_id]["members"] if len(contexts) > 1 else group["members"]
            for item in members:
                if item.get("metadataStatus") == "missing":
                    continue
                member_key = item["itemId"] or item["name"]
                observed = item if item.get("sourceItemIds") else next(rows[member_key] for rows in by_context if member_key in rows)
                cells = [f"`{item['itemId'] or observed['sourceItemIds'][0]}`", item["name"]]
                if len(contexts) == 1:
                    cells += [frequency(item), probability(item)]
                else:
                    for observations in by_context:
                        row = observations.get(item["itemId"] or item["name"])
                        cells.append(f"{frequency(row)}；{probability(row)}" if row else "未记录；未知")
                lines.append("| " + " | ".join(cells) + " |")
            lines += [""]
    seen_tables = set()
    lines += ["### 12.3 节点差分与补充统计", "",
              "诡意行商按层级/商品类别，秘境行商按店型、首次进入/刷新、可用层数筛选分别保存。货架配额的样本是货架数，零件类别/频次的样本是对应物品格位数，不互换分母。候选/陈列不等于玩家已获得物品。", ""]
    for node in data["nodes"]:
        for panel in node["panels"] + node.get("statisticsPanels", []):
            for table in panel["tables"]:
                key = json.dumps(table, ensure_ascii=False, sort_keys=True)
                if key in seen_tables:
                    continue
                seen_tables.add(key)
                title = " / ".join(value for value in (node["name"], panel["option"], table["title"]) if value)
                lines += [f"#### {title}", ""]
                for index, row in enumerate(table["rows"]):
                    cells = [text.replace("\n", "<br>").replace("|", "\\|") for text in row]
                    lines.append("| " + " | ".join(cells) + " |")
                    if index == 0:
                        lines.append("| " + " | ".join("---" for _ in cells) + " |")
                if table["metadata"]:
                    lines += ["", table["metadata"].replace("\n", "；")]
                lines += [""]
    lines += ["### 12.4 战斗奖励出现率", "",
              "下列是结算奖励出现率，和12.2的池内成员比例分开。代表页面复用的普通/紧急样本有其难度、楼层及筛选范围，不当作该关独立概率或N15服务器权重。额外零件与二选一可能同时出现，不能把两行概率当互斥结果相加。零件箱、宝箱的生成与条件完成率未由这些结算统计单独分离；额外现金缺统计时保持未知。", "",
              "| 代表关卡 | 奖励 | 领取方式 | 出现率 | 统计说明 |", "| --- | --- | --- | --- | --- |"]
    for row in data.get("battleRewardObservations", []):
        for group in row["rewardGroups"]:
            item = group["items"][0]
            rate = group["probability"]
            rate_text = f"{rate * 100:.2f}%" if rate is not None else "未知"
            rule = f"{group['candidateCount']}选1" if group["candidateCount"] > 1 else "直接获得"
            note = (group.get("description") or "页面固定奖励").replace("|", "\\|")
            lines.append(f"| `{row['stageId']}` | {item['quantity']}{item['name']} | {rule} | {rate_text} | {note} |")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", help="Read DOM and request metadata for a detail page")
    parser.add_argument("--inspect-json", help="Inspect a public JSON response loaded by the page")
    parser.add_argument("--save-source", type=Path, help="Save the inspected JSON for offline parsing")
    parser.add_argument("--executable")
    parser.add_argument("--offline", type=Path, help="Source directory with archive.json, battles.json, pages.json")
    parser.add_argument("--refresh-node", help="Refresh one node page when reusing --offline sources")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-draft", type=Path, help="Write a separate draft, never the handbook itself")
    args = parser.parse_args()
    if args.output.resolve() in PROTECTED or (args.markdown_draft and args.markdown_draft.resolve() in PROTECTED):
        parser.error("Manually maintained Markdown cannot be overwritten; use a separate draft")
    if args.refresh_node and not args.offline:
        parser.error("--refresh-node requires --offline")
    catalog = json.loads((ROOT / "data" / "lubiao_reference_catalog.json").read_text(encoding="utf-8"))
    if args.offline:
        archive, battles, pages = [json.loads((args.offline / name).read_text(encoding="utf-8"))
                                   for name in ("archive.json", "battles.json", "pages.json")]
        if args.refresh_node:
            from playwright.sync_api import sync_playwright
            from scripts.playwright_browser import chromium_executable

            index = next(index for index, row in enumerate(pages) if row["nodeCategoryId"] == args.refresh_node)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=chromium_executable(args.executable))
                try:
                    entry = {key: pages[index][key] for key in ("name", "nodeCategoryId", "sourceUrl")}
                    pages[index] = collect_page(browser.new_page(), entry)
                finally:
                    browser.close()
            write_json(args.offline / "pages.json", pages)
    else:
        from playwright.sync_api import sync_playwright
        from scripts.playwright_browser import chromium_executable

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=chromium_executable(args.executable))
            try:
                if not args.inspect and not args.inspect_json:
                    archive, battles, pages = collect_sources(browser, catalog, args.source_dir)
                else:
                    page = browser.new_page(viewport={"width": 1440, "height": 1080})
                    if args.inspect_json:
                        response = page.request.get(args.inspect_json)
                        if response.status != 200:
                            raise RuntimeError(f"Failed to read {args.inspect_json}")
                        if args.inspect_json.endswith(".js"):
                            body = response.text()
                            print(body[:18000] + "\nEND\n" + body[-1200:])
                        else:
                            data = response.json()
                            if args.save_source:
                                write_json(args.save_source, data)
                            print(json.dumps(describe(data, 6), ensure_ascii=False, indent=2))
                    else:
                        print(json.dumps(inspect_page(page, args.inspect), ensure_ascii=False, indent=2))
                    return
            finally:
                browser.close()
    source_dir = args.offline or args.source_dir
    observations_path = source_dir / "battle-observations.json"
    battle_observations = (json.loads(observations_path.read_text(encoding="utf-8"))
                           if observations_path.exists() else [])
    payload = build_payload(archive, battles, pages, catalog, battle_observations)
    draft = markdown_draft(payload) if args.markdown_draft else None
    write_json(args.output, payload)
    if args.markdown_draft:
        if args.markdown_draft.resolve() in PROTECTED:
            raise ValueError("Write a separate draft; handbook edits must be manual")
        args.markdown_draft.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_draft.write_text(draft, encoding="utf-8")
    print(f"Saved {len(payload['rewardPools'])} shared definitions / {len(payload['observationContexts'])} observation contexts; "
          f"checked {payload['renderedMembersChecked']} rendered members; {args.output}")


if __name__ == "__main__":
    main()
