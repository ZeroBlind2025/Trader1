"""Dash dashboard: equity curve, open positions, trade history, log feed."""
from __future__ import annotations

import logging
import threading
from typing import Dict

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dash_table, dcc, html, no_update

from .state import DashboardState

log = logging.getLogger(__name__)

DARK_BG = "#0e1117"
CARD_BG = "#161b22"
ACCENT = "#39d98a"
DANGER = "#ff4d4f"
MUTED = "#9aa4b2"


def _fmt_money(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _pnl_style(v: float) -> Dict:
    return {"color": ACCENT if v >= 0 else DANGER, "fontWeight": 600}


def build_app(state: DashboardState) -> dash.Dash:
    app = dash.Dash(__name__, title="Momentum Scalper")
    app.layout = html.Div(
        style={
            "backgroundColor": DARK_BG,
            "color": "#e6edf3",
            "minHeight": "100vh",
            "fontFamily": "JetBrains Mono, Menlo, monospace",
            "padding": "12px",
        },
        children=[
            # -------- TOP BAR --------
            html.Div(
                id="top-bar",
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(5, 1fr)",
                    "gap": "12px",
                    "marginBottom": "12px",
                },
            ),
            # -------- MIDDLE ROW --------
            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "1.3fr 1fr",
                    "gap": "12px",
                    "marginBottom": "12px",
                },
                children=[
                    html.Div(
                        style={"backgroundColor": CARD_BG, "padding": "12px", "borderRadius": "8px"},
                        children=[
                            html.H4("Equity Curve", style={"margin": "0 0 8px 0"}),
                            dcc.Graph(id="equity-graph", config={"displayModeBar": False}),
                        ],
                    ),
                    html.Div(
                        style={"backgroundColor": CARD_BG, "padding": "12px", "borderRadius": "8px"},
                        children=[
                            html.H4("Open Positions", style={"margin": "0 0 8px 0"}),
                            html.Div(id="positions-table"),
                        ],
                    ),
                ],
            ),
            # -------- BOTTOM ROW --------
            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "1.3fr 1fr",
                    "gap": "12px",
                },
                children=[
                    html.Div(
                        style={"backgroundColor": CARD_BG, "padding": "12px", "borderRadius": "8px"},
                        children=[
                            html.H4("Trade History", style={"margin": "0 0 8px 0"}),
                            html.Div(id="trades-table"),
                        ],
                    ),
                    html.Div(
                        style={"backgroundColor": CARD_BG, "padding": "12px", "borderRadius": "8px"},
                        children=[
                            html.H4("Log Feed", style={"margin": "0 0 8px 0"}),
                            html.Div(
                                id="log-feed",
                                style={
                                    "maxHeight": "320px",
                                    "overflowY": "auto",
                                    "fontSize": "12px",
                                    "lineHeight": "1.4",
                                },
                            ),
                        ],
                    ),
                ],
            ),
            # -------- BACKTEST ROW --------
            html.Div(
                style={
                    "backgroundColor": CARD_BG,
                    "padding": "12px",
                    "borderRadius": "8px",
                    "marginTop": "12px",
                },
                children=[
                    html.Div(
                        style={
                            "display": "flex",
                            "alignItems": "center",
                            "justifyContent": "space-between",
                            "marginBottom": "8px",
                        },
                        children=[
                            html.H4("5-Year Backtest", style={"margin": 0}),
                            html.Div(
                                style={"display": "flex", "alignItems": "center", "gap": "12px"},
                                children=[
                                    html.Span(id="backtest-status", style={"color": MUTED, "fontSize": "12px"}),
                                    html.Button(
                                        "Run Backtest",
                                        id="run-backtest-btn",
                                        n_clicks=0,
                                        style={
                                            "backgroundColor": ACCENT,
                                            "color": "#0e1117",
                                            "border": "none",
                                            "padding": "8px 18px",
                                            "borderRadius": "6px",
                                            "fontWeight": 700,
                                            "fontFamily": "JetBrains Mono, monospace",
                                            "cursor": "pointer",
                                        },
                                    ),
                                ],
                            ),
                        ],
                    ),
                    html.Div(id="backtest-grid"),
                ],
            ),
            dcc.Interval(id="tick", interval=2_000, n_intervals=0),
        ],
    )

    # ---------- callbacks ------------------------------------------------
    def _card(label: str, value: str, color: str = "#e6edf3") -> html.Div:
        return html.Div(
            style={
                "backgroundColor": CARD_BG,
                "padding": "12px",
                "borderRadius": "8px",
            },
            children=[
                html.Div(label, style={"color": MUTED, "fontSize": "11px", "textTransform": "uppercase"}),
                html.Div(value, style={"color": color, "fontSize": "22px", "fontWeight": 700}),
            ],
        )

    @app.callback(Output("top-bar", "children"), Input("tick", "n_intervals"))
    def _update_top(_):
        h = state.header()
        badge = (
            html.Span(f"HALTED • {h['halt_reason']}", style={"color": DANGER, "fontWeight": 700})
            if h["halted"]
            else html.Span("LIVE", style={"color": ACCENT, "fontWeight": 700})
        )
        return [
            _card("Equity", _fmt_money(h["equity"])),
            _card("Day PnL", _fmt_money(h["day_pnl"]), ACCENT if h["day_pnl"] >= 0 else DANGER),
            _card("Total PnL", _fmt_money(h["total_pnl"]), ACCENT if h["total_pnl"] >= 0 else DANGER),
            _card("Positions", f"{h['open']}/{h['resolved']}"),
            html.Div(
                style={"backgroundColor": CARD_BG, "padding": "12px", "borderRadius": "8px"},
                children=[
                    html.Div("Status", style={"color": MUTED, "fontSize": "11px", "textTransform": "uppercase"}),
                    html.Div(badge, style={"fontSize": "20px"}),
                    html.Div(f"Universe: {h['universe']}", style={"color": MUTED, "fontSize": "11px"}),
                ],
            ),
        ]

    @app.callback(Output("equity-graph", "figure"), Input("tick", "n_intervals"))
    def _update_curve(_):
        curve = state.equity_curve
        if not curve:
            df = pd.DataFrame({"ts": [], "equity": []})
        else:
            df = pd.DataFrame(curve)
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=df["ts"],
                y=df["equity"],
                mode="lines",
                line=dict(color=ACCENT, width=2),
                fill="tozeroy",
                fillcolor="rgba(57,217,138,0.08)",
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>$%{y:,.2f}<extra></extra>",
            )
        )
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor=CARD_BG,
            plot_bgcolor=CARD_BG,
            margin=dict(l=30, r=10, t=10, b=30),
            height=320,
            xaxis=dict(showgrid=False),
            yaxis=dict(gridcolor="#222", tickprefix="$", tickformat=",.0f"),
        )
        return fig

    def _table(df: pd.DataFrame, pnl_cols: list[str]) -> dash_table.DataTable:
        style_cond = []
        for col in pnl_cols:
            if col in df.columns:
                style_cond.extend(
                    [
                        {"if": {"filter_query": f"{{{col}}} > 0", "column_id": col}, "color": ACCENT},
                        {"if": {"filter_query": f"{{{col}}} < 0", "column_id": col}, "color": DANGER},
                    ]
                )
        return dash_table.DataTable(
            data=df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in df.columns],
            style_header={
                "backgroundColor": "#1f2630",
                "color": MUTED,
                "fontWeight": "bold",
                "textTransform": "uppercase",
                "fontSize": "11px",
            },
            style_cell={
                "backgroundColor": CARD_BG,
                "color": "#e6edf3",
                "fontFamily": "JetBrains Mono, monospace",
                "fontSize": "12px",
                "padding": "6px",
                "border": "1px solid #222",
            },
            style_data_conditional=style_cond,
            page_size=20,
        )

    @app.callback(Output("positions-table", "children"), Input("tick", "n_intervals"))
    def _update_positions(_):
        rows = state.open_positions
        if not rows:
            return html.Div("No open positions", style={"color": MUTED, "padding": "24px 0"})
        df = pd.DataFrame(rows)
        return _table(df, pnl_cols=["pnl_usd", "pnl_pct"])

    @app.callback(Output("trades-table", "children"), Input("tick", "n_intervals"))
    def _update_trades(_):
        rows = state.trade_history
        if not rows:
            return html.Div("No closed trades yet", style={"color": MUTED, "padding": "24px 0"})
        df = pd.DataFrame(rows)
        return _table(df, pnl_cols=["pnl_usd", "pnl_pct"])

    def _run_backtest_async() -> None:
        """Daemon-thread worker. Imports lazily so Dash startup stays cheap."""
        from src.backtest.runner import run_backtest

        state.set_backtest_status("running")
        try:
            result = run_backtest(starting_equity=state.starting_equity or 100_000.0)
            state.set_backtest_summary(result.summary())
        except Exception as exc:  # noqa: BLE001
            log.exception("Backtest failed")
            state.set_backtest_status("error", error=str(exc))

    @app.callback(
        Output("run-backtest-btn", "disabled"),
        Input("run-backtest-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def _on_run_backtest(n_clicks):
        if not n_clicks:
            return no_update
        current = state.get_backtest()["status"]
        if current == "running":
            return True
        threading.Thread(target=_run_backtest_async, daemon=True).start()
        return True

    @app.callback(
        Output("backtest-grid", "children"),
        Output("backtest-status", "children"),
        Output("run-backtest-btn", "disabled", allow_duplicate=True),
        Input("tick", "n_intervals"),
        prevent_initial_call="initial_duplicate",
    )
    def _update_backtest(_):
        bt = state.get_backtest()
        status = bt["status"]
        summary = bt["summary"]
        disabled = status == "running"

        if status == "idle":
            label = "Click Run Backtest to execute a 5-year sim"
        elif status == "running":
            label = "Running backtest… (this can take 30-90s)"
        elif status == "error":
            label = f"Error: {bt['error']}"
        else:
            label = "Last run complete"

        if not summary:
            grid = html.Div(
                "No backtest results yet",
                style={"color": MUTED, "padding": "16px 0"},
            )
        else:
            cells = []
            for name, value in summary.items():
                color = "#e6edf3"
                if name in ("Total PnL", "Total Return", "CAGR"):
                    raw = value.replace("$", "").replace(",", "").replace("%", "").strip()
                    try:
                        color = ACCENT if float(raw) >= 0 else DANGER
                    except ValueError:
                        color = "#e6edf3"
                elif name == "Max DD":
                    color = DANGER
                cells.append(
                    html.Div(
                        style={
                            "backgroundColor": "#1f2630",
                            "padding": "10px 12px",
                            "borderRadius": "6px",
                            "border": "1px solid #222",
                        },
                        children=[
                            html.Div(
                                name,
                                style={
                                    "color": MUTED,
                                    "fontSize": "10px",
                                    "textTransform": "uppercase",
                                    "letterSpacing": "0.5px",
                                },
                            ),
                            html.Div(
                                value,
                                style={"color": color, "fontSize": "18px", "fontWeight": 700, "marginTop": "4px"},
                            ),
                        ],
                    )
                )
            grid = html.Div(
                cells,
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(6, 1fr)",
                    "gap": "8px",
                },
            )

        return grid, label, disabled

    @app.callback(Output("log-feed", "children"), Input("tick", "n_intervals"))
    def _update_logs(_):
        level_colors = {"INFO": "#e6edf3", "WARNING": "#f4c04e", "ERROR": DANGER, "DEBUG": MUTED}
        lines = []
        for ll in state.logs():
            lines.append(
                html.Div(
                    [
                        html.Span(ll.ts.strftime("%H:%M:%S "), style={"color": MUTED}),
                        html.Span(f"[{ll.level}] ", style={"color": level_colors.get(ll.level, MUTED)}),
                        html.Span(ll.msg),
                    ]
                )
            )
        return lines or html.Div("No log lines yet", style={"color": MUTED})

    return app
