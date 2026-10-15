"""Permanent acquisition eligibility, independent of currently held inventory."""

CONTROLLER_OUTCOMES = {"obtained_controller", "controller_obtained", "获得笼控器", "笼控器已获得"}


def controller_obtained(state):
    return bool(state.get("acquisitionFacts", {}).get("controllerEverObtained")) or any(
        row.get("componentId") == "component_012" for row in state.get("componentBox", {}).get("items", [])
    ) or any(outcome in CONTROLLER_OUTCOMES
             for row in state.get("globalEncounterPool", []) if row.get("id") == "encounter_008"
             for outcome in row.get("outcomes", {}).values())


def seed_acquisition_facts(state, past=()):
    if controller_obtained(state) or any(controller_obtained(snapshot) for snapshot in past):
        state.setdefault("acquisitionFacts", {})["controllerEverObtained"] = True
