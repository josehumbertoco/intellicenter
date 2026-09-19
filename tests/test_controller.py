"""BaseController and ModelController: requests, responses and the model."""

import asyncio

from custom_components.intellicenter.pyintellicenter import CommandError, PoolModel
from custom_components.intellicenter.pyintellicenter.controller import (
    SystemInfo,
    prune,
)

from helpers import build_controller


def run(coro):
    return asyncio.run(coro)


def test_prune_strips_placeholders_only():
    payload = [{"objnam": "B1101",
                "params": {"STATUS": "ON", "SNAME": "SNAME", "N": 5, "L": ["a"]}}]
    assert prune(payload) == [
        {"objnam": "B1101", "params": {"STATUS": "ON", "N": 5, "L": ["a"]}}]
    assert prune(7) == 7 and prune(None) is None and prune("x") == "x"


def test_updates_are_pruned_before_reaching_the_model():
    controller, _ = build_controller()
    # a schedule whose ACT has no value used to be stored as the string "ACT",
    # which is never equal to "ON" and so read as permanently off
    controller._applyUpdates([{"objnam": "SCH02", "params": {"ACT": "ACT"}}])
    assert controller.model["SCH02"]["ACT"] is None

    controller._applyUpdates([{"objnam": "SCH02", "params": {"ACT": "ON"}}])
    assert controller.model["SCH02"]["ACT"] == "ON"

    # and a later placeholder must not wipe out a real value
    controller._applyUpdates([{"objnam": "SCH02", "params": {"ACT": "ACT"}}])
    assert controller.model["SCH02"]["ACT"] == "ON"


def test_update_callback_fires_only_on_a_real_change():
    controller, _ = build_controller()
    seen = []
    controller._updatedCallback = lambda c, updates: seen.append(updates)

    controller._applyUpdates([{"objnam": "B1101", "params": {"STATUS": "OFF"}}])
    assert seen == [{"B1101": {"STATUS": "OFF"}}]

    seen.clear()
    controller._applyUpdates([{"objnam": "B1101", "params": {"STATUS": "OFF"}}])
    assert seen == [], "an unchanged value must not wake every entity"


def test_system_info_is_refreshed_from_updates():
    controller, _ = build_controller()
    assert controller.systemInfo.usesMetric is False
    controller._applyUpdates([{"objnam": "_5451", "params": {"MODE": "METRIC"}}])
    assert controller.systemInfo.usesMetric is True


def test_command_is_written_as_json_and_returns_a_future():
    async def scenario():
        controller, transport = build_controller()
        controller._loop = asyncio.get_running_loop()
        future = controller.sendCmd("GetParamList", {"condition": ""})
        assert not future.done()
        sent = transport.requests[0]
        assert sent["command"] == "GetParamList" and sent["condition"] == ""

        controller.receivedMessage(sent["messageID"], "SendParamList", "200",
                                   {"ok": True})
        assert await future == {"ok": True}
    run(scenario())


def test_error_response_raises_command_error():
    async def scenario():
        controller, transport = build_controller()
        controller._loop = asyncio.get_running_loop()
        future = controller.sendCmd("GetParamList")
        controller.receivedMessage(transport.requests[0]["messageID"], "Error",
                                   "400", {})
        try:
            await future
        except CommandError as err:
            assert err.errorCode == "400"
        else:
            raise AssertionError("expected CommandError")
    run(scenario())


def test_fire_and_forget_command_registers_no_future():
    controller, transport = build_controller()
    assert controller.sendCmd("SETPARAMLIST", waitForResponse=False) is None
    assert controller._requests[transport.requests[0]["messageID"]] is None


def test_sending_while_disconnected_fails_cleanly():
    async def scenario():
        controller, _ = build_controller(connect=False)
        controller._loop = asyncio.get_running_loop()
        # must not be an AttributeError from a misspelled set_exception
        try:
            await controller.sendCmd("GetParamList")
        except AttributeError as err:
            raise AssertionError(f"leaked internal error: {err}")
        except Exception:
            pass
        # and the fire and forget path must not raise at all
        controller.requestChanges("C0001", {"STATUS": "ON"}, waitForResponse=False)
    run(scenario())


def test_late_response_to_a_timed_out_request_is_ignored():
    async def scenario():
        controller, transport = build_controller()
        controller._loop = asyncio.get_running_loop()
        future = controller.sendCmd("GetParamList")
        future.cancel()
        # arriving after the caller gave up must not raise InvalidStateError
        controller.receivedMessage(transport.requests[0]["messageID"],
                                   "SendParamList", "200", {})
    run(scenario())


def test_stop_forgets_pending_requests():
    controller, _ = build_controller()
    controller.sendCmd("GetParamList", waitForResponse=False)
    assert controller._requests
    controller.stop()
    assert not controller._requests, "dead futures must not pile up across reconnects"


def test_notification_reaches_the_model():
    controller, _ = build_controller()
    controller.receivedMessage(
        "0", "NotifyList", None,
        {"objectList": [{"objnam": "B1101", "params": {"STATUS": "OFF"}}]})
    assert controller.model["B1101"]["STATUS"] == "OFF"


def test_write_acknowledgement_reaches_the_model():
    controller, _ = build_controller()
    controller.receivedMessage("0", "WriteParamList", None, {"objectList": [
        {"objnam": "C0001", "changes": [
            {"objnam": "C0001", "params": {"STATUS": "ON"}}]}]})
    assert controller.model["C0001"]["STATUS"] == "ON"


def test_handshake_survives_a_system_that_omits_attributes():
    for missing in ("PROPNAME", "VER", "MODE", "SNAME"):
        params = {"PROPNAME": "p", "VER": "1.064", "MODE": "ENGLISH", "SNAME": "s"}
        params.pop(missing)
        SystemInfo("_5451", params)  # must not raise


def test_unique_id_is_stable_and_derived_from_sname():
    full = {"PROPNAME": "p", "VER": "1", "MODE": "ENGLISH", "SNAME": "s"}
    # the config entry's unique id: it must not move for existing installs
    assert SystemInfo("_5451", full).uniqueID == SystemInfo("other", {"SNAME": "s"}).uniqueID
    assert SystemInfo("_5451", full).uniqueID != SystemInfo("_5451", {"SNAME": "t"}).uniqueID


def test_attributes_to_track_covers_every_kept_object():
    controller, _ = build_controller()
    tracked = {q["objnam"] for q in controller.model.attributesToTrack()}
    assert tracked == {o.objnam for o in controller.model.objectList}
