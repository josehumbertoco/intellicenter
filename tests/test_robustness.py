"""Hostile and degraded input. Nothing here may escape as an exception."""

import asyncio
import json
import random

from custom_components.intellicenter.pyintellicenter import PoolModel
from custom_components.intellicenter.pyintellicenter.protocol import ICProtocol

from helpers import FakeTransport, build_controller

MALFORMED = [
    b"not json at all\r\n",
    b"{}\r\n",
    b'{"messageID":"1"}\r\n',
    b'{"command":"NotifyList"}\r\n',
    b'{"messageID":"1","command":"NotifyList"}\r\n',
    b'{"messageID":"1","command":"NotifyList","objectList":"nonsense"}\r\n',
    b'{"messageID":"1","command":"NotifyList","objectList":[{}]}\r\n',
    b'{"messageID":"1","command":"NotifyList","objectList":[{"objnam":"B1101"}]}\r\n',
    b'{"messageID":"1","command":"NotifyList","objectList":[{"objnam":"B1101","params":null}]}\r\n',
    b'{"messageID":"1","command":"WriteParamList","objectList":[]}\r\n',
    b'{"messageID":"1","command":"WriteParamList","objectList":[{"objnam":"x"}]}\r\n',
    b'{"messageID":"1","command":"SendParamList","objectList":[{"objnam":"Z","params":{}}]}\r\n',
    b'{"messageID":"1","command":"SendQuery"}\r\n',
    b'{"messageID":"1","command":"SendParamList","objectList":[{"params":{}}]}\r\n',
    b'{"messageID":"1","command":"\\u0000\\uffff"}\r\n',
    b'{"messageID":null,"command":null}\r\n',
    b"\r\n\r\n\r\n",
    b"pong\r\n",
    b"\x80\x81\x82\r\n",
    b'{"messageID":"1","command":"NotifyList","objectList":[{"objnam":"B1101","params":{"STATUS":null}}]}\r\n',
    b'{"messageID":"1","command":"NotifyList","objectList":[{"objnam":"B1101","params":{"STATUS":["a"]}}]}\r\n',
    b'{"messageID":"1","command":"NotifyList","objectList":[{"objnam":"B1101","params":{"STATUS":{"a":1}}}]}\r\n',
    ('{"messageID":"1","command":"NotifyList","objectList":'
     '[{"objnam":"B1101","params":{"SNAME":"' + "x" * 10000 + '"}}]}\r\n').encode(),
]


def wired():
    controller, _ = build_controller(connect=False)
    protocol = ICProtocol(controller)
    protocol.connection_made(FakeTransport())
    controller._protocol = protocol
    controller._transport = protocol._transport
    return controller, protocol


def test_malformed_messages_never_raise():
    controller, protocol = wired()
    for message in MALFORMED:
        protocol.data_received(message)
    assert controller.model["B1101"] is not None, "the model survived"


def test_random_bytes_never_raise():
    controller, protocol = wired()
    random.seed(20240919)
    for _ in range(5000):
        blob = bytes(random.getrandbits(8) for _ in range(random.randint(1, 80)))
        if random.random() < 0.3:
            blob += b"\r\n"
        protocol.data_received(blob)


def test_structurally_valid_but_nonsense_payloads_never_raise():
    controller, protocol = wired()
    random.seed(7)
    shapes = ["NotifyList", "WriteParamList", "SendParamList", "SendQuery", "Bogus"]
    for _ in range(600):
        msg = {"messageID": random.choice(["0", "1", "", "99999"]),
               "command": random.choice(shapes)}
        if random.random() < 0.7:
            msg["objectList"] = random.choice([
                [], [{}], [{"objnam": "B1101"}],
                [{"objnam": "B1101", "params": {"STATUS": random.choice(
                    ["ON", "OFF", "", None, 1, [], {}])}}],
                [{"objnam": "B1101", "changes": [{"objnam": "B1101", "params": {}}]}],
                "not a list", None])
        if random.random() < 0.3:
            msg["response"] = random.choice(["200", "400", None, ""])
        protocol.data_received((json.dumps(msg) + "\r\n").encode())


def test_a_flood_of_updates_is_absorbed():
    controller, protocol = wired()
    seen = []
    controller._updatedCallback = lambda c, u: seen.append(u)
    blob = b"".join(
        (json.dumps({"messageID": "0", "command": "NotifyList", "objectList": [
            {"objnam": "B1101", "params": {"LSTTMP": str(70 + i % 20)}}]})
         + "\r\n").encode() for i in range(2000))
    protocol.data_received(blob)
    assert controller.model["B1101"]["LSTTMP"] is not None
    assert len(seen) > 0


def test_an_object_that_disappears_mid_session():
    controller, protocol = wired()
    del controller.model.objects["B1101"]
    protocol.data_received(
        (json.dumps({"messageID": "0", "command": "NotifyList", "objectList": [
            {"objnam": "B1101", "params": {"STATUS": "ON"}}]}) + "\r\n").encode())


def test_a_model_with_no_objects_at_all():
    from custom_components.intellicenter import (
        binary_sensor, cover, light, number, sensor, switch, water_heater,
    )
    from helpers import build_hass, setup_platform

    async def scenario():
        controller, _ = build_controller(objects={
            "_5451": {"OBJTYP": "SYSTEM", "SNAME": "s", "PROPNAME": "P",
                      "VER": "1", "MODE": "ENGLISH"}})
        hass, entry, _ = build_hass(controller)
        for module in (binary_sensor, cover, light, number, sensor, switch,
                       water_heater):
            # an empty system must set up cleanly, not crash
            await setup_platform(module, hass, entry)
    asyncio.run(scenario())


def test_a_system_reporting_nothing_but_placeholders():
    from custom_components.intellicenter import binary_sensor, sensor, water_heater
    from helpers import build_hass, setup_platform

    async def scenario():
        controller, _ = build_controller(objects={
            "_5451": {"OBJTYP": "SYSTEM"},
            "B1101": {"OBJTYP": "BODY"},
            "H0001": {"OBJTYP": "HEATER"},
            "SCH01": {"OBJTYP": "SCHED"},
            "PMP01": {"OBJTYP": "PUMP"},
        })
        hass, entry, _ = build_hass(controller)
        for module in (binary_sensor, sensor, water_heater):
            for entity in await setup_platform(module, hass, entry):
                entity.name
                entity.unique_id
                entity.extra_state_attributes
                getattr(entity, "is_on", None)
                getattr(entity, "native_value", None)
                getattr(entity, "state", None)
    asyncio.run(scenario())


def test_duplicate_objects_in_one_payload():
    model = PoolModel({"BODY": {"STATUS"}})
    model.addObjects([
        {"objnam": "B1", "params": {"OBJTYP": "BODY", "STATUS": "ON"}},
        {"objnam": "B1", "params": {"OBJTYP": "BODY", "STATUS": "OFF"}},
    ])
    assert model.numObjects == 1
    assert model["B1"]["STATUS"] == "OFF"


def test_a_malformed_update_is_skipped_not_fatal():
    model = PoolModel({"BODY": {"STATUS"}})
    model.addObjects([{"objnam": "B1", "params": {"OBJTYP": "BODY", "STATUS": "ON"}}])
    # this path also runs from start(), where raising would fail the whole
    # connection and leave the reconnection loop retrying forever
    updated = model.processUpdates([
        {"params": {"STATUS": "OFF"}},          # no objnam
        "not a dict",
        {"objnam": "B1", "params": {"STATUS": "OFF"}},
    ])
    assert updated == {"B1": {"STATUS": "OFF"}}, "the good entry still applied"
