"""
combat_log.py
-------------
Standalone combat logging module for Journey to Winter Haven.

Exports:
    COMBAT_LOG          — the list that stores all entries for the current run
    log(msg)            — prints msg to screen AND appends it to COMBAT_LOG
    log_attack          — logs a detailed attack line, tracks basic vs special dmg
    log_dot             — tracks DoT damage for battle summary
    log_battle_summary  — prints+logs stat block at battle end, accumulates run score
    reset_battle_stats  — zeroes per-battle accumulators (call at battle start)
    show_run_score      — prints grand total score at end of demo run
    view_combat_log     — paginated display of COMBAT_LOG
"""

import os
import textwrap

_LOG_WIDTH = 65


def _wrap(text):
    if not isinstance(text, str):
        text = str(text)
    stripped = text.lstrip()
    indent   = text[: len(text) - len(stripped)]
    return textwrap.fill(
        text,
        width=_LOG_WIDTH,
        initial_indent="",
        subsequent_indent=indent + "  ",
        break_long_words=False,
        replace_whitespace=False,
    )


COMBAT_LOG = []

_battle_stats = {
    "player_dmg_dealt":    0,
    "player_basic_dmg":    0,
    "player_special_dmg":  0,
    "player_dmg_blocked":  0,
    "enemy_dmg_dealt":     0,
    "enemy_dmg_blocked":   0,
    "player_turns":        0,
    "enemy_turns":         0,
    "dot_dmg_to_enemy":    0,
    "dot_dmg_to_player":   0,
}

_run_stats = {
    "total_dmg_dealt":    0,
    "total_basic_dmg":    0,
    "total_special_dmg":  0,
    "total_dmg_blocked":  0,
    "total_dot_dealt":    0,
    "fights_won":         0,
    "fights_lost":        0,
    "total_turns":        0,
}


def _clear_screen():
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")


def log(msg=""):
    print(msg)
    COMBAT_LOG.append(msg)


def reset_battle_stats():
    for key in _battle_stats:
        _battle_stats[key] = 0


def log_attack(
    actor,
    target,
    roll,
    actual,
    blocked,
    *,
    bonus_parts=None,
    effect_tag="",
    is_player=True,
    is_special=False,
):
    parts_str = f"  ({', '.join(bonus_parts)})" if bonus_parts else ""
    block_str = f"  [Blocked {blocked}]" if blocked > 0 else ""
    fx_str    = f"  {effect_tag}" if effect_tag else ""
    atk_type  = "[SPECIAL]" if is_special else "[ATTACK]"

    raw = (
        f"  {atk_type} {actor} -> {target}: "
        f"{actual} dmg (roll {roll}){block_str}{parts_str}{fx_str}"
    )
    COMBAT_LOG.append(_wrap(raw))

    if is_player:
        _battle_stats["player_dmg_dealt"]   += actual
        _battle_stats["player_dmg_blocked"] += blocked
        _battle_stats["player_turns"]       += 1
        if is_special:
            _battle_stats["player_special_dmg"] += actual
        else:
            _battle_stats["player_basic_dmg"]   += actual
    else:
        _battle_stats["enemy_dmg_dealt"]    += actual
        _battle_stats["enemy_dmg_blocked"]  += blocked
        _battle_stats["enemy_turns"]        += 1


def log_dot(target_name, amount, *, is_player_target=True):
    if is_player_target:
        _battle_stats["dot_dmg_to_player"] += amount
    else:
        _battle_stats["dot_dmg_to_enemy"]  += amount
        _run_stats["total_dot_dealt"]      += amount


def log_battle_summary(warrior_name, enemy_name, outcome, turns):
    s = _battle_stats
    total = s["player_dmg_dealt"]
    basic = s["player_basic_dmg"]
    spec  = s["player_special_dmg"]

    lines = [
        "",
        "=" * 40,
        f"BATTLE SUMMARY -- {outcome}",
        f"  {warrior_name} vs {enemy_name}  ({turns} turns)",
        "-" * 40,
        _wrap(f"  Total dealt    : {total} dmg  (blocked {s['player_dmg_blocked']})"),
        _wrap(f"    Basic attacks : {basic} dmg"),
        _wrap(f"    Specials      : {spec} dmg"),
    ]
    if s["dot_dmg_to_enemy"]:
        lines.append(_wrap(f"    DoT to {enemy_name}  : {s['dot_dmg_to_enemy']} dmg"))
    lines.append(
        _wrap(f"  {enemy_name} dealt  : {s['enemy_dmg_dealt']} dmg "
              f"(blocked {s['enemy_dmg_blocked']})")
    )
    if s["dot_dmg_to_player"]:
        lines.append(_wrap(f"  DoT to {warrior_name} : {s['dot_dmg_to_player']} dmg"))
    lines.append("=" * 40)

    for line in lines:
        log(line)

    _run_stats["total_dmg_dealt"]   += total
    _run_stats["total_basic_dmg"]   += basic
    _run_stats["total_special_dmg"] += spec
    _run_stats["total_dmg_blocked"] += s["player_dmg_blocked"]
    _run_stats["total_turns"]       += turns
    if outcome == "VICTORY":
        _run_stats["fights_won"]  += 1
    else:
        _run_stats["fights_lost"] += 1

    reset_battle_stats()


def show_run_score(warrior_name="Hero"):
    r = _run_stats
    total   = r["total_dmg_dealt"]
    basic   = r["total_basic_dmg"]
    spec    = r["total_special_dmg"]
    dot     = r["total_dot_dealt"]
    blocked = r["total_dmg_blocked"]
    won     = r["fights_won"]
    lost    = r["fights_lost"]
    turns   = r["total_turns"]

    basic_pct = int((basic / total * 100)) if total > 0 else 0
    spec_pct  = int((spec  / total * 100)) if total > 0 else 0
    dot_pct   = int((dot   / total * 100)) if total > 0 else 0

    print()
    print("=" * 50)
    print(f"  RUN SCORE -- {warrior_name}")
    print("=" * 50)
    print(f"  Fights Won     : {won}   Lost: {lost}")
    print(f"  Total Turns    : {turns}")
    print(f"  Total Damage   : {total}")
    print(f"    Basic Attacks: {basic}  ({basic_pct}%)")
    print(f"    Specials     : {spec}  ({spec_pct}%)")
    if dot > 0:
        print(f"    DoT          : {dot}  ({dot_pct}%)")
    print(f"  Damage Blocked : {blocked}")
    print("=" * 50)
    input("\nPress Enter to continue...")


def view_combat_log():
    PAGE_SIZE = 20
    entries = COMBAT_LOG if COMBAT_LOG else ["(No combat recorded yet)"]
    total = len(entries)
    page = 0
    total_pages = max(1, -(-total // PAGE_SIZE))

    while True:
        _clear_screen()
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        print(f"======== COMBAT LOG  (Page {page + 1}/{total_pages} | {total} entries) ========")
        for entry in entries[start:end]:
            print(entry)
        print("=" * 50)

        if total_pages == 1:
            input("\nPress Enter to continue...")
            return

        nav = []
        if page > 0:
            nav.append("P) Prev")
        if page < total_pages - 1:
            nav.append("N) Next")
        nav.append("Q) Quit log")
        print("  ".join(nav))

        choice = input("\n> ").strip().lower()
        if choice == "n" and page < total_pages - 1:
            page += 1
        elif choice == "p" and page > 0:
            page -= 1
        elif choice == "q":
            return
