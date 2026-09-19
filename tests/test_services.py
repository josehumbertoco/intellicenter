"""Service calls: what each entity actually puts on the wire."""

import asyncio

from custom_components.intellicenter import binary_sensor  # noqa: F401
from custom_components.intellicenter import cover, light, number, switch, water_heater

from helpers import build_controller, build_hass, by_object, setup_platform


def drain(controller, transport):
    """Release flow control so every queued request reaches the transport."""
    protocol = controller._protocol
    while protocol._out_pending:
        protocol.responseReceived()
    return transport.requests


def platform(module, **kw):
    """Set a platform up and hand back its entities plus the wire."""
    async def scenario():
        controller, transport = build_controller(**kw)
        hass, entry, _ = build_hass(controller)
        entities = await setup_platform(module, hass, entry)
        return controller, transport, entities
    return asyncio.run(scenario())


def only_change(controller, transport):
    """The single SETPARAMLIST payload that was sent."""
    writes = [r for r in drain(controller, transport)
              if r["command"] == "SETPARAMLIST"]
    assert len(writes) == 1, f"expected one write, got {writes}"
    target = writes[0]["objectList"][0]
    return target["objnam"], target["params"]


def test_switch_turns_a_body_on():
    controller, transport, entities = platform(switch)
    by_object(entities, "B1101").turn_on()
    assert only_change(controller, transport) == ("B1101", {"STATUS": "ON"})


def test_switch_turns_a_body_off():
    controller, transport, entities = platform(switch)
    by_object(entities, "B1101").turn_off()
    assert only_change(controller, transport) == ("B1101", {"STATUS": "OFF"})


def test_switch_drives_a_featured_circuit():
    controller, transport, entities = platform(switch)
    by_object(entities, "C0001").turn_on()
    assert only_change(controller, transport) == ("C0001", {"STATUS": "ON"})


def test_superchlorinate_switch_writes_its_own_attribute():
    controller, transport, entities = platform(switch)
    by_object(entities, "CHL01", "SUPER").turn_on()
    assert only_change(controller, transport) == ("CHL01", {"SUPER": "ON"})


def test_vacation_mode_switch_writes_the_system_object():
    controller, transport, entities = platform(switch)
    vacation = by_object(entities, "_5451", "VACFLO")
    assert vacation._attr_entity_registry_enabled_default is False
    vacation.turn_on()
    assert only_change(controller, transport) == ("_5451", {"VACFLO": "ON"})


def test_light_turns_on_and_off():
    controller, transport, entities = platform(light)
    by_object(entities, "C0002").turn_off()
    assert only_change(controller, transport) == ("C0002", {"STATUS": "OFF"})


def test_light_effect_is_written_to_act_not_use():
    controller, transport, entities = platform(light)
    bulb = by_object(entities, "C0002")
    assert "Caribbean" in bulb.effect_list
    bulb.turn_on(effect="Caribbean")
    # the system takes the new colour on ACT but reports it back on USE
    assert only_change(controller, transport) == (
        "C0002", {"STATUS": "ON", "ACT": "CARIB"})


def test_light_ignores_an_unknown_effect():
    controller, transport, entities = platform(light)
    by_object(entities, "C0002").turn_on(effect="Nonsense")
    assert only_change(controller, transport) == ("C0002", {"STATUS": "ON"})


def test_cover_opens_a_normally_on_cover():
    controller, transport, entities = platform(cover)
    asyncio.run(entities[0].async_open_cover())
    # normally on means STATUS ON is closed, so opening writes OFF
    assert only_change(controller, transport) == ("COV01", {"STATUS": "OFF"})


def test_cover_closes_a_normally_on_cover():
    controller, transport, entities = platform(cover)
    asyncio.run(entities[0].async_close_cover())
    assert only_change(controller, transport) == ("COV01", {"STATUS": "ON"})


def test_cover_inverts_for_a_normally_off_cover():
    objects = {"_5451": {"OBJTYP": "SYSTEM", "SNAME": "s", "PROPNAME": "P",
                         "VER": "1", "MODE": "ENGLISH"},
               "COV01": {"OBJTYP": "EXTINSTR", "SUBTYP": "COVER", "SNAME": "Cover",
                         "STATUS": "ON", "NORMAL": "OFF"}}
    controller, transport, entities = platform(cover, objects=objects)
    assert entities[0].is_closed is False
    asyncio.run(entities[0].async_close_cover())
    assert only_change(controller, transport) == ("COV01", {"STATUS": "OFF"})


def test_number_writes_a_whole_percentage():
    controller, transport, entities = platform(number)
    pool_output = entities[0]
    assert pool_output.native_value == 50.0
    pool_output.set_native_value(72.4)
    assert only_change(controller, transport) == ("CHL01", {"PRIM": "72"})


def test_number_covers_each_configured_body():
    _, _, entities = platform(number)
    assert [e._attribute_key for e in entities] == ["PRIM", "SEC"]
    assert "Pool" in entities[0].name and "Spa" in entities[1].name


def test_water_heater_sets_the_target_temperature():
    controller, transport, entities = platform(water_heater)
    by_object(entities, "B1101").set_temperature(temperature=86.0)
    assert only_change(controller, transport) == ("B1101", {"LOTMP": "86"})


def test_water_heater_selects_a_heater_by_name():
    controller, transport, entities = platform(water_heater)
    pool = by_object(entities, "B1101")
    assert pool.operation_list == ["off", "Gas Heater"]
    assert pool.current_operation == "Gas Heater"
    pool.set_operation_mode("Gas Heater")
    assert only_change(controller, transport) == ("B1101", {"HEATER": "H0001"})


def test_water_heater_turns_off_with_the_null_heater():
    controller, transport, entities = platform(water_heater)
    asyncio.run(by_object(entities, "B1101").async_turn_off())
    assert only_change(controller, transport) == ("B1101", {"HEATER": "00000"})


def test_water_heater_turn_on_reuses_the_last_heater():
    controller, transport, entities = platform(water_heater)
    spa = by_object(entities, "B1202")
    assert spa.current_operation == "off"
    asyncio.run(spa.async_turn_on())
    # the spa has never had a heater selected, so it falls back to the first
    assert only_change(controller, transport) == ("B1202", {"HEATER": "H0001"})


def test_service_calls_do_not_write_state_optimistically():
    controller, transport, entities = platform(switch)
    body = by_object(entities, "B1101")
    writes = getattr(body, "state_writes", 0)
    body.turn_off()
    assert body.is_on is True, "state must follow the system, not the request"
    assert getattr(body, "state_writes", 0) == writes
