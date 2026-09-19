"""Connection lifecycle against a real socket: startup, loss, keepalive."""

import asyncio

import custom_components.intellicenter.pyintellicenter.controller as controller_module
from custom_components.intellicenter.pyintellicenter import (
    ConnectionHandler,
    ModelController,
    PoolModel,
)

from fake_intellicenter import FakeIntelliCenter
from helpers import real_attributes_map


class Events(ConnectionHandler):
    """Records the lifecycle callbacks."""

    def __init__(self, controller, **kw):
        self.events = []
        super().__init__(controller, **kw)

    def started(self, controller):
        self.events.append("started")

    def reconnected(self, controller):
        self.events.append("reconnected")

    def disconnected(self, controller, exc):
        # the integration's handler logs the system name here, so read it the
        # same way: it does not exist until the handshake has completed
        info = controller.systemInfo
        self.events.append(f"disconnected:{info.propName if info else controller.host}")

    def retrying(self, delay):
        pass


def run(coro, keepalive=None, timeout=None):
    """Run a scenario, optionally with a compressed keepalive cadence."""
    old = controller_module.KEEPALIVE_INTERVAL, controller_module.KEEPALIVE_TIMEOUT
    if keepalive is not None:
        controller_module.KEEPALIVE_INTERVAL = keepalive
    if timeout is not None:
        controller_module.KEEPALIVE_TIMEOUT = timeout
    try:
        return asyncio.run(coro())
    finally:
        controller_module.KEEPALIVE_INTERVAL, controller_module.KEEPALIVE_TIMEOUT = old


def make_controller(port):
    return ModelController("127.0.0.1", PoolModel(real_attributes_map()),
                           port=port, loop=asyncio.get_running_loop())


async def wait_for(predicate, timeout=6.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


def test_startup_loads_the_whole_model():
    async def scenario():
        server = FakeIntelliCenter()
        port = await server.start()
        controller = make_controller(port)
        try:
            await controller.start()
            info = controller.systemInfo
            assert info.propName == "Pool House" and info.swVersion == "1.064"
            assert info.usesMetric is False
            model = controller.model
            assert model["B1101"]["STATUS"] == "ON"
            assert model["SCH01"]["ACT"] == "ON"
            # placeholders must not survive into the model
            assert model["SCH02"]["ACT"] is None
            assert model["SCH02"].sname is None
            assert model["B1202"]["LSTTMP"] is None
            assert model["COV01"] is not None, "covers must be kept"
        finally:
            controller.stop()
            await server.stop()
    run(scenario)


def test_pushed_changes_reach_the_model():
    async def scenario():
        server = FakeIntelliCenter()
        port = await server.start()
        controller = make_controller(port)
        updates = []
        controller._updatedCallback = lambda c, u: updates.append(u)
        try:
            await controller.start()
            updates.clear()
            server.set("B1101", LSTTMP="86")
            assert await wait_for(lambda: controller.model["B1101"]["LSTTMP"] == "86")
            assert updates and "B1101" in updates[-1]
        finally:
            controller.stop()
            await server.stop()
    run(scenario)


def test_reconnects_after_the_system_hangs_up():
    async def scenario():
        server = FakeIntelliCenter()
        port = await server.start()
        handler = Events(make_controller(port), timeBetweenReconnects=1)
        try:
            await handler.start()
            assert await wait_for(lambda: "started" in handler.events)
            server.drop()
            assert await wait_for(lambda: "reconnected" in handler.events)
            assert any(e.startswith("disconnected") for e in handler.events)
            assert server.connections == 2, "exactly one new connection"
            assert handler.controller.model["B1101"]["STATUS"] == "ON"
        finally:
            handler.stop()
            await server.stop()
    run(scenario)


def test_survives_repeated_drops_without_duplicating_connections():
    async def scenario():
        server = FakeIntelliCenter()
        port = await server.start()
        handler = Events(make_controller(port), timeBetweenReconnects=1)
        try:
            await handler.start()
            assert await wait_for(lambda: "started" in handler.events)
            for _ in range(3):
                server.drop()
                await asyncio.sleep(1.4)
            reconnects = handler.events.count("reconnected")
            assert reconnects >= 2, handler.events
            assert server.connections == 1 + reconnects, "no stacked reconnect loops"
        finally:
            handler.stop()
            await server.stop()
    run(scenario)


def test_keepalive_detects_a_system_that_went_silent():
    async def scenario():
        server = FakeIntelliCenter()
        port = await server.start()
        handler = Events(make_controller(port), timeBetweenReconnects=1)
        try:
            await handler.start()
            assert await wait_for(lambda: "started" in handler.events)
            # stop answering without closing the socket: nothing at the TCP
            # level notices, only the keepalive can
            server.silent = True
            assert await wait_for(
                lambda: any(e.startswith("disconnected") for e in handler.events))
            server.silent = False
            assert await wait_for(lambda: "reconnected" in handler.events)
        finally:
            handler.stop()
            await server.stop()
    run(scenario, keepalive=0.4, timeout=0.4)


def test_keepalive_does_not_fire_while_a_large_model_is_loading():
    """The probe waits for silence, not for the clock.

    Only one request sits on the wire at a time, so a probe sent on a timer
    queues behind the burst of requests that loads the model of a large system
    and times out on a perfectly healthy connection.
    """
    async def scenario():
        objects = {"_5451": {"OBJTYP": "SYSTEM", "SNAME": "system",
                             "PROPNAME": "Big Pool", "VER": "1.064",
                             "MODE": "ENGLISH"}}
        # enough objects that the subscription is split into several batches
        for i in range(40):
            objects[f"C{i:04d}"] = {
                "OBJTYP": "CIRCUIT", "SUBTYP": "GENERIC", "SNAME": f"Circuit {i}",
                "STATUS": "OFF", "FEATR": "OFF", "USE": "USE"}
        server = FakeIntelliCenter(objects)
        server.delay = 0.2      # a slow system: every batch takes its time
        port = await server.start()
        handler = Events(make_controller(port), timeBetweenReconnects=1)
        try:
            await handler.start()
            assert await wait_for(lambda: "started" in handler.events, timeout=20)
            assert not any(e.startswith("disconnected") for e in handler.events), (
                f"the keepalive tore down a healthy connection: {handler.events}")
            assert handler.controller.model.numObjects > 40
            assert server.connections == 1, "startup was restarted"
        finally:
            handler.stop()
            await server.stop()
    run(scenario, keepalive=0.3, timeout=0.3)


def test_keepalive_leaves_a_healthy_but_slow_link_alone():
    async def scenario():
        server = FakeIntelliCenter()
        server.delay = 0.12
        port = await server.start()
        handler = Events(make_controller(port), timeBetweenReconnects=1)
        try:
            await handler.start()
            assert await wait_for(lambda: "started" in handler.events)
            connections = server.connections
            peak = 0
            for _ in range(20):
                await asyncio.sleep(0.1)
                peak = max(peak, len(handler.controller._requests))
            assert not any(e.startswith("disconnected") for e in handler.events), \
                handler.events
            assert server.connections == connections
            assert peak <= 1, "only the probe in flight may be outstanding"
        finally:
            handler.stop()
            await server.stop()
    run(scenario, keepalive=0.3, timeout=0.3)


def test_losing_the_link_mid_handshake_still_reconnects():
    async def scenario():
        controller = make_controller(1)
        handler = Events(controller, timeBetweenReconnects=99)
        # systemInfo does not exist yet; this used to raise out of
        # connection_lost before the reconnection was ever scheduled
        controller.connection_lost(ConnectionResetError("reset"))
        # the callback read systemInfo, which is still None at this point
        assert handler.events == ["disconnected:127.0.0.1"]
        assert handler._starterTask is not None, "no reconnection was scheduled"
        handler.stop()
    run(scenario)


def test_a_raising_callback_cannot_block_reconnection():
    async def scenario():
        class Broken(Events):
            def disconnected(self, controller, exc):
                raise RuntimeError("callback blew up")

        handler = Broken(make_controller(1), timeBetweenReconnects=99)
        handler._controller.connection_lost(None)
        assert handler._starterTask is not None
        handler.stop()
    run(scenario)


def test_a_second_disconnect_does_not_start_a_second_loop():
    async def scenario():
        server = FakeIntelliCenter()
        port = await server.start()
        handler = Events(make_controller(port), timeBetweenReconnects=1)
        try:
            await handler.start()
            assert await wait_for(lambda: "started" in handler.events)

            server.drop()
            assert await wait_for(lambda: handler._starterTask is not None)
            running = handler._starterTask

            # the system reporting the drop twice, or a keepalive firing while
            # the reconnection is already under way, must not stack up loops:
            # each one opens its own connection
            handler._diconnectedCallback(handler.controller, None)
            assert handler._starterTask is running, "a second loop was started"

            connections = server.connections
            assert await wait_for(lambda: "reconnected" in handler.events)
            await asyncio.sleep(1.2)
            assert server.connections == connections + 1, (
                f"{server.connections - connections} connections opened")
        finally:
            handler.stop()
            await server.stop()
    run(scenario)


def test_backoff_grows_but_is_capped():
    handler = ConnectionHandler(ModelController("h", PoolModel({})),
                                timeBetweenReconnects=30)
    delay, seen = 30, []
    for _ in range(20):
        delay = handler._next_delay(delay)
        seen.append(delay)
    assert seen[0] > 30, "should back off"
    assert max(seen) <= controller_module.MAX_TIME_BETWEEN_RECONNECTS
    assert seen[-1] == controller_module.MAX_TIME_BETWEEN_RECONNECTS


def test_stopping_prevents_any_further_reconnection():
    async def scenario():
        server = FakeIntelliCenter()
        port = await server.start()
        handler = Events(make_controller(port), timeBetweenReconnects=1)
        await handler.start()
        assert await wait_for(lambda: "started" in handler.events)
        handler.stop()
        connections = server.connections
        server.drop()
        await asyncio.sleep(1.5)
        assert server.connections == connections, "stopped handler must stay stopped"
        await server.stop()
    run(scenario)
