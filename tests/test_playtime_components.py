"""The component box is a validated inventory, not a Markdown-only table."""

from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from fulcrum.component_box import acquire_component, add_component, INITIAL_VALUES, remove_component, route_items, set_capacity, update_component
from fulcrum.playtime_state import new_playtime, validate_playtime
from fulcrum.playtime_state import merge_map_observation, update_node
from fulcrum.playtime_route import route_inputs
from fulcrum.playtime_view import replace_runtime_sections
from fulcrum.route_planner import RoutePlanner
from fulcrum.map_catalog import TemplateCatalog


ROOT = Path(__file__).resolve().parents[1]


class ComponentBoxTests(unittest.TestCase):
    def test_controller_initial_appraisal_is_sixteen(self):
        box = new_playtime("controller")["componentBox"]
        item = acquire_component(box, "component_012")
        self.assertEqual(INITIAL_VALUES["component_012"], 16)
        self.assertEqual(item["estimatedValue"], 16)

    def test_route_adapter_preserves_hidden_end_and_accepts_external_recruitment_value(self) -> None:
        state = new_playtime("hidden-end")
        template = TemplateCatalog().candidates("main", 1)[0]
        terminal = template.coord(template.terminal_slots[0]).key
        observed = {
            "success": True, "area": "main", "floor": 1, "templateId": template.id,
            "nodes": [
                {"id": template.coord(slot).key, "coord": [template.coord(slot).x, template.coord(slot).y],
                 "slot": list(slot), "categoryId": None if slot in template.terminal_slots else
                 "start" if slot == template.start_slot else "node_type_001",
                 "visibility": "hidden" if slot in template.terminal_slots else "revealed", "marks": []}
                for slot in template.occupied_slots
            ],
            "edges": [[template.coord(a).key, template.coord(b).key] for a, b in template.edges],
            "playerPositionObservation": {"status": "recognized", "nodeId": "0,0"},
        }
        instance = merge_map_observation(state, "I", observed)
        instance["actionPoints"] = 6
        before = deepcopy(state)
        game_map, inputs = route_inputs(state, recruitment_scores={terminal: 0.4})
        self.assertEqual(state, before)
        result = RoutePlanner(game_map).plan(inputs)
        self.assertEqual(result["routes"][0]["endNode"], terminal)
        self.assertEqual(result["routes"][0]["metrics"]["recruitmentValue"], 0.4)
        self.assertEqual(instance["nodes"][terminal]["visibility"], "hidden")
        self.assertEqual(result["weightPolicy"]["unconfiguredRecruitmentNodes"], [])
        with self.assertRaisesRegex(ValueError, "unknown nodes"):
            route_inputs(state, recruitment_scores={"7,7": 1})

    def test_instances_capacity_uses_and_route_filter(self) -> None:
        state = new_playtime("box")
        box = state["componentBox"]
        self.assertEqual(box["capacity"], 8)
        self.assertEqual([item["componentId"] for item in box["items"]], ["component_001", "component_001"])
        self.assertEqual([item["estimatedValue"] for item in box["items"]], [2, 2])
        first = add_component(box, "component_015", estimated_value=11)
        second = add_component(box, "component_015", estimated_value=8, remaining_uses=1, route_candidate=False)
        natural = add_component(box, "component_001", estimated_value=4)
        self.assertNotEqual(first["instanceId"], second["instanceId"])
        self.assertEqual(first["remainingUses"], 3)
        self.assertIsNone(natural["remainingUses"])
        self.assertEqual(route_items(box), [{"instanceId": first["instanceId"], "componentId": "component_015", "remainingUses": 3}])
        update_component(box, second["instanceId"], routeCandidate=True, remainingUses=1)
        self.assertEqual(len(route_items(box)), 2)
        with self.assertRaisesRegex(ValueError, "remaining uses"):
            update_component(box, second["instanceId"], remainingUses=4)
        set_capacity(box, 2)
        self.assertEqual(len(route_items(box)), 2)
        validate_playtime(state)
        with self.assertRaisesRegex(ValueError, "capacity"):
            set_capacity(box, -1)
        remove_component(box, natural["instanceId"])
        remove_component(box, first["instanceId"])
        remove_component(box, second["instanceId"])
        set_capacity(box, 2)
        validate_playtime(state)

    def test_render_only_managed_sections(self) -> None:
        state = new_playtime("render")
        box = state["componentBox"]
        add_component(box, "component_023", instance_id="principle", estimated_value=42, remaining_uses=2)
        state["resources"]["hope"] = 10
        template = (ROOT / "BLACKFLOW_PLAYTIME_TEMPLATE.md").read_text(encoding="utf-8")
        rendered = replace_runtime_sections(template, state)
        self.assertIn("零件箱（当前 3 件，上限 8 件）", rendered)
        self.assertIn("| `principle` | `component_023` | 结构性原理 | 加工品 | 42 | 2 | 是 |", rendered)
        self.assertIn("| 希望 | 10 | - |", rendered)
        self.assertIn("| 总估价 | 46 | - |", rendered)
        self.assertEqual(rendered.count("## 8. 随手记录"), 1)
        self.assertEqual(replace_runtime_sections(rendered, state), rendered)

    def test_route_adapter_uses_current_inventory_and_confirmed_position(self) -> None:
        state = new_playtime("route")
        observed = {
            "success": True, "area": "treehole", "floor": 3, "templateId": "treehole-01",
            "nodes": [
                {"id": "0,0", "coord": [0, 0], "slot": [0, 0], "categoryId": "start", "visibility": "revealed", "marks": []},
                {"id": "1,0", "coord": [1, 0], "slot": [1, 0], "categoryId": "node_type_001", "visibility": "revealed", "marks": []},
            ],
            "edges": [["0,0", "1,0"]],
            "playerPositionObservation": {"status": "recognized", "nodeId": "1,0"},
        }
        from fulcrum.map_catalog import TemplateCatalog
        observed["templateId"] = TemplateCatalog().candidates("treehole", 3)[0].id
        instance = merge_map_observation(state, "III-treehole", observed)
        instance["actionPoints"] = 3
        instance["utopiaId"] = "utopia_005"
        update_node(state, "III-treehole", "0,0", confirmed_mark_ids=["node_mark_007"])
        add_component(state["componentBox"], "component_015")
        add_component(state["componentBox"], "component_014", route_candidate=False)
        self.assertEqual(instance["nodes"]["1,0"]["completion"], "completed")
        route_inputs(state)
        update_node(state, "III-treehole", "1,0", completion="pending")
        with self.assertRaisesRegex(ValueError, "complete the current node"):
            route_inputs(state)
        update_node(state, "III-treehole", "1,0", completion="completed")
        map_result, route_state = route_inputs(state, pursuit=True, top_n=3)
        self.assertEqual(map_result["nodes"][1]["categoryId"], "node_type_001")
        self.assertEqual(route_state["position"], "1,0")
        self.assertEqual(route_state["actionPoints"], 3)
        self.assertEqual(route_state["utopiaId"], "utopia_005")
        self.assertEqual(route_state["componentBoxFreeSlots"], 4)
        self.assertEqual(map_result["nodes"][0]["confirmedMarkIds"], ["node_mark_007"])
        self.assertEqual(len(route_state["items"]), 2)
        self.assertEqual(route_state["items"][0]["componentId"], "component_015")
        self.assertEqual(route_state["useItemIds"], [route_state["items"][0]["instanceId"]])
        self.assertEqual(route_state["completedNodes"], ["1,0", "0,0"])
        self.assertTrue(route_state["pursuit"])
        validate_playtime(state)
        instance["utopiaId"] = "utopia_999"
        with self.assertRaisesRegex(ValueError, "utopia"):
            validate_playtime(state)


if __name__ == "__main__":
    unittest.main()
