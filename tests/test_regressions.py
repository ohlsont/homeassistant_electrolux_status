"""Checks that non-HB appliances are unaffected by hob support."""

from __future__ import annotations

from homeassistant.const import Platform

from conftest import entity_by_path, paths

from custom_components.electrolux_status.catalog_core import CATALOG_BASE, CATALOG_MODEL


def test_fridge_still_sets_up(fridge) -> None:
    """A CR appliance is unchanged by the HB catalog."""
    assert fridge.appliance_type == "CR"
    assert len(fridge.entities) > 10


def test_washer_still_sets_up(washer) -> None:
    """A WM appliance is unchanged by the HB catalog."""
    assert washer.appliance_type == "WM"
    assert len(washer.entities) > 10


def test_appliance_without_overrides_uses_the_base_catalog(washer) -> None:
    """No appliance-type or model override matches, so nothing is merged."""
    assert washer.catalog is CATALOG_BASE


def test_model_overrides_still_apply(fridge) -> None:
    """EHE6899SA keeps its model-level overrides alongside the base catalog."""
    catalog = fridge.catalog
    assert catalog is not CATALOG_BASE
    assert catalog["ui2LockMode"] is CATALOG_MODEL["EHE6899SA"]["ui2LockMode"]
    assert "hobZone*/residualHeatState" not in catalog


def test_non_hb_ui_lock_mode_stays_a_switch(washer) -> None:
    """The HB read-only override must not leak to other appliance types."""
    assert entity_by_path(washer, "uiLockMode").entity_type == Platform.SWITCH


def test_no_hob_entities_on_other_appliances(fridge, washer) -> None:
    """Hob catalog entries never invent entities elsewhere."""
    for appliance in (fridge, washer):
        assert not [path for path in paths(appliance) if path.startswith(("hobZone", "hobHood", "hobModule"))]


def test_wildcard_entries_never_materialise(fridge, washer) -> None:
    """Pattern keys are skipped when entities are rebuilt from the catalog."""
    for appliance in (fridge, washer):
        assert not [path for path in paths(appliance) if "*" in path]


def test_static_attributes_do_not_duplicate_capabilities(fridge, washer, hob) -> None:
    """An attribute advertised as a capability is only created once.

    applianceMode is both a STATIC_ATTRIBUTES entry and a real capability on
    several appliances, which used to produce two entities sharing one unique
    id.
    """
    for appliance in (fridge, washer, hob):
        unique_ids = [entity.unique_id for entity in appliance.entities]
        assert len(unique_ids) == len(set(unique_ids))
