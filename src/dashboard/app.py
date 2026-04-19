"""Dash dashboard: equity curve, open positions, trade history, log feed."""
from __future__ import annotations

from typing import Dict

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, dash_table, dcc, html

from .state import DashboardState

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
