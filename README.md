# Lumina Feeds

Interest-based news and stock market integration for [Home Assistant](https://www.home-assistant.io/). Part of the [Lumina Cards](https://github.com/gabrielozcomidi/lumina-cards) collection.

![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-41BDF5?logo=homeassistant&logoColor=white)

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

Copy `custom_components/lumina_feeds/` to your HA `config/custom_components/` directory.

## Configuration

Add to your `configuration.yaml`:

```yaml
lumina_feeds:
  scan_interval: 30  # minutes for news (default: 30)

  interests:
    - name: Smart Home
      keywords: "home assistant, smart home, IoT"
    - name: Technology
      keywords: "AI, artificial intelligence, tech news"
    - name: Finance
      keywords: "stock market, crypto, investing"
    - name: Local News
      keywords: "Tel Aviv"
      language: he

  stocks:
    scan_interval: 15  # minutes for stocks (default: 15)
    symbols:
      - AAPL
      - MSFT
      - GOOGL
      - TSLA
      - BTC-USD    # crypto
      - ^GSPC      # S&P 500 index
```

Restart Home Assistant after adding the configuration.

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
