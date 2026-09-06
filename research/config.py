"""
Shared constants for the research/backtesting sandbox.

DATA DISCLOSURE
----------------
This project has NO connection to MT5, a broker, or any live/historical
market data feed. `data/synthetic.py` generates a labeled synthetic FX
price process (regime-switching random walk with session/volatility
structure). Every result produced from it is engine-validation evidence
only, never a claim about real market behavior. See audit/
PHASE_7_MULTI_STRATEGY_HEDGE_BACKTEST.md, section "Data Coverage and
Limitations", before drawing any conclusion from these numbers.
"""
from __future__ import annotations
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
NY_TZ = ZoneInfo("America/New_York")
LONDON_TZ = ZoneInfo("Europe/London")

# pip size per symbol (price units per pip)
PIP_SIZE = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDJPY": 0.01,
    "AUDUSD": 0.0001,
    "USDCAD": 0.0001,
    "USDCHF": 0.0001,
    "NZDUSD": 0.0001,
    "XAUUSD": 0.01,
}

# baseline spread in pips (widens synthetically during low-liquidity windows)
BASELINE_SPREAD_PIPS = {
    "EURUSD": 1.0,
    "GBPUSD": 1.5,
    "USDJPY": 1.2,
    "AUDUSD": 1.4,
    "USDCAD": 1.6,
    "USDCHF": 1.7,
    "NZDUSD": 2.0,
    "XAUUSD": 3.0,
}

# contract size (units of base currency per 1.0 lot) - standard FX lot
CONTRACT_SIZE = 100_000

TIMEFRAMES_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

SESSION_TIMEZONE = "America/New_York"
NY_SESSION_OPEN = "09:30"
NY_OPENING_RANGE_MINUTES = 15

RANDOM_SEED = 20240906
