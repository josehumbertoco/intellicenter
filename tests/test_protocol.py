"""Wire protocol: framing, flow control and teardown."""

import json

from custom_components.intellicenter.pyintellicenter.protocol import (
    MAX_LINE_LENGTH,
    ICProtocol,
)

from helpers import FakeTransport


class Recorder:
    """Stands in for the controller."""

    def __init__(self):
        self.messages = []
        self.lost = []

    def connection_made(self, protocol, transport):
        pass

    def connection_lost(self, exc):
        self.lost.append(exc)

    def receivedMessage(self, msg_id, command, response, msg):
        self.messages.append((msg_id, command, response))


def connected():
    controller = Recorder()
    protocol = ICProtocol(controller)
    transport = FakeTransport()
    protocol.connection_made(transport)
    return controller, protocol, transport


def line(msg_id, **extra):
    return (json.dumps({"messageID": msg_id, "command": "NotifyList", **extra})
            + "\r\n").encode()


def test_complete_line_is_delivered_before_a_partial_one():
    controller, protocol, _ = connected()
    whole, partial = line("1"), line("2")
    protocol.data_received(whole + partial[:10])
    # the old implementation held everything back until the buffer ended on a
    # separator, which delayed this message behind an unrelated partial one
    assert [m[0] for m in controller.messages] == ["1"]
    protocol.data_received(partial[10:])
    assert [m[0] for m in controller.messages] == ["1", "2"]


def test_message_split_byte_by_byte():
    controller, protocol, _ = connected()
    for byte in line("7"):
        protocol.data_received(bytes([byte]))
    assert [m[0] for m in controller.messages] == ["7"]


def test_many_messages_in_one_segment():
    controller, protocol, _ = connected()
    protocol.data_received(b"".join(line(str(i)) for i in range(200)))
    assert [m[0] for m in controller.messages] == [str(i) for i in range(200)]


def test_utf8_sequence_split_across_segments():
    controller, protocol, _ = connected()
    raw = (json.dumps({"messageID": "9", "command": "NotifyList",
                       "sname": "Piscine arrière"}, ensure_ascii=False)
           + "\r\n").encode()
    cut = raw.index("è".encode()) + 1
    protocol.data_received(raw[:cut])
    protocol.data_received(raw[cut:])
    assert [m[0] for m in controller.messages] == ["9"]


def test_undelimited_stream_is_capped():
    _, protocol, _ = connected()
    for _ in range(40):
        protocol.data_received(b"x" * 50_000)
    assert len(protocol._lineBuffer) <= MAX_LINE_LENGTH


def test_only_one_request_on_the_wire_at_a_time():
    _, protocol, transport = connected()
    protocol.sendCmd("GetParamList")
    protocol.sendCmd("GetParamList")
    protocol.sendCmd("GetParamList")
    assert len(transport.written) == 1, "the system chokes on concurrent requests"
    protocol.responseReceived()
    assert len(transport.written) == 2
    protocol.responseReceived()
    assert len(transport.written) == 3


def test_message_ids_are_unique_and_restart_per_connection():
    _, protocol, transport = connected()
    ids = [protocol.sendCmd("GetParamList") for _ in range(5)]
    assert len(set(ids)) == 5
    protocol.connection_made(transport)
    assert protocol.sendCmd("GetParamList") == "1"


def test_requests_carry_no_delimiter():
    _, protocol, transport = connected()
    protocol.sendCmd("GetParamList")
    # firmware 1.064 onwards rejects requests with a trailing CR+LF
    assert not transport.written[0].endswith("\r\n")


def test_teardown_drops_queued_requests_and_never_writes_again():
    controller, protocol, transport = connected()
    protocol.sendCmd("GetParamList")
    protocol.sendCmd("GetParamList")
    protocol.connection_lost(None)
    assert protocol._out_pending == 0 and protocol._out_queue.empty()
    assert controller.lost == [None]
    protocol.sendRequest("late")  # must not raise on a dead transport
    assert len(transport.written) == 1


def test_notifications_do_not_consume_flow_control_credit():
    _, protocol, transport = connected()
    protocol.sendCmd("GetParamList")
    protocol.sendCmd("GetParamList")
    # a push carries no "response" field and must not release the queue
    protocol.data_received(line("0", objectList=[]))
    assert len(transport.written) == 1
    protocol.data_received(
        (json.dumps({"messageID": "1", "command": "SendParamList",
                     "response": "200"}) + "\r\n").encode())
    assert len(transport.written) == 2
