"""
ui_bars.py
----------
Drop-in HP/AP/SP bar rendering for Journey to Winter Haven, built on `rich`.

Usage:
    from ui_bars import hp_line, ap_line, stat_bar

    print(hp_line("Saeculum", hero.hp, hero.max_hp))
    print(hp_line(enemy.display_name.title(), enemy.hp, enemy.max_hp, icon="❤️"))
    print(ap_line(hero.ap, hero.max_ap))

Falls back to plain "current/max" text if rich isn't installed, so this
module is always safe to import even before requirements.txt is run.
"""

try:
    from rich.console import Console
    _console = Console()
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


def _pct_color(pct, side="hero"):
    """
    Identity-first, urgency-aware color scheme:
    - Enemies: always shades of red (bright when healthy, deep red near death) —
      they're "the threat", so no health-state read is needed.
    - Heroes: blue while healthy/wounded, flips to red under 25% HP as a
      critical low-health warning (keeps the classic "uh oh" cue).
    """
    if side == "enemy":
        if pct > 0.5:
            return "red1"
        elif pct > 0.25:
            return "red3"
        else:
            return "dark_red"
    else:  # hero
        if pct > 0.5:
            return "dodger_blue1"
        elif pct > 0.25:
            return "steel_blue1"
        else:
            return "red1"


def stat_bar(current, maximum, *, width=20, color=None, empty_char="░", fill_char="█", side="hero"):
    """
    Build a bar string like: [dodger_blue1]████████████[/dodger_blue1][grey37]░░░░[/grey37]
    Returns a rich markup string — pass to hp_line/ap_line or print via rich console.
    """
    maximum = max(maximum, 1)  # avoid div/0 on bugged max stats
    pct = max(0.0, min(1.0, current / maximum))
    filled = int(width * pct)
    bar_color = color or _pct_color(pct, side)
    return f"[{bar_color}]{fill_char * filled}[/{bar_color}][grey37]{empty_char * (width - filled)}[/grey37]"


def _render(label, current, maximum, icon, width, color, side="hero"):
    bar = stat_bar(current, maximum, width=width, color=color, side=side)
    markup = f"{icon} {label} {bar} {current}/{maximum}"
    if _HAS_RICH:
        with _console.capture() as cap:
            _console.print(markup, end="")
        return cap.get()
    # Plain fallback — matches old print format exactly
    return f"{icon} {label} HP: {current}/{maximum}"


def hp_line(label, current, maximum, *, icon="❤️", width=20, color=None, side="hero"):
    return _render(label, current, maximum, icon, width, color, side=side)


def ap_line(current, maximum, *, label="AP", icon="🔷", width=20, color="cyan"):
    return _render(label, current, maximum, icon, width, color)


def sp_line(current, maximum, *, label="SP", icon="💠", width=20, color="magenta"):
    return _render(label, current, maximum, icon, width, color)
