"""Shared geometry and constrained movement choices; inventories are not scalar ranges."""

from __future__ import annotations

from typing import Callable, NamedTuple


def item_preference(rule, uses: int, scope: int, free_slots: int | None) -> tuple[int, ...]:
    return (scope, int(rule.target == "any"), int(not rule.expires_on_exit),
            uses if free_slots is not None and free_slots <= 1 else -uses)


class MoveChoice(NamedTuple):
    kind: str
    entry: int
    item_index: int | None
    cost: int
    gain: int


class TrajectoryPool:
    def __init__(self):
        self.nodes = {}
        self.hits = 0

    def extend(self, parent, entry, arrival):
        key = (parent, entry, arrival)
        if key in self.nodes:
            self.hits += 1
            return self.nodes[key]
        index = len(self.nodes) + 1
        self.nodes[key] = index
        return index


class MovementAllocator:
    def __init__(self, nodes, adjacent, items, targets, scopes):
        self.nodes, self.adjacent, self.items = nodes, adjacent, items
        self.targets, self.scopes = targets, scopes

    def preference(self, choice, uses, free_slots, last_ap):
        item_index = choice[2]
        if item_index is None:
            return (int(last_ap), 0, 0, 0, 0, -1)
        item = self.items[item_index]
        return (0 if last_ap and (item.rule.action_cost == 0 or item.rule.action_gain > 0) else 1,
                *item_preference(item.rule, uses[item_index], self.scopes[item_index], free_slots), item_index)

    def choices(self, position, uses, ap, done, visible, free_slots, *, grouped=True):
        choices = [MoveChoice("walk", target, None, 1, 0) for target in self.adjacent[position]]
        if self.nodes[position].repeatable:
            choices.append(MoveChoice("reenter", position, None, 1, 0))
        last_ap = ap == 1 and any(item.allowed and count > 0
            and (item.rule.action_cost == 0 or item.rule.action_gain > 0)
            for item, count in zip(self.items, uses))
        order = sorted(range(len(self.items)), key=lambda i: (
            item_preference(self.items[i].rule, uses[i], self.scopes[i], free_slots), self.items[i].instance_id))
        for i in order:
            item = self.items[i]
            if not item.allowed or not item.rule.deterministic or not uses[i]:
                continue
            for target in self.targets[i][position]:
                if item.rule.target == "revealed_merchant" and not visible & (1 << target):
                    continue
                if item.rule.target == "noncombat":
                    node = self.nodes[target]
                    category = "node_type_020" if done & (1 << target) and not node.repeatable else node.category
                    if not item.rule.reaches(self.nodes[position].coord, node.coord, category, True):
                        continue
                choices.append(MoveChoice("item", target, i, item.rule.action_cost, item.rule.action_gain))
        if grouped and self.items:
            if last_ap:
                choices.sort(key=lambda choice: 0 if choice.item_index is not None
                             and (choice.cost == 0 or choice.gain > 0) else 1)
            by_entry = {}
            for choice in choices:
                by_entry.setdefault(choice.entry, []).append(choice)
            choices = [choice for variants in by_entry.values() for choice in variants]
        return choices, last_ap


class GeometryCache:
    def __init__(self, nodes, portals, reveal: Callable, limit=65536):
        self.nodes, self.portals, self.reveal = nodes, portals, reveal
        self.limit, self.cache = limit, {}
        self.hits = self.misses = 0

    def resolve(self, entry, done, visible):
        key = (entry, done, visible)
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        self.misses += 1
        arrival = self.portals.get(entry, entry)
        entered = (1 << entry) | (1 << arrival)
        lookout = next((i for i in (entry, arrival) if self.nodes[i].lookout and not done & (1 << i)), None)
        next_done = done | entered
        next_visible = self.reveal(arrival, next_done, visible | entered, lookout)
        result = entered, lookout, next_done, next_visible, (next_visible & ~visible) & ~entered
        if len(self.cache) < self.limit:
            self.cache[key] = result
        return result
