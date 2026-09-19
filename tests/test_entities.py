"""Entity behaviour across every platform, including degraded systems."""

import asyncio

from homeassistant.helpers import dispatcher

from custom_components.intellicenter import (
    binary_sensor,
    cover,
    light,
    number,
    sensor,
    switch,
    water_heater,
)
from custom_components.intellicenter.const import DOMAIN

from fake_intellicenter import DEFAULT_OBJECTS
from helpers import build_controller, build_hass, by_object, setup_platform

PLATFORMS = (binary_sensor, cover, light, number, sensor, switch, water_heater)

# a system where everything that can be missing, is
DEGRADED = {
    "_5451": {"OBJTYP": "SYSTEM", "SNAME": "system", "PROPNAME": "Pool House",
              "VER": "1.064", "MODE": "ENGLISH"},
    # a body that has never reported a temperature
    "B1202": {"OBJTYP": "BODY", "SUBTYP": "SPA", "SNAME": "Spa", "STATUS": "OFF",
              "HEATER": "00000", "HTMODE": "0"},
    "H0001": {"OBJTYP": "HEATER", "SNAME": "Gas", "BODY": "B1202", "LISTORD": "1"},
    # a heater that reports no BODY at all
    "H0002": {"OBJTYP": "HEATER", "SNAME": "Orphan", "LISTORD": "2"},
    # a schedule with neither a name nor a state
    "SCH02": {"OBJTYP": "SCHED"},
    # a light show whose member circuit is not in the model
    "C0004": {"OBJTYP": "CIRCUIT", "SUBTYP": "LITSHO", "SNAME": "Show", "STATUS": "OFF"},
    "CG001": {"OBJTYP": "CIRCGRP", "PARENT": "C0004", "CIRCUIT": "C9999"},
    # an IntelliChlor with no BODY
    "CHL01": {"OBJTYP": "CHEM", "SUBTYP": "ICHLOR", "SNAME": "Chlor", "PRIM": "50"},
}


def all_platforms(**kw):
    async def scenario():
        controller, transport = build_controller(**kw)
        hass, entry, _ = build_hass(controller)
        built = {}
        for module in PLATFORMS:
            name = module.__name__.rsplit(".", 1)[1]
            built[name] = await setup_platform(module, hass, entry)
        return controller, hass, entry, built
    return asyncio.run(scenario())


def read_everything(entity):
    """Touch every property Home Assistant reads on a state write."""
    entity.name
    entity.unique_id
    entity.device_info
    entity.extra_state_attributes
    entity.available
    for prop in ("is_on", "native_value", "state", "is_closed", "current_operation",
                 "operation_list", "current_temperature", "target_temperature",
                 "effect", "min_temp", "max_temp", "temperature_unit",
                 "native_unit_of_measurement"):
        getattr(entity, prop, None)


def test_every_platform_builds_entities():
    _, _, _, built = all_platforms()
    for name, entities in built.items():
        assert entities, f"{name} produced no entities"


def test_every_property_is_readable():
    _, _, _, built = all_platforms()
    for entities in built.values():
        for entity in entities:
            read_everything(entity)


def test_every_property_is_readable_on_a_degraded_system():
    _, _, _, built = all_platforms(objects=DEGRADED)
    for entities in built.values():
        for entity in entities:
            read_everything(entity)


def test_unique_ids_are_unique_within_each_domain():
    _, _, _, built = all_platforms()
    for name, entities in built.items():
        ids = [e.unique_id for e in entities]
        # the registry keys on (domain, platform, unique_id), so uniqueness
        # only has to hold inside a domain
        assert len(ids) == len(set(ids)), f"{name} has duplicate unique ids"


def test_unique_id_scheme_is_pinned():
    """The registry keys on these, so the recipe must not drift.

    An entity tracking STATUS is ``<entry_id><objnam>``; anything else appends
    its attribute key. Changing either orphans every installed entity.
    """
    _, _, entry, built = all_platforms()
    body = by_object(built["switch"], "B1101")
    assert body.unique_id == f"{entry.entry_id}B1101"
    schedule = by_object(built["binary_sensor"], "SCH01")
    assert schedule.unique_id == f"{entry.entry_id}SCH01ACT"
    salt = by_object(built["sensor"], "CHL01", "SALT")
    assert salt.unique_id == f"{entry.entry_id}CHL01SALT"
    # the water heater has always appended LOTMP on top of the body id
    pool = by_object(built["water_heater"], "B1101")
    assert pool.unique_id == f"{entry.entry_id}B1101LOTMP"


def test_unique_ids_do_not_depend_on_the_name():
    """Changing how an entity is named must not orphan it in the registry."""
    _, _, _, built = all_platforms()
    before = {e.unique_id for e in built["switch"]}
    controller, _ = build_controller()
    for obj in controller.model.objectList:
        obj.properties["SNAME"] = "renamed"

    async def scenario():
        hass, entry, _ = build_hass(controller)
        return await setup_platform(switch, hass, entry)

    after = {e.unique_id for e in asyncio.run(scenario())}
    assert before == after


def test_all_devices_belong_to_one_pool_device():
    _, _, _, built = all_platforms()
    identifiers = {tuple(sorted(e.device_info["identifiers"]))
                   for entities in built.values() for e in entities}
    assert len(identifiers) == 1
    info = next(iter(built["switch"])).device_info
    assert info["manufacturer"] == "Pentair" and info["name"] == "Pool House"


# -- schedules ---------------------------------------------------------------

def test_schedule_sensor_reports_running():
    _, _, _, built = all_platforms()
    schedule = by_object(built["binary_sensor"], "SCH01")
    assert schedule.is_on is True
    assert schedule.name == "Pump schedule (schedule)"
    assert schedule.extra_state_attributes["VACFLO"] == "OFF"
    assert schedule._attr_entity_registry_enabled_default is False


def test_schedule_without_a_state_reports_unknown_not_off():
    _, _, _, built = all_platforms()
    schedule = by_object(built["binary_sensor"], "SCH02")
    assert schedule.is_on is None


def test_unnamed_schedule_falls_back_to_its_object_id():
    _, _, _, built = all_platforms()
    assert by_object(built["binary_sensor"], "SCH02").name == "SCH02 (schedule)"


def test_undefined_extra_attributes_are_omitted():
    _, _, _, built = all_platforms()
    assert "VACFLO" not in by_object(built["binary_sensor"], "SCH02").extra_state_attributes


def test_extra_attributes_are_not_shared_between_entities():
    _, _, _, built = all_platforms()
    a = by_object(built["binary_sensor"], "SCH01")
    b = by_object(built["binary_sensor"], "SCH02")
    assert a._extra_state_attributes is not b._extra_state_attributes


# -- other platforms ---------------------------------------------------------

def test_pump_binary_sensor_uses_the_numeric_on_status():
    _, _, _, built = all_platforms()
    assert by_object(built["binary_sensor"], "PMP01").is_on is True


def test_freeze_sensor_is_created():
    _, _, _, built = all_platforms()
    assert by_object(built["binary_sensor"], "C0003").is_on is False


def test_heater_sensor_follows_the_bodies_it_serves():
    _, _, _, built = all_platforms()
    heater = by_object(built["binary_sensor"], "H0001")
    assert heater.is_on is True  # pool is on, heating, and points at this heater
    assert heater.isUpdated({"B1101": {"HTMODE": "0"}}) is True
    assert heater.isUpdated({"C0001": {"STATUS": "ON"}}) is False


def test_heater_without_a_body_does_not_crash():
    _, _, _, built = all_platforms(objects=DEGRADED)
    assert by_object(built["binary_sensor"], "H0002").is_on is False


def test_sensor_values_are_numeric_and_keep_their_formatting():
    _, _, _, built = all_platforms()
    temperature = by_object(built["sensor"], "B1101", "LSTTMP")
    assert temperature.native_value == 82
    assert str(temperature.native_value) == "82", "must not start showing 82.0"
    assert temperature.native_unit_of_measurement == "°F"


def test_sensor_without_a_value_is_unknown():
    _, _, _, built = all_platforms()
    assert by_object(built["sensor"], "B1202", "LSTTMP").native_value is None


def test_pump_power_is_rounded_to_limit_churn():
    _, _, _, built = all_platforms()
    assert by_object(built["sensor"], "PMP01", "PWR").native_value == 1000


def test_sensor_tolerates_a_non_numeric_reading():
    controller, _, _, built = all_platforms()
    controller.model["B1101"].update({"LSTTMP": "n/a"})
    assert by_object(built["sensor"], "B1101", "LSTTMP").native_value == "n/a"


def test_metric_system_reports_celsius():
    _, _, _, built = all_platforms(metric=True)
    assert by_object(built["sensor"], "B1101", "LSTTMP").native_unit_of_measurement == "°C"
    pool = by_object(built["water_heater"], "B1101")
    assert pool.temperature_unit == "°C"
    assert (pool.min_temp, pool.max_temp) == (5.0, 40.0)


def test_imperial_water_heater_limits():
    _, _, _, built = all_platforms()
    pool = by_object(built["water_heater"], "B1101")
    assert (pool.min_temp, pool.max_temp) == (40.0, 104.0)
    assert (pool.current_temperature, pool.target_temperature) == (82.0, 84.0)
    assert pool.state == "on"


def test_water_heater_state_reflects_idle_and_off():
    controller, _, _, built = all_platforms()
    pool = by_object(built["water_heater"], "B1101")
    controller.model["B1101"].update({"HTMODE": "0"})
    assert pool.state == "idle", "heater selected but not running"
    controller.model["B1101"].update({"HEATER": "00000"})
    assert pool.state == "off"


def test_water_heater_without_a_reading_reports_nothing():
    _, _, _, built = all_platforms(objects=DEGRADED)
    spa = by_object(built["water_heater"], "B1202")
    assert spa.current_temperature is None and spa.target_temperature is None


def test_water_heater_only_offers_heaters_that_serve_the_body():
    _, _, _, built = all_platforms(objects=DEGRADED)
    spa = by_object(built["water_heater"], "B1202")
    assert spa.operation_list == ["off", "Gas"], "the orphan heater must not appear"


def test_light_show_with_a_missing_circuit_offers_no_effects():
    _, _, _, built = all_platforms(objects=DEGRADED)
    assert by_object(built["light"], "C0004")._lightEffects is None


def test_colour_light_reports_its_effect():
    _, _, _, built = all_platforms()
    assert by_object(built["light"], "C0002").effect == "Party Mode"


def test_cover_is_created_and_reads_its_state():
    _, _, _, built = all_platforms()
    assert len(built["cover"]) == 1
    assert built["cover"][0].is_closed is True
    assert built["cover"][0].name == "Cover"


def test_chlorinator_without_a_body_creates_no_number():
    _, _, _, built = all_platforms(objects=DEGRADED)
    assert built["number"] == []


def test_only_featured_circuits_become_switches():
    _, _, _, built = all_platforms()
    objnams = {e._poolObject.objnam for e in built["switch"]}
    assert "C0001" in objnams, "featured circuit missing"
    assert "C0002" not in objnams, "a light must not also be a switch"
    assert "C0003" not in objnams, "the freeze circuit is not featured"


# -- update and availability -------------------------------------------------

def test_an_update_writes_state_only_for_interested_entities():
    controller, hass, entry, built = all_platforms()
    schedule = by_object(built["binary_sensor"], "SCH01")
    pool_switch = by_object(built["switch"], "B1101")
    before = getattr(pool_switch, "state_writes", 0)

    controller.model["SCH01"].update({"ACT": "OFF"})
    dispatcher.async_dispatcher_send(hass, f"{DOMAIN}_UPDATE_{entry.entry_id}",
                                     {"SCH01": {"ACT": "OFF"}})
    assert schedule.is_on is False
    assert getattr(pool_switch, "state_writes", 0) == before


def test_entities_go_unavailable_and_come_back():
    controller, hass, entry, built = all_platforms()
    schedule = by_object(built["binary_sensor"], "SCH01")
    signal = f"{DOMAIN}_CONNECTION_{entry.entry_id}"

    dispatcher.async_dispatcher_send(hass, signal, False)
    assert schedule.available is False
    dispatcher.async_dispatcher_send(hass, signal, True)
    assert schedule.available is True


def test_an_object_removed_while_disconnected_stays_unavailable():
    controller, hass, entry, built = all_platforms()
    schedule = by_object(built["binary_sensor"], "SCH01")
    signal = f"{DOMAIN}_CONNECTION_{entry.entry_id}"

    dispatcher.async_dispatcher_send(hass, signal, False)
    del controller.model.objects["SCH01"]
    dispatcher.async_dispatcher_send(hass, signal, True)
    assert schedule.available is False, "must not resurrect a vanished object"


def test_reconnecting_rebinds_entities_to_the_refreshed_object():
    controller, hass, entry, built = all_platforms()
    schedule = by_object(built["binary_sensor"], "SCH01")
    signal = f"{DOMAIN}_CONNECTION_{entry.entry_id}"

    dispatcher.async_dispatcher_send(hass, signal, False)
    replacement = controller.model["SCH01"]
    replacement.update({"ACT": "OFF"})
    dispatcher.async_dispatcher_send(hass, signal, True)
    assert schedule._poolObject is replacement
    assert schedule.is_on is False
