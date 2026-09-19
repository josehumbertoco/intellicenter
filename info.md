# Pentair Intellicenter for Home Assistant



### Features

- Connect to a Pentair Intellicenter thru the local (network) interface
- supports Zeroconf discovery
- reconnects itself gracefully if the Intellicenter reboots and/or gets disconnected,
  and checks regularly that the connection is still alive
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
- for each heater, a binary_sensor will indicate if the heater is running
- creates a switch for all circuits marked as "Featured" on the IntelliCenter
  (for example "Cleaner" or "Spa Blower)
- for each light (and light show) it creates a Light entity
  Note that color effects are only supported for IntelliBrite or MagicStream lights
- for each schedule, a binary_sensor indicates if the schedule is currently running
  Note that these entities are disabled by default
- for each pool cover, a cover entity is created
- if the pool has an IntelliChem or IntelliChlor unit, sensors are created for
  ph, ORP and tank levels, or for the salt level and the output percentage
- a switch controls "Vacation mode". It's disabled by default
- for each pump, a binary_sensor is created
  if the pump supports it, a sensor will reflect how much power the pump uses
- a binary_sensor will indicate if the system is in Freeze prevention mode
- sensors will be created for each sensor in the system (like Water and Air)
  Note that a Solar sensor might also be present even if (like in my case) its value
  is not relevant

### Caveats

- the integration does not create or edit schedules, it only reports whether
  each one is currently running
- while I tried to make the code as generic as possible I could only test using
  my own pool configuration. In particular, I do not have covers, chemistry, cascades,
  solar heater, etc... These may work out of the box or not...
