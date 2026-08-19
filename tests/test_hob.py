"""Tests for HB (hob) appliance support, using the AEG CCE84779CB samples."""

from __future__ import annotations

import asyncio

import pytest

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import Platform, UnitOfTime

from custom_components.electrolux_status.api import catalog_wildcard_key
from custom_components.electrolux_status.catalog_core import CATALOG_APPLIANCE_TYPE


def entity_by_path(appliance, path: str):
    """Return the single entity generated for a capability path."""
    matches = [entity for entity in appliance.entities if entity.json_path == path]
    assert len(matches) == 1, f"expected exactly one entity for {path}, got {len(matches)}"
    return matches[0]


def paths(appliance) -> set[str]:
    """Return every capability path the appliance generated an entity for."""
    return {entity.json_path for entity in appliance.entities}


# --- appliance detection ------------------------------------------------


def test_hob_reports_appliance_type_hb(hob) -> None:
    """The hob is identified by appliance type, not by model name."""
    assert hob.appliance_type == "HB"
    assert hob.model == "CCE84779CB"
    assert hob.brand == "AEG"


def test_hob_initializes_and_creates_entities(hob) -> None:
    """Setting up a CCE84779CB raises nothing and produces entities."""
    assert len(hob.entities) > 20


def test_hob_catalog_layers_appliance_type_over_base(hob) -> None:
    """The HB catalog is merged in on top of the base catalog."""
    catalog = hob.catalog
    # Contributed by CATALOG_BASE.
    assert "alerts" in catalog
    # Contributed by CATALOG_APPLIANCE_TYPE["HB"].
    assert "hobZone*/residualHeatState" in catalog
    # The HB entry wins over the base entry for the same key.
    assert catalog["uiLockMode"] is CATALOG_APPLIANCE_TYPE["HB"]["uiLockMode"]


# --- nested and dynamic capability discovery ----------------------------


def test_nested_hood_capabilities_are_discovered(hob) -> None:
    """Every hobHood/* capability becomes an entity."""
    hood_paths = {path for path in paths(hob) if path.startswith("hobHood/")}
    assert hood_paths == {
        "hobHood/hobToHoodFanSpeed",
        "hobHood/hobToHoodMode",
        "hobHood/hobToHoodState",
        "hobHood/hoodFilterCharcIndication",
        "hobHood/targetDuration",
        "hobHood/timeToEnd",
        "hobHood/windowNotification",
    }


def test_hob_zones_are_discovered_dynamically(hob) -> None:
    """Zones come from the capability document, not from a fixed list.

    The CCE84779CB reports a non-contiguous set of zones: 1-4 are the physical
    zones and 7-8 are the bridged ones, with no zone 5 or 6.
    """
    zones = sorted({path.split("/")[0] for path in paths(hob) if path.startswith("hobZone")})
    assert zones == [
        "hobZone1",
        "hobZone2",
        "hobZone3",
        "hobZone4",
        "hobZone7",
        "hobZone8",
    ]


def test_no_fixed_zone_count_assumption(hob) -> None:
    """Zones with fewer capabilities produce fewer entities, not errors.

    hobZone7/8 are bridge zones and report five properties where hobZone1-4
    report nine. Nothing may assume every zone looks the same.
    """
    def attributes(zone: str) -> set[str]:
        return {path.split("/", 1)[1] for path in paths(hob) if path.startswith(f"{zone}/")}

    assert attributes("hobZone7") < attributes("hobZone1")
    assert "residualHeatState" in attributes("hobZone1")
    assert "residualHeatState" not in attributes("hobZone7")


@pytest.mark.parametrize(
    ("capability", "expected"),
    [
        ("hobZone1/runningTime", "hobZone*/runningTime"),
        ("hobZone12/runningTime", "hobZone*/runningTime"),
        ("hobModule2/procookLevelRear", "hobModule*/procookLevelRear"),
        # No numeric container suffix, so no wildcard form.
        ("userSelections/analogTemperature", None),
        ("applianceState", None),
        ("fCMiscellaneousState/tankAReserve", None),
    ],
)
def test_catalog_wildcard_key(capability: str, expected: str | None) -> None:
    """Wildcard keys are derived only from a numbered container prefix."""
    assert catalog_wildcard_key(capability) == expected


def test_wildcard_catalog_entry_applies_to_every_zone(hob) -> None:
    """One catalog entry describes all zones, whatever they are numbered."""
    for zone in ("hobZone1", "hobZone2", "hobZone3", "hobZone4", "hobZone7", "hobZone8"):
        entity = entity_by_path(hob, f"{zone}/runningTime")
        assert entity.device_class is SensorDeviceClass.DURATION
        assert entity.unit == UnitOfTime.SECONDS
        assert entity.name == "Running time"


def test_wildcard_keys_do_not_become_entities(hob) -> None:
    """Catalog patterns are never mistaken for real capabilities."""
    assert not [path for path in paths(hob) if "*" in path]


# --- values come from the device, not from guesses ----------------------


def test_fan_speed_options_come_from_capabilities(hob) -> None:
    """The CCE84779CB advertises six fan speeds and no drying cycle."""
    fan_speed = entity_by_path(hob, "hobHood/hobToHoodFanSpeed")
    assert fan_speed.entity_type == Platform.SELECT
    assert sorted(fan_speed.options_list.values()) == [
        "BOOST",
        "BREEZE",
        "OFF",
        "STEP_1",
        "STEP_2",
        "STEP_3",
    ]
    assert "DRYING_CYCLE" not in fan_speed.options_list.values()


def test_hood_state_options_come_from_capabilities(hob) -> None:
    """Hood state options are read from the device."""
    hood_state = entity_by_path(hob, "hobHood/hobToHoodState")
    assert hood_state.entity_type == Platform.SELECT
    assert sorted(hood_state.options_list.values()) == [
        "AUTOMATIC",
        "AUTO_SUSPEND",
        "MANUAL",
    ]


def test_disabled_enum_values_are_not_selectable(hob) -> None:
    """AUTO_SUSPEND is marked disabled, so it must not be offered."""
    hood_state = entity_by_path(hob, "hobHood/hobToHoodState")
    assert "Auto Suspend" in hood_state.readonly_options
    assert "Auto Suspend" not in hood_state.options
    assert sorted(hood_state.options) == ["Automatic", "Manual"]


def test_disabled_value_stays_visible_while_reported(hob) -> None:
    """A disabled value the appliance reports must not read as unknown.

    Home Assistant drops the state of a select whose current option is not in
    its option list, so the reported value has to stay in the list while it is
    current - but it must never become settable.
    """
    hood_state = entity_by_path(hob, "hobHood/hobToHoodState")
    hob.update_reported_data({"hobHood": {"hobToHoodState": "AUTO_SUSPEND"}})

    assert hood_state.current_option == "Auto Suspend"
    assert "Auto Suspend" in hood_state.options, "state would render as unknown"
    assert "Auto Suspend" in hood_state.readonly_options

    hob.update_reported_data({"hobHood": {"hobToHoodState": "AUTOMATIC"}})
    assert hood_state.current_option == "Automatic"
    assert "Auto Suspend" not in hood_state.options


def test_disabled_value_cannot_be_sent(hob) -> None:
    """Selecting a disabled value never reaches the appliance."""
    hood_state = entity_by_path(hob, "hobHood/hobToHoodState")
    hob.update_reported_data({"hobHood": {"hobToHoodState": "AUTO_SUSPEND"}})
    assert "Auto Suspend" in hood_state.options

    sent = []

    class RecordingApi:
        async def execute_appliance_command(self, *args):
            sent.append(args)

    hood_state.api = RecordingApi()

    asyncio.run(hood_state.async_select_option("Auto Suspend"))
    assert sent == []

    asyncio.run(hood_state.async_select_option("Manual"))
    assert sent == [(hob.pnc_id, {"hobHood": {"hobToHoodState": "MANUAL"}})]


def test_number_bounds_come_from_capabilities(hob) -> None:
    """Numeric bounds are taken from the capability document."""
    duration = entity_by_path(hob, "hobHood/targetDuration")
    assert duration.entity_type == Platform.NUMBER
    assert duration.capability["min"] == 0
    assert duration.capability["max"] == 5940
    assert duration.capability["step"] == 60


# --- read-only capabilities stay read-only ------------------------------


@pytest.mark.parametrize(
    "path",
    [
        # Reported as readwrite by the appliance but pinned read-only: these
        # are cooking controls, see the note in catalog_hob.py.
        "hobZone1/heatingQualitativeLevel",
        "hobZone3/targetDuration",
        "hobModule1/procookLevelFront",
        "hobModule2/procookLevelRear",
        # Reported as read-only, and must not be promoted by the base catalog.
        "hobZone2/heatingQualitativeLevel",
        "hobZone4/targetDuration",
    ],
)
def test_cooking_controls_are_read_only(hob, path: str) -> None:
    """No hob capability is exposed as a writable cooking control."""
    assert entity_by_path(hob, path).entity_type == Platform.SENSOR


def test_writable_capabilities_are_limited_to_the_extractor(hob) -> None:
    """Only extractor and appliance-settings capabilities are writable."""
    writable = {
        entity.json_path
        for entity in hob.entities
        if entity.entity_type in (Platform.SELECT, Platform.NUMBER, Platform.SWITCH)
    }
    assert writable == {
        "hobHood/hobToHoodFanSpeed",
        "hobHood/hobToHoodMode",
        "hobHood/hobToHoodState",
        "hobHood/targetDuration",
        "keySoundTone",
    }


def test_ui_lock_mode_is_read_only_binary_sensor(hob) -> None:
    """UiLockMode is access "read" on HB and must not become a switch."""
    ui_lock = entity_by_path(hob, "uiLockMode")
    assert ui_lock.entity_type == Platform.BINARY_SENSOR
    assert ui_lock.device_class is BinarySensorDeviceClass.LOCK


# --- child lock ---------------------------------------------------------


def test_child_lock_has_no_remote_disable_action(hob) -> None:
    """Child lock is state-only.

    The capability document marks it readwrite but attaches triggers that drop
    it to read-only once it is enabled, so the appliance cannot honour a remote
    disable. Exposing a switch would offer an action that silently fails.
    """
    child_lock = entity_by_path(hob, "childLock")
    assert child_lock.entity_type == Platform.BINARY_SENSOR
    assert child_lock.device_class is BinarySensorDeviceClass.LOCK
    assert not hasattr(child_lock, "async_turn_off")


def test_child_lock_capability_declares_conditional_access(hob) -> None:
    """Guard the assumption the child lock modelling rests on."""
    capability = hob.data.get_capability("childLock")
    conditions = [trigger["condition"]["operand_2"] for trigger in capability["triggers"]]
    assert "ENABLED" in conditions
    enabled_trigger = next(
        trigger for trigger in capability["triggers"] if trigger["condition"]["operand_2"] == "ENABLED"
    )
    assert enabled_trigger["action"]["$self"]["access"] == "read"


# --- presentation -------------------------------------------------------


def test_durations_have_device_class_and_unit(hob) -> None:
    """Every hob duration is a proper duration sensor."""
    for path in (
        "hobHood/timeToEnd",
        "hobZone1/runningTime",
        "hobZone1/timeToEnd",
        "hobZone2/targetDuration",
        "hobZone4/reminderTime",
    ):
        entity = entity_by_path(hob, path)
        assert entity.device_class is SensorDeviceClass.DURATION, path
        assert entity.unit == UnitOfTime.SECONDS, path


def test_filter_indication_is_a_problem_binary_sensor(hob) -> None:
    """The charcoal filter indication is a state, not a control."""
    charcoal = entity_by_path(hob, "hobHood/hoodFilterCharcIndication")
    assert charcoal.entity_type == Platform.BINARY_SENSOR
    assert charcoal.device_class is BinarySensorDeviceClass.PROBLEM


def test_pot_detection_keeps_all_four_states(hob) -> None:
    """Pot detection stays an enum so idle/running is not thrown away."""
    pot = entity_by_path(hob, "hobZone1/hobPotDetected")
    assert pot.entity_type == Platform.SENSOR
    assert sorted(pot.capability["values"]) == [
        "NO_POT_IDLE",
        "NO_POT_RUNNING",
        "POT_IDLE",
        "POT_RUNNING",
    ]


# --- push updates -------------------------------------------------------


def test_push_update_changes_state_without_recreating_entities(hob) -> None:
    """A pushed delta updates entity values in place."""
    before = list(hob.entities)
    fan_speed = entity_by_path(hob, "hobHood/hobToHoodFanSpeed")
    level = entity_by_path(hob, "hobZone1/heatingQualitativeLevel")
    assert fan_speed.current_option == "Off"
    assert level.native_value == 0

    hob.update_reported_data(
        {
            "applianceState": "RUNNING",
            "hobHood": {"hobToHoodFanSpeed": "STEP_3"},
            "hobZone1": {"heatingQualitativeLevel": 7, "hobPotDetected": "POT_RUNNING"},
        }
    )

    assert hob.entities == before
    assert fan_speed.current_option == "Step 3"
    assert level.native_value == 7
    assert entity_by_path(hob, "hobZone1/hobPotDetected").native_value == "Pot Running"
    assert entity_by_path(hob, "applianceState").native_value == "Running"


def test_push_update_leaves_other_zones_untouched(hob) -> None:
    """A delta for one zone does not disturb the others."""
    hob.update_reported_data({"hobZone1": {"heatingQualitativeLevel": 9}})
    assert entity_by_path(hob, "hobZone1/heatingQualitativeLevel").native_value == 9
    assert entity_by_path(hob, "hobZone2/heatingQualitativeLevel").native_value == 0
