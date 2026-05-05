# eToro Public API — Actual Behavior (Discovered 2026-05-05)

## Summary

The endpoint documentation in `~/SourceCode/trading-marketplace/plugins/etoro-trading/shared/etoro-api/endpoints.md` is **wrong**. This file documents what the live API actually returns, discovered by probing with valid credentials.

## Base URL

| Documented (wrong) | Actual |
|---|---|
| `https://api.etoro.com` | **`https://public-api.etoro.com`** |

The wrong host returns generic `{"statusCode":404,"message":"Resource not found"}` for every path — the host is reachable but it's NOT the API host.

## Headers

Same as documented:
- `x-api-key: <PUBLIC_KEY>`
- `x-user-key: <USER_KEY>`
- `x-request-id: <UUID>`
- `Content-Type: application/json`

## Working Endpoints (verified)

### `GET /api/v1/trading/info/portfolio` — main endpoint

Returns ONE blob with everything: positions, cash, orders. There is no separate `/account` endpoint that we can find.

```json
{
  "clientPortfolio": {
    "positions": [
      {
        "positionID": 0,
        "CID": 0,
        "openDateTime": "2026-01-01T00:00:00Z",
        "openRate": 215.05,
        "instrumentID": 1005,
        "isBuy": true,
        "takeProfitRate": 0.0,
        "stopLossRate": 0.0001,
        "amount": 2500.0,
        "leverage": 1,
        "units": 10.0,
        "totalFees": 0.0,
        "initialAmountInDollars": 2500.0
        // ... ~25 other internal fields
      }
    ],
    "credit": 0.00,        // cash available, USD
    "bonusCredit": 0.0,
    "mirrors": [],
    "orders": [],               // pending orders
    "stockOrders": [],
    "entryOrders": [],
    "exitOrders": [],
    "ordersForOpen": [],
    "ordersForClose": [],
    "ordersForCloseMultiple": []
  }
}
```

### `GET /api/v1/watchlists` — also works

Not used by etoro-tui but confirms auth is correct.

## What's MISSING from the API response

The position records do NOT include:
- `symbol` — only `instrumentID` (resolve via census `instruments.details[]`)
- `currentRate` — current price not provided (use census `instruments.priceData[]`)
- `profit` — must compute locally
- `profitPercentage` — must compute locally
- `value` — must compute locally (`units * current_price`)

## Endpoints that DON'T work (verified 404)

All variants of these paths return `{"errorCode":"RouteNotFound"}`:
- `/api/v1/account`, `/api/v1/Equity/{Real,real}`, `/api/v1/Credit/{Real,real}`
- `/api/v1/instruments`, `/api/v1/instruments/{id}`
- `/api/v1/market-data/*`
- `/api/v1/trading/positions`, `/api/v1/trading/info/{equity,balance,account}`
- And ~15 other guesses

The `api-portal.etoro.com` docs reference `/Credit/{System}` and `/Equity/{System}` endpoints but neither responds with our credentials. May be partner-tier only.

## Implications for etoro-tui

1. **Symbol lookup** uses census `instruments.details[]` — we already had this map.
2. **Current price** uses census `instruments.priceData[]` — refreshes daily ~03:00 UTC, so during market hours prices are stale by hours-to-a-day.
3. **P&L computation** is local: `pnl = (current_price - openRate) * units * (1 if isBuy else -1)`.
4. **Equity** is local: `sum(position.value) + credit`.
5. **One fetch per tick** instead of two (no separate /account call).

## Future work

- If we want sub-day pricing, add yfinance as a fallback price source. Would mean ~170 ticker quotes per tick, batch-fetch via `yfinance.download(tickers, period="1d")`.
- The published eToro API may add more endpoints over time. Re-probe quarterly.
