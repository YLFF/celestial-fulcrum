"""Exact count-vector DP for a declared, approximate node-generation model.

Count priors and placement likelihoods are separate: each count vector has
its own placement partition. Otherwise vectors with more placements acquire
an accidental combinatorial prior. Application eligibility is handled by
the adapter in node_posterior.py, independently of this numerical core.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import product
from math import exp, prod
from time import perf_counter


def max_entropy(minimum: int, maximum: int, mean: float) -> dict[int, float]:
    if not minimum <= mean <= maximum:
        raise ValueError("sample mean is outside allowed count bounds")
    if mean == minimum:
        return {n: float(n == minimum) for n in range(minimum, maximum + 1)}
    if mean == maximum:
        return {n: float(n == maximum) for n in range(minimum, maximum + 1)}
    def distribution(parameter):
        anchor = maximum if parameter > 0 else minimum
        weights = {n: exp(parameter * (n - anchor)) for n in range(minimum, maximum + 1)}
        total = sum(weights.values())
        return {n: weight / total for n, weight in weights.items()}
    low, high = -100.0, 100.0
    for _ in range(100):
        middle = (low + high) / 2
        rows = distribution(middle)
        if sum(n * p for n, p in rows.items()) < mean:
            low = middle
        else:
            high = middle
    return distribution((low + high) / 2)


@dataclass
class Slot:
    id: str
    weights: dict[str, float]


class FamilyModel:
    def __init__(self, slots: list[Slot], priors: dict[str, dict[int, float]], *, state_limit=2_000_000):
        self.slots = sorted(slots, key=lambda slot: (len(slot.weights), slot.id))
        self.priors = priors
        self.types = list(priors)
        self.index = {name: index for index, name in enumerate(self.types)}
        self.maximum = [max(rows) for rows in priors.values()]
        if any(n >= 16 for n in self.maximum):
            raise ValueError("packed counts support at most 15 nodes per type")
        self.state_limit = state_limit
        self.choices = {slot.id: [(self.index[name], weight) for name, weight in slot.weights.items() if weight > 0]
                        for slot in slots}
        if any(not rows for rows in self.choices.values()):
            raise ValueError("a family slot has no positive-weight candidate")
        started = perf_counter()
        layers, _, transitions = self._forward(self.slots, 0)
        self.partition = layers[-1]
        self.preparation_seconds = perf_counter() - started
        self.preparation_states = sum(map(len, layers))
        self.preparation_transitions = transitions
        # Only feasible totals are retained; conditioning all priors on this
        # family's slot count has a common normalization that cancels later.
        self.terminal = {key: self.count_prior(key) / value for key, value in self.partition.items()
                         if value > 0 and self.count_prior(key) > 0}
        if not self.terminal:
            raise ValueError("no count prior is compatible with the family skeleton")

    def counts(self, key):
        return [(key >> (4 * index)) & 15 for index in range(len(self.types))]

    def count_prior(self, key):
        return prod(self.priors[name].get(n, 0) for name, n in zip(self.types, self.counts(key)))

    def advance(self, key, index):
        shift = 4 * index
        if ((key >> shift) & 15) >= self.maximum[index]:
            return None
        return key + (1 << shift)

    def _forward(self, slots, initial, *, count_ways=False):
        layers = [{initial: 1.0}]
        ways = {initial: 1}
        transitions = 0
        for slot in slots:
            next_values, next_ways = {}, {}
            for key, value in layers[-1].items():
                for index, weight in self.choices[slot.id]:
                    target = self.advance(key, index)
                    if target is None:
                        continue
                    next_values[target] = next_values.get(target, 0.0) + value * weight
                    if count_ways:
                        next_ways[target] = next_ways.get(target, 0) + ways[key]
                    transitions += 1
            if sum(map(len, layers)) + len(next_values) > self.state_limit:
                raise RuntimeError("exact DP state limit reached; no approximate result returned")
            layers.append(next_values)
            if count_ways:
                ways = next_ways
        return layers, ways if count_ways else {}, transitions

    def _evidence(self, known):
        initial = 0
        for node_id, name in known.items():
            if node_id not in self.choices or name not in self.slots_by_id[node_id].weights:
                raise ValueError(f"known category contradicts slot rules: {node_id}={name}")
            initial = self.advance(initial, self.index[name])
            if initial is None:
                raise ValueError("known category count exceeds the floor maximum")
        return initial, [slot for slot in self.slots if slot.id not in known]

    @property
    def slots_by_id(self):
        return {slot.id: slot for slot in self.slots}

    def predict(self, known: dict[str, str], *, marker_type=None, excluded_marker_ids=(), marker_requests=None):
        started = perf_counter()
        initial, unknown = self._evidence(known)
        layers, ways, transitions = self._forward(unknown, initial, count_ways=True)
        terminal = {key: self.terminal.get(key, 0) for key in layers[-1]}
        backward = terminal.copy()
        normalizer = sum(value * backward[key] for key, value in layers[-1].items())
        if normalizer <= 0:
            raise ValueError("observations are impossible under the declared model")
        posterior = {}
        for offset in range(len(unknown) - 1, -1, -1):
            slot = unknown[offset]
            masses = {name: 0.0 for name in self.types}
            previous = {}
            for key, forward in layers[offset].items():
                total = 0.0
                for index, weight in self.choices[slot.id]:
                    target = self.advance(key, index)
                    contribution = weight * backward.get(target, 0) if target is not None else 0
                    total += contribution
                    masses[self.types[index]] += forward * contribution
                previous[key] = total
            posterior[slot.id] = {name: mass / normalizer for name, mass in masses.items()}
            backward = previous
        result = {"unknownCount": len(unknown), "rawCombinations": prod(len(self.choices[s.id]) for s in unknown),
                "legalCompletions": sum(n for key, n in ways.items() if self.terminal.get(key, 0) > 0),
                "dpStates": sum(map(len, layers)), "peakLayerStates": max(map(len, layers)),
                "transitions": transitions, "seconds": perf_counter() - started, "probabilities": posterior,
                "posteriorRemainingMeans": {name: sum(row[name] for row in posterior.values()) for name in self.types}}
        requests = dict(marker_requests or {})
        if marker_type is not None:
            requests["legacy"] = {"type": marker_type, "excludedIds": excluded_marker_ids}
        markers = {}
        for marker_id, request in requests.items():
            name = request["type"]
            marker_index = self.index[name]
            competing = request.get("competingMarkers", 1)
            excluded = set(request.get("excludedIds", ()))
            if not excluded <= known.keys():
                raise ValueError("excluded marker positions must have a known category")
            excluded_count = sum(known[key] == name for key in excluded)
            # Select one marker among generated eligible nodes, without
            # conditioning the ordinary category on its existence.
            marker_backward = {}
            for key in layers[-1]:
                count = self.counts(key)[marker_index] - excluded_count
                marker_backward[key] = terminal[key] / max(count, competing) if count > 0 else 0
            known_share = sum(value * marker_backward[key] for key, value in layers[-1].items()) / normalizer
            positions = {key: known_share for key, category in known.items() if category == name and key not in excluded}
            for offset in range(len(unknown) - 1, -1, -1):
                slot = unknown[offset]
                previous, mass = {}, 0.0
                for key, forward in layers[offset].items():
                    total = 0.0
                    for index, weight in self.choices[slot.id]:
                        target = self.advance(key, index)
                        contribution = weight * marker_backward.get(target, 0) if target is not None else 0
                        total += contribution
                        if index == marker_index:
                            mass += forward * contribution
                    previous[key] = total
                positions[slot.id] = mass / normalizer
                marker_backward = previous
            markers[marker_id] = positions
        if markers:
            result["markerProbabilities"] = markers
        if marker_type is not None:
            result["conditionalMarkerProbabilities"] = markers["legacy"]
        result["seconds"] = perf_counter() - started
        return result

    def brute_force(self, known, *, limit=200_000):
        initial, unknown = self._evidence(known)
        if prod(len(self.choices[slot.id]) for slot in unknown) > limit:
            raise ValueError("brute-force verification is restricted to a small exact fixture")
        started = perf_counter()
        sums = {slot.id: Counter() for slot in unknown}
        total, legal = 0.0, 0
        for choices in product(*(self.choices[slot.id] for slot in unknown)):
            key, likelihood = initial, 1.0
            for index, weight in choices:
                key = self.advance(key, index)
                if key is None:
                    break
                likelihood *= weight
            if key is None or not self.terminal.get(key, 0):
                continue
            mass = likelihood * self.terminal[key]
            legal += 1
            total += mass
            for slot, (index, _) in zip(unknown, choices):
                sums[slot.id][self.types[index]] += mass
        if not total:
            raise ValueError("no compatible brute-force completion")
        return {"seconds": perf_counter() - started, "legalCompletions": legal,
                "probabilities": {id: {name: row[name] / total for name in self.types} for id, row in sums.items()}}

    def example_completion(self, known):
        initial, unknown = self._evidence(known)
        failed = set()
        def visit(offset, key):
            if offset == len(unknown):
                return {} if self.terminal.get(key, 0) > 0 else None
            if (offset, key) in failed:
                return None
            slot = unknown[offset]
            for index, _ in self.choices[slot.id]:
                target = self.advance(key, index)
                if target is None:
                    continue
                rest = visit(offset + 1, target)
                if rest is not None:
                    return {slot.id: self.types[index], **rest}
            failed.add((offset, key))
            return None
        result = visit(0, initial)
        if result is None:
            raise ValueError("no compatible completion")
        return {**known, **result}
