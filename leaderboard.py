"""
Journey to Winter Haven — Leaderboard System

Stores the top 10 runs across all play sessions in a local scores.json file.
At end of each run, the player's score is compared to the board:
  - If they made the top 10, they're shown highlighted in the board
  - If not, they see the board plus their result with placement below

Module entry points:
  record_run(warrior, score, outcome)           — call at end of run
  show_leaderboard(highlight_entry=None)        — display top 10
  display_at_end_of_run(warrior, score, outcome)— combined: record + show

Data file format (scores.json):
  [
    {
      "name": "Nathan",
      "score": 4250,
      "rank": "A",
      "outcome": "chimera_victory",
      "level": 5,
      "stats": {
        "hp":      47,
        "max_hp":  52,
        "atk_min": 8,
        "atk_max": 14,
        "defence": 9,
        "max_ap":  5,
        "gold":    340
      },
      "date": "2026-05-18"
    },
    ...
  ]

Note: entries written before v0.6.18 have no "rank" field. The display layer
backfills rank from score on the fly, so old entries render correctly without
a one-time data migration.

Storage rules:
  - Top 10 scores are always retained (sorted by score desc, then date desc)
  - Additionally, up to 10 most recent runs are retained beyond top 10
    so a non-top-10 player can still see "you placed #14" accurately
  - File is created on first write
"""

import json
import os
from datetime import datetime


def _rank_for_score_safe(score):
    """
    Look up the letter rank for a numeric score. Lazy-imports score.py so
    leaderboard.py stays standalone if score.py is missing. Returns "?" if
    the rank table can't be loaded — never crashes the leaderboard.
    """
    try:
        from score import _rank_for_score
        rank_letter, _desc = _rank_for_score(int(score))
        return rank_letter
    except Exception:
        return "?"


# ---------------------------------------------------------------
# Constants
# ---------------------------------------------------------------
SCORES_FILE = "scores.json"   # in working directory
TOP_N       = 10              # top 10 leaderboard
EXTRA_HISTORY = 10            # extra non-top-10 runs to retain for placement display

# Outcome display labels (short — for the board)
OUTCOME_SHORT = {
    "chimera_victory":  "Champion",
    "patronus_victory": "Dark Champion",
    "intervention":     "Intervention",
    "defeat":           "Defeated",
    "gooed":            "Gooed",
    "flayed_one":       "Flayed",
    "drowned_one":      "Drowned",
    "coward":           "Coward",
}


# ---------------------------------------------------------------
# Storage I/O
# ---------------------------------------------------------------
def _load_scores():
    """Load all stored scores from disk. Returns empty list if missing or corrupt."""
    if not os.path.exists(SCORES_FILE):
        return []
    try:
        with open(SCORES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except (OSError, json.JSONDecodeError):
        # Corrupted or unreadable — don't crash, just start fresh.
        # Don't overwrite yet; let the next save replace it cleanly.
        return []


def _save_scores(scores):
    """Persist scores list to disk."""
    try:
        with open(SCORES_FILE, "w", encoding="utf-8") as f:
            json.dump(scores, f, indent=2)
    except OSError as e:
        # Don't crash the run if disk is full or path is unwritable
        print(f"⚠️  Could not save leaderboard: {e}")


def _sort_scores(scores):
    """Sort by score desc, then date desc (newer wins ties)."""
    return sorted(
        scores,
        key=lambda s: (-s.get("score", 0), s.get("date", "")),
        reverse=False,
    )


def _trim_scores(scores):
    """Keep top N plus up to EXTRA_HISTORY most recent non-top-N runs."""
    sorted_by_score = _sort_scores(scores)
    top = sorted_by_score[:TOP_N]
    remainder = sorted_by_score[TOP_N:]
    # From remainder, keep the most recent EXTRA_HISTORY
    remainder_recent = sorted(remainder, key=lambda s: s.get("date", ""), reverse=True)[:EXTRA_HISTORY]
    return top + remainder_recent


# ---------------------------------------------------------------
# Entry construction
# ---------------------------------------------------------------
def _build_entry(warrior, score, outcome):
    """Build a leaderboard entry from a warrior + score + outcome."""
    score_int = int(score)
    return {
        "name":    getattr(warrior, "name", "Unknown"),
        "score":   score_int,
        "rank":    _rank_for_score_safe(score_int),
        "outcome": outcome,
        "level":   int(getattr(warrior, "level", 1)),
        "stats": {
            "hp":      int(getattr(warrior, "hp", 0)),
            "max_hp":  int(getattr(warrior, "max_hp", 0)),
            "atk_min": int(getattr(warrior, "min_atk", 0)),
            "atk_max": int(getattr(warrior, "max_atk", 0)),
            "defence": int(getattr(warrior, "defence", 0)),
            "max_ap":  int(getattr(warrior, "max_ap", 0)),
            "gold":    int(getattr(warrior, "gold", 0)),
        },
        "date":    datetime.now().strftime("%Y-%m-%d"),
    }


def _entries_equal(a, b):
    """Two entries are 'the same run' if all key fields match."""
    if a is None or b is None:
        return False
    return (
        a.get("name")    == b.get("name")
        and a.get("score")   == b.get("score")
        and a.get("date")    == b.get("date")
        and a.get("outcome") == b.get("outcome")
    )


# ---------------------------------------------------------------
# Public API
# ---------------------------------------------------------------
def record_run(warrior, score, outcome):
    """
    Add this run to the leaderboard. Returns (entry, placement_or_None).
      - entry: the dict that was saved
      - placement_or_None: 1-indexed rank if top N, else None
    """
    entry = _build_entry(warrior, score, outcome)
    all_scores = _load_scores()
    all_scores.append(entry)
    all_scores = _trim_scores(all_scores)
    _save_scores(all_scores)

    # Determine if the entry landed in top N
    top = _sort_scores(all_scores)[:TOP_N]
    placement = None
    for i, s in enumerate(top):
        if _entries_equal(s, entry):
            placement = i + 1
            break

    return entry, placement


def _format_row(rank_no, e, highlight=False, width=76):
    """Format one leaderboard row.

    Columns: # | NAME | LVL | SCORE | RANK | OUTCOME | DATE
    `rank_no` is the leaderboard placement (1-indexed). `rank` field on the
    entry is the letter rank earned (S+, S, A, B, C, D, F). Old entries
    without a stored rank are backfilled from their score on display.
    """
    name    = e.get("name", "Unknown")[:14]
    score   = e.get("score", 0)
    outcome = OUTCOME_SHORT.get(e.get("outcome", "defeat"), "?")
    level   = e.get("level", 1)
    date    = e.get("date", "")[:10]   # YYYY-MM-DD

    # Backfill: if old entry has no rank, compute from score on display.
    letter_rank = e.get("rank")
    if not letter_rank:
        letter_rank = _rank_for_score_safe(score)

    # Layout: " #N. NAME............... LVL.. SCORE......  RANK.  OUTCOME....... DATE........"
    line = f" #{rank_no:<2} {name:<14} L{level:<2}  {score:>6}  {letter_rank:<3}  {outcome:<14} {date}"
    if highlight:
        # Wrap in markers for emphasis
        line = f"►{line[1:]}◄"
    return line


def _full_placement(entry, all_scores):
    """Find the 1-indexed rank of `entry` in the full score history."""
    sorted_all = _sort_scores(all_scores)
    for i, s in enumerate(sorted_all):
        if _entries_equal(s, entry):
            return i + 1
    return None


def show_leaderboard(highlight_entry=None, header="TOP 10 LEADERBOARD"):
    """
    Display the leaderboard. If `highlight_entry` is given and it's in the
    top N, that row is highlighted. If `highlight_entry` is given but NOT
    in the top N, show their placement below the board.
    """
    all_scores = _load_scores()
    top = _sort_scores(all_scores)[:TOP_N]

    width = 76
    bar   = "═" * width
    print()
    print(bar)
    title = f"  🏆  {header}"
    print(title)
    print(bar)
    print(" RNK NAME           LVL   SCORE  RANK OUTCOME        DATE")
    print(" " + "─" * (width - 2))

    if not top:
        print()
        print("   (No scores recorded yet — be the first!)")
        print()
    else:
        for i, e in enumerate(top):
            is_highlight = highlight_entry is not None and _entries_equal(e, highlight_entry)
            print(_format_row(i + 1, e, highlight=is_highlight, width=width))

    # If we have a player entry that didn't make the top N, show their placement
    if highlight_entry is not None:
        in_top = any(_entries_equal(e, highlight_entry) for e in top)
        if not in_top:
            placement = _full_placement(highlight_entry, all_scores)
            print(" " + "─" * (width - 2))
            if placement is not None:
                print(f"   Your run:  #{placement}")
                print(_format_row(placement, highlight_entry, highlight=True, width=width))
            else:
                # Edge case: trimmed out of history entirely (shouldn't normally happen)
                print("   Your run didn't crack the leaderboard this time.")
                print(_format_row("--", highlight_entry, highlight=True, width=width))

    print(bar)
    print()


def display_at_end_of_run(warrior, score, outcome):
    """
    Convenience: record the run, then show the leaderboard with the player's
    row highlighted (whether they made top 10 or are shown below it).
    """
    entry, placement = record_run(warrior, score, outcome)

    if placement is not None:
        if placement == 1:
            print()
            print("🏆 NEW #1 SCORE! Your name leads the leaderboard.")
        else:
            print()
            print(f"🎖️  You placed #{placement} on the leaderboard!")

    show_leaderboard(highlight_entry=entry)
    input("Press Enter to continue...")


# ---------------------------------------------------------------
# Standalone viewer (main menu hook)
# ---------------------------------------------------------------
def view_leaderboard_standalone():
    """Display the leaderboard with no highlight — used from main menu."""
    show_leaderboard(highlight_entry=None, header="TOP 10 LEADERBOARD")
    input("Press Enter to return to the main menu...")
