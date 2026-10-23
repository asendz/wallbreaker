from __future__ import annotations

from textual.theme import Theme

WB_THEME = Theme(
    name="wallbreaker",
    primary="#FFD400",
    secondary="#FF7A00",
    accent="#39FF14",
    success="#39FF14",
    warning="#FF9500",
    error="#FF2020",
    surface="#151007",
    panel="#1E1708",
    background="#0A0805",
    dark=True,
    variables={
        "block-cursor-background": "#39FF14",
        "block-cursor-foreground": "#0A0805",
        "input-selection-background": "#FFD400 35%",
        "scrollbar": "#1E1708",
        "scrollbar-hover": "#FFD400",
        "scrollbar-active": "#39FF14",
        "border": "#4A3A0F",
        "border-blurred": "#2E2408",
        "verdict-good": "#39FF14",
        "verdict-partial": "#FFD400",
        "verdict-bad": "#FF2B2B",
        "field-label": "#A89A5C",
        "feedback": "#FF43D4",
    },
)

PALETTE = {
    "user": "#5EF2FF",
    "assistant": "#B6FF00",
    "tool_call": "#FF9124",
    "tool_result": "#FFD24D",
    "info": "#6FD3FF",
    "error": "#FF2B2B",
    "feedback": "#FF43D4",
    "label": "#FFD400",
    "muted": "#A89A5C",
    "accent": "#39FF14",
    "secondary": "#FF7A00",
    "brand": "#FFD400",
    "verdict_good": "#39FF14",
    "verdict_partial": "#FFD400",
    "verdict_bad": "#FF2B2B",
}
