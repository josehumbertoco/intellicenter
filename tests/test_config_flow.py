"""Config flow: discovery, manual setup and failure handling."""

import asyncio
import json

from custom_components.intellicenter import config_flow as flow_module
from custom_components.intellicenter.pyintellicenter import BaseController

from fake_intellicenter import FakeIntelliCenter
from helpers import StubHass


class Flow(flow_module.ConfigFlow):
    """The real flow, with the bits Home Assistant normally supplies."""

    def __init__(self, port, existing=()):
        super().__init__()
        self.hass = StubHass()
        self.hass.loop = asyncio.get_event_loop_policy().get_event_loop()
        self.context = {}
        self.unique_id = None
        self._existing = list(existing)
        self._port = port

    # -- the flow API the integration calls --------------------------------

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self, updates=None):
        if any(e.get("unique_id") == self.unique_id for e in self._existing):
            raise Aborted("already_configured")

    def async_create_entry(self, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_abort(self, reason):
        return {"type": "abort", "reason": reason}

    def async_show_form(self, step_id, data_schema=None, errors=None,
                        description_placeholders=None):
        return {"type": "form", "step_id": step_id, "errors": errors or {},
                "placeholders": description_placeholders or {}}

    def _async_current_entries(self):
        return [type("E", (), {"data": e["data"]})() for e in self._existing]

    # -- point the probe at the fake system --------------------------------

    async def _get_system_info(self, host):
        original = flow_module.BaseController
        flow_module.BaseController = (
            lambda h, loop=None, keepAlive=True: BaseController(
                h, port=self._port, loop=loop, keepAlive=keepAlive))
        try:
            return await super()._get_system_info(host)
        finally:
            flow_module.BaseController = original


class Aborted(Exception):
    def __init__(self, reason):
        self.reason = reason


class Discovery:
    def __init__(self, host):
        self.host = host


def with_server(scenario, **server_kw):
    async def main():
        server = FakeIntelliCenter()
        for key, value in server_kw.items():
            setattr(server, key, value)
        port = await server.start()
        try:
            return await scenario(server, port)
        finally:
            await server.stop()
    return asyncio.run(main())


def test_user_step_shows_a_form_first():
    async def scenario(server, port):
        return await Flow(port).async_step_user(None)
    result = with_server(scenario)
    assert result["type"] == "form" and result["step_id"] == "user"


def test_user_step_creates_the_entry():
    async def scenario(server, port):
        return await Flow(port).async_step_user({"host": "127.0.0.1"})
    result = with_server(scenario)
    assert result["type"] == "create_entry"
    assert result["title"] == "Pool House"
    assert result["data"] == {"host": "127.0.0.1"}


def test_user_step_reports_a_connection_failure():
    async def scenario(server, port):
        # nothing is listening on this port
        return await Flow(port + 1).async_step_user({"host": "127.0.0.1"})
    result = with_server(scenario)
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


def test_user_step_gives_up_on_a_host_that_never_answers():
    original = flow_module.CONNECT_TIMEOUT
    flow_module.CONNECT_TIMEOUT = 0.4

    async def scenario(server, port):
        started = asyncio.get_running_loop().time()
        result = await Flow(port).async_step_user({"host": "127.0.0.1"})
        return result, asyncio.get_running_loop().time() - started

    try:
        result, elapsed = with_server(scenario, silent=True)
    finally:
        flow_module.CONNECT_TIMEOUT = original
    assert result["errors"] == {"base": "cannot_connect"}
    assert elapsed < 3, "the flow must not hang on an unresponsive host"


def test_zeroconf_offers_a_confirmation():
    async def scenario(server, port):
        f = Flow(port)
        result = await f.async_step_zeroconf(Discovery("127.0.0.1"))
        return f, result
    f, result = with_server(scenario)
    assert result["type"] == "form" and result["step_id"] == "zeroconf_confirm"
    assert result["placeholders"] == {"host": "127.0.0.1", "name": "Pool House"}


def test_zeroconf_confirm_creates_the_entry():
    async def scenario(server, port):
        f = Flow(port)
        await f.async_step_zeroconf(Discovery("127.0.0.1"))
        return await f.async_step_zeroconf_confirm({})
    result = with_server(scenario)
    assert result["type"] == "create_entry" and result["title"] == "Pool House"


def test_zeroconf_ignores_a_host_already_configured():
    async def scenario(server, port):
        existing = [{"data": {"host": "127.0.0.1"}, "unique_id": "x"}]
        return await Flow(port, existing).async_step_zeroconf(Discovery("127.0.0.1"))
    result = with_server(scenario)
    assert result == {"type": "abort", "reason": "already_configured"}


def test_zeroconf_aborts_when_the_system_cannot_be_reached():
    async def scenario(server, port):
        return await Flow(port + 1).async_step_zeroconf(Discovery("127.0.0.1"))
    result = with_server(scenario)
    assert result["type"] == "abort" and result["reason"] == "cannot_connect"


def test_the_probe_leaves_no_connection_behind():
    async def scenario(server, port):
        await Flow(port).async_step_user({"host": "127.0.0.1"})
        await asyncio.sleep(0.1)
        return server
    server = with_server(scenario)
    assert server.writers == [], "the probe must close its connection"


def test_every_abort_and_error_reason_has_a_translation():
    import pathlib
    import re
    source = pathlib.Path("custom_components/intellicenter/config_flow.py").read_text()
    used_abort = set(re.findall(r'async_abort\(reason="([a-z_]+)"', source))
    used_error = set(re.findall(r'"base": "([a-z_]+)"', source))
    for path in ("custom_components/intellicenter/strings.json",
                 "custom_components/intellicenter/translations/en.json"):
        data = json.loads(pathlib.Path(path).read_text())["config"]
        missing = used_abort - set(data.get("abort", {}))
        assert not missing, f"{path} is missing abort reasons {sorted(missing)}"
        missing = used_error - set(data.get("error", {}))
        assert not missing, f"{path} is missing errors {sorted(missing)}"
