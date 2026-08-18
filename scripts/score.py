#!/usr/bin/env python3
"""Refresh adjusted daily prices and recompute methodology-v1 performance."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


HORIZONS = {"6m": 182, "12m": 365}
BULLISH = {"STRONG_BUY", "BUY"}
BEARISH = {"SELL", "STRONG_SELL"}
MARKET_TIMEZONE = ZoneInfo("America/New_York")
USER_AGENT = "EquityTrackRecord/1.0 (+public-methodology)"


@dataclass(frozen=True)
class PriceSeries:
    prices: dict[date, float]
    source: str
    dividend_adjusted: bool


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def http_text(url: str, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"price download failed: {last_error}")


def yahoo_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def fetch_yahoo(ticker: str, start: date, end: date) -> PriceSeries:
    period1 = int(datetime.combine(start, wall_time.min, tzinfo=timezone.utc).timestamp())
    period2 = int(datetime.combine(end + timedelta(days=2), wall_time.min, tzinfo=timezone.utc).timestamp())
    symbol = urllib.parse.quote(yahoo_symbol(ticker), safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={period1}&period2={period2}&interval=1d&events=div%2Csplits"
    payload = json.loads(http_text(url))
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    adjclose = ((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    prices: dict[date, float] = {}
    for stamp, value in zip(timestamps, adjclose):
        if value is not None and math.isfinite(float(value)):
            prices[datetime.fromtimestamp(stamp, timezone.utc).date()] = round(float(value), 6)
    if not prices:
        raise RuntimeError("no adjusted closes returned")
    return PriceSeries(prices, "Yahoo Finance chart", True)


def stooq_symbol(ticker: str) -> str:
    if ticker.upper() == "SPY":
        return "spy.us"
    return ticker.lower().replace(".", "-") + ".us"


def fetch_stooq(ticker: str, start: date, end: date) -> PriceSeries:
    query = urllib.parse.urlencode(
        {"s": stooq_symbol(ticker), "d1": start.strftime("%Y%m%d"), "d2": end.strftime("%Y%m%d"), "i": "d"}
    )
    text = http_text("https://stooq.com/q/d/l/?" + query)
    prices: dict[date, float] = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            prices[date.fromisoformat(row["Date"])] = round(float(row["Close"]), 6)
        except (KeyError, TypeError, ValueError):
            continue
    if not prices:
        raise RuntimeError("no daily closes returned")
    return PriceSeries(prices, "Stooq", False)


def fetch_prices(ticker: str, start: date, end: date) -> PriceSeries:
    errors: list[str] = []
    for fetcher in (fetch_yahoo, fetch_stooq):
        try:
            return fetcher(ticker, start, end)
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError("; ".join(errors))


def session_close_utc(session: date) -> datetime:
    return datetime.combine(session, wall_time(16, 0), tzinfo=MARKET_TIMEZONE).astimezone(timezone.utc)


def entry_session(generated_at: datetime, prices: dict[date, float]) -> date | None:
    for session in sorted(prices):
        if session_close_utc(session) >= generated_at:
            return session
    return None


def last_on_or_before(prices: dict[date, float], target: date) -> tuple[date, float] | None:
    candidates = [session for session in prices if session <= target]
    if not candidates:
        return None
    session = max(candidates)
    return session, prices[session]


def verdict(rating: str, excess: float) -> str:
    if rating in BULLISH:
        return "correct" if excess > 0 else "incorrect"
    if rating in BEARISH:
        return "correct" if excess < 0 else "incorrect"
    return "correct" if abs(excess) <= 0.05 else "incorrect"


def target_stop(record: dict[str, Any], prices: dict[date, float], entry: date, p0: float) -> dict[str, Any]:
    stop = record["stop_price"]
    if stop is None:
        return {"outcome": "not_evaluable", "target_date": None, "stop_date": None}
    bullish = record["target_price"] > p0
    target_date: date | None = None
    stop_date: date | None = None
    for session in sorted(day for day in prices if day >= entry):
        price = prices[session]
        if target_date is None and ((bullish and price >= record["target_price"]) or (not bullish and price <= record["target_price"])):
            target_date = session
        if stop_date is None and ((bullish and price <= stop) or (not bullish and price >= stop)):
            stop_date = session
        if target_date or stop_date:
            break
    if target_date:
        outcome = "target_reached"
    elif stop_date:
        outcome = "stop_breached"
    else:
        outcome = "both_pending"
    return {
        "outcome": outcome,
        "target_date": target_date.isoformat() if target_date else None,
        "stop_date": stop_date.isoformat() if stop_date else None,
    }


def score_call(record: dict[str, Any], stock: PriceSeries, benchmark: PriceSeries, now: datetime) -> dict[str, Any]:
    generated_at = parse_utc(record["generated_at"])
    entry = entry_session(generated_at, stock.prices)
    if entry is None or entry not in benchmark.prices:
        return {
            "data_gap": True, "dividend_adjusted": stock.dividend_adjusted,
            "price_source": stock.source, "benchmark_source": benchmark.source,
            "entry_date": None, "entry_price": None, "benchmark_entry_price": None,
            "delisted": False, "horizons": {},
            "target_stop": {"outcome": "not_evaluable", "target_date": None, "stop_date": None},
        }
    p0 = stock.prices[entry]
    b0 = benchmark.prices[entry]
    horizons: dict[str, Any] = {}
    delisted = False
    data_gap = False
    for name, days in HORIZONS.items():
        horizon_date = entry + timedelta(days=days)
        if now.date() < horizon_date:
            horizons[name] = {
                "horizon_date": horizon_date.isoformat(), "price_date": None,
                "stock_return": None, "benchmark_return": None, "excess_return": None,
                "verdict": "pending",
            }
            continue
        stock_end = last_on_or_before(stock.prices, horizon_date)
        bench_end = last_on_or_before(benchmark.prices, horizon_date)
        if stock_end is None or bench_end is None:
            data_gap = True
            horizons[name] = {
                "horizon_date": horizon_date.isoformat(), "price_date": None,
                "stock_return": None, "benchmark_return": None, "excess_return": None,
                "verdict": "data_gap",
            }
            continue
        if stock_end[0] < horizon_date - timedelta(days=10):
            delisted = True
        stock_return = stock_end[1] / p0 - 1
        benchmark_return = bench_end[1] / b0 - 1
        excess = stock_return - benchmark_return
        horizons[name] = {
            "horizon_date": horizon_date.isoformat(), "price_date": stock_end[0].isoformat(),
            "stock_return": round(stock_return, 8), "benchmark_return": round(benchmark_return, 8),
            "excess_return": round(excess, 8), "verdict": verdict(record["rating"], excess),
        }
    return {
        "data_gap": data_gap,
        "dividend_adjusted": stock.dividend_adjusted,
        "price_source": stock.source,
        "benchmark_source": benchmark.source,
        "entry_date": entry.isoformat(),
        "entry_price": p0,
        "benchmark_entry_price": b0,
        "delisted": delisted,
        "horizons": horizons,
        "target_stop": target_stop(record, stock.prices, entry, p0),
    }


def average(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 8) if values else None


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 8) if values else None


def rating_class(rating: str) -> str:
    if rating in BULLISH:
        return "bullish"
    if rating in BEARISH:
        return "bearish"
    return "hold"


def horizon_aggregate(records: list[tuple[dict[str, Any], dict[str, Any]]], name: str) -> dict[str, Any]:
    verdicts: list[str] = []
    excess: list[float] = []
    by_rating: dict[str, dict[str, int | float | None]] = {}
    by_class: dict[str, dict[str, int | float | None]] = {}
    pending = 0
    for record, performance in records:
        result = performance.get("horizons", {}).get(name, {})
        state = result.get("verdict", "data_gap")
        if state == "pending":
            pending += 1
            continue
        if state not in {"correct", "incorrect"}:
            continue
        verdicts.append(state)
        if result.get("excess_return") is not None:
            excess.append(result["excess_return"])
        for key, bucket in ((record["rating"], by_rating), (rating_class(record["rating"]), by_class)):
            item = bucket.setdefault(key, {"n": 0, "correct": 0, "hit_rate": None})
            item["n"] += 1
            item["correct"] += int(state == "correct")
    for bucket in (by_rating, by_class):
        for item in bucket.values():
            item["hit_rate"] = round(item["correct"] / item["n"], 6) if item["n"] else None
    correct = verdicts.count("correct")
    return {
        "n": len(verdicts), "correct": correct, "incorrect": verdicts.count("incorrect"),
        "pending": pending, "hit_rate": round(correct / len(verdicts), 6) if verdicts else None,
        "mean_excess_return": average(excess), "median_excess_return": median(excess),
        "equal_weight_excess_return": average(excess), "by_rating": by_rating, "by_rating_class": by_class,
    }


def aggregate(calls: dict[str, Any], performances: dict[str, Any]) -> dict[str, Any]:
    revealed = [row for row in calls["calls"] if row["state"] == "revealed"]
    live = [row for row in revealed if row["record"]["provenance"] == "live" and row["record"]["voided"] is None]
    scored = [(row["record"], performances[row["call_id"]]) for row in live if row["call_id"] in performances]
    rating_counts: dict[str, int] = {}
    for row in live:
        rating_counts[row["record"]["rating"]] = rating_counts.get(row["record"]["rating"], 0) + 1
    return {
        "total": len(calls["calls"]),
        "sealed": sum(row["state"] == "sealed" for row in calls["calls"]),
        "revealed": len(revealed),
        "live_revealed": len(live),
        "backfilled": sum(row["record"]["provenance"] == "backfilled" for row in revealed),
        "voided": sum(row["record"]["voided"] is not None for row in revealed),
        "by_rating": rating_counts,
        "horizons": {name: horizon_aggregate(scored, name) for name in HORIZONS},
    }


def recompute(calls_path: Path, output_path: Path, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    calls = json.loads(calls_path.read_text(encoding="utf-8"))
    revealed = [row for row in calls["calls"] if row["state"] == "revealed" and row["record"]["voided"] is None]
    if revealed:
        earliest = min(parse_utc(row["record"]["generated_at"]).date() for row in revealed) - timedelta(days=10)
    else:
        earliest = now.date() - timedelta(days=10)
    series: dict[str, PriceSeries | None] = {}
    tickers = ({row["record"]["ticker"] for row in revealed} | {"SPY"}) if revealed else set()
    for ticker in sorted(tickers):
        try:
            series[ticker] = fetch_prices(ticker, earliest, now.date())
        except Exception as exc:
            print(f"warning: {ticker} price data unavailable: {exc}")
            series[ticker] = None
    performances: dict[str, Any] = {}
    benchmark = series.get("SPY")
    for row in revealed:
        stock = series.get(row["record"]["ticker"])
        if stock is None or benchmark is None:
            performances[row["call_id"]] = {
                "data_gap": True, "dividend_adjusted": None, "price_source": None,
                "benchmark_source": None, "entry_date": None, "entry_price": None,
                "benchmark_entry_price": None, "delisted": False, "horizons": {},
                "target_stop": {"outcome": "not_evaluable", "target_date": None, "stop_date": None},
            }
        else:
            performances[row["call_id"]] = score_call(row["record"], stock, benchmark, now)
    result = {
        "format_version": 1,
        "methodology_version": 1,
        "computed_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "calls": performances,
        "aggregates": aggregate(calls, performances),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=Path, default=Path("data/calls.json"))
    parser.add_argument("--output", type=Path, default=Path("data/performance.json"))
    args = parser.parse_args()
    recompute(args.calls, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
