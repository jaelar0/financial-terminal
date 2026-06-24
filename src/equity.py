import pandas as pd
import yfinance as yf
from yfinance import EquityQuery
from typing import Dict, List, Optional

class SectorIndustryLookup:
    def __init__(
        self,
        sector_industry_map: Dict[str, List[str]],
        sector_keys_map: Dict[str, str],
        accepted_sector_keys: List[str] | None = None,
    ):
        # --------------
        # All parameters (sector_industry_map, sector_keys_map, accepted_sector_keys) come from .data_configs
        # --------------

        self.sector_industry_map = sector_industry_map
        self.sector_keys_map = sector_keys_map
        self.accepted_sector_keys = accepted_sector_keys or list(sector_keys_map.keys())

    @staticmethod
    def _clean_industry_name(series: pd.Series) -> pd.Series:
        # Replace long dash for joins later
        return series.str.replace(r"[–—]", " - ", regex=True)

    def _build_base_lookup(self) -> pd.DataFrame:
        # Build base with dictionaries in .data_configs (source: yfinance)
        sector_keys_df = pd.DataFrame(
            [
                {"sector_key": sector_key, "sector_name": sector_name}
                for sector_key, sector_name in self.sector_keys_map.items()
            ]
        )

        sector_industries_df = pd.DataFrame(
            [
                {"sector_name": sector_name, "industry_name": industry_name}
                for sector_name, industries in self.sector_industry_map.items()
                for industry_name in industries
            ]
        )

        base_lookup = sector_keys_df.merge(
            sector_industries_df,
            on="sector_name",
            how="left",
        )

        base_lookup["industry_join_name_key"] = self._clean_industry_name(base_lookup["industry_name"])
        return base_lookup

    def _fetch_yfinance_industries(self) -> pd.DataFrame:
        # Fetching fields not listed in dictionaries from yfinance
        industries_list = []

        for sector_key in self.accepted_sector_keys:
            try:
                sector = yf.Sector(sector_key)
                sector_industries = pd.DataFrame(sector.industries.name).reset_index()
                sector_industries["industry_name"] = self._clean_industry_name(
                    sector_industries["name"]
                )
                industries_list.append(sector_industries)

            except Exception as e:
                print(f"[ERROR] Failed to fetch industries for sector_key={sector_key}: {e}")

        if not industries_list:
            return pd.DataFrame(columns=["industry_key", "industry_name"])

        industries_df = (
            pd.concat(industries_list, ignore_index=True)
            .rename(columns={"key": "industry_key", "name": "industry_join_name_key"})
        )

        return industries_df[["industry_key", "industry_join_name_key"]].drop_duplicates()

    def fetch(self) -> pd.DataFrame:
        # returning clean dataframe for lookups
        base_lookup = self._build_base_lookup()
        yf_industries = self._fetch_yfinance_industries()

        final_df = base_lookup.merge(
            yf_industries,
            on="industry_join_name_key",
            how="left",
        )

        return final_df.reset_index(drop=True)
   
class IndustryPerformanceFetcher:
    def __init__(
        self,
        lookup_df: pd.DataFrame,
        industry_keys: Optional[List[str]] = None,
    ):
        # Include 'lookup dataframe' from Sector Industry for Industry Key
        # If no industry_keys provided, get all performance facts for every industry

        self.lookup_df = lookup_df.copy()

        # Filter valid industry keys
        self.lookup_df = self.lookup_df[self.lookup_df["industry_key"].notna()]

        if industry_keys:
            self.lookup_df = self.lookup_df[
                self.lookup_df["industry_key"].isin(industry_keys)
            ]

        self.lookup_df = self.lookup_df.drop_duplicates(subset=["industry_key"])

    def _fetch_single_industry(self, industry_key: str) -> dict:
        # Fetch for single industry
        # 3 Datapoints: Top Companies (Analyst Recommendations), Top Growth Companies, and Top Performing

        try:
            industry = yf.Industry(industry_key, session=None)

            return {

                "top_companies": industry.top_companies.reset_index(),
                "top_growth": industry.top_growth_companies.reset_index(),
                "top_performing": industry.top_performing_companies.reset_index(),
            }

        except Exception as e:
            print(f"[ERROR] Failed for industry_key={industry_key}: {e}")
            return {
                "top_companies": pd.DataFrame(),
                "top_growth": pd.DataFrame(),
                "top_performing": pd.DataFrame(),
            }

    def fetch(self) -> pd.DataFrame:
        # Return single cleaned dataframe of 3 data points
        all_data = []

        for _, row in self.lookup_df.iterrows():
            industry_key = row["industry_key"]
            sector_name = row["sector_name"]
            industry_name = row["industry_name"]

            datasets = self._fetch_single_industry(industry_key)

            for dataset_name, df in datasets.items():
                if df.empty:
                    continue

                df = df.copy()
                df["industry_key"] = industry_key
                df["industry_name"] = industry_name
                df["sector_name"] = sector_name
                df["dataset_type"] = dataset_name

                all_data.append(df)

        if not all_data:
            return pd.DataFrame()

        final_df = pd.concat(all_data, ignore_index=True)

        return final_df

class IndustryScreener:
    def __init__(
        self,
        lookup_df: pd.DataFrame,
        exchanges: Optional[List[str]] = None,
        region: str = "us",
        sort_field: str = "eodvolume",
        sort_asc: bool = False,
        count: int = 250,
        size: int = 250,
    ):
        # Should enter Industry Lookup dataframe
        # Parameters should be left empty, but can be tweaked with if needed
        self.lookup_df = lookup_df.copy()
        self.exchanges = exchanges or ["NMS", "NYQ"]
        self.region = region
        self.sort_field = sort_field
        self.sort_asc = sort_asc
        self.count = count
        self.size = size

        if "industry_name" not in self.lookup_df.columns:
            raise ValueError("lookup_df must contain an 'industry_name' column")

        # Preserve the exact original name BEFORE cleaning — EquityQuery("eq", ["industry", …])
        # requires the string to match yfinance's SECTOR_INDUSTY_MAPPING verbatim
        # (e.g. "Oil & Gas Midstream", "Banks—Diversified").
        self.lookup_df["_industry_name_original"] = self.lookup_df["industry_name"].copy()

        # Cleaned name (spaces → "--") is used only for internal row-matching.
        self.lookup_df["industry_name"] = self._clean_industry_name(
            self.lookup_df["industry_name"]
        )

    @staticmethod
    def _clean_industry_name(value):
        # Normalise display names for internal matching only (not for API queries).
        # Replaces spaces with "--" so "Oil & Gas Midstream" → "Oil--&--Gas--Midstream"
        # for consistent lookup_df key matching.
        if isinstance(value, pd.Series):
            return value.str.replace(r"[ - ]", "--", regex=True).str.strip()
        if isinstance(value, str):
            return pd.Series([value]).str.replace(r"[ - ]", "--", regex=True).str.strip().iloc[0]
        return value

    def _get_lookup_row(self, industry_name: str) -> pd.Series:
        # Get lookup Industry Name
        industry_name = self._clean_industry_name(industry_name)

        matched = self.lookup_df[
            self.lookup_df["industry_name"].eq(industry_name)
        ].drop_duplicates(subset=["industry_name"])

        if matched.empty:
            raise ValueError(f"Industry name not found in lookup_df: {industry_name}")

        return matched.iloc[0]

    def _build_query(self, original_industry_name: str) -> EquityQuery:
        """
        Build the EquityQuery for a screener call.

        ``original_industry_name`` must be the verbatim string from
        yfinance's SECTOR_INDUSTY_MAPPING (e.g. "Oil & Gas Midstream",
        "Banks—Diversified").  Any other format is rejected by EquityQuery.
        """
        return EquityQuery(
            "and",
            [
                EquityQuery("is-in", ["exchange", *self.exchanges]),
                EquityQuery("eq", ["industry", original_industry_name]),
                EquityQuery("eq", ["region", self.region]),
            ],
        )

    @staticmethod
    def _flatten_response(response) -> pd.DataFrame:
        # Flattening quote data
        df_response = pd.DataFrame(response)

        if df_response.empty or "quotes" not in df_response.columns:
            return pd.DataFrame()

        payload_df = (
            df_response["quotes"]
            .apply(lambda d: d if isinstance(d, dict) else {})
            .apply(pd.Series)
        )

        return payload_df.reset_index(drop=True)

    def fetch_industry(self, industry_name: str) -> pd.DataFrame:
        # Fetching for a single industry
        lookup_row = self._get_lookup_row(industry_name)

        # Retrieve the original display name saved before cleaning.
        # This is the verbatim string EquityQuery requires.
        original_name = (
            lookup_row["_industry_name_original"]
            if "_industry_name_original" in lookup_row.index
            else str(lookup_row["industry_name"]).replace("--", " ")  # safe fallback
        )

        query = self._build_query(original_name)
        response = yf.screen(
            query,
            sortField=self.sort_field,
            sortAsc=self.sort_asc,
            count=self.count,
            size=self.size,
        )

        payload_df = self._flatten_response(response)

        if payload_df.empty:
            return payload_df

        payload_df["industry_name"] = lookup_row["industry_name"]

        if "sector_name" in lookup_row.index:
            payload_df["sector_name"] = lookup_row["sector_name"]

        if "sector_key" in lookup_row.index:
            payload_df["sector_key"] = lookup_row["sector_key"]

        if "industry_key" in lookup_row.index:
            payload_df["industry_key"] = lookup_row["industry_key"]

        return payload_df.reset_index(drop=True)

    def fetch_all(self) -> pd.DataFrame:
        # Fetching for all industries in Base Lookup 
        all_results = []

        industries = (
            self.lookup_df["industry_name"]
            .dropna()
            .drop_duplicates()
            .tolist()
        )

        for industry_name in industries:
            try:
                df = self.fetch_industry(industry_name)
                if not df.empty:
                    all_results.append(df)
            except Exception as e:
                print(f"[ERROR] Failed for industry_name={industry_name}: {e}")

        if not all_results:
            return pd.DataFrame()

        return pd.concat(all_results, ignore_index=True)
    
class TickerOfficersFetcher:
    def __init__(self, ticker: str):
        # Requiring Ticker
        self.ticker = ticker.upper().strip()

    def _get_ticker_object(self):
        # yfinance ticker object
        return yf.Ticker(self.ticker)

    @staticmethod
    def _format_numeric_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        # Utils for cleaning data
        existing_cols = [col for col in columns if col in df.columns]

        if existing_cols:
            df[existing_cols] = (
                df[existing_cols]
                .fillna(0)
                .astype(int)
                .astype(str)
                .replace("0", "-")
            )

        return df

    def fetch(self) -> pd.DataFrame:
        # Fetching and cleaning final Officer dataframe
        try:
            ticker_obj = self._get_ticker_object()
            info = ticker_obj.info

            officers = info.get("companyOfficers", [])

            if not officers or len(officers) == 0:
                return pd.DataFrame()

            officer_df = pd.DataFrame(officers)

            desired_cols = ["name", "age", "title", "yearBorn", "fiscalYear", "totalPay"]
            existing_cols = [col for col in desired_cols if col in officer_df.columns]
            officer_df = officer_df[existing_cols].copy()

            officer_df = self._format_numeric_columns(
                officer_df,
                columns=["age", "yearBorn", "totalPay"]
            )

            officer_df["ticker"] = self.ticker

            return officer_df.reset_index(drop=True)

        except Exception as e:
            print(f"[ERROR] Failed to fetch officers for ticker={self.ticker}: {e}")
            return pd.DataFrame()

class TickerInfoFetcher:
    def __init__(self, ticker: str, fields: Optional[List[str]] = None):
       # Requiring Ticker but allowing for additional fields if needed
        self.ticker = ticker.upper().strip()

        self.fields = fields or [
            "symbol",
            "longName",
            "website",
            "industry",
            "industryKey",
            "sector",
            "sectorKey",
            "longBusinessSummary",
            "fullTimeEmployees",
        ]

    def _get_ticker_object(self):
        return yf.Ticker(self.ticker)

    def fetch(self) -> pd.DataFrame:
       # Fetching company Information
        try:
            ticker_obj = self._get_ticker_object()
            info = ticker_obj.info

            if not info:
                return pd.DataFrame()

            # Extract only selected fields if present
            data = {
                field: info.get(field)
                for field in self.fields
                if field in info
            }

            df = pd.DataFrame(data, index=[0])

            # Add ticker explicitly (in case symbol missing)
            df["ticker"] = self.ticker

            return df.reset_index(drop=True)

        except Exception as e:
            print(f"[ERROR] Failed to fetch info for ticker={self.ticker}: {e}")
            return pd.DataFrame()