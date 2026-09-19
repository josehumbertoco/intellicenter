"""A fake IntelliCenter that speaks the real wire protocol over a real socket.

It is deliberately faithful to the quirks the integration has to cope with:

- responses are ``\\r\\n`` delimited while requests carry no delimiter at all
- an attribute the system has no value for comes back with the key as its
  value (``"ACT": "ACT"``), which the integration has to prune
- a write is acknowledged *and* separately pushed to every subscriber as a
  ``NotifyList``, which is what actually drives entity state

It can also misbehave on demand: go silent without closing the socket, add
latency, or hang up.
"""

import asyncio
import json

# A small but representative system. Values equal to their key are how
# IntelliCenter reports "no value for this attribute".
DEFAULT_OBJECTS = {
    "_5451": {"OBJTYP": "SYSTEM", "SNAME": "system", "PROPNAME": "Pool House",
              "VER": "1.064", "MODE": "ENGLISH", "VACFLO": "OFF"},
    "B1101": {"OBJTYP": "BODY", "SUBTYP": "POOL", "SNAME": "Pool", "STATUS": "ON",
              "HEATER": "H0001", "HTMODE": "1", "LOTMP": "84", "LSTTMP": "82",
              "VOL": "15000"},
    "B1202": {"OBJTYP": "BODY", "SUBTYP": "SPA", "SNAME": "Spa", "STATUS": "OFF",
              "HEATER": "00000", "HTMODE": "0", "LOTMP": "102", "LSTTMP": "LSTTMP",
              "VOL": "800"},
    "H0001": {"OBJTYP": "HEATER", "SUBTYP": "GENERIC", "SNAME": "Gas Heater",
              "BODY": "B1101 B1202", "LISTORD": "1"},
    "C0001": {"OBJTYP": "CIRCUIT", "SUBTYP": "GENERIC", "SNAME": "Cleaner",
              "STATUS": "OFF", "FEATR": "ON"},
    "C0002": {"OBJTYP": "CIRCUIT", "SUBTYP": "INTELLI", "SNAME": "Pool Light",
              "STATUS": "ON", "USE": "PARTY", "FEATR": "OFF"},
    "C0003": {"OBJTYP": "CIRCUIT", "SUBTYP": "FRZ", "SNAME": "Freeze",
              "STATUS": "OFF", "FEATR": "OFF"},
    "SCH01": {"OBJTYP": "SCHED", "SNAME": "Pump schedule", "ACT": "ON",
              "VACFLO": "OFF"},
    # neither a name nor a reported ACT: both echo the key back
    "SCH02": {"OBJTYP": "SCHED", "SNAME": "SNAME", "ACT": "ACT", "VACFLO": "VACFLO"},
    "PMP01": {"OBJTYP": "PUMP", "SNAME": "Pump", "STATUS": "10", "PWR": "1012",
              "RPM": "2750", "GPM": "GPM"},
    "CHL01": {"OBJTYP": "CHEM", "SUBTYP": "ICHLOR", "SNAME": "Chlorinator",
              "PRIM": "50", "SEC": "20", "SUPER": "OFF", "SALT": "3200",
              "BODY": "B1101 B1202"},
    "SNS01": {"OBJTYP": "SENSE", "SUBTYP": "AIR", "SNAME": "Air", "SOURCE": "71"},
    "COV01": {"OBJTYP": "EXTINSTR", "SUBTYP": "COVER", "SNAME": "Cover",
              "STATUS": "ON", "NORMAL": "ON", "BODY": "B1101"},
}


class FakeIntelliCenter:
    """A scriptable stand-in for the real controller."""

    def __init__(self, objects=None):
        self.objects = {k: dict(v) for k, v in (objects or DEFAULT_OBJECTS).items()}
        self.server = None
        self.writers = []
        self.requests = []
        self.connections = 0
        # knobs for misbehaviour
        self.silent = False      # accept requests, never answer
        self.delay = 0.0         # seconds of latency per response
        self.error_for = set()   # commands to answer with an error code

    # -- lifecycle ---------------------------------------------------------

    async def start(self):
        """Listen on an ephemeral port and return it."""
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self):
        self.drop()
        self.server.close()
        await self.server.wait_closed()

    def drop(self):
        """Hang up on every client without warning."""
        for writer in list(self.writers):
            writer.close()
        self.writers.clear()

    # -- protocol ----------------------------------------------------------

    async def _client(self, reader, writer):
        self.connections += 1
        self.writers.append(writer)
        buf = ""
        decoder = json.JSONDecoder()
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                buf += data.decode()
                # requests are not delimited, decode them back to back
                while buf.strip():
                    buf = buf.lstrip()
                    try:
                        msg, end = decoder.raw_decode(buf)
                    except ValueError:
                        break
                    buf = buf[end:]
                    await self._handle(msg, writer)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            if writer in self.writers:
                self.writers.remove(writer)

    def _params(self, objnam, keys):
        stored = self.objects.get(objnam, {})
        # an attribute with no value echoes its own key
        return {key: stored.get(key, key) for key in keys}

    async def _handle(self, msg, writer):
        self.requests.append(msg)
        if self.silent:
            return
        if self.delay:
            await asyncio.sleep(self.delay)

        command = msg.get("command")
        if command in self.error_for:
            return self.send(writer, {"messageID": msg["messageID"],
                                      "command": "Error", "response": "400"})

        if command in ("GetParamList", "RequestParamList"):
            out = []
            for item in msg.get("objectList", []):
                keys = item["keys"]
                if item["objnam"] == "INCR":
                    wanted = self.objects
                    if "SYSTEM" in msg.get("condition", ""):
                        wanted = {"_5451": self.objects["_5451"]}
                    out += [{"objnam": o, "params": self._params(o, keys)}
                            for o in wanted]
                else:
                    out.append({"objnam": item["objnam"],
                                "params": self._params(item["objnam"], keys)})
            self.send(writer, {"messageID": msg["messageID"],
                               "command": "SendParamList", "response": "200",
                               "objectList": out})

        elif command == "SETPARAMLIST":
            change = msg["objectList"][0]
            self.objects.setdefault(change["objnam"], {}).update(change["params"])
            self.send(writer, {"messageID": msg["messageID"],
                               "command": "WriteParamList", "response": "200",
                               "objectList": [{"objnam": change["objnam"],
                                               "changes": [change]}]})
            # the real system also pushes the change to every subscriber, and
            # that is what actually moves the entity
            self.notify(change["objnam"], change["params"])

        elif command == "GetQuery":
            self.send(writer, {"messageID": msg["messageID"], "command": "SendQuery",
                               "response": "200", "answer": []})
        else:
            self.send(writer, {"messageID": msg["messageID"], "command": "Error",
                               "response": "400"})

    # -- pushing -----------------------------------------------------------

    def send(self, writer, obj):
        writer.write((json.dumps(obj) + "\r\n").encode())

    def notify(self, objnam, params):
        """Push an unsolicited change, the way the real system does."""
        for writer in list(self.writers):
            self.send(writer, {"messageID": "0", "command": "NotifyList",
                               "objectList": [{"objnam": objnam, "params": params}]})

    def set(self, objnam, **params):
        """Change the system's own state and notify subscribers."""
        self.objects.setdefault(objnam, {}).update(params)
        self.notify(objnam, params)
