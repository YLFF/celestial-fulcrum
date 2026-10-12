"""Budgeted first-action alternatives, independent of global route ranking."""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, replace
from time import perf_counter

from .movement_rules import COMBAT_CATEGORIES
from .node_scoring import SnapshotScorer
from .route_allocation import GeometryCache, MoveChoice, MovementAllocator
from .route_planner import END_CATEGORY, RoutePlanner, SCORE_SCALE, _State, _bit

UNKNOWN = {"unknown_mystery", "unknown_ferocity"}


@dataclass(frozen=True)
class _Prefix:
    state: _State
    steps: tuple = ()
    preference: tuple = ()


class _AdviceGeometry(RoutePlanner):
    def _visible_after(self, position, done, visible, first_lookout):
        # Known remote clearings are not independent exploration origins.
        visible |= _bit(position)
        if first_lookout is not None:
            visible |= self.lookout_masks[first_lookout][1]
        transparent = done | self.clearing_mask
        pending, visited = [position], 0
        while pending:
            current = pending.pop()
            bit = _bit(current)
            if visited & bit or not transparent & bit:
                continue
            if current != position and self.nodes[current].category == END_CATEGORY:
                continue
            visited |= bit
            for neighbor in self.adjacent[current]:
                visible |= _bit(neighbor)
                if transparent & _bit(neighbor):
                    pending.append(neighbor)
        return visible


class DecisionAdvisor:
    """Use shared utilities, but keep score, information and goals separate."""

    def __init__(self, game_map, inputs, *, on_expand=None):
        self.inputs = deepcopy(inputs)
        self.planner = p = _AdviceGeometry(game_map)
        p._configure_lookout_visibility(inputs)
        self.scorer = p.scorer = SnapshotScorer(p.raw_nodes, inputs["scoringContext"], inputs)
        p.planning_targets = deepcopy(inputs.get("planningTargets", []))
        context = inputs["scoringContext"]
        if context.get("areaKey") == "V" and context.get("goals", {}).get("endingV") in {"normal1", "pursuit1"}:
            p.exit_nodes = frozenset(i for i, node in enumerate(p.nodes) if node.category == "node_type_003")
        self.items, _ = p._items(inputs)
        self.groups, self.portals = p._item_groups(self.items), p._portal_pairs(inputs)
        self.blocked = p._indices(inputs.get("blockedNodes", []), "blockedNodes")
        targets = tuple(tuple(tuple(i for i, node in enumerate(p.nodes)
            if item.rule.reaches(source.coord, node.coord, node.category, True)
            or item.rule.target == "noncombat" and item.rule.reaches(source.coord, node.coord, "node_type_020", True))
            for source in p.nodes) for item in self.items)
        self.allocator = MovementAllocator(p.nodes, p.adjacent, self.items, targets,
                                           tuple(sum(map(len, rows)) for rows in targets))
        self.geometry = GeometryCache(p.nodes, self.portals, p._visible_after)
        self.free_slots = inputs.get("componentBoxFreeSlots", max(0, self.scorer.capacity - len(self.scorer.components)))
        position = p.index[inputs["position"]]
        if position in self.blocked:
            raise ValueError("当前位置不能被设为不可前往")
        done = sum(_bit(i) for i in p._indices(inputs["completedNodes"], "completedNodes"))
        p.initial_done = done
        visible = sum(_bit(i) for i in p._indices(inputs.get("revealedNodes", inputs["completedNodes"]), "revealedNodes")) | done
        visible = p._initial_visibility(position, done, visible)
        ap = min(inputs["actionPoints"], 1) if inputs.get("utopiaId") == "utopia_005" else inputs["actionPoints"]
        self.initial = _State(position, ap, done, visible, 0, tuple(item.uses for item in self.items),
            prefix_cash=self.scorer.cash, prefix_appraisal=self.scorer.initial_appraisal,
            investment_balance=self.scorer.investment_balance,
            merchant_shelves=tuple(self.scorer.merchant_shelves[node.id] for node in p.nodes))
        self.on_expand = on_expand
        self.transitions = self.discarded = self.exit_expanded = 0
        self.exit_cache, self.progress_cache = {}, {}

    def choices(self, state, *, for_exit=False):
        if state.action_points <= 0:
            return
        free = self.free_slots + sum(item.uses > 0 and uses == 0 for item, uses in zip(self.items, state.uses))
        choices, last_ap = self.allocator.choices(state.position, state.uses, state.action_points,
                                                 state.done, state.visible, free, grouped=True)
        seen = set()
        for choice in choices:
            arrival = self.portals.get(choice.entry, choice.entry)
            if choice.entry in self.blocked or arrival in self.blocked or choice.cost > state.action_points:
                continue
            if (self.inputs.get("pursuit") and not for_exit and self.inputs.get("utopiaId") != "utopia_005"
                    and arrival in self.planner.exit_nodes and self.planner.nodes[arrival].category != END_CATEGORY):
                continue
            item = self.items[choice.item_index] if choice.item_index is not None else None
            signature = (choice.entry, item.rule if item else None,
                         state.uses[choice.item_index] if item else None, item.estimated_value if item else None)
            if signature in seen:
                continue
            seen.add(signature)
            if choice.kind == "reenter" and self.planner.nodes[choice.entry].category == END_CATEGORY and not self.inputs.get("pursuit"):
                effect = self.scorer.policy_effect(self.planner.nodes[choice.entry].id,
                    state.prefix_cash + state.economy_movements * self.scorer.step_ingot,
                    self.done_ids(state))
                if not effect or effect["points"] <= 0:
                    continue
            yield choice, self.allocator.preference(choice, state.uses, free, last_ap)

    def done_ids(self, state):
        return {n.id for i, n in enumerate(self.planner.nodes) if state.done & _bit(i)}

    def move(self, state, choice, *, score=True):
        p = self.planner
        arrival = self.portals.get(choice.entry, choice.entry)
        _, lookout, done, visible, newly = self.geometry.resolve(choice.entry, state.done, state.visible)
        remaining = list(state.uses)
        item = self.items[choice.item_index] if choice.item_index is not None else None
        exhausted = item is not None and remaining[choice.item_index] == 1
        if item:
            remaining[choice.item_index] -= 1
        after = replace(state, position=arrival, action_points=state.action_points - choice.cost + choice.gain + int(lookout is not None),
            done=done, visible=visible, information=state.information | newly,
            uses=tuple(remaining), movements=state.movements + 1)
        step = {"from": p.nodes[state.position].id, "entered": p.nodes[choice.entry].id, "arrived": p.nodes[arrival].id,
                "itemInstanceId": item.instance_id if item else None, "componentId": item.component_id if item else None,
                "movement": choice.kind, "actionPointsAfter": after.action_points,
                "actionPointsCost": choice.cost, "actionPointsGain": choice.gain + int(lookout is not None),
                "portalTransfer": choice.entry != arrival, "newlyRevealedNodeIds": [n.id for i, n in enumerate(p.nodes) if newly & _bit(i)]}
        if not score:
            return after, step
        self.transitions += 1
        if self.on_expand:
            self.on_expand({"expandedStates": self.transitions})
        cash = state.prefix_cash + (item.rule.ingot_gain if item else 0)
        appraisal = max(0, state.prefix_appraisal - (item.estimated_value or 0) * state.retained_appraisal_fraction) if exhausted else state.prefix_appraisal
        box = len(self.scorer.components) - sum(i.uses > 0 and u == 0 for i, u in zip(self.items, state.uses)) - int(exhausted)
        value = self.scorer.step([p.nodes[i].id for i in dict.fromkeys((choice.entry, arrival))],
            {p.nodes[i].id for i in (choice.entry, arrival) if not state.done & _bit(i)}, step["newlyRevealedNodeIds"],
            before_done=self.done_ids(state), prefix_cash=cash, appraisal=appraisal, path_steps=state.economy_movements + 1,
            processing=item is not None, box_count=box, investment_balance=state.investment_balance,
            merchant_shelves={n.id: state.merchant_shelves[i] for i, n in enumerate(p.nodes)})
        # Future-information proxy is disclosed, not also cashed in by the rollout.
        income = value["nodeValue"] + value["recruitmentValue"]
        economy = value["merchantTransition"]
        after = replace(after, score_units=state.score_units + round(income * SCORE_SCALE),
            prefix_cash=round(economy["cashAfter"], 6), prefix_appraisal=round(economy["appraisalAfter"], 6),
            economy_movements=round(economy["movementProxyStepsAfter"], 6),
            investment_balance=round(economy["investmentBalanceAfter"], 6),
            merchant_shelves=tuple(economy["viewedShelvesAfter"][n.id] for n in p.nodes),
            retained_appraisal_fraction=round(state.retained_appraisal_fraction * economy["retainedAppraisalFraction"], 6))
        step.update(weightedValue=round(income, 2), revealValue=round(value["revealValue"], 2),
                    revealTerms=value["revealTerms"], scoreDetails=value,
                    referenceLossPoints=value.get("referenceLossPoints", 0))
        if p.nodes[arrival].category in {"node_type_015", "node_type_016"} and not self.inputs.get("pursuit"):
            terminal = self.scorer.terminal(p.nodes[arrival].id, after.action_points, pursuit=False, done=self.done_ids(after))
            after = replace(after, score_units=after.score_units + round(terminal["points"] * SCORE_SCALE))
            step["terminalScore"] = terminal
            step["weightedValue"] += terminal["points"]
        if after.action_points == 0 and self.inputs.get("pursuit") and self.inputs.get("utopiaId") != "utopia_005":
            terminal = self.scorer.terminal(p.nodes[arrival].id, 0, pursuit=True, done=self.done_ids(after))
            after = replace(after, score_units=after.score_units + round(terminal["points"] * SCORE_SCALE))
            step.update(pursuitTriggered=True, terminalScore=terminal)
            step["weightedValue"] += terminal["points"]
        if arrival in p.treehole_nodes and after.action_points > 0 and any(after.uses):
            terminal = self.scorer.terminal(p.nodes[arrival].id, after.action_points, pursuit=False, treehole=True)
            after = replace(after, score_units=after.score_units + round(terminal["points"] * SCORE_SCALE))
            step.update(treeholeChoicePending=True, terminalScore=terminal)
            step["weightedValue"] += terminal["points"]
        return after, step

    def stopped(self, prefix):
        return prefix.state.action_points <= 0 or bool(prefix.steps and
            (self.inputs.get("utopiaId") == "utopia_005" or prefix.steps[-1].get("treeholeChoicePending")
             or prefix.state.position in self.planner.exit_nodes
             and (not self.inputs.get("pursuit") or self.planner.nodes[prefix.state.position].category != END_CATEGORY)))

    def spent_flexible(self, state):
        return sum(item.uses - count for item, count in zip(self.items, state.uses)
                   if item.allowed and item.rule.shape == "any" and item.rule.deterministic)

    def progress(self, state):
        key = state.done, state.information
        if key not in self.progress_cache:
            self.progress_cache[key] = self.planner._prerequisite_progress(state)
        return self.progress_cache[key]

    def rank(self, prefix, policy):
        income = prefix.state.score_units
        if policy == "mobility":
            return (-self.spent_flexible(prefix.state), income, prefix.state.action_points)
        if policy == "information":
            useful = sum(self.scorer.values[n.id]["points"] > 0 for i, n in enumerate(self.planner.nodes)
                         if prefix.state.information & _bit(i))
            return (useful, income, -self.spent_flexible(prefix.state))
        if policy.startswith("goal:"):
            target = next(row for row in self.progress(prefix.state) if row["id"] == policy[5:])
            return (target["plannedCompletion"], target["searchCoverage"], income, -self.spent_flexible(prefix.state))
        return (income, -self.spent_flexible(prefix.state), prefix.state.action_points)

    def retain(self, values, policies, width):
        unique = {}
        for prefix in values:
            key = self.planner._state_key(prefix.state, self.groups)
            old = unique.get(key)
            if old is None or (prefix.state.score_units, tuple(-v for v in prefix.preference[-1])) > (
                    old.state.score_units, tuple(-v for v in old.preference[-1])):
                unique[key] = prefix
        queues = [sorted(unique.values(), key=lambda p: self.rank(p, policy), reverse=True) for policy in policies]
        selected, seen = [], set()
        for offset in range(min(width, len(unique))):
            for queue in queues:
                prefix = queue[offset]
                key = self.planner._state_key(prefix.state, self.groups)
                if key not in seen:
                    selected.append(prefix)
                    seen.add(key)
                    if len(selected) >= width:
                        self.discarded += len(unique) - len(selected)
                        return selected
        return selected

    def exit_status(self, state, limit=350):
        if state.position in self.planner.treehole_nodes and state.action_points > 0 and any(state.uses):
            return {"status": "transfer_boundary", "steps": []}
        stamp = lambda s: (s.position, s.action_points, s.done, s.visible, s.uses)
        key = stamp(state)
        if key in self.exit_cache:
            return self.exit_cache[key]
        queue, seen = deque([(state, ())]), set()
        while queue:
            current, path = queue.popleft()
            if current.position in self.planner.exit_nodes:
                result = {"status": "reachable", "steps": list(path), "remainingActionPoints": current.action_points}
                break
            identity = stamp(current)
            if identity in seen:
                continue
            if len(seen) >= limit:
                return {"status": "undetermined", "steps": []}
            seen.add(identity)
            self.exit_expanded += 1
            if self.on_expand:
                self.on_expand({"exitCheck": True})
            for choice, _ in self.choices(current, for_exit=True):
                if self.planner.nodes[choice.entry].category in UNKNOWN and not current.done & _bit(choice.entry):
                    continue
                after, step = self.move(current, choice, score=False)
                queue.append((after, (*path, step)))
        else:
            result = {"status": "no_known_exit", "steps": []}
        self.exit_cache[key] = result
        return result

    def random_targets(self):
        nodes, state = self.planner.nodes, self.initial
        unknown = [i for i, n in enumerate(nodes) if n.base_category == "unknown_mystery" and not state.done & _bit(i)]
        if unknown:
            return unknown, "unknown_mystery"
        valid = [i for i, n in enumerate(nodes) if ("node_type_020" if state.done & _bit(i)
                 and not n.repeatable else n.effective_category) not in COMBAT_CATEGORIES | {None, "unreadable"}]
        fresh = [i for i in valid if not state.done & _bit(i)]
        return (fresh, "unvisited_noncombat") if fresh else (valid, "all_noncombat")

    def summarize(self, prefix):
        return {"steps": [{key: value for key, value in step.items() if key != "scoreDetails"} for step in prefix.steps],
                "points": round(prefix.state.score_units / SCORE_SCALE, 2),
                "remainingActionPoints": prefix.state.action_points, "flexibleUsesSpent": self.spent_flexible(prefix.state),
                "goals": deepcopy(self.progress(prefix.state)), "remainingItems": [
                    {"instanceId": item.instance_id, "componentId": item.component_id, "remainingUses": uses}
                    for item, uses in zip(self.items, prefix.state.uses) if uses > 0]}

    def plan(self):
        started = perf_counter()
        budget = self.inputs.get("maxStates", 50000)
        if type(budget) is not int or not 1 <= budget <= 500000:
            raise ValueError("路径搜索上限必须为1至500000的整数")
        top = self.inputs.get("topN", 5)
        if type(top) is not int or not 1 <= top <= 50:
            raise ValueError("显示数量必须为1至50的整数")
        policies = ["income", "mobility", "information", *["goal:" + t["id"] for t in self.planner.planning_targets]]
        horizon = min(6, max(3, self.initial.action_points + 1))
        width = max(8, len(policies) * 2)
        actions, frontiers, histories = [], [], []
        for choice, preference in self.choices(self.initial):
            actions.append({"choice": choice, "preference": preference})
        random_index = next((i for i, item in enumerate(self.items)
                             if item.component_id == "component_019" and self.initial.uses[i]), None)
        random_basis = None
        if random_index is not None and self.initial.action_points > 0:
            targets, random_basis = self.random_targets()
            actions.extend({"choice": MoveChoice("random", i, random_index, 0, 0), "preference": (), "random": True}
                           for i in targets if i not in self.blocked and self.portals.get(i, i) not in self.blocked)
        # A small budget never silently drops legal first actions.
        root_budget = len(actions)
        for action in actions:
            state, step = self.move(self.initial, action["choice"])
            prefix = _Prefix(state, (step,), (action["preference"],))
            frontiers.append([prefix])
            histories.append([prefix])
        exhausted = root_budget > budget
        depth = 1
        for depth in range(2, horizon + 1):
            next_frontiers = []
            changed = False
            quota = max(0, (budget - self.transitions) // max(1, len(actions)))
            for index, frontier in enumerate(frontiers):
                candidates, used = [], 0
                for prefix in frontier:
                    if self.stopped(prefix):
                        continue
                    for choice, preference in self.choices(prefix.state):
                        if used >= quota:
                            exhausted = True
                            break
                        after, step = self.move(prefix.state, choice)
                        candidates.append(_Prefix(after, (*prefix.steps, step), (*prefix.preference, preference)))
                        used += 1
                    if used >= quota:
                        break
                kept = self.retain(candidates, policies, width)
                next_frontiers.append(kept)
                histories[index].extend(kept)
                changed |= bool(kept)
            frontiers = next_frontiers
            if not changed or self.transitions >= budget:
                break

        rows = []
        random_rows = []
        for action, candidates in zip(actions, histories):
            root = candidates[0]
            alternatives = {policy: max(candidates, key=lambda p: self.rank(p, policy)) for policy in policies}
            options = []
            for policy, prefix in alternatives.items():
                summary = self.summarize(prefix)
                summary["policy"] = policy
                options.append(summary)
            first = root.steps[0]
            exit_result = self.exit_status(root.state)
            information = []
            next_targets = {self.planner.nodes[c.entry].id for c, _ in self.choices(root.state)} if not self.stopped(root) else set()
            for term in first["revealTerms"]:
                values = self.scorer.values[term["nodeId"]].get("types", [])
                information.append({**term, "reachableNext": term["nodeId"] in next_targets,
                    "scoreRange": [round(min((v["score"]["points"] for v in values), default=0), 2),
                                   round(max((v["score"]["points"] for v in values), default=0), 2)]})
            goals = self.progress(root.state)
            related = sorted({g["id"] for option in options for g in option["goals"] if g["related"]})
            row = {"id": f"{first['entered']}:{first['itemInstanceId'] or 'walk'}", "firstStep": first,
                "firstPoints": first["weightedValue"], "revealPoints": first["revealValue"],
                "lookaheadPoints": alternatives["income"].state.score_units / SCORE_SCALE,
                "information": information, "goals": deepcopy(goals), "relatedGoalIds": related,
                "continuations": options, "exitCheck": exit_result, "labels": [],
                "remainingActionPoints": root.state.action_points, "remainingItems": self.summarize(root)["remainingItems"],
                "flexibleUsesSpent": self.spent_flexible(root.state), "random": bool(action.get("random"))}
            reasons = ["徒步前往，不消耗加工品。" if not first["componentId"] else "使用一次加工品移动，按剩余库存推演后续。"]
            if information:
                reachable = sum(r["reachableNext"] for r in information)
                reasons.append(f"新揭示{len(information)}个未知节点，其中{reachable}个可用剩余资源下一步前往；揭示分单列，不重复加入推演收益。")
            if any(g["related"] for g in goals):
                reasons.append("本步可经过或揭示优先项候选位置；探索覆盖不等于完成概率。")
            if first["entered"] in {n.id for n in self.planner.nodes if n.category in {"node_type_004", "node_type_013"}}:
                reasons.append("进店价值按现有经济函数估计；不预支商店购入的移动能力。")
            if first["referenceLossPoints"] < 0:
                reasons.append(f"上贡资源参考损失{first['referenceLossPoints']:.1f}分，软优先目标的该损失不计入排序。")
            if first.get("treeholeChoicePending"):
                reasons.append("误入奇境收益为进入树洞的行动力机会值，需再交出一件加工品；进入后重新规划，不推演返回主层。")
            row["reasons"] = reasons
            (random_rows if action.get("random") else rows).append(row)

        selected = []
        def choose(label, pool, key):
            if not pool:
                return
            winner = max(pool, key=key)
            winner["labels"].append(label)
            if winner not in selected:
                selected.append(winner)
        viable = rows if self.inputs.get("pursuit") else [r for r in rows if r["exitCheck"]["status"] in {"reachable", "transfer_boundary"}] or rows
        choose("发育收益", viable, lambda r: (r["lookaheadPoints"], r["firstPoints"], -r["flexibleUsesSpent"]))
        choose("就近步行", [r for r in viable if not r["firstStep"]["componentId"] and r["firstPoints"] > 0],
               lambda r: (r["lookaheadPoints"], r["firstPoints"]))
        if any(item.allowed and item.rule.shape == "any" and item.rule.deterministic for item in self.items):
            choose("保留传送", viable, lambda r: (-r["flexibleUsesSpent"], r["lookaheadPoints"]))
        for target in self.planner.planning_targets:
            def goal_rank(row):
                option = next(o for o in row["continuations"] if o["policy"] == "goal:" + target["id"])
                goal = next(g for g in option["goals"] if g["id"] == target["id"])
                return goal["plannedCompletion"], goal["searchCoverage"], option["points"], row["firstPoints"]
            choose(target["name"], [r for r in viable if target["id"] in r["relatedGoalIds"]], goal_rank)
        choose("探明再决定", [r for r in viable if r["information"]],
               lambda r: (sum(i["reachableNext"] for i in r["information"]), r["lookaheadPoints"]))
        risk = [r for r in rows if r["exitCheck"]["status"] in {"no_known_exit", "undetermined"}]
        if risk and (not viable or max(r["lookaheadPoints"] for r in risk) > max(r["lookaheadPoints"] for r in viable)):
            choose("离层待确认", risk, lambda r: r["lookaheadPoints"])
        for row in sorted(rows, key=lambda r: (r["lookaheadPoints"], r["firstPoints"]), reverse=True):
            if row not in selected:
                selected.append(row)
        # Keep all alternatives server-side so priority filters don't lose candidates.
        random = None
        if random_rows:
            probability = 1 / len(random_rows)
            for row in random_rows:
                row["probability"] = probability
            random = {"id": "little-eight", "random": True, "labels": ["小八戒随机转移"],
                "basis": random_basis, "branches": random_rows, "relatedGoalIds": sorted({g for r in random_rows for g in r["relatedGoalIds"]}),
                "firstPoints": sum(r["firstPoints"] * probability for r in random_rows),
                "lookaheadPoints": sum(r["lookaheadPoints"] * probability for r in random_rows),
                "exitCoverage": sum(probability for r in random_rows if r["exitCheck"]["status"] == "reachable")}
            selected.insert(min(2, len(selected)), random)
        # Only displayed policy representatives need constructive continuation receipts.
        reviewed = selected[:top] + [r for r in selected if r.get("labels") and not r.get("random")]
        for row in reviewed:
            branches = row["branches"] if row.get("random") else [row]
            for branch in branches:
                index = next(i for i, action in enumerate(actions)
                             if self.planner.nodes[action["choice"].entry].id == branch["firstStep"]["entered"]
                             and (self.items[action["choice"].item_index].instance_id if action["choice"].item_index is not None else None)
                             == branch["firstStep"]["itemInstanceId"])
                for option in branch["continuations"]:
                    prefix = max(histories[index], key=lambda p: self.rank(p, option["policy"]))
                    option["exitStatus"] = self.exit_status(prefix.state)["status"]
        return {"mode": "advice", "suggestions": selected, "priorityTargets": deepcopy(self.planner.planning_targets),
            "searchComplete": not exhausted, "expandedStates": self.transitions,
            "metrics": {"seconds": round(perf_counter() - started, 3), "firstActions": len(rows),
                        "randomLandings": len(random_rows), "maxDepth": max((len(p.steps) for rows in histories for p in rows), default=0), "beamWidth": width,
                        "beamDiscarded": self.discarded, "exitStates": self.exit_expanded,
                        "rootBudgetOverrun": max(0, root_budget - budget)},
            "method": {"version": "first-action-v1", "nodeWeightsChanged": False, "revealIncludedInRollout": False,
                       "rewardInventorySimulated": False, "jointOutcomeSimulation": False},
            "limitations": ["后续方向按当前库存及节点期望分推演，不预支随机奖励；不是整层最优路线。",
                            "离层检查只验证当前已知节点的可行走法；未找到不代表游戏中无法离层。",
                            "揭示分仅作参考；未知节点揭示后的联合概率更新尚未进行随机模拟。",
                            "不同目标的建议分别比较，不给前置、追猎风险与发育收益强行设置兑换权重。"]}


def advise(game_map, inputs, *, on_expand=None):
    return DecisionAdvisor(game_map, inputs, on_expand=on_expand).plan()
