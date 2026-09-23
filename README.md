# Pentair Intellicenter for Home Assistant

[![hacs][hacsbadge]][hacs]
[![GitHub Release][releases-shield]][releases]

## Installation

### From HACS

1. Install HACS if you haven't already (see [installation guide](https://hacs.netlify.com/docs/installation/manual)).
2. Add custom repository `https://github.com/josehumbertoco/intellicenter` as "Integration" in the settings tab of HACS.
3. Find and install "Pentair Intellicenter" integration in HACS's "Integrations" tab.
4. Restart your Home Assistant.
5. 'Pentair Intellicenter' should appear thru discovery in your Home Assistant Integration's page

### Features

- Connect to a Pentair Intellicenter thru the local (network) interface
- supports Zeroconf discovery
- reconnects itself gracefully in the Intellicenter reboots and/or gets disconnected,
  and checks regularly that the connection is still alive so a connection that died
  without the socket noticing is detected instead of going silently stale
- "Local push" makes system very responsive
- The integration works independently of the security setting on the Intellicenter

### Entities created

- for each body of water (like Pool and Spa) it creates:
    - a switch to turn the body on and off
    - a sensor for the last temperature
    - a sensor for the desired temperature
    - a water heater entity (if applicable):
        - choose a heater from the list to enable it, set to OFF otherwise
        - status is 'OFF', 'IDLE' (if heater is enabled but NOT running) or
          'ON' is the heater is currently running
        Note that the water heater supports turn_on and turn_off operations.
        for turn_on, it will reuse the last heater chosen.
- for each heater, a binary sensor will indicate is the heater is running
  independently of which body is heating
- creates a switch for all circuits marked as "Featured" on the IntelliCenter
  (for example "Cleaner" or "Spa Blower)
- for each light (and light show) it creates a Light entity
  Note that color effects are only supported for IntelliBrite or MagicStream lights
- for each schedule, a binary_sensor will indicate if the schedule is currently running
  Note that these entities are disabled by default, enable them from the entity registry
  A schedule the system reports no state for shows as 'unknown' rather than 'off'
- if the pool has a IntelliChem unit, sensors will be created for
  ph level, ORP level, ph tank level and ORP tank level
- if the pool has an IntelliChlor unit, it creates
  a sensor for the salt level, a switch for "Superchlorinate", and a number entity
  for the output percentage of each body the unit is configured for
- for each pool cover, a cover entity is created
  Note that it reports open/closed based on the cover's "normally on" setting
- a switch controls "Vacation mode". It's disabled by default
- for each pump, a binary_sensor is created
  if the pump supports these features, sensors will reflect power consumption, RPM and GPM
  Note that the power usage is rounded to the nearest 25W to reduced the amount of changes in HA
  Also note that depending on the setting of the pump, RPM or GPM can fluctuate constantly.
- a binary_sensor will indicate if the system is in Freeze prevention mode
- sensors will be created for each sensor in the system (like Water and Air)
  Note that a Solar sensor might also be present even if (like in my case) its value
  is not relevant

### Connection handling

The integration keeps a single TCP connection open to the IntelliCenter and
receives updates as they happen ("local push"), so it does not poll.

- whenever the connection has been silent for 30 seconds it sends a small
  request to confirm the system is still there, and drops and reconnects the
  connection if no answer arrives within a further 30 seconds. Anything
  received counts, so a busy system is never probed. Without this, a connection
  that dies without the socket noticing — a system reboot, a Wi-Fi drop, a
  router dropping an idle NAT entry — would leave the integration silently
  stale, showing values that never change again
- on disconnection, entities are marked unavailable and reconnection is retried
  with an exponential backoff starting at 30 seconds and capped at 5 minutes
- when the connection comes back, entities are re-bound to the pool objects and
  refreshed. Objects removed from the system while disconnected leave their
  entity unavailable
- the timings live in `custom_components/intellicenter/pyintellicenter/controller.py`
  as `KEEPALIVE_INTERVAL`, `KEEPALIVE_TIMEOUT` and `MAX_TIME_BETWEEN_RECONNECTS`.
  Raise the timeout if a busy or slow system produces spurious reconnections
  (they are logged as `no answer from <host> ...`)

### Troubleshooting

Turn on debug logging for the integration and the protocol layer:

```yaml
logger:
  default: warning
  logs:
    custom_components.intellicenter: debug
    custom_components.intellicenter.pyintellicenter: debug
```

The integration also supports Home Assistant's diagnostics download, which dumps
every pool object it tracks and their current attributes — the fastest way to
see what the system actually reports for an entity that looks wrong.

Note that IntelliCenter reports an attribute it has no value for by echoing the
attribute name back as its value (`"ACT": "ACT"`). The integration strips those,
so such an attribute shows as unknown/absent rather than as a state.

### Examples

<img src="device_info.png" width="400"/>

<img src="entities.png" width="400"/>

### Caveats

- while I tried to make the code as robust as possible I could only test using
  my own pool configuration. In particular, I do not have covers, chemistry, cascades,
  multiple heaters, etc... These may work out of the box or not...
- while the choice is metric/english on the Intellicenter is handled, changing it
  while the integration is running can lead to some values being off.
- In general it is recommended to reload the integration where significant changes are done to the pool configuration
- the integration does not create or edit schedules, it only reports whether
  each one is currently running

### Changes

See [CHANGELOG.md](CHANGELOG.md).

[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange
[releases-shield]: https://img.shields.io/github/v/release/josehumbertoco/intellicenter
[releases]: https://github.com/josehumbertoco/intellicenter/releases
