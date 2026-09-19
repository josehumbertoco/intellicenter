"""Setup, unload and the packaging Home Assistant reads at load time."""

import asyncio
import json
import pathlib

from homeassistant.helpers import dispatcher

from custom_components.intellicenter import (
    PLATFORMS,
    async_setup,
    async_setup_entry,
    async_unload_entry,
    diagnostics,
)
from custom_components.intellicenter.const import DOMAIN

from fake_intellicenter import FakeIntelliCenter
from helpers import (
    StubConfigEntries,
    StubHass,
    build_controller,
    build_hass,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "intellicenter"


def test_async_setup_accepts_yaml_free_configuration():
    assert asyncio.run(async_setup(StubHass(), {})) is True


def test_setup_registers_the_handler_then_connects():
    async def scenario():
        from homeassistant.config_entries import ConfigEntry
        server = FakeIntelliCenter()
        port = await server.start()
        hass = StubHass()
        hass.loop = asyncio.get_running_loop()
        hass.config_entries = StubConfigEntries()
        entry = ConfigEntry("e1", {"host": "127.0.0.1"})

        import custom_components.intellicenter.pyintellicenter as lib
        original = lib.ModelController
        # point the controller at the fake system's port
        import custom_components.intellicenter as integration
        integration.ModelController = (
            lambda host, model, loop=None: original(host, model, port=port, loop=loop))
        try:
            assert await async_setup_entry(hass, entry) is True
            # the handler must be registered before anything can look it up
            assert hass.data[DOMAIN]["e1"] is not None
            for _ in range(200):
                await asyncio.sleep(0.02)
                if hass.config_entries.forwarded:
                    break
            assert hass.config_entries.forwarded == [("e1", list(PLATFORMS))]
            handler = hass.data[DOMAIN]["e1"]
            assert handler.controller.model.numObjects > 0
            handler.stop()
        finally:
            integration.ModelController = original
            await server.stop()
    asyncio.run(scenario())


def test_unload_reports_success_and_cleans_up():
    async def scenario():
        controller, _ = build_controller()
        hass, entry, _ = build_hass(controller)
        assert await async_unload_entry(hass, entry) is True
        assert hass.config_entries.unloaded == [(entry.entry_id, list(PLATFORMS))]
        assert DOMAIN not in hass.data
    asyncio.run(scenario())


def test_a_failed_unload_keeps_the_entry():
    async def scenario():
        controller, _ = build_controller()
        hass, entry, _ = build_hass(controller)
        hass.config_entries.unload_result = False
        assert await async_unload_entry(hass, entry) is False
        assert entry.entry_id in hass.data[DOMAIN], "the entry is still in use"
    asyncio.run(scenario())


def test_unloading_one_of_two_pools_leaves_the_other():
    async def scenario():
        from homeassistant.config_entries import ConfigEntry
        controller_a, _ = build_controller()
        controller_b, _ = build_controller()
        hass, entry_a, _ = build_hass(controller_a, "poolA")
        entry_b = ConfigEntry("poolB", {"host": "127.0.0.2"})
        hass.data[DOMAIN]["poolB"] = type(
            "H", (), {"controller": controller_b, "stop": lambda self: None})()

        assert await async_unload_entry(hass, entry_a) is True
        assert DOMAIN in hass.data and "poolB" in hass.data[DOMAIN]
    asyncio.run(scenario())


def test_two_pools_do_not_cross_talk():
    """Each entry's dispatcher signals are namespaced by entry id."""
    async def scenario():
        from custom_components.intellicenter import binary_sensor
        from helpers import by_object, setup_platform

        controller_a, _ = build_controller()
        hass, entry_a, _ = build_hass(controller_a, "poolA")
        entities_a = await setup_platform(binary_sensor, hass, entry_a)

        from homeassistant.config_entries import ConfigEntry
        controller_b, _ = build_controller()
        entry_b = ConfigEntry("poolB", {"host": "127.0.0.2"})
        hass.data[DOMAIN]["poolB"] = type(
            "H", (), {"controller": controller_b, "stop": lambda self: None})()
        entities_b = await setup_platform(binary_sensor, hass, entry_b)

        a = by_object(entities_a, "SCH01")
        b = by_object(entities_b, "SCH01")
        assert a.unique_id != b.unique_id

        dispatcher.async_dispatcher_send(hass, f"{DOMAIN}_CONNECTION_poolA", False)
        assert a.available is False
        assert b.available is True, "one pool going away must not affect the other"
    asyncio.run(scenario())


def test_removing_an_entity_unsubscribes_it():
    async def scenario():
        from custom_components.intellicenter import binary_sensor
        from helpers import by_object, setup_platform

        controller, _ = build_controller()
        hass, entry, _ = build_hass(controller)
        entities = await setup_platform(binary_sensor, hass, entry)
        schedule = by_object(entities, "SCH01")
        schedule.remove()

        dispatcher.async_dispatcher_send(hass, f"{DOMAIN}_CONNECTION_{entry.entry_id}",
                                         False)
        assert schedule.available is True, "a removed entity must not still listen"
    asyncio.run(scenario())


def test_diagnostics_dump_every_tracked_object():
    async def scenario():
        controller, _ = build_controller()
        hass, entry, _ = build_hass(controller)
        report = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
        assert len(report["objects"]) == controller.model.numObjects
        entry_for_pool = next(o for o in report["objects"] if o["objnam"] == "B1101")
        assert entry_for_pool["objtype"] == "BODY"
        assert entry_for_pool["properties"]["STATUS"] == "ON"
    asyncio.run(scenario())


# -- packaging ---------------------------------------------------------------

def test_manifest_is_valid_for_a_custom_integration():
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["domain"] == COMPONENT.name
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_push"
    assert "version" in manifest, "custom integrations must declare a version"
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:]), "hassfest wants the rest alphabetical"


def test_every_declared_platform_has_a_module():
    for platform in PLATFORMS:
        assert (COMPONENT / f"{platform}.py").exists(), f"{platform}.py missing"


def test_hacs_manifest_lists_every_platform():
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert set(PLATFORMS) <= set(hacs["domains"]), (
        f"hacs.json is missing {sorted(set(PLATFORMS) - set(hacs['domains']))}")


def test_translations_match_the_strings_file():
    def shape(node, prefix=""):
        keys = set()
        for key, value in node.items():
            keys.add(prefix + key)
            if isinstance(value, dict):
                keys |= shape(value, prefix + key + ".")
        return keys

    strings = json.loads((COMPONENT / "strings.json").read_text())
    english = json.loads((COMPONENT / "translations" / "en.json").read_text())
    assert shape(strings) == shape(english)
