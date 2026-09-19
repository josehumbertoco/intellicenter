"""Shared fixtures for the testbench."""

import asyncio
import inspect
import json

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import dispatcher

import custom_components.intellicenter as integration
from custom_components.intellicenter.const import DOMAIN
from custom_components.intellicenter.pyintellicenter import ModelController, PoolModel
from custom_components.intellicenter.pyintellicenter.controller import SystemInfo
from custom_components.intellicenter.pyintellicenter.protocol import ICProtocol

from fake_intellicenter import DEFAULT_OBJECTS


def real_attributes_map():
    """Return the attribute map async_setup_entry really builds.

    Reading it from the source keeps the tests honest: an object type missing
    from it means the model drops those objects and the matching platform
    creates nothing, which is not otherwise visible.
    """
    src = inspect.getsource(integration.async_setup_entry)
    body = src[src.index("attributes_map = {"):src.index("model = PoolModel")]
    return eval(body[body.index("{"):body.rindex("}") + 1], dict(vars(integration)))


def pruned(objects=None):
    """The default system as the model holds it, placeholders stripped."""
    out = []
    for objnam, params in (objects or DEFAULT_OBJECTS).items():
        kept = {k: v for k, v in params.items() if k != v}
        out.append({"objnam": objnam, "params": kept})
    return out


class FakeTransport:
    """Captures what the integration puts on the wire."""

    def __init__(self):
        self.written = []
        self.closed = False

    def write(self, data):
        self.written.append(data.decode())

    def is_closing(self):
        return self.closed

    def close(self):
        self.closed = True

    @property
    def requests(self):
        """Everything written, decoded back into dicts."""
        out, decoder = [], json.JSONDecoder()
        for chunk in self.written:
            buf = chunk.strip()
            while buf:
                msg, end = decoder.raw_decode(buf)
                out.append(msg)
                buf = buf[end:].strip()
        return out


class StubHass:
    def __init__(self):
        self.data = {}
        self.loop = None
        self.config_entries = None
        self.bus = self
        self.tasks = []

    def async_listen_once(self, event, target):
        return lambda: None

    def async_create_task(self, coro):
        task = asyncio.ensure_future(coro)
        self.tasks.append(task)
        return task


class StubConfigEntries:
    """Just enough of hass.config_entries for setup and unload."""

    def __init__(self):
        self.forwarded = []
        self.unloaded = []
        self.unload_result = True

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry.entry_id, list(platforms)))

    async def async_unload_platforms(self, entry, platforms):
        self.unloaded.append((entry.entry_id, list(platforms)))
        return self.unload_result


def build_controller(objects=None, metric=False, attributes_map=None, connect=True):
    """A ModelController wired to a fake transport, with the model loaded.

    No socket is involved, but the real protocol object is, so anything a
    service call sends can be inspected as actual wire traffic.
    """
    model = PoolModel(attributes_map or real_attributes_map())
    model.addObjects(pruned(objects))

    controller = ModelController("127.0.0.1", model)
    controller._systemInfo = SystemInfo("_5451", {
        "PROPNAME": "Pool House", "VER": "1.064",
        "MODE": "METRIC" if metric else "ENGLISH", "SNAME": "system"})

    transport = FakeTransport()
    if connect:
        protocol = ICProtocol(controller)
        protocol.connection_made(transport)
        controller._protocol = protocol
        controller._transport = transport
    return controller, transport


def build_hass(controller, entry_id="entry1"):
    """A hass/entry/handler triple as the platforms expect to find it."""
    dispatcher.reset()
    hass = StubHass()
    hass.loop = asyncio.get_event_loop_policy().get_event_loop()
    hass.config_entries = StubConfigEntries()
    entry = ConfigEntry(entry_id, {"host": "127.0.0.1"})
    handler = type("Handler", (), {
        "controller": controller, "stop": lambda self: None})()
    hass.data[DOMAIN] = {entry_id: handler}
    return hass, entry, handler


async def setup_platform(module, hass, entry):
    """Run a platform's async_setup_entry and return the entities it made."""
    added = []
    await module.async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    for entity in added:
        entity.hass = hass
        await entity.async_added_to_hass()
    return added


def by_object(entities, objnam, attribute_key=None):
    """Find the entity built for a given pool object."""
    for entity in entities:
        if entity._poolObject.objnam != objnam:
            continue
        if attribute_key is None or entity._attribute_key == attribute_key:
            return entity
    raise AssertionError(f"no entity for {objnam}/{attribute_key}")


async def settle(seconds=0.05):
    await asyncio.sleep(seconds)
