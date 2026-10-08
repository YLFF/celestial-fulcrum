from __future__ import annotations

from typing import Any


class InventoryFrontier:
    """Keep componentwise-incomparable inventories for one future-equivalent state."""

    def __init__(self, limits: tuple[int, ...] | None = None) -> None:
        self.groups: dict[tuple[Any, ...], list[tuple[tuple[int, ...] | int, int]]] = {}
        self.obsolete: set[int] = set()
        self.width = max(limits, default=0).bit_length() + 1 if limits is not None else 0
        self.dimensions = len(limits or ())
        self.guard = sum(1 << (self.width * i + self.width - 1) for i in range(len(limits or ())))
        self.packed: dict[tuple[int, ...], int] = {}

    def _vector(self, uses: tuple[int, ...]) -> tuple[int, ...] | int:
        if not self.width:
            return uses
        if uses not in self.packed:
            if len(uses) != self.dimensions or any(value < 0 or value >= 1 << (self.width - 1) for value in uses):
                raise ValueError("inventory count exceeds its packed comparison bounds")
            self.packed[uses] = sum(value << (self.width * i) for i, value in enumerate(uses))
        return self.packed[uses]

    def _at_least(self, left: tuple[int, ...] | int, right: tuple[int, ...] | int) -> bool:
        if self.width:
            # One guard bit per charge count absorbs borrowing inside that lane.
            # All guards survive subtraction iff every left count >= its right count.
            return ((left | self.guard) - right) & self.guard == self.guard
        return all(a >= b for a, b in zip(left, right))

    def admit(self, key: tuple[Any, ...], uses: tuple[int, ...], label_id: int) -> bool:
        peers = self.groups.setdefault(key, [])
        vector = self._vector(uses)
        if any(self._at_least(other, vector) for other, _ in peers):
            return False
        kept = []
        for other, other_id in peers:
            if self._at_least(vector, other):
                self.obsolete.add(other_id)
            else:
                kept.append((other, other_id))
        kept.append((vector, label_id))
        self.groups[key] = kept
        return True


class ScoredInventoryFrontier(InventoryFrontier):
    """A larger inventory only dominates with adequate score and tie preference."""

    def admit(self, key, uses, label_id, score=0, preference=()):
        peers = self.groups.setdefault(key, [])
        vector = self._vector(uses)

        def better(a, a_score, a_preference, b, b_score, b_preference):
            return (a_score >= b_score and self._at_least(a, b)
                    and (a_score > b_score or a_preference <= b_preference))

        if any(better(other, points, pref, vector, score, preference)
               for other, points, pref, _ in peers):
            return False
        kept = []
        for other, points, pref, other_id in peers:
            if better(vector, score, preference, other, points, pref):
                self.obsolete.add(other_id)
            else:
                kept.append((other, points, pref, other_id))
        kept.append((vector, score, preference, label_id))
        self.groups[key] = kept
        return True
