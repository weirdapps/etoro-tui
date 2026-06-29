# tests/test_clients_price_stream.py
import asyncio
import json

import pytest
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from etoro_tui.clients.price_stream import EtoroPriceStream, ws_content_to_rate

# ---------------------------------------------------------------------------
# ws_content_to_rate — pure adapter
# ---------------------------------------------------------------------------

_SNAPSHOT = {
    "InstrumentID": "100000",
    "Ask": "100.5",
    "Bid": "100.4",
    "LastExecution": "100.45",
    "ConversionRateAsk": "1.1",
    "ConversionRateBid": "1.1",
    "Date": "2026-06-29T15:43:05Z",
}
_DELTA_PRICE = {
    "Ask": "101.0",
    "Bid": "100.9",
    "LastExecution": "100.95",
    "Date": "2026-06-29T15:43:06Z",
}
_DELTA_PRICELESS = {"Date": "2026-06-29T15:43:07Z", "PriceRateID": "999"}


def test_adapter_snapshot_produces_rest_camelcase_floats():
    out = ws_content_to_rate(_SNAPSHOT, None)
    assert out["lastExecution"] == 100.45
    assert out["ask"] == 100.5
    assert out["bid"] == 100.4
    assert out["conversionRateAsk"] == 1.1
    assert out["conversionRateBid"] == 1.1
    assert out["date"] == "2026-06-29T15:43:05Z"


def test_adapter_delta_keeps_conversion_rate_from_prev():
    prev = ws_content_to_rate(_SNAPSHOT, None)
    out = ws_content_to_rate(_DELTA_PRICE, prev)
    assert out["lastExecution"] == 100.95  # updated by delta
    assert out["conversionRateAsk"] == 1.1  # retained from snapshot (delta has no FX)


def test_adapter_priceless_frame_retains_prev_price():
    prev = ws_content_to_rate(_SNAPSHOT, None)
    out = ws_content_to_rate(_DELTA_PRICELESS, prev)
    assert out["lastExecution"] == 100.45  # unchanged
    assert out["conversionRateAsk"] == 1.1
    assert out["date"] == "2026-06-29T15:43:07Z"  # date advances


def test_adapter_tolerates_unparseable_numeric():
    out = ws_content_to_rate({"Ask": "not-a-number", "Bid": "5"}, None)
    assert "ask" not in out  # bad value skipped
    assert out["bid"] == 5.0


# ---------------------------------------------------------------------------
# EtoroPriceStream — against a local in-process WebSocket server
# ---------------------------------------------------------------------------


async def _wait_until(cond, timeout=3.0):
    loop_end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < loop_end:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return False


def _snapshot_frame(topic: str) -> str:
    content = {
        "InstrumentID": topic.split(":")[1],
        "Ask": "100.5",
        "Bid": "100.4",
        "LastExecution": "100.45",
        "ConversionRateAsk": "1.1",
        "ConversionRateBid": "1.1",
        "Date": "2026-06-29T15:43:05Z",
    }
    return json.dumps(
        {
            "messages": [
                {"topic": topic, "content": json.dumps(content), "id": "s", "type": "Snapshot"}
            ]
        }
    )


def _delta_frame(topic: str) -> str:
    content = {
        "Ask": "101.0",
        "Bid": "100.9",
        "LastExecution": "100.95",
        "Date": "2026-06-29T15:43:06Z",
    }
    return json.dumps(
        {
            "messages": [
                {
                    "topic": topic,
                    "content": json.dumps(content),
                    "id": "d",
                    "type": "Trading.Instrument.Rate",
                }
            ]
        }
    )


class _Server:
    """Local fake eToro WS. Captures client->server messages in `.received`."""

    def __init__(self):
        self.received: list[str] = []
        self.connections = 0
        self.drop_first = False

    async def handler(self, ws):
        self.connections += 1
        drop = self.drop_first and self.connections == 1
        try:
            async for raw in ws:
                self.received.append(raw)
                msg = json.loads(raw)
                op, rid = msg.get("operation"), msg.get("id")
                if op == "Authenticate":
                    await ws.send(
                        json.dumps({"id": rid, "success": True, "operation": "Authenticate"})
                    )
                    if drop:
                        await ws.close()
                        return
                elif op == "Subscribe":
                    await ws.send(
                        json.dumps({"id": rid, "success": True, "operation": "Subscribe"})
                    )
                    for topic in msg["data"]["topics"]:
                        await ws.send(b"\x00")  # binary keepalive — must be ignored
                        await ws.send(_snapshot_frame(topic))
                        await ws.send(_delta_frame(topic))
                elif op == "Unsubscribe":
                    await ws.send(
                        json.dumps({"id": rid, "success": True, "operation": "Unsubscribe"})
                    )
        except ConnectionClosed:
            pass  # client closed mid-exchange (e.g. test teardown) — expected


async def _start_server(srv: _Server):
    server = await serve(srv.handler, "localhost", 0)
    port = server.sockets[0].getsockname()[1]
    return server, f"ws://localhost:{port}"


@pytest.mark.asyncio
async def test_stream_auth_subscribe_and_store():
    srv = _Server()
    server, url = await _start_server(srv)
    stream = EtoroPriceStream("pk", "uk", url=url, backoff_seconds=(0,))
    try:
        await stream.start()
        await stream.set_instruments({100000})
        assert await _wait_until(
            lambda: stream.latest().get(100000, {}).get("lastExecution") == 100.95
        )
        rate = stream.latest()[100000]
        assert rate["conversionRateAsk"] == 1.1  # snapshot FX retained over delta
        assert stream.is_connected() is True
        # auth used apiKey=public_key, userKey=user_key
        auth = json.loads(srv.received[0])
        assert auth["data"]["apiKey"] == "pk"
        assert auth["data"]["userKey"] == "uk"
    finally:
        await stream.aclose()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_stream_unsubscribe_drops_store_entry():
    srv = _Server()
    server, url = await _start_server(srv)
    stream = EtoroPriceStream("pk", "uk", url=url, backoff_seconds=(0,))
    try:
        await stream.start()
        await stream.set_instruments({100000, 1005})
        assert await _wait_until(lambda: 1005 in stream.latest() and 100000 in stream.latest())
        await stream.set_instruments({1005})
        assert await _wait_until(lambda: 100000 not in stream.latest())
        # Server-side receipt is a separate async event from the client store-pop.
        assert await _wait_until(
            lambda: any('"Unsubscribe"' in m and "instrument:100000" in m for m in srv.received)
        )
    finally:
        await stream.aclose()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_stream_reconnects_after_drop():
    srv = _Server()
    srv.drop_first = True
    server, url = await _start_server(srv)
    stream = EtoroPriceStream("pk", "uk", url=url, backoff_seconds=(0,))
    try:
        await stream.start()
        await stream.set_instruments({100000})
        assert await _wait_until(lambda: 100000 in stream.latest(), timeout=4.0)
        assert srv.connections >= 2  # dropped once, reconnected and re-subscribed
    finally:
        await stream.aclose()
        server.close()
        await server.wait_closed()
