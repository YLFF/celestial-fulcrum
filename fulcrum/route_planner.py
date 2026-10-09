from __future__ import annotations

import heapq
import math
from dataclasses import astuple, dataclass
from functools import lru_cache
from typing import Any, Callable, Mapping

from .map_catalog import TemplateCatalog
from .movement_rules import MOVEMENT_RULES, MovementRule
from .route_frontier import InventoryFrontier, ScoredInventoryFrontier
from .node_scoring import SnapshotScorer
from .route_allocation import GeometryCache, MovementAllocator, TrajectoryPool, item_preference
from .goals import planning_pursuit
from .lookout_rules import lookout_radii
from .scoring_profile import PROFILE
from .diagnostics import localize_result, message


EXIT_CATEGORIES = {"node_type_003", "node_type_015", "node_type_016"}
EXIT_HINTS = {"danger-enemy", "danger-end", "danger-path"}
NO_NODE_REWARD = {None, "start", "node_type_003", "node_type_010", "node_type_014",
                  "node_type_015", "node_type_016", "node_type_018", "node_type_020"}
REPEATABLE_CATEGORIES = {"node_type_004", "node_type_013", "node_type_014",
                         "node_type_015", "node_type_016"}
LOOKOUT_CATEGORY = "node_type_018"
TREEHOLE_CATEGORY = "node_type_010"
PORTAL_CATEGORY = "node_type_014"
MYSTERY_CATEGORY = "unknown_mystery"
FEROCITY_CATEGORY = "unknown_ferocity"
SCORE_SCALE = PROFILE["search"]["scoreScale"]
END_CATEGORY = "node_type_015"
EXIT_HINT_CATEGORIES = {"danger-enemy": "node_type_003", "danger-end": END_CATEGORY,
                        "danger-path": "node_type_016"}


@lru_cache(maxsize=1)
def _template_terminals() -> dict[str, dict[tuple[int, int], str]]:
    return {
        template.id: {(template.coord(slot).x, template.coord(slot).y): template.terminal_type
                      for slot in template.terminal_slots}
        for template in TemplateCatalog().templates
    }


@dataclass(frozen=True)
class _Node:
    id: str
    coord: tuple[int, int]
    category: str | None
    revealed: bool
    terminal: bool
    base_category: str | None
    marks: tuple[str, ...]
    recruitment_units: int = 0
    fate_role: str = "unknown"

    @property
    def lookout(self) -> bool:
        return self.base_category == LOOKOUT_CATEGORY

    @property
    def effective_category(self) -> str | None:
        return "node_type_021" if "node_mark_001" in self.marks else self.category

    @property
    def repeatable(self) -> bool:
        if self.category == "node_type_012":
            return self.fate_role == "true"
        return self.category in REPEATABLE_CATEGORIES


def _node_from_map(raw: Mapping[str, Any], template_hint: str | None = None) -> _Node:
    marks = tuple(sorted(set(raw.get("confirmedMarkIds", [])) | {
        mark["id"] for mark in raw.get("marks", []) if mark.get("status") == "confirmed"
    }))
    category = raw.get("categoryId")
    base_category = category
    hint = raw.get("templateHint") or template_hint
    if category in (None, MYSTERY_CATEGORY, FEROCITY_CATEGORY, "node_type_020") and hint in EXIT_HINTS:
        category = EXIT_HINT_CATEGORIES[hint]
    if "node_mark_003" in marks and category in (None, MYSTERY_CATEGORY, FEROCITY_CATEGORY, "node_type_020"):
        category = "node_type_012"
    recruitment = raw.get("recruitmentScore", 0)
    if (isinstance(recruitment, bool) or not isinstance(recruitment, (int, float))
            or not math.isfinite(recruitment) or recruitment < 0):
        raise ValueError("recruitmentScore must be a finite nonnegative number")
    if recruitment and category != END_CATEGORY:
        raise ValueError("recruitmentScore is only supported at danger-end nodes")
    resident = "node_mark_001" in marks
    fate_role = raw.get("fateRole", "true" if "node_mark_003" in marks else "unknown")
    if fate_role not in {"unknown", "true", "fake"}:
        raise ValueError("invalid fate role")
    if fate_role != "unknown" and category != "node_type_012":
        raise ValueError("fate role requires a fate node")
    if "node_mark_003" in marks:
        if fate_role == "fake":
            raise ValueError("fake fate node conflicts with truth mark")
        fate_role = "true"
    if resident and (category in REPEATABLE_CATEGORIES
                     or category == "node_type_012" and fate_role != "fake"):
        raise ValueError("resident mark cannot occupy a repeatable node; confirm the map")
    return _Node(
        id=str(raw["id"]), coord=(int(raw["coord"][0]), int(raw["coord"][1])),
        category=category,
        revealed=raw.get("visibility") == "revealed",
        terminal=category in EXIT_CATEGORIES or hint in EXIT_HINTS,
        base_category=base_category, marks=marks,
        recruitment_units=round(recruitment * SCORE_SCALE),
        fate_role=fate_role,
    )


@dataclass(frozen=True)
class _Item:
    instance_id: str
    component_id: str
    uses: int
    rule: MovementRule
    allowed: bool
    estimated_value: int | None = None


@dataclass(frozen=True)
class _State:
    position: int
    action_points: int
    done: int
    visible: int
    information: int
    uses: tuple[int, ...]
    score_units: int = 0
    prefix_cash: float = 0.0
    prefix_appraisal: float = 0.0
    movements: int = 0
    economy_movements: float = 0.0
    investment_balance: float = 0.0
    merchant_shelves: tuple[int, ...] = ()
    retained_appraisal_fraction: float = 1.0


@dataclass(frozen=True)
class _Label:
    state: _State
    parent: int | None
    step: dict[str, Any] | None
    trajectory: int = 0
    preference: tuple[tuple[int, ...], ...] = ()


@dataclass(frozen=True)
class _Candidate:
    label_index: int
    goal_id: str
    metrics: tuple[int, ...]
    area_exit: bool = False
    treehole_item_index: int | None = None
    trajectory: int | None = None
    preference: tuple[tuple[int, ...], ...] = ()
    prerequisite_rank: tuple[int, int] = (0, 0)
    relevance_mask: int = 0


def _bit(index: int) -> int:
    return 1 << index


def _dominates(left: tuple[int, ...], right: tuple[int, ...]) -> bool:
    return all(a >= b for a, b in zip(left, right)) and any(a > b for a, b in zip(left, right))


def _allocation_rank(value):
    return (*(-v for v in value.prerequisite_rank), -value.metrics[0], value.preference, tuple(-v for v in value.metrics[1:]))


def _candidate_rank(value):
    return (*(-v for v in value.prerequisite_rank), *(-v for v in value.metrics))


class RoutePlanner:
    """Enumerate executable route states and rank Pareto routes by known node value."""

    def __init__(self, map_result: Mapping[str, Any]) -> None:
        if not map_result.get("success") or not map_result.get("nodes"):
            raise ValueError("route planning requires a confirmed, matched map")
        raw_nodes = map_result["nodes"]
        terminals = _template_terminals().get(map_result.get("templateId"), {})
        self.nodes = tuple(_node_from_map(raw, terminals.get(tuple(raw["coord"]))) for raw in raw_nodes)
        self.template_knowledge = [
            {"nodeId": node.id, "categoryId": node.category, "source": "matched_template",
             "gameVisibility": raw.get("visibility")}
            for raw, node in zip(raw_nodes, self.nodes) if raw.get("categoryId") != node.category
        ]
        self.recruitment_scores = tuple((i, node.recruitment_units) for i, node in enumerate(self.nodes)
                                        if node.recruitment_units)
        self.unconfigured_recruitment = tuple(node.id for raw, node in zip(raw_nodes, self.nodes)
                                              if node.category == END_CATEGORY and "recruitmentScore" not in raw)
        self.index = {node.id: index for index, node in enumerate(self.nodes)}
        if len(self.index) != len(self.nodes):
            raise ValueError("map contains duplicate node IDs")
        if len({node.coord for node in self.nodes}) != len(self.nodes):
            raise ValueError("map contains duplicate coordinates")
        adjacent = [set() for _ in self.nodes]
        for a, b in map_result.get("edges", []):
            if a not in self.index or b not in self.index or a == b:
                raise ValueError(f"invalid map edge: {a}, {b}")
            ia, ib = self.index[a], self.index[b]
            adjacent[ia].add(ib)
            adjacent[ib].add(ia)
        self.adjacent = tuple(tuple(sorted(neighbors)) for neighbors in adjacent)
        self.exit_nodes = frozenset(i for i, node in enumerate(self.nodes) if node.terminal)
        self.default_exit_nodes = self.exit_nodes
        self.treehole_nodes = frozenset(i for i, node in enumerate(self.nodes)
                                       if node.effective_category == TREEHOLE_CATEGORY)
        self.reward_mask = sum(
            _bit(i) for i, node in enumerate(self.nodes) if node.effective_category not in NO_NODE_REWARD
        )
        self.mystery_mask = sum(
            _bit(i) for i, node in enumerate(self.nodes) if node.effective_category == MYSTERY_CATEGORY
        )
        self.ferocity_mask = sum(
            _bit(i) for i, node in enumerate(self.nodes) if node.effective_category == FEROCITY_CATEGORY
        )
        self.clearing_mask = sum(
            _bit(i) for i, node in enumerate(self.nodes) if node.effective_category == "node_type_020"
        )
        self.template_id = map_result.get("templateId")
        self.raw_nodes = [dict(raw, categoryId=node.category, fateRole=node.fate_role,
                              confirmedMarkIds=list(node.marks)) for raw, node in zip(raw_nodes, self.nodes)]
        self.scorer: SnapshotScorer | None = None
        self.terminal_cache = {}
        self.planning_targets = []
        self.group_by_priority = False
        self._configure_lookout_visibility({})

    def _prerequisite_progress(self, state):
        rows = []
        newly_visited = state.done & ~self.initial_done
        for target in self.planning_targets:
            known = target["knownNodeIds"]
            feasible = target["id"] != "ending3_trade" or self.scorer.natural_count_initial >= 2
            complete = feasible and any(state.done & _bit(self.index[key]) for key in known)
            weights = target.get("positionProbabilities", {})
            if not weights and target.get("candidateNodeIds"):
                weights = {key: self.scorer.probabilities(self.scorer.nodes[key])["probabilities"].get("node_type_009", 0)
                           for key in target["candidateNodeIds"]}
            searched = min(1, sum(probability for key, probability in weights.items() if key in self.index
                                 and (state.information | state.done & ~self.initial_done) & _bit(self.index[key]))) if feasible else 0
            positions = set(known) | {key for key, probability in weights.items() if probability > 0}
            visited = sorted(key for key in positions if key in self.index and newly_visited & _bit(self.index[key]))
            revealed = sorted(key for key in positions if key in self.index and state.information & _bit(self.index[key]))
            rows.append({"id": target["id"], "name": target["name"], "plannedCompletion": bool(complete),
                         "searchCoverage": searched, "knownNodeIds": known, "feasibleFromSnapshot": feasible,
                         "related": bool(visited or revealed), "visitedNodeIds": visited, "revealedNodeIds": revealed})
        return rows

    def _prerequisite_rank(self, state):
        rows = self._prerequisite_progress(state)
        return (sum(row["plannedCompletion"] for row in rows), round(sum(row["searchCoverage"] for row in rows) * 1000000))

    def _result_rank(self, candidate):
        return tuple(-value for value in candidate.metrics) if self.group_by_priority else _candidate_rank(candidate)

    def _terminal_value(self, state, *, treehole=False):
        pursuit = self._pursuit and not self._single_step
        key = ("treehole",) if treehole else ("pursuit",) if pursuit else (
            state.position, state.action_points, state.done)
        if key not in self.terminal_cache:
            self.terminal_cache[key] = self.scorer.terminal(
                self.nodes[state.position].id, state.action_points, pursuit=pursuit, treehole=treehole,
                done={self.nodes[i].id for i in range(len(self.nodes)) if state.done & _bit(i)})
        return self.terminal_cache[key]

    def _indices(self, values: list[str], field: str) -> set[int]:
        unknown = set(values) - self.index.keys()
        if unknown:
            raise ValueError(f"{field} references unknown nodes: {sorted(unknown)}")
        return {self.index[value] for value in values}

    def score_snapshot(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Preview arrival visibility without changing frozen node utility or run state."""
        self._configure_lookout_visibility(state)
        scorer = SnapshotScorer(self.raw_nodes, state["scoringContext"], state)
        report = scorer.report()
        report["lookoutVisibilityRule"] = self.lookout_visibility_rule
        done = sum(_bit(i) for i in self._indices(list(state["completedNodes"]), "completedNodes"))
        revealed = (self._indices(list(state["revealedNodes"]), "revealedNodes")
                    if "revealedNodes" in state else {i for i, node in enumerate(self.nodes) if node.revealed})
        visible = sum(_bit(i) for i in revealed) | done
        position = self.index[str(state["position"])]
        visible = self._initial_visibility(position, done, visible)
        portals = self._portal_pairs(state)
        for entry, node in enumerate(self.nodes):
            arrival = portals.get(entry, entry)
            entered = _bit(entry) | _bit(arrival)
            lookout = entry if node.lookout and not done & _bit(entry) else None
            after = self._visible_after(arrival, done | entered, visible | entered, lookout)
            newly_visible = (after & ~visible) & ~entered
            after_done = {other.id for i, other in enumerate(self.nodes) if (done | entered) & _bit(i)}
            terms = []
            for i, other in enumerate(self.nodes):
                if newly_visible & _bit(i) and scorer.nodes[other.id].get("categoryId") in {MYSTERY_CATEGORY, FEROCITY_CATEGORY}:
                    opportunity = max(0, scorer.preview_value(other.id, done=after_done)["points"])
                    terms.append({"nodeId": other.id, "opportunityPoints": opportunity,
                                  "points": scorer.reveal_coefficient * opportunity})
            value = report["nodeValues"][node.id]
            value["arrivalRevealTerms"] = terms
            value["revealValue"] = sum(term["points"] for term in terms)
            value["arrivalPoints"] = value["points"] + value["revealValue"]
        return report

    def _portal_pairs(self, state: Mapping[str, Any]) -> dict[int, int]:
        specified = state.get("portalPairs")
        if specified is None:
            portals = [i for i, node in enumerate(self.nodes) if node.category == PORTAL_CATEGORY]
            if len(portals) not in (0, 2):
                raise ValueError("portal endpoints are ambiguous; supply portalPairs")
            specified = [[self.nodes[portals[0]].id, self.nodes[portals[1]].id]] if portals else []
        result: dict[int, int] = {}
        for pair in specified:
            if len(pair) != 2:
                raise ValueError("each portal pair must contain two node IDs")
            endpoints = [str(value) for value in pair]
            self._indices(endpoints, "portalPairs")
            a, b = (self.index[value] for value in endpoints)
            if a == b or a in result or b in result:
                raise ValueError("portal endpoints must be distinct and appear once")
            if self.nodes[a].category != PORTAL_CATEGORY or self.nodes[b].category != PORTAL_CATEGORY:
                raise ValueError("portalPairs must reference portal nodes")
            result[a], result[b] = b, a
        known_portals = {i for i, node in enumerate(self.nodes) if node.category == PORTAL_CATEGORY}
        if set(result) != known_portals:
            raise ValueError("portalPairs must cover every identified portal node")
        return result

    def _items(self, state: Mapping[str, Any]) -> tuple[tuple[_Item, ...], list[str]]:
        raw_items = state.get("items", [])
        ids = [str(item["instanceId"]) for item in raw_items]
        if len(set(ids)) != len(ids):
            raise ValueError("each processing item requires a unique instanceId")
        include = {str(value) for value in state.get("useItemIds", ids)}
        exclude = {str(value) for value in state.get("excludeItemIds", [])}
        unknown = (include | exclude) - set(ids)
        if unknown:
            raise ValueError(f"item filter references unknown instances: {sorted(unknown)}")
        items = []
        warnings = []
        for raw in raw_items:
            component_id = str(raw["componentId"])
            if component_id not in MOVEMENT_RULES:
                raise ValueError(f"unsupported processing item: {component_id}")
            uses = int(raw["remainingUses"])
            if uses < 0:
                raise ValueError("remainingUses must be nonnegative")
            rule = MOVEMENT_RULES[component_id]
            instance_id = str(raw["instanceId"])
            allowed = instance_id in include and instance_id not in exclude
            if allowed and uses and not rule.deterministic:
                warnings.append(f"{raw['instanceId']} is random; excluded from guaranteed routes")
            value = raw.get("estimatedValue")
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("estimatedValue must be a nonnegative integer or null")
            items.append(_Item(instance_id, component_id, uses, rule, allowed, value))
        return tuple(items), warnings

    @staticmethod
    def _item_groups(items: tuple[_Item, ...]) -> tuple[tuple[int, ...], ...]:
        grouped: dict[tuple[Any, ...], list[int]] = {}
        for index, item in enumerate(items):
            key = (astuple(item.rule)[1:], item.allowed, item.estimated_value)
            grouped.setdefault(key, []).append(index)
        return tuple(tuple(indices) for indices in grouped.values())

    @staticmethod
    def _state_key(state: _State, groups: tuple[tuple[int, ...], ...]) -> tuple[Any, ...]:
        # Canonicalize interchangeable inventories, without rewriting step/item IDs.
        uses = list(state.uses)
        for indices in groups:
            if len(indices) < 2:
                continue
            for index, remaining in zip(indices, sorted((uses[i] for i in indices), reverse=True)):
                uses[index] = remaining
        return (state.position, state.action_points, state.done, state.visible,
                state.information, tuple(uses), state.prefix_cash, state.prefix_appraisal, state.movements,
                state.economy_movements, state.investment_balance, state.merchant_shelves,
                state.retained_appraisal_fraction)

    def _configure_lookout_visibility(self, state: Mapping[str, Any]) -> None:
        opening = state.get("scoringContext", {}).get("opening", {})
        difficulty = state.get("difficulty", opening.get("difficulty", 15))
        split = state.get("lookoutSplitUnlocked", opening.get("lookoutSplitUnlocked", True))
        spawn_radius, arrival_radius = lookout_radii(difficulty, split)
        self.lookout_visibility_rule = {"difficulty": difficulty, "splitUnlocked": split,
            "spawnRadius": spawn_radius, "arrivalRadius": arrival_radius,
            "spawnNeighborCells": 2 * spawn_radius * (spawn_radius + 1),
            "arrivalNeighborCells": 2 * arrival_radius * (arrival_radius + 1)}
        self.lookout_masks = {}
        for source, node in enumerate(self.nodes):
            if node.lookout:
                distances = [abs(other.coord[0] - node.coord[0]) + abs(other.coord[1] - node.coord[1])
                             for other in self.nodes]
                self.lookout_masks[source] = tuple(sum(_bit(i) for i, distance in enumerate(distances) if distance <= radius)
                                                  for radius in (spawn_radius, arrival_radius))

    def _initial_visibility(self, position: int, done: int, visible: int) -> int:
        # Spawn sight and previously completed lookouts are baseline information, not new rewards.
        for index, (spawn, arrival) in self.lookout_masks.items():
            visible |= arrival if done & _bit(index) else spawn
        return self._visible_after(position, done, visible, None)

    def _visible_after(self, position: int, done: int, visible: int, first_lookout: int | None) -> int:
        visible |= _bit(position)
        if first_lookout is not None:
            visible |= self.lookout_masks[first_lookout][1]
        visited = 0
        transparent = done | self.clearing_mask
        # Visible clearings transmit vision even when their completion is unknown.
        pending = [position] + [i for i in range(len(self.nodes)) if visible & self.clearing_mask & _bit(i)]
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

    def _score_units(self, new_nodes: int, newly_revealed: int) -> tuple[int, int]:
        node_units = (
            SCORE_SCALE * new_nodes.bit_count()
            - 10 * (new_nodes & self.mystery_mask).bit_count()
            - 4 * (new_nodes & self.ferocity_mask).bit_count()
        )
        reveal_units = (
            4 * (newly_revealed & self.mystery_mask).bit_count()
            + (newly_revealed & self.ferocity_mask).bit_count()
        )
        return node_units, reveal_units

    def _recruitment_units(self, visited: int) -> int:
        return sum(units for index, units in self.recruitment_scores if visited & _bit(index))

    def _metrics(self, state: _State, initial_done: int, items: tuple[_Item, ...],
                 area_exit: bool = False, treehole_item_index: int | None = None) -> tuple[int, ...]:
        new_node_mask = (state.done & ~initial_done) & self.reward_mask
        new_nodes = new_node_mask.bit_count()
        new_information = state.information.bit_count()
        treeholes = int(treehole_item_index is not None)
        new_nodes += treeholes
        node_units, reveal_units = self._score_units(new_node_mask, state.information)
        total_units = (node_units + reveal_units + SCORE_SCALE * treeholes
                       + self._recruitment_units(state.done & ~initial_done))
        if self.scorer is not None:
            total_units = state.score_units
            if area_exit or treeholes:
                total_units += round(self._terminal_value(state, treehole=bool(treeholes))["points"] * SCORE_SCALE)
        effective_uses = tuple(
            0 if index == treehole_item_index or (area_exit and item.rule.expires_on_exit) else uses
            for index, (item, uses) in enumerate(zip(items, state.uses))
        )
        survivors = sum(uses > 0 for uses in effective_uses)
        remaining_uses = sum(effective_uses)
        return total_units, new_nodes, new_information, treeholes, survivors, remaining_uses

    def _queue_priority(self, metrics: tuple[int, ...], exit_distance: float,
                        action_points: int, serial: int) -> tuple[int, ...]:
        return (-metrics[0], -metrics[1], -metrics[4], -metrics[5], serial)

    def _offer(self, pool: list[_Candidate], candidate: _Candidate, limit_equal: int) -> None:
        if self.scorer is not None:
            def peer(other):
                return other.goal_id == candidate.goal_id and (
                    not self.group_by_priority or other.relevance_mask == candidate.relevance_mask)
            peers = [other for other in pool if peer(other)]
            matching = [other for other in peers if other.trajectory == candidate.trajectory]

            if matching and _allocation_rank(matching[0]) <= _allocation_rank(candidate):
                return
            pool[:] = [other for other in pool if other not in matching]
            pool.append(candidate)
            peers = sorted((other for other in pool if peer(other)), key=self._result_rank)
            discarded = peers[limit_equal:]
            pool[:] = [other for other in pool if other not in discarded]
            return
        peers = [other for other in pool if other.goal_id == candidate.goal_id]
        if any(_dominates(other.metrics, candidate.metrics) for other in peers):
            return
        if sum(other.metrics == candidate.metrics for other in peers) >= limit_equal:
            return
        pool[:] = [
            other for other in pool
            if other.goal_id != candidate.goal_id or not _dominates(candidate.metrics, other.metrics)
        ]
        pool.append(candidate)

    def _select(self, candidates: list[_Candidate], top_n: int, labels: list[_Label]) -> list[_Candidate]:
        groups: dict[str, list[_Candidate]] = {}
        for candidate in candidates:
            groups.setdefault(candidate.goal_id, []).append(candidate)
        for group in groups.values():
            group.sort(key=self._result_rank)
        ordered = sorted(groups, key=lambda key: self._result_rank(groups[key][0]))
        if self.scorer is not None:
            ordered_candidates = sorted(candidates, key=self._result_rank)
            groups = {"all": ordered_candidates}
            ordered = ["all"]
        selected = []
        selected_paths = set()
        while len(selected) < top_n and any(groups.values()):
            for key in ordered:
                if groups[key] and len(selected) < top_n:
                    candidate = groups[key].pop(0)
                    cursor = candidate.label_index
                    path = []
                    while labels[cursor].parent is not None:
                        step = labels[cursor].step
                        path.append((step["entered"], step["arrived"]))
                        cursor = labels[cursor].parent
                    signature = (candidate.goal_id, tuple(reversed(path)))
                    if signature not in selected_paths:
                        selected_paths.add(signature)
                        selected.append(candidate)
        return selected

    def _route(self, candidate: _Candidate, labels: list[_Label], items: tuple[_Item, ...],
               goal_type: str) -> dict[str, Any]:
        label = labels[candidate.label_index]
        steps = []
        cursor = candidate.label_index
        while labels[cursor].parent is not None:
            steps.append(labels[cursor].step)
            cursor = labels[cursor].parent
        steps.reverse()
        state = label.state
        metrics = candidate.metrics
        new_node_mask = (state.done & ~labels[0].state.done) & self.reward_mask
        node_units, reveal_units = self._score_units(new_node_mask, state.information)
        recruitment_units = self._recruitment_units(state.done & ~labels[0].state.done)
        treehole_units = SCORE_SCALE if candidate.treehole_item_index is not None else 0
        terminal_score = None
        if self.scorer is not None:
            terminal_score = self._terminal_value(state, treehole=candidate.treehole_item_index is not None
                ) if candidate.area_exit or candidate.treehole_item_index is not None else {"points": 0, "parts": {}}
            node_units = round((sum(step["nodeValue"] for step in steps) + terminal_score["points"]) * SCORE_SCALE)
            reveal_units = round(sum(step["revealValue"] for step in steps) * SCORE_SCALE)
            recruitment_units = round(sum(step["recruitmentValue"] for step in steps) * SCORE_SCALE)
            treehole_units = 0
        missing_terms = set(terminal_score.get("missingTerms", [])) if terminal_score else set()
        if self.scorer is not None:
            for step in steps:
                for row in step["scoreBreakdown"]["nodeTerms"]:
                    missing_terms.update(row["missingTerms"])
                for row in step["scoreBreakdown"]["revealTerms"]:
                    missing_terms.update(self.scorer.values[row["nodeId"]]["missingTerms"])
        remaining = tuple(
            0 if index == candidate.treehole_item_index or (candidate.area_exit and item.rule.expires_on_exit)
            else uses
            for index, (item, uses) in enumerate(zip(items, state.uses))
        )
        return {
            "goalType": goal_type,
            "prerequisites": self._prerequisite_progress(state),
            "relatedGoalIds": [target["id"] for target in self._prerequisite_progress(state) if target["related"]],
            "prerequisiteRanking": {"plannedKnownCompletions": candidate.prerequisite_rank[0],
                                    "searchCoverage": candidate.prerequisite_rank[1] / 1000000,
                                    "allSelectedKnownCompleted": all(row["plannedCompletion"] for row in self._prerequisite_progress(state)),
                                    "actualProgressUnchanged": True},
            "endNode": self.nodes[state.position].id,
            "remainingActionPoints": (
                steps[-1].get("actualActionPointsAfter", state.action_points) if steps else state.action_points
            ),
            "planningActionPointsRemaining": state.action_points,
            "metrics": {
                "weightedValue": metrics[0] / SCORE_SCALE,
                "nodeValue": (node_units + treehole_units) / SCORE_SCALE,
                "revealValue": reveal_units / SCORE_SCALE,
                "recruitmentValue": recruitment_units / SCORE_SCALE,
                "revealedUnknownMystery": (state.information & self.mystery_mask).bit_count(),
                "revealedUnknownFerocity": (state.information & self.ferocity_mask).bit_count(),
                "newNodes": metrics[1],
                "newlyRevealedOtherNodes": metrics[2],
                "treeholesReached": metrics[3],
                "survivingProcessingItems": metrics[4],
                "remainingItemUses": metrics[5],
            },
            "remainingItems": [
                {"instanceId": item.instance_id, "componentId": item.component_id, "remainingUses": uses}
                for item, uses in zip(items, remaining)
            ],
            "treeholeEntryItemInstanceId": (
                items[candidate.treehole_item_index].instance_id
                if candidate.treehole_item_index is not None else None
            ),
            "treeholeEntryValue": (terminal_score["points"] if self.scorer is not None
                                   and candidate.treehole_item_index is not None else treehole_units / SCORE_SCALE),
            **({"terminalScore": terminal_score,
                "referenceLossPoints": sum(step["scoreBreakdown"].get("referenceLossPoints", 0) for step in steps),
                "expectedPrefixEconomy": {"cash": state.prefix_cash, "appraisal": state.prefix_appraisal,
                                          "movementCashProxy": state.economy_movements * self.scorer.step_ingot,
                                          "investmentBalance": state.investment_balance,
                                          "merchantViewedShelves": {node.id: state.merchant_shelves[i] for i, node in enumerate(self.nodes)
                                              if node.category in {"node_type_004", "node_type_013"}},
                                          "confirmedResourcesUnchanged": True},
                "scoreMode": "snapshot_expected_utility",
                "scoreCoverage": "partial" if missing_terms else "complete_for_configured_approximation",
                "missingScoreTerms": sorted(missing_terms)} if self.scorer is not None else {}),
            "steps": steps,
        }

    def _relaxed_distances(
        self,
        goals: set[int],
        blocked: set[int],
        portal_pairs: dict[int, int],
        items: tuple[_Item, ...],
        item_targets: tuple[tuple[tuple[int, ...], ...], ...],
    ) -> tuple[float, ...]:
        reverse: list[list[tuple[int, int]]] = [[] for _ in self.nodes]
        for source in range(len(self.nodes)):
            if source in blocked:
                continue
            for entry in self.adjacent[source]:
                destination = portal_pairs.get(entry, entry)
                if entry not in blocked and destination not in blocked:
                    reverse[destination].append((source, 1))
            for index, item in enumerate(items):
                if not item.allowed or not item.rule.deterministic or item.uses == 0:
                    continue
                for entry in item_targets[index][source]:
                    destination = portal_pairs.get(entry, entry)
                    if entry not in blocked and destination not in blocked:
                        reverse[destination].append((source, item.rule.action_cost))
        distances = [float("inf")] * len(self.nodes)
        queue = []
        for goal in goals - blocked:
            distances[goal] = 0
            heapq.heappush(queue, (0, goal))
        while queue:
            distance, target = heapq.heappop(queue)
            if distance != distances[target]:
                continue
            for source, cost in reverse[target]:
                candidate = distance + cost
                if candidate < distances[source]:
                    distances[source] = candidate
                    heapq.heappush(queue, (candidate, source))
        return tuple(distances)

    def plan(self, state: Mapping[str, Any], *,
             on_expand: Callable[[dict[str, Any]], None] | None = None,
             on_generate: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        if any(field not in state for field in ("position", "actionPoints", "completedNodes")):
            raise ValueError("position, actionPoints, and completedNodes are required")
        position_id = str(state["position"])
        if position_id not in self.index:
            raise ValueError(f"current position is not on map: {position_id}")
        position = self.index[position_id]
        action_points = int(state["actionPoints"])
        if action_points < 0:
            raise ValueError("actionPoints must be nonnegative")
        observed_action_points = action_points
        single_step = state.get("utopiaId") == "utopia_005"
        if single_step:
            action_points = min(action_points, 1)
        context = state.get("scoringContext", {})
        pursuit = planning_pursuit(context.get("goals", {}), context.get("areaKey"), bool(state.get("pursuit", False)))
        self.exit_nodes = self.default_exit_nodes
        if context.get("areaKey") == "V" and context.get("goals", {}).get("endingV") in {"normal1", "pursuit1"}:
            self.exit_nodes = frozenset(i for i, node in enumerate(self.nodes) if node.category == "node_type_003")
        self._pursuit, self._single_step = pursuit, single_step
        self._configure_lookout_visibility(state)
        self.terminal_cache = {}
        self.scorer = SnapshotScorer(self.raw_nodes, state["scoringContext"], {**state, "actionPoints": action_points}) if state.get("scoringContext") else None
        self.planning_targets = state.get("planningTargets", []) if self.scorer is not None else []
        self.group_by_priority = bool(self.planning_targets and state.get("groupByPriority", False))
        top_n = int(state.get("topN", PROFILE["search"]["defaultTopN"]))
        max_states = int(state.get("maxStates", PROFILE["search"]["defaultMaxStates"]))
        if type(state.get("allocationDominance", PROFILE["search"]["allocationDominance"])) is not bool:
            raise ValueError("allocationDominance must be boolean")
        search_mode = state.get("searchMode", PROFILE["search"]["defaultMode"])
        if search_mode not in ("target", "reference"):
            raise ValueError("searchMode must be target or reference")
        optimized = search_mode == "target"
        if not 1 <= top_n <= 50 or max_states < 1:
            raise ValueError("topN must be 1..50 and maxStates must be positive")
        completed = self._indices(list(state["completedNodes"]), "completedNodes")
        blocked = self._indices(list(state.get("blockedNodes", [])), "blockedNodes")
        if position in blocked:
            raise ValueError("current position cannot be blocked")
        if "revealedNodes" in state:
            revealed = self._indices(list(state["revealedNodes"]), "revealedNodes")
        else:
            revealed = {i for i, node in enumerate(self.nodes) if node.revealed}
        items, warnings = self._items(state)
        item_groups = self._item_groups(items)
        item_group_ids = {index: group_id for group_id, indices in enumerate(item_groups) for index in indices}
        free_slots = state.get("componentBoxFreeSlots")
        if free_slots is None and self.scorer is not None:
            free_slots = max(0, self.scorer.capacity - len(self.scorer.components))
        if free_slots is not None and (type(free_slots) is not int or free_slots < 0):
            raise ValueError("componentBoxFreeSlots must be a nonnegative integer or null")
        portal_pairs = self._portal_pairs(state)
        if position not in completed:
            raise ValueError("current position must be in completedNodes before route planning")
        completed_mask = sum(_bit(i) for i in completed)
        visible_mask = sum(_bit(i) for i in revealed | completed)
        visible_mask = self._initial_visibility(position, completed_mask, visible_mask)
        initial = _State(
            position=position,
            action_points=action_points,
            done=completed_mask,
            visible=visible_mask,
            information=0,
            uses=tuple(item.uses for item in items),
            prefix_cash=self.scorer.cash if self.scorer else 0.0,
            prefix_appraisal=self.scorer.initial_appraisal if self.scorer else 0.0,
            investment_balance=self.scorer.investment_balance if self.scorer else 0.0,
            merchant_shelves=tuple(self.scorer.merchant_shelves[node.id] for node in self.nodes) if self.scorer else (),
        )
        initial_done = completed_mask
        self.initial_done = initial_done
        item_targets = tuple(
            tuple(
                tuple(
                    target for target, node in enumerate(self.nodes)
                    if rule.reaches(source_node.coord, node.coord, node.category, True)
                    or (rule.target == "noncombat" and rule.reaches(
                        source_node.coord, node.coord, "node_type_020", True
                    ))
                )
                for source_node in self.nodes
            )
            for rule in (item.rule for item in items)
        )
        item_scopes = tuple(sum(len(targets) for targets in by_source) for by_source in item_targets)
        goals = set(self.exit_nodes) | set(self.treehole_nodes)
        relaxed = self._relaxed_distances(goals, blocked, portal_pairs, items, item_targets)
        labels = [_Label(initial, None, None)]
        initial_key = self._state_key(initial, item_groups)
        trajectory_limit = top_n if self.scorer is not None else 1
        seen = {initial_key: [0]}
        inventory_frontier = (ScoredInventoryFrontier(initial_key[5]) if self.scorer is not None
                              else InventoryFrontier(initial_key[5]))
        # AP stays exact. Resource-producing item usage and tight-box choices are
        # not future-equivalent to merely keeping more movement charges.
        resource_items = tuple(i for i, item in enumerate(items) if item.rule.hope_gain or item.rule.ingot_gain)
        scored_guards = []
        if self.scorer is not None:
            if free_slots is None or free_slots <= 1:
                scored_guards.append("tight_or_unknown_box")
            if any(value < 0 for value in self.scorer.weights.values()):
                scored_guards.append("negative_strategy_weight")
            if any(item.uses and item.estimated_value is None for item in items):
                scored_guards.append("unknown_processing_appraisal")
            if not state.get("allocationDominance", PROFILE["search"]["allocationDominance"]):
                scored_guards.append("explicitly_disabled")
        dominance_enabled = (optimized and bool(items) and (not scored_guards if self.scorer is not None
                             else free_slots is None or free_slots > 1)
                             and any(not (item.rule.hope_gain or item.rule.ingot_gain)
                                     and item.allowed and item.uses for item in items))

        def frontier_key(key: tuple[Any, ...]) -> tuple[Any, ...]:
            return (*key[:5], *key[6:], tuple(key[5][i] for i in resource_items))

        def admit_inventory(key, label_id, score=0, preference=(), trajectory=0):
            if self.scorer is not None:
                group = (frontier_key(key), trajectory) if trajectory_limit > 1 else frontier_key(key)
                return inventory_frontier.admit(group, key[5], label_id, score, preference)
            return inventory_frontier.admit(frontier_key(key), key[5], label_id)

        def candidate(label_index, goal, metrics, *, area_exit=False, treehole_item_index=None):
            label = labels[label_index]
            relevance = sum(_bit(i) for i, row in enumerate(self._prerequisite_progress(label.state)) if row["related"])
            return _Candidate(label_index, goal, metrics, area_exit, treehole_item_index,
                              label.trajectory, label.preference, self._prerequisite_rank(label.state), relevance)

        if dominance_enabled:
            admit_inventory(initial_key, 0)
        allocator = MovementAllocator(self.nodes, self.adjacent, items, item_targets, item_scopes)
        trajectory_pool = TrajectoryPool()
        geometry_cache = GeometryCache(self.nodes, portal_pairs, self._visible_after)
        score_cache = {}
        score_cache_hits = 0
        queue: list[tuple[tuple[int, ...], int]] = []
        serial = 0

        def priority(current: _State) -> tuple[int, ...]:
            metrics = self._metrics(current, initial_done, items)
            prerequisites = () if self.group_by_priority else self._prerequisite_rank(current)
            return (*(-v for v in prerequisites),
                    *self._queue_priority(metrics, relaxed[current.position], current.action_points, serial))

        heapq.heappush(queue, (priority(initial), 0))

        def record_generated(label_index: int, key: tuple[Any, ...]) -> None:
            if on_generate is None:
                return
            label = labels[label_index]
            current = label.state
            terminal = (current.position in self.exit_nodes and not pursuit
                        or current.action_points == 0 and pursuit and not single_step
                        or single_step and label.parent is not None)
            on_generate({
                "labelId": label_index, "parentLabelId": label.parent,
                "position": self.nodes[current.position].id,
                "actionPoints": current.action_points,
                "doneMask": current.done, "visibleMask": current.visible,
                "informationMask": current.information,
                "rewardNodeMask": (current.done & ~initial_done) & self.reward_mask,
                "canonicalUses": key[5], "score": self._metrics(current, initial_done, items)[0] / SCORE_SCALE,
                "prefixCash": current.prefix_cash, "prefixAppraisal": current.prefix_appraisal,
                "movements": current.movements,
                "economyMovements": current.economy_movements, "investmentBalance": current.investment_balance,
                "merchantShelves": current.merchant_shelves,
                "retainedAppraisalFraction": current.retained_appraisal_fraction,
                "terminalScore": self._metrics(current, initial_done, items, area_exit=True)[0] / SCORE_SCALE
                                 if terminal else None,
                "step": None if label.step is None else {
                    name: label.step[name] for name in ("from", "entered", "arrived", "itemInstanceId")
                },
            })

        record_generated(0, initial_key)
        complete: list[_Candidate] = []
        treehole_branches: list[_Candidate] = []
        expanded = 0
        limited = False
        duplicate_states = 0
        equivalent_actions = 0
        unreachable_states = 0
        terminal_frontier_evaluated = 0
        dominated_inventories = 0
        obsolete_labels_skipped = 0
        target_effects_reused = 0
        last_ap_exceptions = 0
        walking_equivalents = 0
        zero_ap_dead_ends = 0
        no_effect_end_reentries = 0
        pursuit_terminals_pruned = 0
        pursuit_terminals_settled = 0
        pursuit_cutoff = None
        pursuit_terminal_units = round(self._terminal_value(initial)["points"] * SCORE_SCALE
            ) if optimized and self.scorer is not None and pursuit and not single_step else 0
        while queue:
            if expanded >= max_states:
                limited = True
                break
            queue_priority, label_index = heapq.heappop(queue)
            if label_index in inventory_frontier.obsolete or label_index not in seen.get(self._state_key(labels[label_index].state, item_groups), []):
                obsolete_labels_skipped += 1
                continue
            label = labels[label_index]
            current = label.state
            expanded += 1
            if on_expand is not None:
                on_expand({
                    "labelId": label_index, "parentLabelId": label.parent,
                    "expansion": expanded, "position": self.nodes[current.position].id,
                    "actionPoints": current.action_points,
                    "weightedValue": self._metrics(current, initial_done, items)[0] / SCORE_SCALE,
                    "queuePriority": queue_priority,
                    "rewardNodeMask": (current.done & ~initial_done) & self.reward_mask,
                    "step": None if label.step is None else {
                        key: label.step[key] for key in ("movement", "entered", "arrived", "itemInstanceId")
                    },
                })
            if single_step and label.parent is not None:
                area_exit = current.position in self.exit_nodes
                self._offer(complete, candidate(
                    label_index, self.nodes[current.position].id,
                    self._metrics(current, initial_done, items, area_exit=area_exit), area_exit=area_exit,
                ), top_n)
                continue
            if current.position in self.exit_nodes:
                if not pursuit:
                    self._offer(complete, candidate(label_index, self.nodes[current.position].id,
                                                     self._metrics(current, initial_done, items, area_exit=True),
                                                     area_exit=True), top_n)
                if self.nodes[current.position].category != END_CATEGORY:
                    continue
            if current.action_points == 0:
                if pursuit and not single_step:
                    self._offer(complete, candidate(label_index, "pursuit",
                                                     self._metrics(current, initial_done, items, area_exit=True),
                                                     area_exit=True), top_n)
                continue
            if not pursuit and not single_step:
                potential_gain = sum(
                    uses * item.rule.action_gain for item, uses in zip(items, current.uses)
                    if item.allowed
                ) + sum(
                    not current.done & _bit(i) for i, node in enumerate(self.nodes)
                    if node.lookout
                )
                if relaxed[current.position] > current.action_points + potential_gain:
                    unreachable_states += 1
                    continue

            walk_targets = set(self.adjacent[current.position]) - blocked
            current_free = None if free_slots is None else free_slots + sum(
                item.uses > 0 and remaining == 0 for item, remaining in zip(items, current.uses)
            )
            current_box_count = (len(self.scorer.components) - sum(item.uses > 0 and remaining == 0
                for item, remaining in zip(items, current.uses))) if self.scorer is not None else 0
            actions, last_ap_exception = allocator.choices(current.position, current.uses, current.action_points,
                current.done, current.visible, current_free, grouped=optimized)
            if optimized and items and last_ap_exception:
                last_ap_exceptions += 1
            action_keys = set()

            for kind, entry, item_index, cost, gain in actions:
                # Waiting at an exit is normally redundant, but a benefit policy can pay again.
                if kind == "reenter" and self.nodes[entry].category == END_CATEGORY and not pursuit and not single_step:
                    policy_effect = self.scorer.policy_effect(self.nodes[entry].id,
                        current.prefix_cash + current.economy_movements * self.scorer.step_ingot,
                        {self.nodes[i].id for i in range(len(self.nodes)) if current.done & _bit(i)}) if self.scorer else None
                    policy_points = (policy_effect["points"] * self.scorer.weights.get(self.nodes[entry].id, 1)
                                     if policy_effect else 0)
                    if policy_points <= 0:
                        no_effect_end_reentries += 1
                        continue
                if item_index is not None:
                    action_key = (entry, item_group_ids[item_index], current.uses[item_index])
                    if action_key in action_keys:
                        equivalent_actions += 1
                        continue
                    action_keys.add(action_key)
                    item = items[item_index]
                    if (self.scorer is None and dominance_enabled and not last_ap_exception and entry in walk_targets
                            and cost == 1 and gain == 0 and not item.rule.hope_gain and not item.rule.ingot_gain):
                        walking_equivalents += 1
                        continue
                arrival = portal_pairs.get(entry, entry)
                if entry in blocked or arrival in blocked or cost > current.action_points:
                    continue
                if (pursuit and not single_step and arrival in self.exit_nodes
                        and self.nodes[arrival].category != END_CATEGORY):
                    continue
                if optimized:
                    before_hits = geometry_cache.hits
                    entered, first_lookout, done, visible, newly_visible_other = geometry_cache.resolve(
                        entry, current.done, current.visible)
                    target_effects_reused += geometry_cache.hits - before_hits
                else:
                    entered = _bit(entry) | _bit(arrival)
                    first_lookout = next((
                        index for index in (entry, arrival)
                        if self.nodes[index].lookout and not current.done & _bit(index)
                    ), None)
                    done = current.done | entered
                    visible = self._visible_after(arrival, done, current.visible | entered, first_lookout)
                    newly_visible_other = (visible & ~current.visible) & ~entered
                action_after = current.action_points - cost + gain + (1 if first_lookout is not None else 0)
                if action_after < 0:
                    continue
                if optimized and not pursuit and not single_step and action_after == 0 and arrival not in self.exit_nodes:
                    zero_ap_dead_ends += 1
                    continue
                item = items[item_index] if item_index is not None else None
                exhausted = item is not None and current.uses[item_index] == 1
                scored_step = None
                if self.scorer is not None:
                    exhausted_value = ((item.estimated_value or 0) * current.retained_appraisal_fraction) if exhausted else 0
                    cash_at_arrival = current.prefix_cash + (item.rule.ingot_gain if item else 0)
                    appraisal_at_arrival = max(0, current.prefix_appraisal - exhausted_value)
                    box_count_at_arrival = current_box_count - int(exhausted)
                    score_key = (entry, current.done, current.visible, cash_at_arrival, appraisal_at_arrival,
                                 current.economy_movements + 1, item is not None, box_count_at_arrival,
                                 current.investment_balance, current.merchant_shelves)
                    if optimized and score_key in score_cache:
                        score_cache_hits += 1
                        scored_step = score_cache[score_key]
                    else:
                        entered_ids = [self.nodes[i].id for i in dict.fromkeys((entry, arrival))]
                        scored_step = self.scorer.step(entered_ids,
                            fresh={self.nodes[i].id for i in (entry, arrival) if not current.done & _bit(i)},
                            revealed=[self.nodes[i].id for i in range(len(self.nodes)) if newly_visible_other & _bit(i)],
                            before_done={self.nodes[i].id for i in range(len(self.nodes)) if current.done & _bit(i)},
                            prefix_cash=cash_at_arrival, appraisal=appraisal_at_arrival,
                            path_steps=current.economy_movements + 1, processing=item is not None,
                            box_count=box_count_at_arrival, investment_balance=current.investment_balance,
                            merchant_shelves={node.id: current.merchant_shelves[i] for i, node in enumerate(self.nodes)})
                        if optimized and len(score_cache) < 65536:
                            score_cache[score_key] = scored_step
                    transition = scored_step["merchantTransition"]
                    prefix_cash = round(transition["cashAfter"], 6)
                    prefix_appraisal = round(transition["appraisalAfter"], 6)
                    score_units = current.score_units + round((scored_step["nodeValue"] + scored_step["revealValue"]
                                                               + scored_step["recruitmentValue"]) * SCORE_SCALE)
                else:
                    prefix_cash, prefix_appraisal, score_units = 0.0, 0.0, 0
                pursuit_terminal = optimized and self.scorer is not None and pursuit and not single_step and action_after == 0
                if pursuit_terminal and not self.planning_targets and pursuit_cutoff is not None and score_units + pursuit_terminal_units < pursuit_cutoff:
                    pursuit_terminals_pruned += 1
                    continue
                remaining = list(current.uses)
                if item_index is not None:
                    remaining[item_index] -= 1
                next_state = _State(arrival, action_after, done, visible,
                                    current.information | newly_visible_other, tuple(remaining),
                                    score_units, prefix_cash, prefix_appraisal,
                                    current.movements + 1 if self.scorer is not None else 0,
                                    round(transition["movementProxyStepsAfter"], 6) if self.scorer is not None else 0,
                                    round(transition["investmentBalanceAfter"], 6) if self.scorer is not None else 0,
                                    tuple(transition["viewedShelvesAfter"][node.id] for node in self.nodes) if self.scorer is not None else (),
                                    round(current.retained_appraisal_fraction * transition["retainedAppraisalFraction"], 6)
                                        if self.scorer is not None else 1.0)
                next_trajectory = trajectory_pool.extend(label.trajectory, entry, arrival)
                next_preference = label.preference + (allocator.preference(
                    (kind, entry, item_index, cost, gain), current.uses, current_free, last_ap_exception),)
                pursuit_metrics = None
                if pursuit_terminal:
                    pursuit_metrics = self._metrics(next_state, initial_done, items, area_exit=True)
                    peers = [other for other in complete if other.goal_id == "pursuit"]
                    trial = _Candidate(-1, "pursuit", pursuit_metrics, True, None, next_trajectory, next_preference,
                                       self._prerequisite_rank(next_state))
                    if any(other.trajectory == next_trajectory and _allocation_rank(other) <= _allocation_rank(trial)
                           for other in peers):
                        pursuit_terminals_pruned += 1
                        continue
                next_key = self._state_key(next_state, item_groups)
                peers = seen.get(next_key, [])
                if peers and self.scorer is None:
                    duplicate_states += 1
                    continue
                trial_rank = (-score_units, next_preference)
                replaced = []
                if peers:
                    equivalent = [i for i in peers if labels[i].trajectory == next_trajectory or trajectory_limit == 1]
                    if any((-labels[i].state.score_units, labels[i].preference) <= trial_rank for i in equivalent):
                        duplicate_states += 1
                        continue
                    replaced = equivalent
                    others = [i for i in peers if i not in replaced]
                    if len(others) >= trajectory_limit:
                        worst = max(others, key=lambda i: (-labels[i].state.score_units, labels[i].preference))
                        if (-labels[worst].state.score_units, labels[worst].preference) <= trial_rank:
                            duplicate_states += 1
                            continue
                        replaced.append(worst)
                if len(labels) >= max_states:
                    limited = True
                    break
                if dominance_enabled and not admit_inventory(next_key, len(labels), score_units, next_preference, next_trajectory):
                    dominated_inventories += 1
                    continue
                seen[next_key] = [i for i in peers if i not in replaced] + [len(labels)]
                new_nodes = (entered & ~current.done) & self.reward_mask
                node_units, reveal_units = self._score_units(new_nodes, newly_visible_other)
                recruitment_units = self._recruitment_units(entered & ~current.done)
                revealed_mystery = newly_visible_other & self.mystery_mask
                revealed_ferocity = newly_visible_other & self.ferocity_mask
                step = {
                    "movement": kind,
                    "from": self.nodes[current.position].id,
                    "entered": self.nodes[entry].id,
                    "arrived": self.nodes[arrival].id,
                    "portalTransfer": entry != arrival,
                    "itemInstanceId": item.instance_id if item else None,
                    "componentId": item.component_id if item else None,
                    "actionPointsBefore": current.action_points,
                    "actionCost": cost,
                    "actionGain": gain + (1 if first_lookout is not None else 0),
                    "actionPointsAfter": action_after,
                    "newNodes": [self.nodes[i].id for i in range(len(self.nodes)) if new_nodes & _bit(i)],
                    "newlyRevealedOtherNodes": [
                        self.nodes[i].id for i in range(len(self.nodes)) if newly_visible_other & _bit(i)
                    ],
                    "revealedUnknownMysteryNodes": [
                        self.nodes[i].id for i in range(len(self.nodes)) if revealed_mystery & _bit(i)
                    ],
                    "revealedUnknownFerocityNodes": [
                        self.nodes[i].id for i in range(len(self.nodes)) if revealed_ferocity & _bit(i)
                    ],
                    "nodeValue": node_units / SCORE_SCALE,
                    "revealValue": reveal_units / SCORE_SCALE,
                    "recruitmentValue": recruitment_units / SCORE_SCALE,
                    "weightedValue": (node_units + reveal_units + recruitment_units) / SCORE_SCALE,
                    "itemRemainingUses": remaining[item_index] if item_index is not None else None,
                    "hopeDelta": item.rule.hope_gain if item else 0,
                    "ingotDelta": item.rule.ingot_gain if item else 0,
                    "treeholeChoicePending": entry in self.treehole_nodes,
                    "fateChoicePending": self.nodes[entry].fate_role == "true",
                    "allocationPreference": next_preference[-1],
                }
                if scored_step is not None:
                    step.update({key: scored_step[key] for key in ("nodeValue", "revealValue", "recruitmentValue")})
                    step["weightedValue"] = (next_state.score_units - current.score_units) / SCORE_SCALE
                    step["scoreBreakdown"] = scored_step
                    step["referenceLossPoints"] = scored_step.get("referenceLossPoints", 0)
                    step["expectedPrefixCashAfter"] = prefix_cash
                    step["expectedPrefixAppraisalAfter"] = prefix_appraisal
                    step["expectedInvestmentBalanceAfter"] = next_state.investment_balance
                    step["expectedMovementCashProxyAfter"] = next_state.economy_movements * self.scorer.step_ingot
                if single_step:
                    step["actualActionPointsBefore"] = observed_action_points
                    step["actualActionPointsAfter"] = observed_action_points - cost + gain + (
                        1 if first_lookout is not None else 0
                    )
                affected = [index for index in sorted({entry, arrival}) if self.nodes[index].marks]
                if affected:
                    step["nodeEffects"] = [
                        {"nodeId": self.nodes[index].id,
                         "baseCategoryId": self.nodes[index].base_category,
                         "effectiveCategoryId": (
                             "node_type_020" if current.done & _bit(index)
                             and not self.nodes[index].repeatable
                             else self.nodes[index].effective_category
                         ),
                         "residentBattle": "node_mark_001" in self.nodes[index].marks
                         and not current.done & _bit(index),
                         "baseRewardSuppressed": "node_mark_001" in self.nodes[index].marks
                         and not current.done & _bit(index) and not self.nodes[index].lookout,
                         "lookoutPreserved": self.nodes[index].lookout and not current.done & _bit(index),
                         "fruitRewardAvailable": "node_mark_007" in self.nodes[index].marks
                         and not current.done & _bit(index)}
                        for index in affected
                    ]
                labels.append(_Label(next_state, label_index, step, next_trajectory, next_preference))
                new_index = len(labels) - 1
                record_generated(new_index, next_key)
                if pursuit_terminal:
                    self._offer(complete, candidate(new_index, "pursuit", pursuit_metrics, area_exit=True), top_n)
                    if len(complete) >= top_n:
                        pursuit_cutoff = min(other.metrics[0] for other in complete)
                    pursuit_terminals_settled += 1
                    continue
                if entry in self.treehole_nodes and step.get("actualActionPointsAfter", action_after) > 0:
                    for sacrifice_index, uses in enumerate(next_state.uses):
                        if uses > 0:
                            self._offer(treehole_branches,
                                        candidate(new_index, self.nodes[entry].id,
                                                   self._metrics(next_state, initial_done, items,
                                                                 treehole_item_index=sacrifice_index),
                                                   treehole_item_index=sacrifice_index), top_n)
                serial += 1
                heapq.heappush(queue, (priority(next_state), new_index))
            if limited:
                break

        if limited:
            # Budget exhaustion stops expansion, not evaluation of generated terminal states.
            for _, label_index in queue:
                if label_index in inventory_frontier.obsolete or label_index not in seen.get(self._state_key(labels[label_index].state, item_groups), []):
                    continue
                label = labels[label_index]
                current = label.state
                area_exit = current.position in self.exit_nodes
                if single_step and label.parent is not None:
                    goal_id = self.nodes[current.position].id
                elif area_exit and not pursuit:
                    goal_id = self.nodes[current.position].id
                elif (current.action_points == 0 and pursuit and not single_step
                      and (not area_exit or self.nodes[current.position].category == END_CATEGORY)):
                    goal_id = "pursuit"
                    area_exit = True
                else:
                    continue
                terminal_frontier_evaluated += 1
                self._offer(complete, candidate(
                    label_index, goal_id, self._metrics(current, initial_done, items, area_exit=area_exit),
                    area_exit=area_exit,
                ), top_n)

        selected = self._select(complete, top_n, labels)
        branches = self._select(treehole_branches, top_n, labels)
        route_groups = []
        if self.group_by_priority:
            for mask in sorted({candidate.relevance_mask for candidate in complete}):
                grouped = self._select([candidate for candidate in complete if candidate.relevance_mask == mask], top_n, labels)
                route_groups.append({"relatedGoalIds": [target["id"] for i, target in enumerate(self.planning_targets) if mask & _bit(i)],
                                     "routes": [self._route(candidate, labels, items,
                                                            "rolling_step" if single_step and not candidate.area_exit else
                                                            "pursuit" if pursuit and not single_step else "exit") for candidate in grouped]})
        if not complete and not pursuit and not single_step and not self.exit_nodes:
            warnings.append("No exit node is identified; only treehole branch routes may be available")
        if any(node.category == TREEHOLE_CATEGORY for node in self.nodes):
            warnings.append("Treehole entry consumes the listed processing item; routes continuing past that node decline entry")
        warnings.append("Unknown node outcomes, combat results, and item/relic side effects are not simulated; replan after changes")
        if single_step:
            warnings.append("Blind-zone planning uses at most 1 AP and one movement; refresh the map before the next plan")
        if any("node_mark_001" in node.marks for node in self.nodes):
            warnings.append("Resident occupancy is from the confirmed snapshot; future resident movement is not simulated")
        if self.unconfigured_recruitment and self.scorer is None:
            warnings.append("Danger-end recruitment utility is unconfigured; no recruitment points are added there")
        if self.scorer is not None:
            warnings.extend(sorted(self.scorer.warnings))
        return localize_result({
            "schemaVersion": 3 if self.scorer is not None else 2,
            "templateId": self.template_id,
            "planningNodeKnowledge": self.template_knowledge,
            "lookoutVisibilityRule": self.lookout_visibility_rule,
            "mode": "single_step" if single_step else "pursuit" if pursuit else "exit",
            "searchComplete": not limited,
            "requestedTopN": top_n,
            "priorityTargets": [{"id": target["id"], "name": target["name"]} for target in self.planning_targets],
            "routeGroups": route_groups,
            "priorityFiltering": {"enabled": self.group_by_priority, "topNPerGroup": top_n,
                                  "relation": "visited_or_newly_revealed_candidate", "sort": "weightedValue"},
            "trajectoryAlternativesPerState": trajectory_limit,
            "planningPolicy": {
                "mode": "single_step" if single_step else "full_route",
                "utopiaId": state.get("utopiaId"),
                "observedActionPoints": observed_action_points,
                "planningActionPoints": action_points,
                "replanAfterMovement": single_step,
            },
            "randomMovement": {
                "status": "not_implemented",
                "policy": "excluded_from_guaranteed_routes; inventory and treehole sacrifice retained",
                "excludedItemInstanceIds": [item.instance_id for item in items
                                            if item.allowed and item.uses and not item.rule.deterministic],
            },
            "selection": ("score-ranked trajectory representatives; feasible allocation preference breaks same-path score ties"
                          if self.scorer is not None else "per-goal Pareto representatives; display sorted by weightedValue first, not probability"),
            "weightPolicy": {
                "baseRewardNode": 1.0,
                "unknownMysteryVisitPenalty": -0.5,
                "unknownFerocityVisitPenalty": -0.2,
                "newUnknownMysteryReveal": 0.2,
                "newUnknownFerocityReveal": 0.05,
                "recruitmentScorePrecision": 0.05,
                "unconfiguredRecruitmentNodes": list(self.unconfigured_recruitment),
            } if self.scorer is None else {"mode": "snapshot_expected_utility", "revealCoefficient": self.scorer.reveal_coefficient,
                                           "scorePrecision": 1 / SCORE_SCALE, "endingAddOns": "selected per-floor soft targets; selected tribute loss is reference-only",
                                           "unconfiguredRecruitmentNodes": []},
            **({"scoring": self.scorer.report()} if self.scorer is not None else {}),
            "expandedStates": expanded,
            "generatedStates": len(labels),
            "searchDiagnostics": {
                "algorithm": "best_first",
                "searchMode": search_mode,
                "queueOrder": (["selectedKnownPrerequisites", "selectedPrerequisiteSearchCoverage"] if self.planning_targets and not self.group_by_priority else []) + ["weightedValue", "newNodes", "survivingProcessingItems",
                               "remainingItemUses", "insertionOrder"],
                "exitDistanceUse": "optimistic feasibility check only, not queue or route ranking",
                "actionPointsUse": "movement feasibility and state transitions, not an extra ranking score",
                "prerequisiteRanking": ("retain top N per relevance combination; score-ranked within filters" if self.group_by_priority else
                                        "lexicographic soft targets; maximize reachable subset, not a hard all-target filter"),
                "priorityStateMerging": "done/information masks preserve goal progress; only equal-future states can merge",
                "budgetStop": limited,
                "duplicateStatesSkipped": duplicate_states,
                "equivalentItemActionsSkipped": equivalent_actions,
                "unreachableStatesPruned": unreachable_states,
                "terminalFrontierEvaluated": terminal_frontier_evaluated,
                "dominatedInventoryStatesSkipped": dominated_inventories,
                "obsoleteQueuedStatesSkipped": obsolete_labels_skipped,
                "targetEffectsReused": target_effects_reused,
                "inventoryDominanceEnabled": dominance_enabled,
                "scoredInventoryDominanceGuards": scored_guards,
                "allocationFrameCount": len(inventory_frontier.groups),
                "geometricPathNodesCreated": len(trajectory_pool.nodes) + 1,
                "geometricPathNodesReused": trajectory_pool.hits,
                "geometryCacheEntries": len(geometry_cache.cache),
                "sharedScoreTransitionsReused": score_cache_hits,
                "scoreCacheEntries": len(score_cache),
                "pursuitTerminalsPruned": pursuit_terminals_pruned,
                "pursuitTerminalsSettledWithoutQueue": pursuit_terminals_settled,
                "lastActionPointExceptions": last_ap_exceptions,
                "walkingEquivalentItemActionsSkipped": walking_equivalents,
                "zeroAPNonterminalActionsPruned": zero_ap_dead_ends,
                "noEffectEndReentriesSkipped": no_effect_end_reentries,
                "itemEquivalenceGroups": [[items[i].instance_id for i in indices] for indices in item_groups],
                "itemPreference": "walk first at equal AP; last-AP AP-affecting items first; then smaller reach, expiring first, more uses; fewer uses when free slots <= 1",
                "preferenceScope": "feasible allocations; score first, then whole-path item preference for the same trajectory",
                "routeDeduplication": "entered/arrived node sequence, not item instance IDs",
            },
            "routes": [self._route(item, labels, items,
                                   "rolling_step" if single_step and not item.area_exit else
                                   "pursuit" if pursuit and not single_step else "exit") for item in selected],
            "treeholeBranches": [self._route(item, labels, items,
                                             "treehole_replan") for item in branches],
            "warnings": [message(text) for text in warnings],
        })
