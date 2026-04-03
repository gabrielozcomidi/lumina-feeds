"""Constants for Lumina Feeds integration."""

DOMAIN = "lumina_feeds"

CONF_INTERESTS = "interests"
CONF_STOCKS = "stocks"
CONF_KEYWORDS = "keywords"
CONF_SYMBOLS = "symbols"
CONF_LANGUAGE = "language"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 30  # minutes for news
DEFAULT_STOCK_SCAN_INTERVAL = 15  # minutes for stocks
DEFAULT_LANGUAGE = "en"

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?q={query}&hl={lang}&gl={region}&ceid={region}:{lang}"

YAHOO_FINANCE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"
