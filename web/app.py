"""
Phase 23-27 — Web backtesting terminal.

Local, browser-based research terminal (Dash + Plotly) reading the JSON
artifacts produced by `research/run_experiments.py`. This app makes NO
network calls, connects to no broker, and places no orders -- it is a
read-only viewer over already-computed, labeled-synthetic research
results.

Run:
    research/.venv/bin/python web/app.py
then open http://127.0.0.1:8050
"""
from __future__ import annotations

import json
from pathlib import Path

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dash_table, dcc, html

RESULTS_DIR = Path(__file__).parent.parent / "research" / "results"
RESULTS_DIR_8 = Path(__file__).parent.parent / "research" / "results_8"
RESULTS_DIR_9B = Path(__file__).parent.parent / "research" / "results_9b"


def load(name: str, base: Path = RESULTS_DIR):
    path = base / f"{name}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


matrix = load("matrix") or []
sl_comparison = load("sl_comparison") or []
tp_comparison = load("tp_comparison") or []
exit_comparison = load("exit_comparison") or []
exit_by_strategy = load("exit_by_strategy") or []
fib_comparison = load("fibonacci_level_comparison") or []
risk_sweep = load("risk_level_sweep") or []
lot_size = load("lot_size_experiment") or []
hedge_cases = load("hedge_cases") or {}
ablation = load("ablation") or []
sample_trades = load("sample_trades") or []
sample_rejected = load("sample_rejected_candidates") or []
candles = load("candles_eurusd_sample") or []
overlays = load("overlays_eurusd_sample") or {}
data_quality = load("data_quality") or []
regime_validation = load("regime_validation") or {}

# Phase 8 artifacts (research/results_8/) -- corrected cost model, expanded
# regime taxonomy, and every genuinely new Phase 8 experiment. Loaded
# alongside (never merged into) the Phase 7 artifacts above.
matrix_corrected = load("matrix_corrected", RESULTS_DIR_8) or []
no_trade_funnel = load("no_trade_funnel", RESULTS_DIR_8) or []
sl_comparison_v2 = load("sl_comparison_v2", RESULTS_DIR_8) or []
tp_comparison_v2 = load("tp_comparison_v2", RESULTS_DIR_8) or []
cost_sensitivity = load("cost_sensitivity", RESULTS_DIR_8) or []
nested_bias_experiment = load("nested_bias_experiment", RESULTS_DIR_8) or []
ablation_matrix_8 = load("ablation_matrix", RESULTS_DIR_8) or []
rolling_hedge_correlation = load("rolling_hedge_correlation", RESULTS_DIR_8) or []
negative_controls_8 = load("negative_controls", RESULTS_DIR_8) or {}
trend_only_comparison = load("trend_only_comparison", RESULTS_DIR_8) or []
strategy_selector_comparison = load("strategy_selector_comparison", RESULTS_DIR_8) or []
robustness_perturbation = load("robustness_perturbation", RESULTS_DIR_8) or {}
out_of_sample_locked = load("out_of_sample_locked", RESULTS_DIR_8) or {}
mutation_tests = load("mutation_tests", RESULTS_DIR_8) or []

# Phase 9B artifacts (research/results_9b/) -- opening_range_v2 (1UP/2DOWN)
# state machine, MARKET_CONTEXT/EntryDecision objects, and every genuinely
# new Phase 9B experiment. Loaded alongside (never merged into) Phase 7/8.
or_v2_matrix = load("or_v2_matrix", RESULTS_DIR_9B) or []
decision_inspector_sample = load("decision_inspector_sample", RESULTS_DIR_9B) or {}
no_trade_funnel_v2 = load("no_trade_funnel_v2", RESULTS_DIR_9B) or []
regime_gating_9b = load("regime_gating", RESULTS_DIR_9B) or []
fibonacci_depth_experiment = load("fibonacci_depth_experiment", RESULTS_DIR_9B) or []
candle_pattern_ablation_9b = load("candle_pattern_ablation", RESULTS_DIR_9B) or []
sl_tp_v2_comparison = load("sl_tp_v2_comparison", RESULTS_DIR_9B) or []
cost_sensitivity_9b = load("cost_sensitivity", RESULTS_DIR_9B) or []
portfolio_gating_9b = load("portfolio_gating", RESULTS_DIR_9B) or []
robustness_perturbation_9b = load("robustness_perturbation", RESULTS_DIR_9B) or {}
out_of_sample_locked_9b = load("out_of_sample_locked", RESULTS_DIR_9B) or {}
mutation_tests_9b = load("mutation_tests", RESULTS_DIR_9B) or []

candles_df = pd.DataFrame(candles)
if not candles_df.empty:
    candles_df["ts"] = pd.to_datetime(candles_df["ts"])

NUMERIC_COLS_TO_ROUND = [
    "win_rate", "expectancy_r", "median_r", "profit_factor", "avg_win_r", "avg_loss_r",
    "max_drawdown_r", "sharpe", "sortino", "avg_mfe_r", "avg_mae_r", "avg_duration_bars",
]


def _round_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in NUMERIC_COLS_TO_ROUND:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").round(3)
    return df


def make_table(df: pd.DataFrame, id_: str, page_size: int = 20, selectable: bool | None = None):
    if selectable is None:
        selectable = id_ == "trade-table"
    return dash_table.DataTable(
        id=id_,
        data=df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in df.columns],
        page_size=page_size,
        sort_action="native",
        filter_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "monospace", "fontSize": "12px", "padding": "4px", "textAlign": "left"},
        style_header={"fontWeight": "bold", "backgroundColor": "#f0f0f0"},
        row_selectable="single" if selectable else None,
    )


app = dash.Dash(__name__, title="Multi-Strategy Hedge Backtest Terminal")
server = app.server

DISCLAIMER = html.Div(
    "SYNTHETIC DATA ONLY -- no MT5/broker connection, no live trading, no real market data. "
    "Every number on this page is an engine-validation result, not a claim about real markets. "
    "See audit/PHASE_7_MULTI_STRATEGY_HEDGE_BACKTEST.md.",
    style={"background": "#fff3cd", "border": "1px solid #ffc107", "padding": "8px 14px",
           "marginBottom": "10px", "fontSize": "13px", "fontFamily": "sans-serif"},
)


# ---------------------------------------------------------------- Replay tab
LAYER_OPTIONS = [
    {"label": "Opening Range", "value": "or"},
    {"label": "Structure (BOS/CHOCH)", "value": "structure"},
    {"label": "Liquidity Sweeps", "value": "liquidity"},
    {"label": "Trades (entry/SL/TP/exit)", "value": "trades"},
]

replay_tab = html.Div([
    html.Div([
        html.Label("Layers:"),
        dcc.Checklist(id="layer-toggle", options=LAYER_OPTIONS, value=["or", "trades"], inline=True),
    ], style={"marginBottom": "8px"}),
    html.Div([
        html.Button("Reset", id="btn-reset", n_clicks=0),
        html.Button("Step Back", id="btn-back", n_clicks=0),
        html.Button("Play/Pause", id="btn-play", n_clicks=0),
        html.Button("Step Forward", id="btn-fwd", n_clicks=0),
        dcc.Slider(id="speed-slider", min=200, max=2000, step=200, value=600,
                   marks={200: "Fast", 2000: "Slow"}),
    ], style={"display": "flex", "gap": "8px", "alignItems": "center", "marginBottom": "8px"}),
    dcc.Slider(id="bar-slider", min=50, max=max(50, len(candles_df)), step=1,
               value=min(200, len(candles_df)) if len(candles_df) else 50,
               marks=None, tooltip={"placement": "bottom"}),
    dcc.Graph(id="replay-chart", style={"height": "70vh"}),
    dcc.Interval(id="play-interval", interval=600, n_intervals=0, disabled=True),
])


def build_replay_figure(n_bars: int, layers: list) -> go.Figure:
    fig = go.Figure()
    if candles_df.empty:
        fig.update_layout(title="No candle sample available -- run research/run_experiments.py first")
        return fig

    view = candles_df.iloc[:n_bars]
    fig.add_trace(go.Candlestick(
        x=view["ts"], open=view["open"], high=view["high"], low=view["low"], close=view["close"],
        name="EURUSD M5",
    ))

    window_end = view["ts"].iloc[-1] if len(view) else None

    if "or" in layers and window_end is not None:
        for orr in overlays.get("opening_ranges", []):
            open_ts = pd.Timestamp(orr["session_open_utc"])
            close_ts = pd.Timestamp(orr["or_close_utc"])
            if open_ts > window_end:
                continue
            end_x = min(window_end, open_ts + pd.Timedelta(hours=6))
            fig.add_shape(type="rect", x0=open_ts, x1=end_x, y0=orr["or_low"], y1=orr["or_high"],
                          fillcolor="rgba(255,165,0,0.12)", line=dict(color="orange", width=1))

    if "structure" in layers and window_end is not None:
        bull = [e for e in overlays.get("structure_events", []) if pd.Timestamp(e["ts"]) <= window_end and e["direction"] == "BULLISH"]
        bear = [e for e in overlays.get("structure_events", []) if pd.Timestamp(e["ts"]) <= window_end and e["direction"] == "BEARISH"]
        if bull:
            fig.add_trace(go.Scatter(
                x=[e["ts"] for e in bull], y=[e["price"] for e in bull], mode="markers",
                marker=dict(symbol="triangle-up", size=9, color="green"),
                name="BOS/CHOCH bullish",
            ))
        if bear:
            fig.add_trace(go.Scatter(
                x=[e["ts"] for e in bear], y=[e["price"] for e in bear], mode="markers",
                marker=dict(symbol="triangle-down", size=9, color="red"),
                name="BOS/CHOCH bearish",
            ))

    if "liquidity" in layers and window_end is not None:
        sweeps = [s for s in overlays.get("liquidity_sweeps", []) if pd.Timestamp(s["ts"]) <= window_end]
        if sweeps:
            fig.add_trace(go.Scatter(
                x=[s["ts"] for s in sweeps], y=[s["price"] for s in sweeps], mode="markers",
                marker=dict(symbol="x", size=8, color="purple"),
                name="ESTIMATED_STOP_LIQUIDITY sweep",
            ))

    if "trades" in layers and window_end is not None:
        trades = [t for t in overlays.get("trades", [])
                  if t["symbol"] == "EURUSD" and pd.Timestamp(t["entry_ts"]) <= window_end]
        for t in trades:
            color = "green" if t["r_multiple"] and t["r_multiple"] > 0 else "crimson"
            fig.add_trace(go.Scatter(
                x=[t["entry_ts"]], y=[t["entry_price"]], mode="markers",
                marker=dict(symbol="circle", size=10, color=color, line=dict(width=1, color="black")),
                name=f"{t['strategy']} entry", showlegend=False,
                hovertext=f"{t['strategy']} {t['direction']} R={t['r_multiple']:.2f} exit={t['exit_reason']}",
            ))

    fig.update_layout(xaxis_rangeslider_visible=False, margin=dict(l=40, r=20, t=30, b=30),
                       legend=dict(orientation="h"))
    return fig


@app.callback(Output("replay-chart", "figure"), Input("bar-slider", "value"), Input("layer-toggle", "value"))
def _update_replay(n_bars, layers):
    return build_replay_figure(n_bars or 50, layers or [])


@app.callback(Output("play-interval", "disabled"), Input("btn-play", "n_clicks"), State("play-interval", "disabled"))
def _toggle_play(n_clicks, disabled):
    if not n_clicks:
        return True
    return not disabled


@app.callback(Output("play-interval", "interval"), Input("speed-slider", "value"))
def _set_speed(v):
    return v or 600


@app.callback(
    Output("bar-slider", "value"),
    Input("play-interval", "n_intervals"), Input("btn-fwd", "n_clicks"),
    Input("btn-back", "n_clicks"), Input("btn-reset", "n_clicks"),
    State("bar-slider", "value"),
)
def _advance(n_intervals, fwd_clicks, back_clicks, reset_clicks, current):
    trigger = dash.ctx.triggered_id
    current = current or 50
    max_bars = max(50, len(candles_df))
    if trigger == "btn-reset":
        return 50
    if trigger == "btn-back":
        return max(50, current - 5)
    if trigger in ("play-interval", "btn-fwd"):
        return min(max_bars, current + (1 if trigger == "btn-fwd" else 3))
    return current


# ------------------------------------------------------------ Comparison tabs
def comparison_tab(rows, group_col, title):
    if not rows:
        return html.Div(f"No data for {title} -- run research/run_experiments.py first.")
    df = pd.DataFrame(rows)
    agg_cols = [c for c in NUMERIC_COLS_TO_ROUND if c in df.columns]
    agg = df.groupby(group_col)[agg_cols].mean(numeric_only=True).reset_index()
    agg = _round_df(agg)
    per_symbol = _round_df(df)
    return html.Div([
        html.H4(f"{title} -- aggregated across symbols"),
        make_table(agg, f"{group_col}-agg-table"),
        html.H4(f"{title} -- per symbol detail"),
        make_table(per_symbol, f"{group_col}-detail-table", page_size=15),
    ])


def strategy_tab():
    if not matrix:
        return html.Div("No matrix data -- run research/run_experiments.py first.")
    df = pd.DataFrame(matrix)
    keep = ["symbol", "strategy", "n", "win_rate", "expectancy_r", "profit_factor", "sharpe",
            "sortino", "max_drawdown_r", "verdict", "bh_fdr_survives"]
    keep = [c for c in keep if c in df.columns]
    detail = _round_df(df[keep])
    agg_cols = [c for c in NUMERIC_COLS_TO_ROUND if c in df.columns]
    agg = df.groupby("strategy")[agg_cols].mean(numeric_only=True).reset_index()
    agg = _round_df(agg)
    verdict_counts = df.groupby(["strategy", "verdict"]).size().reset_index(name="count")
    return html.Div([
        html.H4("Strategy comparison -- aggregated across symbols"),
        make_table(agg, "strategy-agg-table"),
        html.H4("Verdicts by strategy (count of symbol cells)"),
        make_table(verdict_counts, "strategy-verdict-table"),
        html.H4("Pair x Strategy x Regime matrix (detail)"),
        make_table(detail, "strategy-detail-table", page_size=30),
    ])


def regime_detail_tab():
    if not matrix:
        return html.Div("No matrix data.")
    rows = []
    for row in matrix:
        for regime, stats in (row.get("regime_breakdown") or {}).items():
            rows.append({"symbol": row["symbol"], "strategy": row["strategy"], "regime": regime, **stats})
    if not rows:
        return html.Div("No regime breakdown available.")
    df = _round_df(pd.DataFrame(rows))
    return html.Div([
        html.H4("Pair x Strategy x Regime -- full breakdown"),
        make_table(df, "regime-detail-table", page_size=30),
    ])


ENTRY_TABLE_COLS = ["symbol", "strategy", "n", "win_rate", "expectancy_r", "median_r", "profit_factor",
                    "sharpe", "sortino", "max_drawdown_r", "n_rejected_candidates", "bh_fdr_survives", "verdict"]


def entry_comparison_tab():
    or_rows = [r for r in matrix if str(r["strategy"]).startswith("opening_range_")]
    or_df = pd.DataFrame(or_rows)
    if not or_df.empty:
        or_df = or_df[[c for c in ENTRY_TABLE_COLS if c in or_df.columns]]
    return html.Div([
        html.H4("Entry family comparison: Breakout vs Retest vs Reversal (Opening Range variants)"),
        make_table(_round_df(or_df), "entry-table") if or_rows else html.Div("No data."),
        html.H4("Fibonacci level comparison (Fibonacci levels vs. non-Fibonacci control depths)"),
        make_table(_round_df(pd.DataFrame(fib_comparison)), "fib-table") if fib_comparison else html.Div("No data."),
    ])


def exit_tab():
    winners = []
    if exit_by_strategy:
        df = pd.DataFrame(exit_by_strategy)
        for strat, g in df.groupby("strategy"):
            g_valid = g[g["n"] > 0]
            if g_valid.empty:
                continue
            best = g_valid.loc[g_valid["expectancy_r"].idxmax()]
            winners.append({"strategy": strat, "best_exit_model": best["exit_model"],
                             "expectancy_r": round(best["expectancy_r"], 3), "n": int(best["n"])})
    return html.Div([
        html.H4("Exit model comparison -- aggregated (opening_range_continuation, all symbols)"),
        make_table(_round_df(pd.DataFrame(exit_comparison)), "exit-agg-table") if exit_comparison else html.Div("No data."),
        html.H4("Which exit wins for which strategy? (best expectancy_r, EURUSD, informational only -- see report for OOS caveat)"),
        make_table(pd.DataFrame(winners), "exit-winner-table") if winners else html.Div("No data."),
        html.H4("Exit model x strategy -- full detail"),
        make_table(_round_df(pd.DataFrame(exit_by_strategy)), "exit-detail-table", page_size=30) if exit_by_strategy else html.Div(),
    ])


def risk_tab():
    return html.Div([
        html.H4("Risk-level sweep (opening_range_continuation, EURUSD, R-multiple compounding)"),
        make_table(_round_df(pd.DataFrame(risk_sweep)), "risk-table") if risk_sweep else html.Div("No data."),
        html.H4("Lot-size experiment -- separates strategy edge (R-multiples, unchanged) from position size ($ P&L)"),
        make_table(_round_df(pd.DataFrame(lot_size)), "lot-table") if lot_size else html.Div("No data."),
    ])


def hedge_tab():
    if not hedge_cases:
        return html.Div("No hedge case data -- run research/run_experiments.py first.")
    rows = [{"case": name, **stats} for name, stats in hedge_cases.items()]
    return html.Div([
        html.H4("Hedge / portfolio cases A-G"),
        make_table(_round_df(pd.DataFrame(rows)), "hedge-table"),
        dcc.Graph(figure=go.Figure(
            data=[go.Bar(x=[r["case"] for r in rows], y=[r["total_return_r"] for r in rows], name="Total return (R)")],
            layout=go.Layout(title="Total return (R) by hedge case", margin=dict(l=40, r=20, t=40, b=80)),
        )),
    ])


def ablation_tab():
    return html.Div([
        html.H4("Feature ablation: baseline -> +HTF bias alignment -> +structure confirmation"),
        make_table(_round_df(pd.DataFrame(ablation)), "ablation-table") if ablation else html.Div("No data."),
    ])


def data_quality_tab():
    quality_df = pd.DataFrame(data_quality)
    if not quality_df.empty and "notes" in quality_df.columns:
        quality_df["notes"] = quality_df["notes"].apply(lambda ns: " | ".join(ns) if isinstance(ns, list) else ns)
    return html.Div([
        html.H4("Data quality / causality audit (Phase 2)"),
        make_table(quality_df, "quality-table") if data_quality else html.Div("No data."),
        html.H4("Regime classifier vs. hidden synthetic ground truth (engine validation diagnostic ONLY)"),
        make_table(pd.DataFrame([{"symbol": s, **v} for s, v in regime_validation.items()]), "regime-val-table")
        if regime_validation else html.Div("No data."),
    ])


TRADE_TABLE_COLS = ["symbol", "strategy", "variant", "direction", "entry_ts", "entry_price", "sl_model",
                    "tp_model", "exit_model", "exit_ts", "exit_reason", "r_multiple", "mfe_r", "mae_r",
                    "duration_bars", "market_condition", "directional_bias", "candle_pattern"]


def trade_inspector_tab():
    trades_df = pd.DataFrame(sample_trades)
    rejected_df = pd.DataFrame(sample_rejected)
    trades_display = trades_df[[c for c in TRADE_TABLE_COLS if c in trades_df.columns]] if not trades_df.empty else trades_df
    return html.Div([
        html.H4("Trade Inspector -- select a row to see \"why did the system enter?\""),
        make_table(_round_df(trades_display), "trade-table", page_size=10) if not trades_df.empty else html.Div("No trades."),
        html.Div(id="trade-detail", style={"marginTop": "10px", "padding": "10px", "background": "#f7f7f7",
                                             "fontFamily": "monospace", "whiteSpace": "pre-wrap"}),
        html.H4("Rejected candidates -- \"why did the system NOT enter?\" (first failing rule)"),
        make_table(pd.DataFrame([
            {"symbol": r["symbol"], "strategy": r["strategy"], "variant": r["variant"], "ts": r["ts"],
             "entry_state_reached": r["entry_state_reached"], "first_failing_rule": r["first_failing_rule"]}
            for r in sample_rejected
        ]), "rejected-table", page_size=10) if not rejected_df.empty else html.Div("No rejected candidates."),
    ])


@app.callback(Output("trade-detail", "children"), Input("trade-table", "selected_rows"))
def _show_trade_detail(selected_rows):
    if not selected_rows or not sample_trades:
        return "Select a trade above to see its full entry/exit reasoning."
    t = sample_trades[selected_rows[0]]
    lines = [
        f"WHY DID THE SYSTEM ENTER?",
        f"  Strategy: {t['strategy']} ({t['variant']}) | Direction: {t['direction']}",
        f"  Setup reason: {t['setup_reason']}",
        f"  Rules passed: {', '.join(t['rules_passed']) or '(none)'}",
        f"  Rules failed: {', '.join(t['rules_failed']) or '(none)'}",
        f"  Market condition: {t['market_condition']} | Directional bias: {t['directional_bias']}",
        f"  Candle pattern: {t['candle_pattern']}",
        "",
        f"EXECUTION",
        f"  Entry: {t['entry_ts']} @ {t['entry_price']}",
        f"  SL model: {t['sl_model']} (initial SL={t['initial_sl']}) | TP model: {t['tp_model']} | Exit model: {t['exit_model']}",
        f"  Exit: {t['exit_ts']} @ {t['exit_price']} ({t['exit_reason']})",
        f"  R multiple: {t['r_multiple']:.3f} | MFE: {t['mfe_r']:.3f}R | MAE: {t['mae_r']:.3f}R | Duration: {t['duration_bars']} bars",
    ]
    return "\n".join(lines)


# ============================================================ Phase 8 tabs
PHASE8_BANNER = html.Div(
    "PHASE 8 -- corrected cost model (exit-side spread now deducted, previously missing) and expanded "
    "regime taxonomy. Numbers on this tab supersede the Phase 7 tables above for the same symbols/strategies.",
    style={"background": "#e7f1ff", "border": "1px solid #4a90d9", "padding": "6px 12px",
           "marginBottom": "8px", "fontSize": "12px", "fontFamily": "sans-serif"},
)


def corrected_matrix_tab():
    if not matrix_corrected:
        return html.Div("No Phase 8 corrected-matrix data -- run research/run_experiments_phase8.py first.")
    df = pd.DataFrame(matrix_corrected)
    keep = ["symbol", "strategy", "n", "win_rate", "expectancy_r", "profit_factor", "sharpe",
            "max_drawdown_r", "verdict", "bh_fdr_survives"]
    keep = [c for c in keep if c in df.columns]
    agg_cols = [c for c in NUMERIC_COLS_TO_ROUND if c in df.columns]
    agg = _round_df(df.groupby("strategy")[agg_cols].mean(numeric_only=True).reset_index())
    return html.Div([
        PHASE8_BANNER,
        html.H4("Corrected Pair x Strategy matrix -- aggregated across symbols"),
        make_table(agg, "corrected-agg-table"),
        html.H4("Corrected matrix -- detail (with purge/embargo fold summary in raw JSON)"),
        make_table(_round_df(df[keep]), "corrected-detail-table", page_size=30),
    ])


def bias_tab():
    if not nested_bias_experiment:
        return html.Div("No nested bias experiment data.")
    rows = []
    for r in nested_bias_experiment:
        sym = r["symbol"]
        for condition in ("BIAS_ONLY", "BIAS_PLUS_STRUCTURE", "BIAS_PLUS_STRUCTURE_PLUS_REGIME"):
            c = r.get(condition, {})
            rows.append({"symbol": sym, "condition": condition, "n": c.get("n"),
                         "mean_signed_return_atr": c.get("mean_signed_return_atr"), "verdict": c.get("verdict")})
    df = pd.DataFrame(rows)
    if "mean_signed_return_atr" in df.columns:
        df["mean_signed_return_atr"] = pd.to_numeric(df["mean_signed_return_atr"], errors="coerce").round(4)
    return html.Div([
        PHASE8_BANNER,
        html.H4("Nested bias experiment: BIAS ONLY -> +STRUCTURE -> +STRUCTURE+REGIME"),
        html.P("Target: ATR-normalized forward return, signed so correct bias direction is positive. "
               "A monotonic increase across the three rows means each added confirmation layer adds real information."),
        make_table(df, "bias-experiment-table", page_size=20),
    ])


def negative_controls_tab():
    rows = []
    for name, r in negative_controls_8.items():
        if name == "hedge_pairing":
            rows.append({"control": name, "real": r.get("real_mean_abs_correlation"),
                         "permuted": r.get("permuted_pairing_mean_abs_correlation"),
                         "edge_survives_control": r.get("edge_survives_control")})
        else:
            real = r.get("real", {})
            permuted = r.get("permuted_structure_direction") or r.get("permuted_strength_label") or {}
            rows.append({"control": name, "real_expectancy_r": real.get("expectancy_r"),
                         "permuted_expectancy_r": permuted.get("expectancy_r"),
                         "edge_survives_control": r.get("edge_survives_control")})
    return html.Div([
        PHASE8_BANNER,
        html.H4("Negative controls -- real feature vs. permuted feature"),
        html.P("A feature whose real result does not clearly beat its own permuted-label control is not "
               "demonstrated to carry real information, regardless of how the real number looks in isolation."),
        make_table(_round_df(pd.DataFrame(rows)), "negative-controls-table") if rows else html.Div("No data."),
    ])


def ablation_matrix_tab():
    if not ablation_matrix_8:
        return html.Div("No generalized ablation matrix data.")
    rows = []
    for r in ablation_matrix_8:
        sym = r["symbol"]
        for stage, stats in r.items():
            if stage == "symbol":
                continue
            rows.append({"symbol": sym, "stage": stage, "n": stats.get("n"),
                         "mean_signed_return_atr": stats.get("mean_signed_return_atr"),
                         "verdict": stats.get("verdict")})
    df = pd.DataFrame(rows)
    if "mean_signed_return_atr" in df.columns:
        df["mean_signed_return_atr"] = pd.to_numeric(df["mean_signed_return_atr"], errors="coerce").round(4)
    return html.Div([
        PHASE8_BANNER,
        html.H4("Generalized ablation matrix: BASELINE + each feature independently"),
        html.P("BASELINE is a deliberately trivial 1-bar breakout signal, not conditioned on any feature below -- "
               "isolates whether each feature adds information on its own, not how good any one strategy's combination is."),
        make_table(df, "ablation-matrix-table", page_size=30),
    ])


def hedge_correlation_tab():
    if not rolling_hedge_correlation:
        return html.Div("No rolling hedge correlation data.")
    rows = []
    for r in rolling_hedge_correlation:
        row = {"pair": f"{r['symbol_a']}/{r['symbol_b']}", "window_bars": r["window_bars"],
               "overall_mean_correlation": r["overall_mean_correlation"], "overall_mean_beta": r["overall_mean_beta"]}
        for bucket, stats in r.get("regime_buckets", {}).items():
            row[f"{bucket}_mean_corr"] = stats["mean_correlation"]
        rows.append(row)
    return html.Div([
        PHASE8_BANNER,
        html.H4("Rolling correlation/beta by regime bucket (designed synthetic correlation -- engine validation only)"),
        make_table(_round_df(pd.DataFrame(rows)), "hedge-corr-table"),
    ])


def trend_only_tab():
    if not trend_only_comparison:
        return html.Div("No trend-only comparison data.")
    rows = []
    for r in trend_only_comparison:
        sym = r["symbol"]
        for mode in ("ALL_REGIMES", "TREND_ONLY", "STRONG_TREND_ONLY"):
            stats = r.get(mode, {})
            rows.append({"symbol": sym, "mode": mode, "n": stats.get("n"), "win_rate": stats.get("win_rate"),
                         "expectancy_r": stats.get("expectancy_r"), "profit_factor": stats.get("profit_factor"),
                         "sharpe": stats.get("sharpe"), "n_skipped": stats.get("n_skipped"),
                         "opportunity_cost_total_r": stats.get("opportunity_cost_total_r")})
    return html.Div([
        PHASE8_BANNER,
        html.H4("Aggressive trend-only mode: ALL_REGIMES vs TREND_ONLY vs STRONG_TREND_ONLY (trend_pullback)"),
        make_table(_round_df(pd.DataFrame(rows)), "trend-only-table", page_size=30),
    ])


def strategy_selector_tab():
    if not strategy_selector_comparison:
        return html.Div("No strategy selector comparison data.")
    rows = []
    for r in strategy_selector_comparison:
        sym = r["symbol"]
        for mode in ("ALWAYS_ON", "RANDOM_SELECTION", "REGIME_SELECTOR"):
            stats = r.get(mode, {})
            rows.append({"symbol": sym, "mode": mode, "n": stats.get("n"), "win_rate": stats.get("win_rate"),
                         "expectancy_r": stats.get("expectancy_r"), "profit_factor": stats.get("profit_factor"),
                         "sharpe": stats.get("sharpe"), "keep_rate": stats.get("keep_rate")})
    return html.Div([
        PHASE8_BANNER,
        html.H4("Strategy selection engine vs. random selection (matched keep-rate) vs. always-on"),
        make_table(_round_df(pd.DataFrame(rows)), "selector-table", page_size=30),
    ])


def no_trade_funnel_tab():
    if not no_trade_funnel:
        return html.Div("No no-trade funnel data.")
    df = pd.DataFrame(no_trade_funnel)
    keep = ["symbol", "strategy", "n_candidates", "n_filtered", "n_confirmed_but_not_triggered",
            "n_executed", "n_win", "n_loss", "filtered_rate", "confirmation_failure_rate", "execution_rate"]
    keep = [c for c in keep if c in df.columns]
    return html.Div([
        PHASE8_BANNER,
        html.H4("No-trade funnel: CANDIDATES -> FILTERED -> CONFIRMED -> EXECUTED -> WIN/LOSS"),
        make_table(_round_df(df[keep]), "funnel-table", page_size=30),
        html.H4("Rejection reason detail (per row, see filtered_reasons / confirmation_pending_reasons in raw JSON)"),
        html.P(f"{RESULTS_DIR_8}/no_trade_funnel.json has the full per-cell rejection-reason breakdown.",
               style={"fontSize": "12px", "color": "#666"}),
    ])


def robustness_oos_mutation_tab():
    plateau_summary = robustness_perturbation.get("summary", {})
    rows = robustness_perturbation.get("rows", [])
    mutation_rows = mutation_tests
    return html.Div([
        PHASE8_BANNER,
        html.H4("Parameter-perturbation robustness (trend_pullback x XAUUSD, the Phase 7 EDGE_ESTABLISHED cell)"),
        html.P(f"Verdict: {plateau_summary.get('verdict', 'N/A')} -- "
               f"{plateau_summary.get('fraction_positive_expectancy', 0):.0%} of {plateau_summary.get('n_configs_with_enough_trades', 0)} "
               f"nearby parameter configurations retained positive expectancy."),
        make_table(_round_df(pd.DataFrame(rows)), "robustness-table", page_size=30) if rows else html.Div("No data."),
        html.H4("Locked out-of-sample test (frozen model, fresh seed, run once, reported as-is)"),
        html.Pre(json.dumps(out_of_sample_locked, indent=2, default=str), style={"fontSize": "12px"}),
        html.H4("Mutation testing (each row: was the intentional bug detected?)"),
        make_table(pd.DataFrame(mutation_rows), "mutation-table") if mutation_rows else html.Div("No data."),
    ])


# =========================================================== Phase 9B tabs
PHASE9B_BANNER = html.Div(
    "PHASE 9B -- opening_range_v2 (1UP/2DOWN) state machine: explicit OR_CREATED->...->TRADE_EXECUTED states, "
    "genuine M15 (OR) -> M5 (confirmation) -> M1 (entry) timeframe separation, and a directional bias-hierarchy "
    "check that never assumes direction from a boundary break alone. Still 100% synthetic data.",
    style={"background": "#eee7ff", "border": "1px solid #8a63d2", "padding": "6px 12px",
           "marginBottom": "8px", "fontSize": "12px", "fontFamily": "sans-serif"},
)


def or_v2_matrix_tab():
    if not or_v2_matrix:
        return html.Div("No Phase 9B OR v2 matrix data -- run research/run_experiments_phase9b.py first.")
    df = pd.DataFrame(or_v2_matrix)
    keep = ["symbol", "entry_family", "n", "win_rate", "expectancy_r", "profit_factor", "sharpe",
            "max_drawdown_r", "verdict", "bh_fdr_survives", "n_rejected_candidates"]
    keep = [c for c in keep if c in df.columns]
    agg_cols = [c for c in NUMERIC_COLS_TO_ROUND if c in df.columns]
    agg = _round_df(df.groupby("entry_family")[agg_cols].mean(numeric_only=True).reset_index()) if agg_cols else pd.DataFrame()
    return html.Div([
        PHASE9B_BANNER,
        html.H4("OR v2 matrix -- aggregated by entry family (breakout / retest / reversal)"),
        make_table(agg, "or-v2-agg-table") if not agg.empty else html.Div("No data."),
        html.H4("OR v2 matrix -- detail per symbol x family (walk-forward/purge summary in raw JSON)"),
        make_table(_round_df(df[keep]), "or-v2-detail-table", page_size=30),
    ])


def no_trade_funnel_v2_tab():
    if not no_trade_funnel_v2:
        return html.Div("No Phase 9B no-trade funnel data.")
    df = pd.DataFrame(no_trade_funnel_v2)
    return html.Div([
        PHASE9B_BANNER,
        html.H4("13-stage no-trade funnel: session -> regime -> bias -> structure -> liquidity -> "
                "breakout -> M5 confirm -> M1 trigger -> SL -> RR -> risk -> overlap -> EXECUTE"),
        html.P("Ranging markets and every rejection stage are recorded, never silently discarded -- "
               "rejections_by_stage/rejection_pct_by_stage in the raw JSON show exactly where each family's "
               "candidates are lost."),
        make_table(_round_df(pd.DataFrame([
            {"symbol": r["symbol"], "entry_family": r["entry_family"], "n_candidates": r["n_candidates"],
             "n_executed": r["n_executed"], "execution_rate": r["execution_rate"],
             **{f"rej_{k}": v for k, v in r.get("rejections_by_stage", {}).items()}}
            for r in no_trade_funnel_v2
        ])), "funnel-v2-table", page_size=30),
    ])


def regime_gating_9b_tab():
    if not regime_gating_9b:
        return html.Div("No Phase 9B regime gating data.")
    rows = []
    for r in regime_gating_9b:
        sym = r["symbol"]
        for regime, stats in r.get("regime_breakdown_ungated", {}).items():
            rows.append({"symbol": sym, "regime": regime, "n": stats.get("n"),
                         "expectancy_r": stats.get("expectancy_r"), "win_rate": stats.get("win_rate")})
    gate_rows = []
    for r in regime_gating_9b:
        sym = r["symbol"]
        for config, stats in r.get("gate_configs", {}).items():
            gate_rows.append({"symbol": sym, "gate_config": config, "n": stats.get("n"),
                               "expectancy_r": stats.get("expectancy_r"), "gate_counts": stats.get("gate_counts")})
    return html.Div([
        PHASE9B_BANNER,
        html.H4("Regime breakdown -- ungated (breakout family, nothing discarded)"),
        make_table(_round_df(pd.DataFrame(rows)), "regime-breakdown-table", page_size=30) if rows else html.Div("No data."),
        html.H4("Gate configuration comparison: UNGATED / DIRECTION_AGREEMENT_REQUIRED / STRONG_TREND_REQUIRED"),
        make_table(_round_df(pd.DataFrame(gate_rows)), "regime-gate-config-table", page_size=30) if gate_rows else html.Div("No data."),
    ])


def fibonacci_candle_9b_tab():
    fib_rows = []
    for r in fibonacci_depth_experiment:
        sym = r["symbol"]
        fib_rows.append({"symbol": sym, "stage": "STRUCTURE_ONLY_BASELINE", "n": r["structure_only_baseline"].get("n"),
                          "mean_displacement_after": r["structure_only_baseline"].get("mean_displacement_after")})
        for bucket, stats in r.get("depth_buckets", {}).items():
            fib_rows.append({"symbol": sym, "stage": bucket, "n": stats.get("n"),
                              "mean_displacement_after": stats.get("mean_displacement_after"),
                              "distinguishable_from_baseline": stats.get("distinguishable_from_structure_only_pool")})
    candle_rows = []
    for r in candle_pattern_ablation_9b:
        sym = r["symbol"]
        for pattern, stats in r.get("results", {}).items():
            candle_rows.append({"symbol": sym, "pattern": pattern, "n": stats.get("n"),
                                 "mean_signed_return_atr": stats.get("mean_signed_return_atr"),
                                 "verdict": stats.get("verdict")})
    return html.Div([
        PHASE9B_BANNER,
        html.H4("Fibonacci retracement depth: does exact depth add information beyond known structure preservation?"),
        make_table(_round_df(pd.DataFrame(fib_rows)), "fib-depth-table", page_size=30) if fib_rows else html.Div("No data."),
        html.H4("Named candlestick patterns vs. primitive anatomy (do named patterns add information?)"),
        make_table(_round_df(pd.DataFrame(candle_rows)), "candle-ablation-table", page_size=30) if candle_rows else html.Div("No data."),
    ])


def sl_tp_cost_9b_tab():
    return html.Div([
        PHASE9B_BANNER,
        html.H4("New SL/TP models (BREAKOUT_CANDLE, OR_OPPOSITE_BOUNDARY_TARGET, LIQUIDITY_TARGET) -- breakout family"),
        make_table(_round_df(pd.DataFrame(sl_tp_v2_comparison)), "sl-tp-v2-table", page_size=30) if sl_tp_v2_comparison else html.Div("No data."),
        html.H4("Cost sensitivity: COST_NEUTRAL / BASE_COST / ADVERSE_COST / STRESS_COST -- breakout family"),
        make_table(_round_df(pd.DataFrame(cost_sensitivity_9b)), "cost-sensitivity-9b-table", page_size=30) if cost_sensitivity_9b else html.Div("No data."),
    ])


def portfolio_gating_9b_tab():
    if not portfolio_gating_9b:
        return html.Div("No Phase 9B portfolio gating data.")
    return html.Div([
        PHASE9B_BANNER,
        html.H4("Position-overlap / correlation / risk portfolio gating (breakout family, correlated symbol pairs)"),
        html.P("A candidate signal must NOT automatically become a trade -- outcome_counts breaks down "
               "EXECUTED vs BLOCKED_POSITION_OVERLAP vs BLOCKED_RISK vs BLOCKED_CORRELATION."),
        make_table(pd.DataFrame([
            {"pair": r["pair"], "n_candidates": r["n_candidates"], "n_executed": r["n_executed"],
             "execution_rate": round(r["execution_rate"], 3) if r.get("execution_rate") is not None else None,
             "final_equity": round(r["final_equity"], 2) if r.get("final_equity") is not None else None,
             **{f"outcome_{k}": v for k, v in r.get("outcome_counts", {}).items()}}
            for r in portfolio_gating_9b
        ]), "portfolio-gating-table"),
    ])


def robustness_oos_mutation_9b_tab():
    plateau_summary = robustness_perturbation_9b.get("summary", {})
    rows = robustness_perturbation_9b.get("rows", [])
    return html.Div([
        PHASE9B_BANNER,
        html.H4("Parameter-perturbation robustness (opening_range_v2 breakout x EURUSD): "
                "require_bias_agreement x sl_model x tp_model grid"),
        html.P(f"Verdict: {plateau_summary.get('verdict', 'N/A')} -- "
               f"{(plateau_summary.get('fraction_positive_expectancy') or 0):.0%} of "
               f"{plateau_summary.get('n_configs_with_enough_trades', 0)} nearby configurations "
               f"retained positive expectancy."),
        make_table(_round_df(pd.DataFrame(rows)), "robustness-9b-table", page_size=30) if rows else html.Div("No data."),
        html.H4("Locked out-of-sample test (frozen model, fresh never-reused seed, run once, reported as-is)"),
        html.Pre(json.dumps(out_of_sample_locked_9b, indent=2, default=str), style={"fontSize": "12px"}),
        html.H4("Mutation testing -- all 15 (7 Phase 8 + 8 new Phase 9B invariants)"),
        make_table(pd.DataFrame(mutation_tests_9b), "mutation-9b-table") if mutation_tests_9b else html.Div("No data."),
    ])


# ------------------------------------------------------- Decision Inspector
DECISION_INSPECTOR_FAMILIES = [f for f in ("breakout", "retest", "reversal") if decision_inspector_sample.get(f)]


def _day_summary_row(family: str, idx: int, day: dict) -> dict:
    decisions = day.get("entry_decisions", [])
    final = decisions[-1] if decisions else None
    return {
        "family": family, "row_idx": idx, "date": day.get("date"),
        "or_high": day.get("or_high"), "or_low": day.get("or_low"),
        "n_states": len(day.get("state_history", [])), "n_decisions": len(decisions),
        "final_decision": final.get("decision") if final else "NO_CANDIDATE",
        "final_blocking_code": final.get("blocking_code") if final else "",
    }


def decision_inspector_tab():
    if not DECISION_INSPECTOR_FAMILIES:
        return html.Div("No Phase 9B decision inspector sample -- run research/run_experiments_phase9b.py first.")
    return html.Div([
        PHASE9B_BANNER,
        html.H4("Decision Inspector -- WHY did the OR state machine enter, or not, on each NY session day?"),
        html.P("Select an entry family, then a day, to see the full per-day state history (every OR state "
               "transition with its timestamp) and every EntryDecision (what each timeframe knew via "
               "MARKET_CONTEXT, which bias sources agreed/conflicted, and the exact blocking code if rejected)."),
        dcc.Dropdown(
            id="decision-inspector-family",
            options=[{"label": f.upper(), "value": f} for f in DECISION_INSPECTOR_FAMILIES],
            value=DECISION_INSPECTOR_FAMILIES[0], clearable=False, style={"width": "300px", "marginBottom": "10px"},
        ),
        html.Div(id="decision-inspector-day-table"),
        html.Div(id="decision-inspector-detail", style={"marginTop": "10px", "padding": "10px", "background": "#f7f7f7",
                                                          "fontFamily": "monospace", "whiteSpace": "pre-wrap"}),
    ])


@app.callback(Output("decision-inspector-day-table", "children"), Input("decision-inspector-family", "value"))
def _render_decision_inspector_days(family):
    days = decision_inspector_sample.get(family, [])
    rows = [_day_summary_row(family, i, d) for i, d in enumerate(days)]
    df = pd.DataFrame(rows)
    return make_table(df, "decision-inspector-table", page_size=15, selectable=True)


@app.callback(
    Output("decision-inspector-detail", "children"),
    Input("decision-inspector-table", "selected_rows"),
    State("decision-inspector-family", "value"),
)
def _show_decision_detail(selected_rows, family):
    if not selected_rows:
        return "Select a day above to see its full OR state-machine history and every entry decision."
    days = decision_inspector_sample.get(family, [])
    day = days[selected_rows[0]]
    lines = [f"OR DAY {day.get('date')}  (family={family})  or_high={day.get('or_high')} or_low={day.get('or_low')}",
             "", "STATE HISTORY (every OR state transition, in order):"]
    for ev in day.get("state_history", []):
        lines.append(f"  {ev.get('timestamp')}  {ev.get('state')}  -- {ev.get('detail')}")

    for i, dec in enumerate(day.get("entry_decisions", [])):
        mc = dec.get("market_context", {}) or {}
        lines += [
            "", f"ENTRY DECISION #{i + 1}: {dec.get('decision')}  (entry_type={dec.get('entry_type')})",
            f"  Direction: {dec.get('direction')} | Confidence: {dec.get('confidence')} | Score: {dec.get('score')}",
            f"  Blocking code: {dec.get('blocking_code')}",
            f"  WHY: reasons passed = {dec.get('reasons') or '(none)'}",
            f"       failed conditions = {dec.get('failed_conditions') or '(none)'}",
            "  WHAT EACH TIMEFRAME KNEW (MARKET_CONTEXT as-of this decision):",
            f"    HTF bias={mc.get('htf_bias')} (confidence={mc.get('bias_confidence')}) | "
            f"regime={mc.get('market_regime')} | trend={mc.get('trend_state')} | volatility={mc.get('volatility_state')}",
            f"    External structure={mc.get('swing_structure')} | Internal structure={mc.get('internal_structure')} | "
            f"last BOS/CHOCH={mc.get('last_bos_or_choch')}",
            f"    Protected high={mc.get('protected_high')} | Protected low={mc.get('protected_low')} | "
            f"Liquidity state={mc.get('liquidity_state')}",
            f"    OR state={mc.get('or_state')} OR_high={mc.get('or_high')} OR_low={mc.get('or_low')} | "
            f"price_location={mc.get('price_location_vs_or')}",
            f"    ATR={mc.get('atr')} | Spread={mc.get('spread')} | Cost assumption: {mc.get('cost_assumption')}",
            f"  Confirmation ts: {dec.get('confirmation_timestamp')} | Entry ts: {dec.get('entry_timestamp')} | "
            f"Risk state: {dec.get('risk_state')}",
        ]
    return "\n".join(lines)


app.layout = html.Div([
    DISCLAIMER,
    html.H2("Multi-Strategy Hedge Backtest Terminal (Research / Synthetic Data)"),
    dcc.Tabs([
        dcc.Tab(label="Candle Replay", children=[replay_tab]),
        dcc.Tab(label="Strategy Comparison", children=[strategy_tab()]),
        dcc.Tab(label="Pair x Strategy x Regime", children=[regime_detail_tab()]),
        dcc.Tab(label="Entry Comparison", children=[entry_comparison_tab()]),
        dcc.Tab(label="SL Comparison", children=[comparison_tab(sl_comparison, "sl_model", "Stop-Loss Models")]),
        dcc.Tab(label="TP Comparison", children=[comparison_tab(tp_comparison, "tp_model", "Take-Profit Models")]),
        dcc.Tab(label="Exit Comparison", children=[exit_tab()]),
        dcc.Tab(label="Risk / Lot Size", children=[risk_tab()]),
        dcc.Tab(label="Hedge / Portfolio", children=[hedge_tab()]),
        dcc.Tab(label="Feature Ablation", children=[ablation_tab()]),
        dcc.Tab(label="Trade Inspector", children=[trade_inspector_tab()]),
        dcc.Tab(label="Data Quality / Audit", children=[data_quality_tab()]),
        dcc.Tab(label="[P8] Corrected Matrix", children=[corrected_matrix_tab()]),
        dcc.Tab(label="[P8] Directional Bias", children=[bias_tab()]),
        dcc.Tab(label="[P8] Negative Controls", children=[negative_controls_tab()]),
        dcc.Tab(label="[P8] Ablation Matrix", children=[ablation_matrix_tab()]),
        dcc.Tab(label="[P8] Hedge Correlation", children=[hedge_correlation_tab()]),
        dcc.Tab(label="[P8] Trend-Only Mode", children=[trend_only_tab()]),
        dcc.Tab(label="[P8] Strategy Selector", children=[strategy_selector_tab()]),
        dcc.Tab(label="[P8] No-Trade Funnel", children=[no_trade_funnel_tab()]),
        dcc.Tab(label="[P8] Robustness/OOS/Mutation", children=[robustness_oos_mutation_tab()]),
        dcc.Tab(label="[P9B] OR v2 Matrix", children=[or_v2_matrix_tab()]),
        dcc.Tab(label="[P9B] Decision Inspector", children=[decision_inspector_tab()]),
        dcc.Tab(label="[P9B] No-Trade Funnel (13-stage)", children=[no_trade_funnel_v2_tab()]),
        dcc.Tab(label="[P9B] Regime Gating", children=[regime_gating_9b_tab()]),
        dcc.Tab(label="[P9B] Fibonacci Depth / Candle Ablation", children=[fibonacci_candle_9b_tab()]),
        dcc.Tab(label="[P9B] SL/TP v2 / Cost Sensitivity", children=[sl_tp_cost_9b_tab()]),
        dcc.Tab(label="[P9B] Portfolio Gating", children=[portfolio_gating_9b_tab()]),
        dcc.Tab(label="[P9B] Robustness/OOS/Mutation", children=[robustness_oos_mutation_9b_tab()]),
    ]),
])


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
