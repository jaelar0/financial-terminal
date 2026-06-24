import pandas as pd
import yfinance as yf
from typing import Callable, List, Optional, Union
import asyncio

class TickerHistoryFetcher:
    def __init__(
        self,
        ticker: str,
        period: str = "1mo",
        interval: Optional[str] = '1d',
        repair: bool = True,
    ):
        # Required Parameters:
        # Ticker
        # Period: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max
        # interval: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo
        # Repair is optional but set to True for most occassions- repairs yfinance price adjustments

        self.ticker = ticker.upper().strip()
        self.period = period
        self.interval = interval
        self.repair = repair

    def _get_ticker_object(self):
        return yf.Ticker(self.ticker)

    def fetch(self) -> pd.DataFrame:
        # Clean dataframe of Price History - for charting
        try:
            ticker_obj = self._get_ticker_object()

            df = ticker_obj.history(
                period=self.period,
                interval=self.interval,
                repair=self.repair,
            ).reset_index()

            if df.empty:
                return pd.DataFrame()

            # Normalize datetime column name
            if "Date" in df.columns:
                df["datetime"] = pd.to_datetime(df["Date"], errors="coerce")
                df = df.drop(columns=["Date"])
            elif "Datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["Datetime"], errors="coerce")
                df = df.drop(columns=["Datetime"])

            # Add metadata
            df["ticker"] = self.ticker
            df["period"] = self.period
            df["interval"] = self.interval if self.interval else "1d"

            return df.reset_index(drop=True)

        except Exception as e:
            print(f"[ERROR] Failed to fetch history for ticker={self.ticker}: {e}")
            return pd.DataFrame()

class YFinanceWebSocketStreamer:
    def __init__(
        self,
        symbols: Union[str, List[str]],
        message_handler: Optional[Callable] = None,
    ):
        self.symbols = symbols if isinstance(symbols, list) else [symbols]
        self.message_handler = message_handler or self._default_message_handler

        self._running = False
        self._ws = None  # store websocket instance

    @staticmethod
    def _default_message_handler(message):
        print("Received message:", message)

    async def stream(
        self,
        max_messages: Optional[int] = None,
        timeout: Optional[int] = None,
    ):
        # should enter max_messages and timeout parameters for safely closing connectin
        # timeout in seconds
        self._running = True
        message_count = 0

        try:
            async with yf.AsyncWebSocket() as ws:
                self._ws = ws
                await ws.subscribe(self.symbols)

                start_time = asyncio.get_event_loop().time()

                while self._running:
                    message = await ws.listen()

                    if message is not None:
                        self.message_handler(message)
                        message_count += 1

                    # Stop conditions
                    if max_messages and message_count >= max_messages:
                        break

                    if timeout:
                        elapsed = asyncio.get_event_loop().time() - start_time
                        if elapsed >= timeout:
                            break

        except Exception as e:
            print(f"[ERROR] WebSocket stream error: {e}")

        finally:
            await self._close_ws()

    async def _close_ws(self):
        # safely closing connection
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            finally:
                self._ws = None
                self._running = False
                print("[INFO] WebSocket closed.")

    def stop(self):
        # Signaling connectino to close
        self._running = False

    def run(self, **kwargs):
        # Runner
        asyncio.run(self.stream(**kwargs))