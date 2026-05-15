"""Plotly chart helpers"""
import plotly.express as px


def line_chart(df, x, y, title: str = ""):
    fig = px.line(df, x=x, y=y, title=title)
    return fig
