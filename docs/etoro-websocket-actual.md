# eToro WebSocket API — Actual Behavior (verified 2026-06-29)

Live probe against `wss://ws.etoro.com/ws` (read-only: public instrument feed only).
Supersedes the published doc where they conflict.

## Connection & auth
- Endpoint: `wss://ws.etoro.com/ws` (Cloudflare-fronted), no subprotocol.
- Auth message (TEXT): `{"id":<uuid>,"operation":"Authenticate","data":{"userKey":<USER_KEY>,"apiKey":<PUBLIC_KEY>}}`
  - **`apiKey` = public_key (REST `x-api-key`), `userKey` = user_key (REST `x-user-key`).**
  - Success: `{"id":<uuid>,"success":true,"operation":"Authenticate"}` (echoes the request `id`).
  - Failure adds `errorMessage` + `errorCode` (e.g. `Unauthorized`, `InvalidKey`, `TooManyRequests`).

## Framing
- **Client may send TEXT frames only.** A binary frame → `{"success":false,"errorCode":"BinaryMessagesNotSupported"}`.
- The server emits periodic **binary `\x00` keepalive frames** — ignore them; never echo.
- Keepalive from the client: rely on the WS protocol-level ping (control frame), not application data.

## Subscribe / unsubscribe
- `{"id":<uuid>,"operation":"Subscribe","data":{"topics":["instrument:<id>"],"snapshot":true}}`
- `{"id":<uuid>,"operation":"Unsubscribe","data":{"topics":["instrument:<id>"]}}`
- Ack: `{"id":<uuid>,"success":true,"operation":"Subscribe"}`.

## Inbound data
- Envelope: `{"messages":[{"topic":"instrument:<id>","content":<escaped-JSON-string>,"id":<uuid>,"type":<str>}]}`.
- `content` is a **JSON-escaped string** → parse twice.
- `type:"Snapshot"` (sent once on subscribe with `snapshot:true`) — FULL state incl.
  `ConversionRateAsk`, `ConversionRateBid`, `Ask`, `Bid`, `LastExecution`, `OfficialClosingPrice`,
  `DailyClose`, `Date`, `IsMarketOpen`.
- `type:"Trading.Instrument.Rate"` (deltas) — **price-only**, PascalCase: `Ask`, `Bid`,
  `LastExecution`, `Date`, `PriceRateID`. **No ConversionRate.** Some deltas are price-less (`{Date,PriceRateID}`).
- Field casing is **PascalCase** (REST is camelCase). Cadence: BTC ~0.3–1.5 s.

## Implications for etoro-tui
1. The conversion rate (FX) arrives only in the snapshot → the client caches it per instrument
   and merges onto price-only deltas. WS is self-sufficient for FX.
2. Normalize WS PascalCase → REST camelCase so the existing pipeline consumes it unchanged
   (`clients/price_stream.py :: ws_content_to_rate`).
3. REST `fetch_rates` is retained only as a fallback when the socket is down.

## Not covered / future
- `private` topic (real-time position open/close) — not yet used.
- `OfficialClosingPrice`/`DailyClose` could replace the Yahoo prev-close dependency.
