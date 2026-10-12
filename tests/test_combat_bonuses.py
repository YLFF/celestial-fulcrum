"""Focused tests for derived combat summaries; no frontend or scoring changes."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from fulcrum.combat_bonuses import describe_layer_environment, fresh_relic_state, render_combat_bonuses, summarize_combat_bonuses
from fulcrum.playtime_state import new_playtime
from fulcrum.relic_effects import evaluate_numeric, load_definitions
from fulcrum.service.app import create_app


ROOT = Path(__file__).resolve().parents[1]


def rows(view, metric=None, side=None, domain=None, bucket=None):
    return [row for category in view["categories"] for row in category["rows"]
            if (metric is None or row["metric"] == metric) and (side is None or row["side"] == side)
            and (domain is None or row["domain"] == domain) and (bucket is None or row["bucket"] == bucket)]


class CombatBonusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definitions = load_definitions()

    def setUp(self):
        sample = json.loads((ROOT / "samples/combat_bonuses/n15_floor2.json").read_text(encoding="utf-8"))
        self.state, self.context = sample["state"], sample["context"]

    def report(self, **context):
        return summarize_combat_bonuses(self.state, context={**self.context, **context})

    def test_sample_constant_and_conditional_scopes(self):
        report = self.report()
        self.assertEqual(rows(report["global"], "attack", "friendly_unit", "outside_battle")[0]["relativeFactor"], "1.2")
        self.assertFalse(rows(report["global"], "redeployment_time"))
        for view in report["operators"]:
            self.assertEqual(view["operator"]["position"], "melee")
            self.assertEqual(rows(view, "attack", "operator", "outside_battle", "constant")[0]["relativeFactor"], "1.55")
            self.assertEqual(rows(view, "max_hp", "operator", "outside_battle", "constant")[0]["relativeFactor"], "1.25")
            self.assertEqual(rows(view, "defense", "operator", "outside_battle", "constant")[0]["relativeFactor"], "1.2")
            attack = rows(view, "attack", "operator", "inside_battle", "conditional")[0]
            self.assertEqual(attack["baseRatioDelta"], "0.64")
            self.assertEqual(rows(view, "max_hp", "operator", "inside_battle")[0]["baseRatioDelta"], "0.64")
            self.assertTrue(rows(view, "attack", "operator", "inside_battle", "unresolved"))
        self.assertFalse(rows(report["operators"][0], "redeployment_time"))
        self.assertEqual(rows(report["operators"][1], "redeployment_time")[0]["relativeFactor"], "0.5")

    def test_enemy_factors_and_coverage(self):
        global_view = self.report()["global"]
        self.assertEqual(rows(global_view, "max_hp", "enemy", bucket="constant")[0]["factor"], "1.70352")
        self.assertEqual(rows(global_view, "attack", "enemy", bucket="constant")[0]["factor"], "1.872")
        self.assertEqual(rows(global_view, "attack", "enemy", bucket="conditional")[0]["factor"], "1.15")
        self.assertEqual(rows(global_view, "damage_taken", "enemy")[0]["factor"], "0.8")
        outside = self.report(dystopiaAffected=False)["global"]
        self.assertEqual(rows(outside, "max_hp", "enemy", bucket="constant")[0]["factor"], "1.3104")
        self.assertEqual(rows(outside, "attack", "enemy", bucket="constant")[0]["factor"], "1.44")
        unknown = self.report(dystopiaAffected=None)["global"]
        self.assertEqual(rows(unknown, "max_hp", "enemy", bucket="constant")[0]["factor"], "1.3104")
        self.assertEqual(rows(unknown, "max_hp", "enemy", bucket="conditional")[0]["factor"], "1.3")

    def test_no_region_or_flight_inference(self):
        context = {key: value for key, value in self.context.items() if key != "enemyRegionCount"}
        report = summarize_combat_bonuses(self.state, context=context)
        self.assertTrue(rows(report["global"], "attack", "enemy", bucket="unresolved"))
        flight = self.report(airborneCount=2)["operators"][1]
        wing = next(row for row in rows(flight, "attack", "operator") if row["sources"][0]["id"] == "relic_130")
        self.assertEqual(wing["bucket"], "conditional")
        self.assertEqual(wing["baseRatioDelta"], "0.5")
        self.assertIn({"scope": {"flightState": "airborne"}}, wing["conditions"])

    def test_used_bindings_survive_without_held_relic_and_do_not_duplicate(self):
        original = self.report()["operators"][1]
        self.state["grantedEffects"] = [{"relicId": "relic_180", "operatorInstanceIds": ["angelina"]}]
        self.assertEqual(rows(self.report()["operators"][1], "redeployment_time"), rows(original, "redeployment_time"))
        self.state["relics"] = [row for row in self.state["relics"] if row["id"] != "relic_180"]
        self.assertEqual(rows(self.report()["operators"][1], "redeployment_time")[0]["relativeFactor"], "0.5")

    def test_one_shot_state_and_profession_validation(self):
        relic = self.state["relics"][2]
        relic.update(value=False, operatorInstanceIds=[])
        self.assertFalse(rows(self.report()["operators"][1], "redeployment_time"))
        relic["value"] = True
        self.assertEqual(rows(self.report()["global"], "redeployment_time")[0]["bucket"], "unresolved")
        relic["operatorInstanceIds"] = ["mechanist"]
        with self.assertRaisesRegex(ValueError, "职业不匹配"):
            self.report()

    def test_granted_acquisitions_are_distinct_and_conflicts_rejected(self):
        self.state["relics"] = []
        self.state["grantedEffects"] = [
            {"acquisitionId": "cookie-1", "relicId": "relic_188", "operatorInstanceIds": ["mechanist"]},
            {"acquisitionId": "cookie-2", "relicId": "relic_188", "operatorInstanceIds": ["angelina"]}]
        report = self.report()
        for view in report["operators"]:
            self.assertEqual(rows(view, "sp_recovery_per_second")[0]["flatDelta"], "0.8")
        duplicate = deepcopy(self.state["grantedEffects"][0])
        self.state["grantedEffects"].append(duplicate)
        self.assertEqual(rows(self.report()["operators"][0], "sp_recovery_per_second")[0]["flatDelta"], "0.8")
        duplicate["operatorInstanceIds"] = ["angelina"]
        with self.assertRaisesRegex(ValueError, "同次获取"):
            self.report()

    def test_lucky_cookie_two_instances_and_sp_channels(self):
        self.state["relics"] = [{"id": "relic_188", "value": True, "operatorInstanceIds": ["mechanist", "angelina"]},
                                {"id": "relic_153", "value": None}]
        report = self.report()
        for view in report["operators"]:
            recovery = rows(view, "sp_recovery_per_second", "operator")
            self.assertTrue(any(row["flatDelta"] == "0.8" for row in recovery))
            self.assertTrue(all(row["tags"] == {"skillRecoveryType": "natural"} for row in recovery))
        self.assertFalse(any(source["id"] == "relic_188" for row in rows(report["global"]) for source in row["sources"]))

    def test_evasion_complement_and_vulnerability_addition(self):
        self.state["relics"] = [{"id": key} for key in ("relic_103", "relic_104", "relic_105", "relic_173")]
        definitions = deepcopy(self.definitions)
        clone = deepcopy(definitions["relic_173"])
        clone["id"], clone["name"] = "test_vulnerable", "测试同类脆弱"
        clone["effects"] = [deepcopy(clone["effects"][1])]
        clone["effects"][0]["value"]["ratio"] = .2
        definitions[clone["id"]] = clone
        self.state["relics"].append({"id": clone["id"]})
        report = summarize_combat_bonuses(self.state, context=self.context, definitions=definitions)
        dodge = rows(report["global"], "dodge_probability")
        self.assertEqual(len(dodge), 2)
        self.assertTrue(all(row["ratio"] == "0.235" for row in dodge))
        fragile = rows(report["global"], "vulnerability")[0]
        self.assertEqual(fragile["ratio"], "0.7")
        self.assertEqual(fragile["factor"], "1.7")
        self.assertEqual(len(fragile["sources"]), 2)

    def test_damage_channels_flat_then_factor_and_combo_dependencies(self):
        self.state["relics"] = [{"id": key} for key in ("relic_225", "relic_227", "relic_167")]
        self.assertFalse(rows(self.report()["global"], "direct_sp_grant"))
        self.state["relics"].append({"id": "relic_160"})
        self.assertTrue(rows(self.report()["global"], "direct_sp_grant"))
        # Test the presentation phases without assuming an operator base panel.
        definitions = deepcopy(self.definitions)
        for index, (operation, value) in enumerate((("flat_delta", 2), ("factor", .5))):
            template = deepcopy(definitions["relic_052"])
            template["id"] = f"cost_{index}"
            template["effects"][0].update(combatCategory="cost", operation=operation, value=value)
            template["effects"][0]["target"] = {"side": "friendly_operator", "metric": "deployment_cost", "scope": {}}
            definitions[template["id"]] = template
        self.state["relics"] = [{"id": "cost_0"}, {"id": "cost_1"}]
        report = summarize_combat_bonuses(self.state, context=self.context, definitions=definitions)
        cost = rows(report["operators"][0], "deployment_cost")[0]
        self.assertEqual((cost["flatDelta"], cost["factor"]), ("2", "0.5"))

    def test_unknown_operator_scope_is_not_silently_counted(self):
        self.state["operators"] = [{"instanceId": "new", "name": "新干员临时占位", "profession": "特种"}]
        self.state["relics"] = [{"id": "relic_052"}]
        report = self.report()
        self.assertEqual(rows(report["operators"][0], "attack", "operator", bucket="constant")[0]["relativeFactor"], "1.2")
        self.assertEqual(rows(report["operators"][0], "attack", "operator", bucket="unresolved")[0]["pending"], ["部署位未确认"])

    def test_counters_random_recipient_and_loss_reset(self):
        self.state["relics"] = [{"id": "relic_197", "value": 10}, {"id": "relic_035", "value": 7},
                                {"id": "relic_218", "value": 10}]
        report = self.report()
        for view in report["operators"]:
            constant = rows(view, "attack", "operator", bucket="constant")[0]
            self.assertEqual(constant["relativeFactor"], "1.94")
            random = rows(view, "attack", "operator", bucket="conditional")[0]
            self.assertEqual(random["relativeFactor"], "1.55")
        self.state["squad"] = ["angelina"]
        self.assertFalse(rows(self.report()["operators"][0], "attack", "operator", bucket="conditional"))
        for key in ("relic_193", "relic_208", "relic_218"):
            self.assertEqual(fresh_relic_state(key)["value"], 0)
            self.assertTrue(self.definitions[key]["lossPolicy"]["resetCounterOnReacquire"])
        self.assertFalse(self.definitions["relic_198"]["effects"][0]["revokeOnLoss"])

    def test_cash_snapshot_and_component_count_are_from_real_state(self):
        self.state["resources"] = {"originiumIngot": 14}
        self.state["componentBox"] = {"items": [{}, {}]}
        self.state["relics"] = [{"id": "relic_192"}, {"id": "relic_199"}]
        report = summarize_combat_bonuses(self.state, context={"enemyRegionCount": 2})
        self.assertEqual(rows(report["global"], "attack_speed")[0]["flatDelta"], "14")
        self.assertEqual(rows(report["global"], "attack", "friendly_operator", "inside_battle")[0]["baseRatioDelta"], "0.16")

    def test_difficulty_variants_expiry_and_description_only(self):
        self.state["relics"] = [{"id": "relic_002"}, {"id": "relic_034", "value": 3},
                                {"id": "relic_126"}, {"id": "relic_127"}]
        report = self.report()
        self.assertEqual(rows(report["global"], "attack_speed")[0]["flatDelta"], "7")
        self.assertFalse(any(source["id"] == "relic_034" for row in rows(report["global"]) for source in row["sources"]))
        cocoa = next(row for row in rows(report["global"], "attack") if row["sources"][0]["id"] == "relic_126")
        self.assertEqual(cocoa["strategy"], "describe")
        self.assertNotIn("relativeFactor", cocoa)

    def test_no_mutation_and_json_markdown_serialization(self):
        before = deepcopy((self.state, self.context))
        report = self.report()
        self.assertEqual((self.state, self.context), before)
        json.dumps(report)
        text = render_combat_bonuses(report)
        self.assertIn("+55%", text)
        self.assertIn("-50%", text)
        self.assertIn("起飞状态", text)

    def test_all_definitions_are_readable_without_filling_unknowns(self):
        self.state["relics"] = [fresh_relic_state(key) for key in self.definitions]
        report = self.report()
        json.dumps(report)
        self.assertTrue(render_combat_bonuses(report))
        self.assertEqual(len(self.definitions), 239)

    def test_outside_attribute_percentages_sum_with_technology(self):
        self.state["relics"].append({"id": "relic_051"})
        report = self.report()
        for view in report["operators"]:
            attack = rows(view, "attack", "operator", "outside_battle", "constant")[0]
            self.assertEqual((attack["baseRatioDelta"], attack["relativeFactor"]), ("0.8", "1.8"))
            self.assertEqual(len(attack["multiplicationZones"]), 1)
            self.assertEqual(attack["multiplicationZones"][0]["id"], "outside_attribute")
            self.assertEqual({source["id"] for source in attack["sources"]},
                             {"technology", "relic_051", "relic_052"})
        self.assertEqual(rows(report["global"], "attack", "friendly_unit", "outside_battle")[0]["relativeFactor"], "1.2")
        self.state["opening"]["technologyCombatBonuses"]["attackPercent"] = 7
        attack = rows(self.report()["operators"][0], "attack", "operator", "outside_battle", "constant")[0]
        self.assertEqual(attack["relativeFactor"], "1.67")

    def test_independent_percentage_zones_multiply_after_same_zone_sum(self):
        definitions = deepcopy(self.definitions)
        clone = deepcopy(definitions["relic_052"])
        clone["id"], clone["name"] = "independent_attack", "测试独立攻击乘区"
        clone["effects"][0].update(id="independent_attack.attack", value=.25, stackingGroup="test_independent")
        definitions[clone["id"]] = clone
        self.state["relics"].append({"id": clone["id"]})
        report = summarize_combat_bonuses(self.state, context=self.context, definitions=definitions)
        attack = rows(report["operators"][0], "attack", "operator", "outside_battle", "constant")[0]
        self.assertEqual(attack["relativeFactor"], "1.9375")
        self.assertEqual({zone["id"]: zone["baseRatioDelta"] for zone in attack["multiplicationZones"]},
                         {"outside_attribute": "0.55", "test_independent": "0.25"})

    def test_damage_taken_bonuses_sum_by_type_and_keep_other_zones_separate(self):
        self.state["relics"] = [{"id": key} for key in ("relic_041", "relic_042", "relic_044", "relic_045",
                                                       "relic_089", "relic_133", "relic_173")]
        view = self.report()["global"]
        damage = {row["tags"]["damageType"]: row for row in rows(view, "damage_taken", "enemy", bucket="constant")}
        self.assertEqual(damage["physical"]["relativeFactor"], "1.4")
        self.assertEqual(damage["arts"]["relativeFactor"], "1.5")
        self.assertEqual(damage["physical"]["multiplicationZones"][0]["id"], "enemy_damage_taken_bonus")
        self.assertEqual(damage["elemental_damage"]["relativeFactor"], "3.5")
        self.assertEqual(rows(view, "vulnerability")[0]["factor"], "1.5")
        self.assertEqual(rows(view, "damage_taken", "enemy", bucket="conditional")[0]["factor"], "0.8")

    def test_real_cost_flat_then_percentage_without_operator_base_stats(self):
        self.state["relics"] = [{"id": "relic_225"}, {"id": "relic_123"}]
        report = self.report()
        cost = rows(report["operators"][0], "deployment_cost")[0]
        self.assertEqual((cost["flatDelta"], cost["baseRatioDelta"], cost["relativeFactor"]), ("2", "-0.5", "0.5"))
        self.assertEqual(evaluate_numeric(10, flat_deltas=[cost["flatDelta"]],
                                         base_ratio_deltas=[cost["baseRatioDelta"]], factors=[cost["factor"]]), 6)
        self.assertIn("（基础值+2）×0.5；基础值未代入", render_combat_bonuses(report))

    def test_invalid_counts_and_duplicate_instances(self):
        for field, value in (("componentCount", True), ("enemyRegionCount", -1), ("dystopiaAffected", "yes")):
            with self.assertRaises(ValueError):
                self.report(**{field: value})
        self.state["relics"][0]["value"] = 8
        with self.assertRaisesRegex(ValueError, "null"):
            self.report()
        self.state["operators"].append(deepcopy(self.state["operators"][0]))
        with self.assertRaisesRegex(ValueError, "重复"):
            self.report()

    def test_six_cells_snapshot_and_operator_specific_values(self):
        self.state["relics"].extend([{"id": "relic_051"}, {"id": "relic_192"}])
        report = self.report(cash=14)
        global_cells = {(cell["metric"], cell["domain"]): cell for cell in report["global"]["attributeSummary"]}
        self.assertEqual(len(global_cells), 6)
        self.assertEqual(global_cells["attack", "outside_battle"]["relativePercent"], "20")
        self.assertEqual(global_cells["max_hp", "outside_battle"]["relativePercent"], "25")
        self.assertEqual(global_cells["attack", "inside_battle"]["relativePercent"], "64")
        self.assertEqual(global_cells["attack_speed", "outside_battle"]["flatDelta"], "14")
        self.assertEqual(global_cells["attack_speed", "inside_battle"]["flatDelta"], "0")
        for view in report["operators"]:
            attack = next(cell for cell in view["attributeSummary"] if cell["metric"] == "attack" and cell["domain"] == "outside_battle")
            self.assertEqual(attack["relativePercent"], "80")
            inside = next(cell for cell in view["attributeSummary"] if cell["metric"] == "attack" and cell["domain"] == "inside_battle")
            self.assertEqual(inside["relativePercent"], "64")

    def test_conditional_peaks_and_random_recipients_do_not_enter_six_cells(self):
        self.state["relics"] = [{"id": "relic_130"}, {"id": "relic_126"}, {"id": "relic_197", "value": 10}]
        report = self.report(airborneCount=2)
        for view in [report["global"], *report["operators"]]:
            for cell in view["attributeSummary"]:
                self.assertFalse({source["id"] for source in cell["sources"]} & {"relic_130", "relic_126", "relic_197"})
        self.assertTrue(any(row["bucket"] == "conditional" for row in rows(report["operators"][1], "attack")))

    def test_global_unit_and_operator_attribute_sources_share_a_zone(self):
        definitions = deepcopy(self.definitions)
        clone = deepcopy(definitions["relic_052"])
        clone["id"], clone["name"] = "universal_attack", "测试全干员攻击"
        clone["effects"][0]["target"] = {"side": "friendly_operator", "metric": "attack", "scope": {}}
        definitions[clone["id"]] = clone
        self.state["relics"] = [{"id": clone["id"]}]
        report = summarize_combat_bonuses(self.state, definitions=definitions)
        cell = next(cell for cell in report["global"]["attributeSummary"] if cell["metric"] == "attack" and cell["domain"] == "outside_battle")
        self.assertEqual(cell["relativePercent"], "55")
        self.assertEqual(len(cell["sources"]), 2)

    def test_overview_lists_scoped_effects_without_changing_global_totals(self):
        self.state["relics"].append({"id": "relic_051"})
        report = self.report()
        detail_rows = rows({"categories": report["global"]["detailCategories"]})
        melee_attack = next(row for row in detail_rows if row["metric"] == "attack"
                            and row.get("displayScope") == {"position": "melee"})
        self.assertEqual(melee_attack["relativePercent"], "60")
        self.assertIn("近战", melee_attack["scopeLabel"])
        self.assertEqual({source["id"] for source in melee_attack["sources"]}, {"relic_052", "relic_051"})
        binding = next(row for row in detail_rows if row["metric"] == "redeployment_time")
        self.assertIn("予愿安洁莉娜", binding["scopeLabel"])
        self.assertEqual(binding["displayScope"]["operatorInstanceIds"], ["angelina"])
        cell = next(cell for cell in report["global"]["attributeSummary"]
                    if cell["metric"] == "attack" and cell["domain"] == "outside_battle")
        self.assertEqual(cell["relativePercent"], "20")
        self.assertEqual(report["global"]["categories"], self.report()["global"]["categories"])
        self.assertIn("老近卫军之锋", render_combat_bonuses(report))

    def test_overview_does_not_merge_different_professions_or_bound_recipients(self):
        definitions = deepcopy(self.definitions)
        for name, scope in (("guard", {"profession": "近卫"}), ("sniper", {"profession": "狙击"})):
            clone = deepcopy(definitions["relic_052"])
            clone["id"], clone["name"] = name, name
            clone["effects"][0]["target"]["side"] = "friendly_operator"
            clone["effects"][0]["target"]["scope"] = scope
            definitions[name] = clone
        self.state["relics"] = [{"id": "guard"}, {"id": "sniper"}]
        self.state["grantedEffects"] = [
            {"relicId": "relic_188", "acquisitionId": "cookie-1", "operatorInstanceIds": ["angelina"]},
            {"relicId": "relic_188", "acquisitionId": "cookie-2", "operatorInstanceIds": ["mechanist"]},
        ]
        report = summarize_combat_bonuses(self.state, definitions=definitions)
        detail = {"categories": report["global"]["detailCategories"]}
        attack = rows(detail, "attack", "friendly_operator")
        self.assertEqual(len(attack), 2)
        self.assertTrue(all(row["relativePercent"] == "35" for row in attack))
        cookies = rows(detail, "sp_recovery_per_second", "bound_operator")
        self.assertEqual(len(cookies), 2)
        self.assertTrue(all(row["flatDelta"] == "0.8" for row in cookies))

    def test_environment_is_a_separate_read_only_description(self):
        from fulcrum.service.catalog import entries
        instance = {"areaKey": "II", "dystopia": {"active": True, "ideologyId": "dystopia_001", "policyId": "dystopia_014"}}
        original = deepcopy(instance)
        description = describe_layer_environment(instance, 15, entries())
        self.assertEqual(description["name"], "黑流地脉")
        self.assertIn("+30%", description["effect"])
        self.assertEqual(description["policy"]["name"], "增益")
        self.assertEqual(instance, original)
        self.assertIsNone(describe_layer_environment(None, 15, entries()))
        self.assertIsNone(describe_layer_environment({"areaKey": "II", "utopiaId": "utopia_001"}, 15, entries()))
        self.assertEqual(describe_layer_environment({"areaKey": "III-treehole", "utopiaId": "utopia_001"}, 15, entries())["kind"], "乌托邦")

    def test_all_dystopia_tiers_and_boundaries(self):
        from fulcrum.service.catalog import entries
        checks = {"002": ("-20%", "-35%", "-50%"), "003": ("每60秒", "每45秒", "每30秒"),
                  "004": ("+25%", "+40%", "+70%"), "005": ("-10%", "-30%", "-50%"),
                  "006": ("30%", "50%", "70%"), "007": ("-20%", "-25%", "-40%"),
                  "008": ("攻击+10%、生命+10%", "攻击+15%、生命+20%", "攻击+20%、生命+30%")}
        for difficulty, index in ((0, 0), (5, 0), (6, 1), (11, 1), (12, 2), (15, 2)):
            for suffix, values in checks.items():
                with self.subTest(difficulty=difficulty, suffix=suffix):
                    instance = {"areaKey": "III", "dystopia": {"active": True, "ideologyId": "dystopia_" + suffix}}
                    result = describe_layer_environment(instance, difficulty, entries())
                    self.assertEqual(result["tier"], index + 1)
                    self.assertIn(values[index], result["effect"])
        utopia = {"areaKey": "III-treehole", "utopiaId": "utopia_004"}
        low, high = [describe_layer_environment(utopia, level, entries()) for level in (0, 15)]
        self.assertEqual(low["effect"], high["effect"])
        self.assertIsNone(high["tier"])


class CombatBonusApiTests(unittest.TestCase):
    def test_ui_environment_is_not_applied_to_numeric_rows(self):
        with tempfile.TemporaryDirectory() as root:
            app = create_app(root)
            with TestClient(app, client=("127.0.0.1", 12345)) as client:
                headers = {"X-Fulcrum-Token": client.get("/api/session").json()["token"]}
                state = json.loads((ROOT / "runs/true-run-001/playtime.json").read_text(encoding="utf-8"))
                slot = state["areas"]["I"]
                instance = next(item for item in slot["instances"] if item["instanceId"] == slot["activeInstanceId"])
                instance["dystopia"] = {"active": True, "ideologyId": "dystopia_001", "policyId": "dystopia_014",
                    "affectedNodeIds": list(instance["nodes"]), "uncertainNodeIds": [], "idealSourceNodeId": None}
                initial = client.post("/api/runs/restore", json={"state": state, "runId": "environment-test"}, headers=headers).json()
                response = client.post("/api/runs/environment-test/combat-bonuses", json={
                    "expectedRevision": initial["revision"], "areaKey": "I"}, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                report = response.json()["report"]
                self.assertIn("+30%", report["environment"]["effect"])
                self.assertFalse(any(source["id"] == "dystopia_001" for row in rows(report["global"]) for source in row["sources"]))
                self.assertEqual(app.state.store.load("environment-test"), initial)

    def test_read_only_endpoint_and_revision_checks(self):
        with tempfile.TemporaryDirectory() as root:
            app = create_app(root)
            with TestClient(app, client=("127.0.0.1", 12345)) as client:
                headers = {"X-Fulcrum-Token": client.get("/api/session").json()["token"]}
                state = new_playtime("combat-test", squad_id="squad_001")
                initial = client.post("/api/runs/restore", json={"state": state}, headers=headers).json()
                request = {"expectedRevision": initial["revision"], "context": {"enemyRegionCount": 1}}
                response = client.post("/api/runs/combat-test/combat-bonuses", json=request, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn("全局加成", response.json()["markdown"])
                self.assertEqual(len(response.json()["report"]["global"]["attributeSummary"]), 6)
                self.assertIsNone(response.json()["report"]["environment"])
                self.assertEqual(app.state.store.load("combat-test"), initial)
                invalid = client.post("/api/runs/combat-test/combat-bonuses", json={**request, "operatorInstanceId": "missing"}, headers=headers)
                self.assertEqual(invalid.status_code, 422)
                stale = client.post("/api/runs/combat-test/combat-bonuses", json={**request, "expectedRevision": 0}, headers=headers)
                self.assertEqual(stale.status_code, 409)


if __name__ == "__main__":
    unittest.main()
