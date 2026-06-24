import pandas as pd
import asyncio
from data_configs import NEWS_FEEDS, SECTOR_INDUSTRY_MAP, SECTOR_KEYS_MAP
from news import (
    RSSNewsFetcher,
    EconomicCalendarFetcher,
    TickerEarningsDatesFetcher,
    TickerNewsFetcher
)
from equity import (
    SectorIndustryLookup,
    IndustryPerformanceFetcher,
    IndustryScreener,
    TickerOfficersFetcher,
    TickerInfoFetcher
)
from price import (
    TickerHistoryFetcher,
    YFinanceWebSocketStreamer
)

# EconomicCalendarFetcher USAGE
# fetcher = EconomicCalendarFetcher(region="US")
# df = fetcher.fetch()
# print(df.head())

# RSSNewsFetcher USAGE
# fetcher = RSSNewsFetcher(NEWS_FEEDS, filter_today=True)
# df = fetcher.fetch()
# print(df.head())

# TickerEarningsDatesFetcher USAGE
# fetcher = TickerEarningsDatesFetcher(ticker="AAPL", limit=20)
# apple_earn_dates = fetcher.fetch()
# print(apple_earn_dates.head())

# TickerNewsFetcher USAGE
# fetcher = TickerNewsFetcher("AAPL", count=20)
# apple_news_df = fetcher.fetch()
# print(apple_news_df.head())

# SectorIndustryLookup USAGE
lookup = SectorIndustryLookup(
    sector_industry_map=SECTOR_INDUSTRY_MAP,
    sector_keys_map=SECTOR_KEYS_MAP
)

sectors_industries_df = lookup.fetch()
print(sectors_industries_df)
sectors_industries_df.to_csv('sectors_industry.csv', index=False)

# IndustryPerformanceFetcher USAGE
# fetcher = IndustryPerformanceFetcher(sectors_industries_df, ['agricultural-inputs'])
# df = fetcher.fetch()
# print(df.head())

# IndustryScreener USAGE
# screener = IndustryScreener(lookup_df=sectors_industries_df)
# banks_df = screener.fetch_industry("Utilities - Regulated Electric")
# print(banks_df.head())

# TickerOfficersFetcher USAGE
# fetcher = TickerOfficersFetcher("AAPL")
# apple_officers_df = fetcher.fetch()
# print(apple_officers_df.head())

# TickerInfoFetcher USAGE
# fetcher = TickerInfoFetcher("AAPL")
# apple_info_df = fetcher.fetch()
# print(apple_info_df.head())

# TickerHistoryFetcher USAGE
# EOD 
# fetcher = TickerHistoryFetcher("MSFT", period="5y")
# day_interval_msft = fetcher.fetch()
# print(day_interval_msft.head())

# # Intraday
# fetcher = TickerHistoryFetcher("MSFT", period="1mo", interval="5m")
# interval_msft = fetcher.fetch()
# print(interval_msft.head())

# YFinanceWebSocketStreamer USAGE
# streamer = YFinanceWebSocketStreamer(["AAPL", "MSFT"])
# # streamer.run(timeout=30)

# # Allows for keyboard interrupt. Closes connection
# async def run_and_stop():
#     task = asyncio.create_task(streamer.stream())
#     await asyncio.sleep(5)  
#     streamer.stop()

#     await task

# asyncio.run(run_and_stop())