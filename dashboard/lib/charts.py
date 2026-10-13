"""Plotly figures shared across pages. Colors come only from theme."""

from __future__ import annotations

import plotly.graph_objects as go

from . import theme
from .models import Driver, Forecast


def driver_bars(drivers: list[Driver], height: int | None = None, title: str = "Why (longer bar = bigger reason)") -> go.Figure:
    """Horizontal bars of contribution_logodds, colored by support level. Positive = pushes risk up."""
    ds = sorted(drivers, key=lambda d: d.contribution_logodds)
    fig = go.Figure()
    seen: set[str] = set()
    for d in ds:
        sup = theme.SUPPORT.get(d.support_level, theme.SUPPORT["supported"])
        fig.add_trace(
            go.Bar(
                x=[d.contribution_logodds],
                y=[d.title],
                orientation="h",
                marker=dict(color=sup["color"], cornerradius=4),
                name=sup["label"],
                legendgroup=d.support_level,
                showlegend=d.support_level not in seen,
                marker_pattern_shape="/" if d.support_level != "supported" else "",
                hovertemplate=f"<b>{theme.esc(d.title)}</b><br>{theme.esc(d.reason)}<br>{sup['label']}<extra></extra>",
            )
        )
        seen.add(d.support_level)
    fig.add_vline(x=0, line_color="#c3c2b7", line_width=1)
    fig.update_layout(barmode="overlay", bargap=0.45, title=title)
    theme.style_fig(fig, height or max(160, 64 * len(ds) + 70))
    fig.update_xaxes(title=None, showticklabels=False)
    return fig


def forecast_band(fc: Forecast, height: int = 300, total_rooms: int | None = None) -> go.Figure:
    x = [d.date for d in fc.days]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x + x[::-1],
            y=[d.high for d in fc.days] + [d.low for d in fc.days][::-1],
            fill="toself",
            fillcolor="rgba(42,120,214,0.16)",
            line=dict(width=0),
            hoverinfo="skip",
            name="likely range",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[d.mean for d in fc.days],
            mode="lines+markers",
            name="rooms full (expected)",
            line=dict(color="#2a78d6", width=2),
            marker=dict(size=8, color="#2a78d6", line=dict(color="#fff", width=2)),
            customdata=[[d.low, d.high] for d in fc.days],
            hovertemplate="%{x|%a %d %b}<br>about %{y:.0%} full<br>likely %{customdata[0]:.0%} – %{customdata[1]:.0%}<extra></extra>",
        )
    )
    hi = [d for d in fc.days if d.high_demand_alert]
    lo = [d for d in fc.days if d.low_demand_alert]
    if hi:
        fig.add_trace(
            go.Scatter(
                x=[d.date for d in hi],
                y=[d.mean for d in hi],
                mode="markers",
                name="very busy day",
                marker=dict(symbol="triangle-up", size=13, color=theme.BAND["high"]["dot"], line=dict(color="#fff", width=2)),
            )
        )
    if lo:
        fig.add_trace(
            go.Scatter(
                x=[d.date for d in lo],
                y=[d.mean for d in lo],
                mode="markers",
                name="quiet day",
                marker=dict(symbol="triangle-down", size=13, color=theme.BAND["watch"]["dot"], line=dict(color="#fff", width=2)),
            )
        )
    theme.style_fig(fig, height)
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    fig.update_xaxes(tickformat="%a %d")
    return fig
