<p align="center">
  <img src="Lumina Logo.png" alt="Lumina Feeds" width="400">
</p>

<p align="center">
  Interest-based news and stock market integration for <a href="https://www.home-assistant.io/">Home Assistant</a>.<br>
  Part of the <a href="https://github.com/gabrielozcomidi/lumina-cards">Lumina Cards</a> collection.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Home%20Assistant-2024.1%2B-41BDF5?logo=homeassistant&logoColor=white" alt="Home Assistant">
</p>

## What it does

Define your **interests as keywords** — the integration automatically fetches relevant news from Google News. Add **stock symbols** — it fetches live quotes from Yahoo Finance. No API keys needed.

## Installation

### HACS (Recommended)

1. Open HACS in your HA instance
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/gabrielozcomidi/lumina-feeds` as category **Integration**
4. Search for **Lumina Feeds** and install
5. Restart Home Assistant

### Manual

Copy `custom_components/lumina_feeds/` to your HA `config/custom_components/` directory and restart.

## Configuration

Lumina Feeds is configured through the **Home Assistant UI** — no YAML required.

1. Settings → **Devices & Services** → **Add Integration**
2. Search for **Lumina Feeds**
3. Add your interests (one per line, `Name | keywords` — keywords are comma-separated and OR-combined) and stock symbols
4. Re-open the integration's **Configure** menu any time to add/edit interests, symbols, and scan intervals

Example interests:

```
Smart Home | home assistant, smart home, IoT
Technology | AI, artificial intelligence, tech news
Finance | stock market, crypto, investing
Local News | Tel Aviv
```

You can also paste a direct RSS URL instead of keywords for a specific feed.

Example stock symbols: `AAPL`, `MSFT`, `GOOGL`, `TSLA`, `BTC-USD`, `^GSPC` (S&P 500 index).

## Entities Created

### News Sensors

Each interest creates a sensor:

| Entity | State | Attributes |
|--------|-------|------------|
| `sensor.lumina_feed_smart_home` | "5 articles" | `entries[]` with title, source, published, link |
| `sensor.lumina_feed_technology` | "8 articles" | same |
| `sensor.lumina_feed_finance` | "4 articles" | same |

### Stock Sensors

Each symbol creates a sensor + one summary:

| Entity | State | Key Attributes |
|--------|-------|----------------|
| `sensor.lumina_stock_aapl` | 172.50 | symbol, short_name, change, change_percent, trending, market_state |
| `sensor.lumina_stock_btc_usd` | 67432.10 | same (works for crypto) |
| `sensor.lumina_stocks_summary` | "6 stocks" | stocks[] array with all quotes |

### Stock Attributes

| Attribute | Example |
|-----------|---------|
| `symbol` | AAPL |
| `short_name` | Apple Inc. |
| `regular_market_price` | 172.50 |
| `regular_market_change` | +2.25 |
| `regular_market_change_percent` | +1.32 |
| `trending` | up / down |
| `market_state` | REGULAR / CLOSED / PRE / POST |
| `currency` | USD |

## Use with Lumina Status Card

```yaml
type: custom:ha-lumina-status-card
rss_entity: sensor.lumina_feed_smart_home
stock_entities:
  - sensor.lumina_stock_aapl
  - sensor.lumina_stock_msft
  - sensor.lumina_stock_btc_usd
stock_scroll: true
rss_scroll: true
```

## Interest Configuration

### Keywords

Separate multiple keywords with commas. They're combined with OR logic:
```yaml
keywords: "home assistant, smart home, IoT, Zigbee"
# Becomes: "home assistant OR smart home OR IoT OR Zigbee"
```

### Languages

| Code | Language | Region |
|------|----------|--------|
| `en` | English | US (default) |
| `he` | Hebrew | Israel |
| `de` | German | Germany |
| `fr` | French | France |
| `es` | Spanish | Spain |
| `it` | Italian | Italy |
| `pt` | Portuguese | Brazil |
| `ja` | Japanese | Japan |
| `ar` | Arabic | Saudi Arabia |
| `ru` | Russian | Russia |

### Stock Symbols

Supports anything Yahoo Finance tracks:
- Stocks: `AAPL`, `MSFT`, `TSLA`
- ETFs: `SPY`, `QQQ`, `VOO`
- Indices: `^GSPC` (S&P 500), `^DJI` (Dow Jones), `^IXIC` (NASDAQ)
- Crypto: `BTC-USD`, `ETH-USD`, `SOL-USD`
- Forex: `EURUSD=X`, `GBPUSD=X`

## Data Sources

- **News**: [Google News RSS](https://news.google.com/) — free, no API key
- **Stocks**: [Yahoo Finance](https://finance.yahoo.com/) — free public API, no key

## License

MIT
