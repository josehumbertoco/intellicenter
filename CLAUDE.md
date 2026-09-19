# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A Home Assistant custom integration (HACS) for Pentair IntelliCenter pool
controllers. It holds one long-lived TCP connection to the controller on port
6681 and receives push notifications — `iot_class` is `local_push`, so nothing
polls and entities set `_attr_should_poll = False`.

There are no dependencies beyond Home Assistant itself (`"requirements": []`)
and no build step.

**Run the testbench after any change:**

```bash
python3 tests/run.py          # 133 checks, no dependencies, ~15s
python3 tests/run.py -v       # name every check
python3 tests/run.py protocol # only modules matching "protocol"
```

It needs nothing installed — not even Home Assistant. `tests/_stubs/` stands in
for the Home Assistant APIs the integration imports, and
`tests/fake_intellicenter.py` is a fake controller speaking the real wire
protocol over a real socket, which can also go silent, lag or hang up on
demand. See `tests/README.md`. The stubs cannot catch a breaking change in a
Home Assistant API, so a real deployment is still the final word.

CI runs the testbench (`.github/workflows/tests.yaml`) and `hassfest`
(`.github/workflows/hassfest.yaml`).

`pyintellicenter` imports nothing from Home Assistant, so it can be imported and
exercised directly from `custom_components/intellicenter/`.

Style is enforced by `.pre-commit-config.yaml` (black, flake8, isort). `setup.cfg`
holds the flake8 and isort settings — line length 88, E501 ignored, imports
grouped and sorted with `force_sort_within_sections`.

## Layout

```
custom_components/intellicenter/
  __init__.py       setup/unload, the Handler subclass, and PoolEntity (the base
                    class every platform entity derives from)
  const.py          DOMAIN and two unit strings
  config_flow.py    user + zeroconf flows; probes the host with a BaseController
  diagnostics.py    dumps every tracked pool object and its attributes
  <platform>.py     binary_sensor, cover, light, number, sensor, switch,
                    water_heater — each maps pool objects to entities
  pyintellicenter/  the protocol library, independent of Home Assistant
    attributes.py   every known OBJTYP and attribute name, with comments on what
                    the values mean. The reference for anything protocol related
    protocol.py     asyncio.Protocol: message ids, line framing, flow control
    controller.py   BaseController, ModelController, ConnectionHandler
    model.py        PoolObject and PoolModel — the local mirror of the system
```

The layering is strict and worth preserving: platforms depend on
`pyintellicenter`, never the other way round, and platforms do not import from
each other. Import constants from `.pyintellicenter` (the package re-exports
them), not from `.pyintellicenter.attributes`, and never through an absolute
`custom_components.intellicenter...` path.

## How it fits together

`async_setup_entry` builds a `PoolModel` with an attributes map — which
attributes to track per object type — then a `ModelController`, then a local
`Handler(ConnectionHandler)` subclass, and registers the handler in
`hass.data[DOMAIN][entry.entry_id]` **before** starting it. Platforms reach the
controller through `hass.data[DOMAIN][entry.entry_id].controller`.

`ConnectionHandler.start()` only spawns a retry task; it does not wait for the
connection. Setup therefore returns `True` even if the system is unreachable,
and platforms are forwarded later from `Handler.started()`, once the model has
loaded. This is deliberate — do not "fix" it into raising `ConfigEntryNotReady`
without a reason.

Updates flow: `NotifyList` → `ModelController._applyUpdates` → `PoolModel`
mutated → `_updatedCallback` → a dispatcher signal → `PoolEntity._update_callback`
→ `async_write_ha_state` if `isUpdated()` says the entity cares. Connection
state flows over a second dispatcher signal and drives `_attr_available`.

## Protocol quirks that will bite you

These are properties of the IntelliCenter, not of this code. Most of the bugs
in this repository's history come from forgetting one of them.

- **An undefined attribute is reported with the key as its value** — `"ACT": "ACT"`
  means "no value", not a state. `prune()` in `controller.py` strips these and is
  applied on both the initial object load and every update. Anything reading an
  attribute must therefore handle `None`: `obj[SOME_ATTR]` returns `None` freely,
  including for `SNAME` and `BODY`. Guard before `.split()`, `float()` or string
  concatenation.
- **Error responses come back with a messageID that does not match the request.**
  This is why `protocol.py` does not rely on message ids for flow control, and
  why a request that fails never resolves its future. The keepalive timeout is
  what eventually unblocks that case.
- **Only one request may be on the wire at a time.** `ICProtocol.sendRequest`
  queues anything sent while a response is outstanding; `responseReceived()`
  releases the next one. A response that never arrives stalls the queue, so
  anything that can swallow a response is a liveness bug, not a latency bug.
- **Large queries choke the parser.** `ModelController.start()` splits the
  subscription into batches of ~50 attributes. Do not raise that number casually.
- **Messages are `\r\n` delimited and arbitrarily split across TCP segments**,
  possibly mid UTF-8 character. `data_received` handles both; keep it that way.
- **`ping`/`pong` is not supported on firmware 1.064 and later.** It was removed
  in `429759b`. Liveness is checked by `BaseController._keepAliveLoop`, which
  sends an ordinary `GetParamList` once the connection has been silent for
  `KEEPALIVE_INTERVAL` and closes the transport if nothing comes back within
  `KEEPALIVE_TIMEOUT`. It keys off `_lastActivity`, refreshed in
  `receivedMessage`: probing unconditionally would queue the probe behind the
  model-loading burst on a large system and time out on a healthy connection.
  Do not reintroduce a raw `ping`: unanswered, it also corrupts the
  flow-control counter.
- **Writes and reads are not always the same attribute.** Setting a light effect
  writes `ACT` but the current effect is read from `USE`. This asymmetry is
  correct — see `light.py`.
- **`PUMP` objects use `"10"`/`"4"` for on/off**, everything else uses
  `"ON"`/`"OFF"`. Use `PoolObject.onStatus` / `offStatus` rather than literals.

## The attribute map decides what exists

`async_setup_entry` builds `attributes_map`, which is handed to `PoolModel` and
does two separate jobs. Both are easy to get wrong:

1. **It is an allow-list of object types.** `PoolModel.addObject` silently drops
   any object whose `OBJTYP` is not a key in the map. A platform looking for a
   type that is missing from it finds nothing and creates no entities, with no
   error anywhere. This is exactly how cover support shipped broken: `cover.py`
   searched for `EXTINSTR` objects that the model had already thrown away.
2. **It is the subscription.** The values are the attributes tracked for that
   type, which become the `RequestParamList` subscription. An entity reading an
   attribute that is not in the set gets `None` forever and never updates.

So adding a platform means adding its object type *and* every attribute it
reads to that map. An empty set (`CHEM_TYPE: {}`) is falsy and falls back to the
library's full attribute list for that type.

`test_model.py` guards both halves of this: it reads the real map out of
`async_setup_entry` and asserts every type and attribute the platforms use is
present. Extend it when you add a platform.

## Conventions

- The library uses camelCase (`sendCmd`, `_applyUpdates`, `objnam`); Home
  Assistant code uses snake_case and the `_attr_*` entity properties. Both are
  correct in their own file — match the surrounding code.
- f-strings in log calls throughout, and `_LOGGER.debug` liberally on the
  protocol paths.
- Entity naming: `PoolEntity.name` treats a `name` starting with `+` as a suffix
  appended to the object's `SNAME`, e.g. `"+ (schedule)"` → `"Pump schedule (schedule)"`.
- `unique_id` is `entry_id + objnam`, plus the attribute key when the entity does
  not track `STATUS`. Changing how it is built orphans everyone's existing
  entities — don't.
- Service calls go through `PoolEntity.requestChanges`, which sends with
  `waitForResponse=False` and lets the resulting notification update the state.
  Do not optimistically write state.
- New entity types that the user may not want default to
  `enabled_by_default=False` (schedules and vacation mode do).

## Working here

This integration runs against hardware that cannot be simulated, in people's
homes, and much of it is written defensively against a controller that reports
things inconsistently. Treat unusual-looking code as load-bearing until the git
history says otherwise — `git log -p --follow <file>` is genuinely useful here,
and several apparent bugs are documented workarounds.

Prefer narrow, well-understood fixes. When a change alters what an entity
reports (a state that used to read `off` now reading `unknown`, say), say so in
`CHANGELOG.md`, because it will land in someone's automations.
