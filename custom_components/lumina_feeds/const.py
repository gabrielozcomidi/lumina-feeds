"""Constants for Lumina Feeds integration."""

DOMAIN = "lumina_feeds"

CONF_INTERESTS = "interests"
CONF_STOCKS = "stocks"
CONF_NEWS_INTERVAL = "news_interval"
CONF_STOCK_INTERVAL = "stock_interval"

DEFAULT_NEWS_INTERVAL = 30
DEFAULT_STOCK_INTERVAL = 15

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?q={query}&hl={lang}&gl={region}&ceid={region}:{lang}"
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"
