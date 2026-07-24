"""
Journey to Winter Haven — Leaderboard System (v0.8)
----------------------------------------------------
LOCAL:  Top 10 runs stored in scores.json (unchanged from v0.7)
GLOBAL: Top 25 per difficulty submitted to Supabase after each run

Difficulty tiers on the global board:
  🛡️  Noob      — Top 25
  ⚔️  Warrior   — Top 25
  👑  Champion  — Top 25 (prestige tier)
  🐛  Debug     — Top 25 ("How Badly Can You Break It?")

Debug run detection:
  - Any run where warrior.debug_mode is True at submission time
  - Routed to the Debug tier automatically — no penalty needed
  - A warning is shown the first time debug menu is opened in a run
  - Debug runs are excluded from Noob/Warrior/Champion boards

Supabase config:
  Set SUPABASE_URL and SUPABASE_ANON_KEY in a .env file in your
  game directory (never hardcode keys in source):

      SUPABASE_URL=https://your-project.supabase.co
      SUPABASE_ANON_KEY=eyJ...

  If the .env file or keys are missing, global submission is skipped
  silently — the local leaderboard always works regardless.

Module entry points:
  record_run(warrior, score, outcome)            — call at end of run
  show_leaderboard(highlight_entry=None)         — display local top 10
  display_at_end_of_run(warrior, score, outcome) — record + show + global submit
  view_leaderboard_standalone()                  — main menu hook

Data file format (scores.json) — unchanged from v0.7:
  [
    {
      "name":       "Nathan",
      "score":      4250,
      "rank":       "A",
      "outcome":    "chimera_victory",
      "difficulty": "warrior",
      "level":      5,
      "stats": { "hp": 47, "max_hp": 52, ... },
      "date":       "2026-05-18",
      "debug_run":  false
    },
    ...
  ]

Storage rules (local):
  - Top 10 scores always retained (sorted by score desc, then date desc)
  - Up to 10 most recent non-top-10 runs retained for placement display
  - File created on first write
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime


# ---------------------------------------------------------------
# Supabase config — loaded from .env
# ---------------------------------------------------------------
def _load_env():
    """
    Load SUPABASE_URL and SUPABASE_ANON_KEY from a .env file in the
    current working directory. Returns (url, key) or (None, None) if
    missing — global submission is skipped gracefully when absent.
    """
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return None, None
    url = None
    key = None
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("SUPABASE_URL="):
                    url = line.split("=", 1)[1].strip()
                elif line.startswith("SUPABASE_ANON_KEY="):
                    key = line.split("=", 1)[1].strip()
    except OSError:
        pass
    return url, key

SUPABASE_URL, SUPABASE_ANON_KEY = _load_env()


# ---------------------------------------------------------------
# Constants
# ---------------------------------------------------------------
SCORES_FILE    = "scores.json"
TOP_N          = 10
EXTRA_HISTORY  = 10
GLOBAL_TOP_N   = 25

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

DIFF_ICON = {"noob": "🛡️", "warrior": "⚔️", "champion": "👑", "debug": "🐛"}


# ---------------------------------------------------------------
# Score rank helper
# ---------------------------------------------------------------
def _rank_for_score_safe(score):
    try:
        from score import _rank_for_score
        rank_letter, _desc = _rank_for_score(int(score))
        return rank_letter
    except Exception:
        return "?"


# ---------------------------------------------------------------
# Local storage I/O
# ---------------------------------------------------------------
def _load_scores():
    if not os.path.exists(SCORES_FILE):
        return []
    try:
        with open(SCORES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except (OSError, json.JSONDecodeError):
        return []


def _save_scores(scores):
    try:
        with open(SCORES_FILE, "w", encoding="utf-8") as f:
            json.dump(scores, f, indent=2)
    except OSError as e:
        print(f"⚠️  Could not save leaderboard: {e}")


def _sort_scores(scores):
    return sorted(
        scores,
        key=lambda s: (-s.get("score", 0), s.get("date", "")),
        reverse=False,
    )


def _trim_scores(scores):
    sorted_by_score = _sort_scores(scores)
    top = sorted_by_score[:TOP_N]
    remainder = sorted_by_score[TOP_N:]
    remainder_recent = sorted(
        remainder, key=lambda s: s.get("date", ""), reverse=True
    )[:EXTRA_HISTORY]
    return top + remainder_recent


# ---------------------------------------------------------------
# Entry construction
# ---------------------------------------------------------------
def _build_entry(warrior, score, outcome):
    score_int  = int(score)
    is_debug   = bool(getattr(warrior, "debug_mode", False))
    difficulty = "debug" if is_debug else getattr(warrior, "difficulty", "warrior")
    return {
        "name":       getattr(warrior, "name", "Unknown"),
        "sex":        getattr(warrior, "sex", "male"),
        "score":      score_int,
        "rank":       _rank_for_score_safe(score_int),
        "outcome":    outcome,
        "difficulty": difficulty,
        "level":      int(getattr(warrior, "level", 1)),
        "stats": {
            "hp":      int(getattr(warrior, "hp", 0)),
            "max_hp":  int(getattr(warrior, "max_hp", 0)),
            "atk_min": int(getattr(warrior, "min_atk", 0)),
            "atk_max": int(getattr(warrior, "max_atk", 0)),
            "defence": int(getattr(warrior, "defence", 0)),
            "max_ap":  int(getattr(warrior, "max_ap", 0)),
            "gold":    int(getattr(warrior, "gold", 0)),
        },
        "date":      datetime.now().strftime("%Y-%m-%d"),
        "debug_run": is_debug,
    }


def _entries_equal(a, b):
    if a is None or b is None:
        return False
    return (
        a.get("name")    == b.get("name")
        and a.get("score")   == b.get("score")
        and a.get("date")    == b.get("date")
        and a.get("outcome") == b.get("outcome")
    )


# ---------------------------------------------------------------
# Global leaderboard — Supabase submission
# ---------------------------------------------------------------
def _submit_global_score(entry):
    """
    POST the run entry to Supabase. Fails silently if:
      - .env is missing / keys not configured
      - Network is unavailable
      - Supabase returns an error
    The local leaderboard always works regardless.
    """
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return  # Not configured — skip silently

    payload = {
        "player_name": entry.get("name", "Unknown"),
        "sex":         entry.get("sex", "male"),
        "score":       entry.get("score", 0),
        "rank":        entry.get("rank", "?"),
        "difficulty":  entry.get("difficulty", "warrior"),
        "outcome":     entry.get("outcome", "defeat"),
        "level":       entry.get("level", 1),
        "hp":          entry["stats"].get("hp", 0),
        "max_hp":      entry["stats"].get("max_hp", 0),
        "atk_min":     entry["stats"].get("atk_min", 0),
        "atk_max":     entry["stats"].get("atk_max", 0),
        "defence":     entry["stats"].get("defence", 0),
        "max_ap":      entry["stats"].get("max_ap", 0),
        "gold":        entry["stats"].get("gold", 0),
        "debug_run":   entry.get("debug_run", False),
    }

    try:
        url      = f"{SUPABASE_URL}/rest/v1/scores"
        data     = json.dumps(payload).encode("utf-8")
        req      = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type",  "application/json")
        req.add_header("apikey",        SUPABASE_ANON_KEY)
        req.add_header("Authorization", f"Bearer {SUPABASE_ANON_KEY}")
        req.add_header("Prefer",        "return=minimal")

        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status in (200, 201):
                return True
    except (urllib.error.URLError, OSError):
        pass  # Network unavailable — silent fail, local board unaffected
    except Exception:
        pass

    return False


def _fetch_global_scores(difficulty, limit=GLOBAL_TOP_N):
    """
    Fetch top scores for a difficulty from Supabase.
    Returns a list of score dicts, or empty list on failure.
    """
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return []

    try:
        url = (
            f"{SUPABASE_URL}/rest/v1/scores"
            f"?difficulty=eq.{difficulty}"
            f"&order=score.desc"
            f"&limit={limit}"
            f"&select=player_name,sex,score,rank,outcome,level,difficulty,debug_run,submitted_at"
        )
        req = urllib.request.Request(url)
        req.add_header("apikey",        SUPABASE_ANON_KEY)
        req.add_header("Authorization", f"Bearer {SUPABASE_ANON_KEY}")

        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []


# ---------------------------------------------------------------
# Debug warning — call from debug.py when menu first opens
# ---------------------------------------------------------------
def warn_debug_mode_score_impact():
    """
    Show a one-time warning when the debug menu is opened during a run.
    Call this from debug.py's debug_menu() on first entry per run.
    The warning explains the score routing so players can make an informed choice.
    """
    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║           🐛  DEBUG MODE ACTIVATED  🐛               ║")
    print("  ╠══════════════════════════════════════════════════════╣")
    print("  ║  Using the debug menu flags this run permanently.    ║")
    print("  ║                                                       ║")
    print("  ║  Your score will be submitted to the                  ║")
    print("  ║  🐛 DEBUG leaderboard instead of the main boards.    ║")
    print("  ║                                                       ║")
    print("  ║  Debug board motto:                                   ║")
    print("  ║  \"How Badly Can You Break My Game?\"                   ║")
    print("  ║                                                       ║")
    print("  ║  No penalty — just a separate category. Go wild!     ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()
    input("  Press Enter to continue to the debug menu...")


# ---------------------------------------------------------------
# Public API
# ---------------------------------------------------------------
def record_run(warrior, score, outcome):
    """
    Add this run to the local leaderboard.
    Returns (entry, placement_or_None).
    """
    entry = _build_entry(warrior, score, outcome)
    all_scores = _load_scores()
    all_scores.append(entry)
    all_scores = _trim_scores(all_scores)
    _save_scores(all_scores)

    top = _sort_scores(all_scores)[:TOP_N]
    placement = None
    for i, s in enumerate(top):
        if _entries_equal(s, entry):
            placement = i + 1
            break

    return entry, placement


def _format_row(rank_no, e, highlight=False, width=76):
    """Format one leaderboard row."""
    name        = e.get("name", "Unknown")[:14]
    sex         = e.get("sex", "male")
    sex_icon    = "♀" if sex == "female" else "♂"
    score       = e.get("score", 0)
    outcome     = OUTCOME_SHORT.get(e.get("outcome", "defeat"), "?")
    level       = e.get("level", 1)
    date        = e.get("date", "")[:10]
    letter_rank = e.get("rank") or _rank_for_score_safe(score)
    diff        = e.get("difficulty", "warrior")
    diff_icon   = DIFF_ICON.get(diff, "⚔️")

    line = f" #{rank_no:<2} {name:<14} {sex_icon}  L{level:<2}  {score:>6}  {letter_rank:<3}  {outcome:<14} {diff_icon} {date}"
    if highlight:
        line = f"►{line[1:]}◄"
    return line


def _full_placement(entry, all_scores):
    sorted_all = _sort_scores(all_scores)
    for i, s in enumerate(sorted_all):
        if _entries_equal(s, entry):
            return i + 1
    return None


def show_leaderboard(highlight_entry=None, header="TOP 10 LEADERBOARD", difficulty=None):
    """Display the local leaderboard, optionally filtered by difficulty."""
    all_scores = _load_scores()
    if difficulty:
        filtered = [s for s in all_scores if s.get("difficulty", "warrior") == difficulty]
        top   = _sort_scores(filtered)[:TOP_N]
        header = f"TOP 10 — {difficulty.upper()}"
    else:
        top = _sort_scores(all_scores)[:TOP_N]

    width = 76
    bar   = "═" * width
    print()
    print(bar)
    print(f"  🏆  {header}")
    print(bar)
    print(" RNK NAME           SEX LVL   SCORE  RANK OUTCOME        DATE")
    print(" " + "─" * (width - 2))

    if not top:
        print()
        print("   (No scores recorded yet — be the first!)")
        print()
    else:
        for i, e in enumerate(top):
            is_highlight = highlight_entry is not None and _entries_equal(e, highlight_entry)
            print(_format_row(i + 1, e, highlight=is_highlight, width=width))

    if highlight_entry is not None:
        in_top = any(_entries_equal(e, highlight_entry) for e in top)
        if not in_top:
            placement = _full_placement(highlight_entry, all_scores)
            print(" " + "─" * (width - 2))
            if placement is not None:
                print(f"   Your run:  #{placement}")
                print(_format_row(placement, highlight_entry, highlight=True, width=width))
            else:
                print("   Your run didn't crack the leaderboard this time.")
                print(_format_row("--", highlight_entry, highlight=True, width=width))

    print(bar)
    print()


def show_global_leaderboard(default_difficulty="warrior"):
    """
    Fetch and display the global top 25 for a single difficulty bracket.
    Shows the default_difficulty first, then lets the player browse others.
    Called from the main menu (defaults to warrior) or post-run (defaults to
    the player's difficulty).
    """
    width = 76
    bar   = "=" * width

    TIER_LABELS = {
        "noob":     "Shield  NOOB      -  Global Top 25",
        "warrior":  "Sword   WARRIOR   -  Global Top 25",
        "champion": "Crown   CHAMPION  -  Global Top 25",
        "debug":    "Bug     DEBUG     -  How Badly Can You Break It?  Top 25",
    }

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        print()
        print(bar)
        print("  GLOBAL LEADERBOARD")
        print(bar)
        print()
        print("  Global leaderboard not configured.")
        print("  Add SUPABASE_URL and SUPABASE_ANON_KEY to your .env file.")
        print()
        print(bar)
        input("\nPress Enter to return...")
        return

    current = default_difficulty
    while True:
        scores = _fetch_global_scores(current)
        label  = TIER_LABELS.get(current, current.upper())

        print()
        print(bar)
        print("  JOURNEY TO WINTER HAVEN - GLOBAL LEADERBOARD")
        print(bar)
        print(f"  {label}")
        print(" " + "-" * (width - 2))
        print(" RNK NAME                SEX SCORE  RANK  OUTCOME          DATE")
        print(" " + "-" * (width - 2))

        if not scores:
            print("   (No scores yet - be the first!)")
        else:
            for i, s in enumerate(scores[:GLOBAL_TOP_N], 1):
                name    = s.get("player_name", "Unknown")[:16]
                sex_icon = "♀" if s.get("sex") == "female" else "♂"
                score   = s.get("score", 0)
                rank    = s.get("rank", "?")
                outcome = OUTCOME_SHORT.get(s.get("outcome", "defeat"), "?")
                date    = (s.get("submitted_at") or "")[:10]
                debug   = " [debug]" if s.get("debug_run") else ""
                print(f" #{i:<2} {name:<16}  {sex_icon}  {score:>6}  {rank:<4}  {outcome:<16} {date}{debug}")

        print()
        print(bar)
        print("  [1] Noob  [2] Warrior  [3] Champion  [4] Debug  [5] Back")
        choice = input("  Select bracket or go back: ").strip()

        if choice == "1":
            current = "noob"
        elif choice == "2":
            current = "warrior"
        elif choice == "3":
            current = "champion"
        elif choice == "4":
            current = "debug"
        elif choice == "5":
            return
        else:
            input("  Please enter 1-5. Press Enter to try again...")


def display_at_end_of_run(warrior, score, outcome):
    """
    Convenience: record locally, show local board with highlight,
    then submit to global leaderboard.
    """
    entry, placement = record_run(warrior, score, outcome)

    if placement is not None:
        if placement == 1:
            print()
            print("🏆 NEW #1 SCORE! Your name leads the leaderboard.")
        else:
            print()
            print(f"🎖️  You placed #{placement} on the local leaderboard!")

    player_diff = entry.get("difficulty", "warrior")
    show_leaderboard(highlight_entry=entry, difficulty=player_diff)

    # Global submission
    is_debug = entry.get("debug_run", False)
    if SUPABASE_URL and SUPABASE_ANON_KEY:
        print("  🌐 Submitting to global leaderboard...", end="", flush=True)
        success = _submit_global_score(entry)
        if success:
            tier = "🐛 Debug" if is_debug else {
                "noob": "🛡️ Noob",
                "warrior": "⚔️ Warrior",
                "champion": "👑 Champion",
            }.get(entry.get("difficulty", "warrior"), "⚔️ Warrior")
            print(f" submitted to {tier} board!")
        else:
            print(" (offline — score saved locally)")

    # v0.7.20: final screen of the run — names itself so it's distinct from
    # the score and combat-log prompts that precede it.
    input("Press Enter to finish your run...")


# ---------------------------------------------------------------
# Standalone viewer (main menu hook)
# ---------------------------------------------------------------
def view_leaderboard_standalone():
    """Display local leaderboard — used from main menu."""
    show_leaderboard(highlight_entry=None, header="TOP 10 LEADERBOARD")
    input("Press Enter to return to the main menu...")
