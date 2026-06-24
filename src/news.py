import ssl
import certifi
import urllib.request
import feedparser
import pandas as pd
from datetime import datetime, date
from typing import List
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
# from .data_configs import NEWS_FEEDS ; Initialize in Main

class RSSNewsFetcher:
    def __init__(self, feed_urls: List[str], filter_today: bool = False):
        # - feed_urls: list of RSS URLs; Get from .data_config
        # - filter_today: if True, only return today's news

        self.feed_urls = feed_urls
        self.filter_today = filter_today

    def _parse_feed(self, url: str):
        # parse feed with ssl certification error handler
        try:
            ctx = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(url, context=ctx, timeout=10) as response:
                return feedparser.parse(response.read())

        except Exception:
            print(f"[WARN] SSL failed for {url}, retrying without verification...")

            try:
                ctx = ssl._create_unverified_context()
                with urllib.request.urlopen(url, context=ctx, timeout=10) as response:
                    return feedparser.parse(response.read())
            except Exception as e2:
                print(f"[ERROR] Completely failed for {url}: {e2}")
                return None

    def _extract_entries(self, feed, url: str) -> List[dict]:
        records = []

        source_title = feed.feed.get("title", "Unknown Source")

        for entry in feed.entries:
            record = {
                # Only keeping necessary fields from feed
                "source": source_title,
                "provider_name": entry.get("source", {}).get("title"),
                "feed_url": url,
                "title": entry.get("title"),
                "link": entry.get("link"),
                "published": None,
                "summary": entry.get("summary"),
            }

            # Safe datetime parsing
            if "published_parsed" in entry and entry.published_parsed:
                record["published"] = datetime(*entry.published_parsed[:6])

            records.append(record)

        return records

    def fetch(self) -> pd.DataFrame:
        # Returning a clean dataframe 
        all_entries = []

        for url in self.feed_urls:
            try:
                feed = self._parse_feed(url)

                if not feed:
                    continue

                if getattr(feed, "bozo", False):
                    print(f"[WARNING] Issue parsing feed: {url}")
                    print(f"Reason: {feed.bozo_exception}")

                entries = self._extract_entries(feed, url)
                all_entries.extend(entries)

            except Exception as e:
                print(f"[ERROR] Failed to process {url}: {e}")

        df = pd.DataFrame(all_entries)

        if df.empty:
            return df

        # Sort by most recent
        if "published" in df.columns:
            df = df.sort_values(by="published", ascending=False)

            df["published"] = pd.to_datetime(df["published"], errors="coerce")
            df["published_date"] = df["published"].dt.date

        # Optional: filter to today's news
        if self.filter_today:
            today = date.today()
            df = df[df["published_date"] == today]

        return df.reset_index(drop=True)

class EconomicCalendarFetcher:
    def __init__(self, region: str = "US"):
        # Only parameter is Region, by default US
        self.region = region
        self.calendars = yf.Calendars()

    def _get_date_range(self):
        # Get today's date and tomorrow for API range
        today = datetime.today().date()
        tomorrow = today + timedelta(days=1)
        return str(today), str(tomorrow)

    def fetch(self) -> pd.DataFrame:
        # Main calendar fetcher, returns dataframe
        start, end = self._get_date_range()

        df = (
            self.calendars
            .get_economic_events_calendar(start=start, end=end, limit=100)
            .reset_index()
        )

        if df.empty:
            return pd.DataFrame()

        # Rename columns for normalizing
        df = df.rename(columns={
            'Event': 'event_name',
            'Region': 'region_name',
            'For': 'month_for',
            'Actual': 'actual_value',
            'Expected': 'expected_value',
            'Last': 'last_value',
            'Revised': 'revised_value'
        })

        # Filter region
        df = df[df['region_name'] == self.region].copy()

        # Convert datetime
        df['Event Time'] = pd.to_datetime(df['Event Time'], errors='coerce')

        # Sort
        df = df.sort_values('Event Time', ascending=True)

        # Derived columns
        df['event_time_ampm'] = df['Event Time'].dt.strftime('%I:%M %p')
        df['event_date'] = df['Event Time'].dt.date

        # Drop original column
        df = df.drop(columns=['Event Time'])

        # Reset index
        return df.reset_index(drop=True)
    
class TickerEarningsDatesFetcher:
    def __init__(self, ticker: str, limit: int = 20):
       # Must include ticker
        self.ticker = ticker.upper().strip()
        self.limit = limit

    def _get_ticker_object(self):
        # Needed ticker object
        return yf.Ticker(self.ticker)

    def fetch(self) -> pd.DataFrame:
        # Earnings date dataframe, set to return last 20 earnings date including upcoming
        try:
            ticker_obj = self._get_ticker_object()

            df = (
                ticker_obj
                .get_earnings_dates(limit=self.limit)
                .sort_values(by="Earnings Date", ascending=False)
                .reset_index()
            )

            if df.empty:
                return pd.DataFrame()

            df["ticker"] = self.ticker

            if "Earnings Date" in df.columns:
                df["Earnings Date"] = pd.to_datetime(df["Earnings Date"], errors="coerce")
                df["earnings_date"] = df["Earnings Date"].dt.date
                df["earnings_time"] = df["Earnings Date"].dt.strftime("%I:%M %p")

            return df.reset_index(drop=True)

        except Exception as e:
            print(f"[ERROR] Failed to fetch earnings dates for ticker={self.ticker}: {e}")
            return pd.DataFrame()
        
class TickerNewsFetcher:
    def __init__(self, ticker: str, count: int = 20, tab: str = "all"):
        # Requiring Ticker Symbol
        self.ticker = ticker.upper().strip()
        self.count = count
        self.tab = tab

    def _get_ticker_object(self):
        # Grabbing yfinance ticker object
        return yf.Ticker(self.ticker)

    @staticmethod
    def _flatten_news(df: pd.DataFrame) -> pd.DataFrame:
        # Flattening util
        if df.empty or "content" not in df.columns:
            return pd.DataFrame()

        return (
            df["content"]
            .apply(lambda d: d if isinstance(d, dict) else {})
            .apply(pd.Series)
        )

    def fetch(self) -> pd.DataFrame:
        # fetching and cleaning Ticker news
        try:
            ticker_obj = self._get_ticker_object()

            raw_news = pd.DataFrame(
                ticker_obj.get_news(count=self.count, tab=self.tab)
            )

            if raw_news.empty:
                return pd.DataFrame()

            df = self._flatten_news(raw_news)

            if df.empty:
                return df

            # Select relevant columns
            cols = ['id', 'title', 'summary', 'pubDate', 'provider', 'canonicalUrl']
            df = df[[c for c in cols if c in df.columns]].copy()

            # Derived fields
            df["published_date"] = pd.to_datetime(df["pubDate"], errors="coerce").dt.date

            df["provider_name"] = df["provider"].apply(
                lambda d: d.get("displayName") if isinstance(d, dict) else None
            )

            df["news_url"] = df["canonicalUrl"].apply(
                lambda d: d.get("url") if isinstance(d, dict) else None
            )

            # Add ticker context
            df["ticker"] = self.ticker

            # Drop raw nested fields
            df = df.drop(columns=["id", "pubDate", "provider", "canonicalUrl"], errors="ignore")

            return df.reset_index(drop=True)

        except Exception as e:
            print(f"[ERROR] Failed to fetch news for ticker={self.ticker}: {e}")
            return pd.DataFrame()