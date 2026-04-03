"""Constants for Lumina Feeds integration."""

DOMAIN = "lumina_feeds"

CONF_INTERESTS = "interests"
CONF_STOCKS = "stocks"
CONF_NEWS_INTERVAL = "news_interval"
CONF_STOCK_INTERVAL = "stock_interval"

DEFAULT_NEWS_INTERVAL = 30
DEFAULT_STOCK_INTERVAL = 15

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?q={query}&hl={lang}&gl={region}&ceid={region}:{lang}"

# v8 chart API — more reliable, doesn't require auth cookies
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d&includePrePost=false"

# Yahoo Finance search/autocomplete API
YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=8&newsCount=0&listsCount=0"
