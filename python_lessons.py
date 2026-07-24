"""
python_lessons.py — "Learn Basic Python" mini-mode for Journey to Winter Haven.

v0.7.18 (Stage 1): sandboxed code runner + Lesson 1 (print statements & variables).
Lessons 2 (if/else + while) and 3 (lists + dicts) are added in later stages.

Design notes
------------
- Teaches Python using the game's OWN code as examples, so a player who
  built JTWH by trial-and-error can see the concepts named and explained.
- Each lesson: short explanation -> a real game-code example -> a hands-on
  challenge the player types into a built-in sandbox terminal.
- The sandbox NEVER uses bare exec() on arbitrary input. It runs player
  code in a locked-down namespace: a small allow-list of safe builtins,
  NO imports, NO file/OS access. See run_sandbox() for the guard rails.
- Unlock progress is difficulty-gated and persisted to the save file
  (handled by the caller via lesson_progress on the warrior/save; this
  module only reads/reports it, it does not own the save format).

This module is intentionally dependency-light: it imports only from
`shared` (clear_screen / wrap / space) so it can't create import cycles
with combat/hero/etc.
"""

from shared import clear_screen, wrap, space

import io
import contextlib
import json
import os


# ============================================================
# PROGRESS PERSISTENCE (Stage 1 — self-contained)
# ============================================================
# Until the game has a full save system, this module owns a tiny JSON
# file recording which difficulties the player has beaten. Lesson unlocks
# are derived from the COUNT of distinct difficulties cleared:
#   - mode unlocks (and Lesson 1 opens) after the first win, any difficulty
#   - Lesson 2 opens after a win on a SECOND distinct difficulty
#   - Lesson 3 opens after a win on a THIRD distinct difficulty
# When the real save system lands, fold this into it and delete this file.

_PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "python_progress.json")


def _load_progress():
    """Return the progress dict, or a fresh default if none/corrupt."""
    try:
        with open(_PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError
        data.setdefault("difficulties_beaten", [])
        return data
    except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
        return {"difficulties_beaten": []}


def _save_progress(data):
    """Best-effort write. A failed save never crashes the game."""
    try:
        with open(_PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def record_run_completed(difficulty):
    """
    Call this once when the player FINISHES a run they should get credit
    for (a victory). Records the difficulty and persists. Distinct
    difficulties beaten is what gates lesson unlocks.

    `difficulty` is the run's difficulty string ("noob"/"warrior"/"champion").
    Safe to call repeatedly — duplicates are ignored.
    """
    if not difficulty:
        return
    data = _load_progress()
    if difficulty not in data["difficulties_beaten"]:
        data["difficulties_beaten"].append(difficulty)
        _save_progress(data)


def is_mode_unlocked():
    """True once the player has completed at least one qualifying run."""
    return len(_load_progress()["difficulties_beaten"]) >= 1


def unlocked_lesson_count():
    """
    How many lessons are open right now = number of DISTINCT difficulties
    beaten, capped at TOTAL_LESSONS. Zero if the mode isn't unlocked yet.
    """
    n = len(_load_progress()["difficulties_beaten"])
    return max(0, min(TOTAL_LESSONS, n))


# ============================================================
# LESSON REGISTRY
# ============================================================
# Each lesson is unlocked by BEATING THE GAME on a specific difficulty.
# Lesson 1 is available as soon as the mode itself is unlocked (any first
# win). Lessons 2 and 3 require wins on difficulties you haven't cleared
# yet — so you can't grind one difficulty three times; you have to broaden.
#
# The caller passes in `unlocked_lessons` (an int: how many are open) so
# this module stays decoupled from how progress is stored/saved.

LESSON_TITLES = {
    1: "Lesson 1 — Print Statements & Variables",
    2: "Lesson 2 — Choices & Loops (if / else / while)",   # Stage 2
    3: "Lesson 3 — Lists & Dictionaries",                    # Stage 3
}

TOTAL_LESSONS = 3


# ============================================================
# SANDBOX — safely run player-typed Python
# ============================================================

# The ONLY builtins a lesson sandbox exposes. Everything else (open,
# __import__, eval, exec, input, etc.) is absent, so player code cannot
# read files, import modules, or touch the OS. This is an allow-list, not
# a block-list — safer, because anything we forgot to think about is
# denied by default rather than allowed by default.
_SAFE_BUILTINS = {
    "print":     print,
    "int":       int,
    "float":     float,
    "str":       str,
    "bool":      bool,
    "len":       len,
    "range":     range,
    "abs":       abs,
    "min":       min,
    "max":       max,
    "sum":       sum,
    "round":     round,
    "sorted":    sorted,
    "list":      list,
    "dict":      dict,
    "tuple":     tuple,
    "set":       set,
    "enumerate": enumerate,
    "zip":       zip,
    "True":      True,
    "False":     False,
    "None":      None,
}

# Substrings that must never appear in player code. Belt-and-suspenders on
# top of the empty-builtins sandbox: even though __import__ isn't exposed,
# we reject these outright so the player gets a clear teaching message
# instead of a confusing NameError, and so no dunder-escape trick even
# gets a chance to run.
_BLOCKED_TOKENS = (
    "import", "__", "open(", "eval(", "exec(", "compile(",
    "globals(", "locals(", "input(", "exit(", "quit(",
    "os.", "sys.", "subprocess", "getattr(", "setattr(",
)


def run_sandbox(code, extra_names=None):
    """
    Execute a player's code string in a locked-down namespace.

    Parameters
    ----------
    code : str
        The Python the player typed.
    extra_names : dict | None
        Optional pre-seeded variables a lesson wants available (e.g. a
        starting `hp = 30`). Read-only intent — a copy is used.

    Returns
    -------
    (ok, output, error)
        ok     : bool     — True if the code ran without raising.
        output : str      — whatever the code print()ed.
        error  : str|None — a friendly message if something went wrong.

    Safety
    ------
    - No __import__ / open / eval / exec / file / OS access is reachable:
      __builtins__ is replaced with our tiny allow-list.
    - _BLOCKED_TOKENS are rejected before running, with a teaching message.
    - All exceptions are caught and returned as strings so a typo can
      never crash the game — the player just sees the error and retries.
    """
    if not code or not code.strip():
        return False, "", "You didn't type anything — give it a try!"

    lowered = code.lower()
    for tok in _BLOCKED_TOKENS:
        if tok in lowered:
            return (
                False, "",
                f"For safety, the lesson sandbox doesn't allow '{tok.strip('(')}'. "
                "Stick to the basics we're practicing — no imports or file access needed here."
            )

    # Build the restricted namespace. Replacing __builtins__ with our dict
    # is what actually locks things down — the code literally cannot see
    # any name we didn't put here.
    sandbox_globals = {"__builtins__": _SAFE_BUILTINS}
    if extra_names:
        sandbox_globals.update(extra_names)

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            # exec is safe HERE only because sandbox_globals has no
            # dangerous builtins and the input was token-screened above.
            exec(code, sandbox_globals)
    except SyntaxError as e:
        return False, buf.getvalue(), f"Syntax error: {e.msg} (check line {e.lineno})."
    except Exception as e:
        return False, buf.getvalue(), f"{type(e).__name__}: {e}"

    return True, buf.getvalue(), None


def _sandbox_prompt(intro_lines, check=None, extra_names=None):
    """
    Interactive multi-line code entry + run loop.

    The player types code line by line; an empty line runs it. They can
    type 'skip' to move on, or 'menu' to bail out to the lesson menu.

    `check(output, code)` — optional callable returning (passed, message).
    When provided, a run that executes successfully is graded; passing
    ends the challenge, failing lets them try again.
    """
    for line in intro_lines:
        print(wrap(line))
    print()
    print(wrap("Type your code below. Press ENTER on a blank line to RUN it. "
               "Type 'skip' to move on, or 'menu' to leave."))
    print()

    while True:
        lines = []
        while True:
            try:
                raw = input("  >>> " if not lines else "  ... ")
            except EOFError:
                return
            stripped = raw.strip().lower()
            if not lines and stripped in ("skip", "menu"):
                return stripped
            if raw.strip() == "" and lines:
                break
            if raw.strip() == "" and not lines:
                # blank first line — nudge, don't run nothing
                print(wrap("  (type some code first, or 'skip' to move on)"))
                continue
            lines.append(raw)

        code = "\n".join(lines)
        ok, output, error = run_sandbox(code, extra_names=extra_names)

        print()
        print("  " + "-" * 46)
        if output:
            print("  Output:")
            for ol in output.rstrip("\n").split("\n"):
                print(f"    {ol}")
        if error:
            print(f"  ⚠️  {error}")
        if not output and not error:
            print("  (your code ran, but didn't print anything)")
        print("  " + "-" * 46)
        print()

        if check and ok:
            passed, message = check(output, code)
            print(wrap("  " + message))
            print()
            if passed:
                input("  ✅ Nice work! Press Enter to continue...")
                return "passed"
        else:
            input("  Press Enter to keep experimenting (or blank-run again)...")
        # loop back for another attempt


# ============================================================
# LESSON 1 — PRINT STATEMENTS & VARIABLES
# ============================================================

def _lesson_1():
    clear_screen()
    print("=" * 52)
    print("  🐍 LESSON 1 — Print Statements & Variables")
    print("=" * 52)
    print()
    print(wrap(
        "Every message this game shows you — every 'LEVEL UP!', every damage "
        "number — starts with the simplest tool in Python: the print statement."
    ))
    space()
    print(wrap("Here's a real line straight out of the game's level-up code:"))
    print()
    print('      print("✨ LEVEL UP! You are now Level 2 ✨")')
    print()
    print(wrap(
        "`print(...)` takes whatever is inside the parentheses and shows it on "
        "screen. Text goes in quotes — that's called a STRING. Simple as that."
    ))
    space()
    input("  Press Enter to continue...")

    clear_screen()
    print("=" * 52)
    print("  🐍 LESSON 1 — Variables")
    print("=" * 52)
    print()
    print(wrap(
        "A VARIABLE is a labelled box that holds a value so you can use it "
        "later. Your hero's health is a variable. So is their attack."
    ))
    print()
    print(wrap("Here's how the game sets up a brand-new warrior (simplified):"))
    print()
    print("      hp = 30")
    print("      min_atk = 1")
    print("      max_atk = 5")
    print()
    print(wrap(
        "`hp = 30` means 'make a box called hp and put the number 30 in it.' "
        "Numbers with no decimal point are INTEGERS (whole numbers). You can "
        "use the variable's name anywhere you'd use its value:"
    ))
    print()
    print('      print(hp)          # shows: 30')
    print('      print(hp + 5)      # shows: 35')
    print()
    print(wrap(
        "That '+ 5' is exactly what happens when you get the '+5 Max HP' buff "
        "on level up — the game takes your hp box and adds 5 to it."
    ))
    space()
    input("  Press Enter to try it yourself...")

    # ---- Challenge ----
    clear_screen()
    print("=" * 52)
    print("  🐍 LESSON 1 — Your Turn")
    print("=" * 52)
    print()

    def _check(output, code):
        out = output.strip()
        # Accept if they printed 35 anywhere (the "hp after +5 buff" answer),
        # which is the whole point of the exercise.
        if "35" in out:
            return True, "You leveled up your hero's HP from 30 to 35 — exactly how the game does it. 🎉"
        if out:
            return False, ("Close! I'm looking for the value 35 in your output — "
                           "the hero's HP after a +5 buff. Remember hp starts at 30.")
        return False, "Try printing the result of hp plus 5."

    result = _sandbox_prompt(
        intro_lines=[
            "CHALLENGE: A variable `hp` is already set to 30 for you.",
            "",
            "The hero just got a '+5 Max HP' buff. Print their NEW hp value "
            "(it should come out as 35).",
            "",
            "Hint: you can do it in one line — print(hp + 5) — or set a new "
            "variable first. Try a few ways and see what happens!",
        ],
        check=_check,
        extra_names={"hp": 30},
    )
    return result


# ============================================================
# LESSON DISPATCH + MENU
# ============================================================

_LESSON_FUNCS = {
    1: _lesson_1,
    # 2: _lesson_2,   # Stage 2
    # 3: _lesson_3,   # Stage 3
}


def _difficulty_hint(lesson_num):
    """Human-readable unlock hint for a locked lesson."""
    if lesson_num == 2:
        return "Beat the game on a SECOND difficulty to unlock."
    if lesson_num == 3:
        return "Beat the game on a THIRD difficulty to unlock."
    return "Locked."


def python_lessons_menu(unlocked_lessons=1):
    """
    Top-level 'Learn Basic Python' menu, reached from the main menu (option 5,
    visible once the mode is unlocked by finishing a run).

    Parameters
    ----------
    unlocked_lessons : int
        How many lessons the player has unlocked (>=1 once the mode exists).
        Difficulty-gating that produces this number lives in the save/main
        code; this menu just renders what's open.
    """
    unlocked_lessons = max(1, min(TOTAL_LESSONS, int(unlocked_lessons)))

    while True:
        clear_screen()
        print("=" * 52)
        print("        🐍 LEARN BASIC PYTHON")
        print("=" * 52)
        print()
        print(wrap(
            "Learn to read the language this whole game is written in — using "
            "the game's own code as your guide. Unlock more lessons by beating "
            "the game on difficulties you haven't cleared yet."
        ))
        print()
        for num in range(1, TOTAL_LESSONS + 1):
            title = LESSON_TITLES[num]
            if num <= unlocked_lessons and num in _LESSON_FUNCS:
                print(f"   [{num}] {title}")
            elif num <= unlocked_lessons:
                print(f"   [{num}] {title}   (coming soon)")
            else:
                print(f"   [ 🔒 ] {title}")
                print(f"         {_difficulty_hint(num)}")
        print()
        print("   [0] Back to main menu")
        print()

        choice = input("   Select a lesson: ").strip()
        if choice in ("0", ""):
            return
        if not choice.isdigit():
            continue
        num = int(choice)
        if num < 1 or num > TOTAL_LESSONS:
            continue
        if num > unlocked_lessons:
            print()
            print(wrap(f"   🔒 {_difficulty_hint(num)}"))
            input("   Press Enter...")
            continue
        func = _LESSON_FUNCS.get(num)
        if func is None:
            print()
            print(wrap("   That lesson is coming in a future update — stay tuned!"))
            input("   Press Enter...")
            continue
        func()
