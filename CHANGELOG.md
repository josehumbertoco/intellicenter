# Changelog

All notable changes to this integration are documented here.

## 2.1.1 - 2026-09-22

### Fixes

- **Replaced the deprecated `CONCENTRATION_PARTS_PER_MILLION` constant** used by
  the IntelliChlor salt sensor with `UnitOfRatio.PARTS_PER_MILLION`. Home
  Assistant logged a deprecation warning for it and removes the old constant in
  2027.8. Older Home Assistant releases without `UnitOfRatio` fall back to the
  old constant. The unit string is still `ppm`, so the sensor, its history and
  its statistics are unaffected.

### Housekeeping

- `manifest.json` (`codeowners`, `documentation`, `issue_tracker`) and the
  README now point at this fork, `josehumbertoco/intellicenter`.

## 2.1.0 - 2026-09-19

Bug fixes and robustness work across the connection layer and the entity
platforms. No configuration changes are needed and no entities are renamed or
removed, so upgrading is a drop-in replacement.

### Connection stability

- **Added a keepalive.** The protocol layer documented a `ping`/`pong`
  heartbeat, but it had been removed because firmware 1.064 stopped answering
  the raw `ping` string. Nothing replaced it, so a connection that died without
  the socket noticing (system reboot, Wi-Fi drop, a NAT entry expiring) left the
  integration "connected" to a dead socket indefinitely: no updates arrived and
  no reconnection was ever attempted. `BaseController` now probes the system
  with a regular `GetParamList` request once the connection has been silent for
  30s, and closes the connection if no answer comes back within a further 30s,
  which hands over to the normal reconnect
  path. Being a documented request rather than the raw `ping` string, it works
  across firmware versions. The probe is only sent once the connection has been
  silent for the interval — anything received is already proof it is alive — so
  it adds no traffic to a busy system and cannot queue up behind the burst of
  requests that loads the model of a large installation. Tune
  `KEEPALIVE_INTERVAL` / `KEEPALIVE_TIMEOUT` in `pyintellicenter/controller.py`
  if your system needs more slack.
- **Fixed messages being delayed or lost when split across TCP segments.**
  `data_received` required the *whole* receive buffer to end on `\r\n`. A chunk
  holding a complete message followed by the start of the next one held both
  back, and a trailing partial line that never completed discarded everything
  buffered behind it. Complete lines are now processed as they arrive and only
  the remainder is kept.
- **Fixed corruption of messages containing non-ASCII characters** (accented
  pool or circuit names) when a multi-byte UTF-8 sequence was split across two
  TCP segments. Decoding is now incremental.
- **Fixed `AttributeError` when sending a command while disconnected.**
  `BaseController.sendCmd` called a misspelled `setException`. Commands sent
  without waiting for a response are now logged when they have to be dropped
  instead of disappearing silently.
- **Fixed response futures being created against the wrong event loop.** They
  are now created from the controller's own loop rather than whatever
  `asyncio.get_event_loop()` happened to return.
- **Capped the reconnection backoff at 300s.** It grew by a factor of 1.5
  without limit, so a system that stayed unreachable for a while could end up
  with an hours-long retry delay and would not be picked up promptly when it
  came back.
- **Fixed duplicate reconnection loops.** A disconnection reported while a
  reconnection was already in progress started a second loop, ending up with two
  connections to the system.
- Pending requests are now dropped on disconnection instead of accumulating
  across reconnections, the send queue is drained when the connection is lost,
  writes to a closed transport no longer raise, and a late answer to a request
  that already timed out is ignored rather than raising `InvalidStateError`.

- **Fixed reconnection being disabled for good when the link dropped during the
  handshake.** The disconnection handler logged `controller.systemInfo`, which
  does not exist until the handshake completes. The resulting `AttributeError`
  escaped out of `connection_lost` *before* the reconnection was scheduled, so
  a drop at that moment left the integration dead until Home Assistant was
  restarted. The handler now copes with a system it never finished identifying,
  and the connection callbacks are invoked defensively so that a failure in one
  can never again stop the reconnection from being scheduled.

### Entities that were never created

- **Fixed pool covers never appearing.** The model only keeps object types
  listed in the integration's attribute map, and `EXTINSTR` — the type covers
  use — was never added to it when cover support landed. Every cover object was
  therefore discarded as it arrived and the cover platform, which looks for
  exactly those objects, created nothing. No cover entity has existed since the
  feature was added. Covers are now tracked and appear as cover entities.
  Because this code path has never run against real hardware, please report
  anything that looks wrong about the open/closed state.

### Schedule binary sensor

- **Fixed schedule sensors being stuck off and never updating.** IntelliCenter
  reports an attribute it has no value for by echoing the key as the value
  (`"ACT": "ACT"`). The initial object load stripped those placeholders but the
  update path did not, so the model stored the literal string `"ACT"` as the
  schedule's state and `"ACT" == "ON"` was never true. Updates are now pruned
  the same way as the initial load.
- A schedule whose state is genuinely unknown now reports *unknown* rather than
  *off*, and `VACFLO` no longer shows up as the literal string `"VACFLO"` in the
  entity attributes.
- **Fixed a crash on schedules with no name.** `SNAME` is not always defined;
  building the entity name raised a `TypeError` instead. Entities now fall back
  to the object id.
- `binary_sensor.py` imported the package through absolute
  `custom_components.intellicenter...` paths and pulled two attribute constants
  from the `water_heater` platform; it now uses relative imports from
  `.pyintellicenter` and the shared constants instead of hardcoded strings.

Schedule sensors remain disabled by default — enable them from the entity
registry if you want them.

### Entity platforms

- `water_heater`: a restored state with no recorded last heater stored `None`,
  which `turn_on` would then send to the system as a heater id; reading the
  current or target temperature raised when the system had not reported one yet.
- **`sensor`: temperatures were not converted between unit systems.** The
  sensors overrode `state` directly, which bypasses the conversion Home
  Assistant performs — while still letting it convert the unit *label*. A pool
  reporting Fahrenheit to a metric Home Assistant was displayed as Celsius with
  the Fahrenheit number untouched. They now expose `native_value`, so values
  and units stay consistent and long-term statistics work. Whole numbers are
  kept whole, so readings are displayed exactly as before when the two unit
  systems agree.
- `sensor`: a missing value was reported as the literal state `"None"`, which a
  sensor carrying a device class and a state class cannot interpret; it now
  reports *unknown*. Rounding no longer raises on a non-numeric value.
- `water_heater`: a heater with no name put `None` into the operation list,
  which the frontend cannot render; it now falls back to the object id.
- `number`: the IntelliChlor output percentage was handed to `NumberEntity` as a
  string instead of a number.
- `light`: a light show whose member circuit is missing from the model no longer
  crashes platform setup.
- `binary_sensor`, `water_heater`, `number`: heaters and IntelliChlor units that
  do not report a `BODY` attribute no longer crash platform setup.
- `PoolEntity` had a mutable default argument for its extra state attributes.

### Surviving a system that misbehaves

These paths all ended in `start()` raising, which the reconnection loop then
retried forever without ever being able to succeed — the integration would stay
broken with only a terse message in the log.

- A system that omits one of the four attributes read during the handshake
  (`PROPNAME`, `VER`, `MODE`, `SNAME`) no longer prevents the integration from
  connecting. The config entry's unique id is unchanged whenever `SNAME` is
  reported, so existing installations keep their entities.
- A single object arriving without an `OBJTYP` no longer aborts loading the
  whole model; it is skipped and the rest load normally.
- Likewise a malformed entry inside a response is skipped rather than failing
  the batch it arrived in.
- The receive buffer is capped, so a peer that never sends a message delimiter
  cannot grow it without bound.

### Integration setup

- `async_unload_entry` ignored the result of unloading the platforms and always
  reported success, and raised `KeyError` if setup had not completed. It now
  uses `async_unload_platforms` and reports the real result.
- The connection handler is registered before it is started, so platform setup
  cannot race ahead of it.
- The config flow now times out after 30s instead of hanging forever on a host
  that accepts the connection but never answers, and reports "cannot connect"
  for any connection error rather than only for a refused connection.
- The zeroconf flow could abort with `cannot_connect` or `unknown`, neither of
  which was declared in `strings.json`, so the user was shown the raw key
  instead of a message. Also fixed an "alreay configured" typo.
- Dropped `CONNECTION_CLASS`, which Home Assistant has ignored since config
  flows stopped using connection classes. `iot_class` in `manifest.json` is the
  replacement and already says `local_push`. It was an import that could only
  break on a future upgrade.
- Removed unused imports that fail the repository's own flake8 pre-commit hook.
- `cover` was missing from the `domains` list in `hacs.json`.

### Testing

- Added a testbench under `tests/`, covering the wire protocol, the model, the
  controller, the connection lifecycle, every entity platform, every service
  call, the config flow, setup and unload, and a robustness suite that throws
  malformed and random input at the protocol. It needs no dependencies — not
  even Home Assistant — and runs with `python3 tests/run.py`. CI runs it on
  every push alongside `hassfest`. See `tests/README.md`.

### Library

- **Debug logging can now be turned on for the controller.** It pinned its own
  logger to `INFO` at import, which overrode whatever level was configured for
  the integration in Home Assistant's `logger:` block, so its debug output could
  never be seen.
- `getHardwareDefinition` never awaited its query and returned unpruned data.
- `pyintellicenter.__all__` listed objects instead of names, so
  `from pyintellicenter import *` raised `TypeError`.
