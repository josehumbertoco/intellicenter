# Testbench

A self-contained bench for the IntelliCenter integration. It needs **no
dependencies at all** — not even Home Assistant — so it runs anywhere Python 3
does, including on Python versions Home Assistant does not yet support.

```bash
python3 tests/run.py            # everything
python3 tests/run.py -v         # name every check as it runs
python3 tests/run.py protocol   # only modules matching "protocol"
```

`pytest tests/` also works if you have it: the tests are plain `test_*`
functions using `assert`, and the async ones drive their own event loop, so no
asyncio plugin is required.

## How it works

Two stand-ins replace what is normally there:

- **`_stubs/homeassistant/`** — the handful of Home Assistant classes and
  constants the integration imports. `Entity` reproduces the `_attr_*`
  convention, so entities are exercised the way Home Assistant drives them.
- **`fake_intellicenter.py`** — a fake controller speaking the real wire
  protocol over a real socket. It reproduces the quirks the integration has to
  live with: responses are `\r\n` delimited while requests carry no delimiter,
  an attribute with no value echoes its own key back (`"ACT": "ACT"`), and a
  write is both acknowledged *and* pushed separately as a `NotifyList`. It can
  misbehave on demand — go silent without closing the socket, add latency, or
  hang up.

The stubs are a convenience, not a substitute for the real thing. They cannot
catch a breaking change in a Home Assistant API. For that, run the integration
against a real Home Assistant, or add
[`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
once it supports the Python version you are on.

## What each module covers

| Module | Covers |
| --- | --- |
| `test_protocol.py` | line framing, messages split across segments, split UTF-8, one-request-at-a-time flow control, teardown |
| `test_model.py` | what the model keeps and drops, placeholder handling, the attribute map being an allow-list |
| `test_controller.py` | requests and responses, futures, pruning, a system that omits handshake attributes |
| `test_connection.py` | startup, pushed changes, reconnection, keepalive, backoff — all over a real socket |
| `test_entities.py` | every platform's entities and properties, including a deliberately degraded system |
| `test_services.py` | what each service call actually puts on the wire |
| `test_config_flow.py` | manual setup, zeroconf, duplicates, timeouts, translation coverage |
| `test_integration.py` | setup and unload, two pools side by side, manifest and translations |
| `test_robustness.py` | malformed messages, random bytes, floods, empty and placeholder-only systems |

## Adding a test

Put a `test_*` function in the matching module and use `assert`. `helpers.py`
has the fixtures:

- `build_controller()` — a controller with the sample system loaded and a fake
  transport, so you can read back what was sent
- `build_hass()` / `setup_platform()` — run a platform's `async_setup_entry`
  and get the entities it built
- `by_object(entities, objnam)` — find the entity for a pool object
- `real_attributes_map()` — the attribute map `async_setup_entry` really
  builds, read from the source so the tests cannot drift from it

Async tests are sync functions that call `asyncio.run(...)`, which keeps them
working under both runners.
