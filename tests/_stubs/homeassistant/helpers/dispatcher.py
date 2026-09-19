"""Minimal stand-in for homeassistant.helpers.dispatcher."""

_subs = {}


def reset():
    """Drop every subscription (used between tests)."""
    _subs.clear()


def async_dispatcher_connect(hass, signal, target):
    _subs.setdefault(signal, []).append(target)

    def _unsub():
        if target in _subs.get(signal, []):
            _subs[signal].remove(target)

    return _unsub


def async_dispatcher_send(hass, signal, *args):
    for target in list(_subs.get(signal, [])):
        target(*args)
