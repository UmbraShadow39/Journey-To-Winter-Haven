"""
combat_log.py
-------------
Standalone combat logging module for Journey to Winter Haven.

Exports:
    COMBAT_LOG        — the list that stores all entries for the current run
    log(msg)          — prints msg to screen AND appends it to COMBAT_LOG
    view_combat_log() — paginated display of COMBAT_LOG (20 entries per page)

Usage in main file:
    from combat_log import COMBAT_LOG, log, view_combat_log

Important: COMBAT_LOG is a list (mutable), so both this module and the main
file share the exact same list object in memory. Calling COMBAT_LOG.clear()
in the main file clears the same list that log() appends to here.
"""

import os


# The single list that holds the entire run's combat history.
# Cleared at the start of each new run via COMBAT_LOG.clear() in main.
COMBAT_LOG = []


def _clear_screen():
    """Clear the console screen (Windows / Mac / Linux)."""
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")


def log(msg=""):
    """Print msg to the terminal and append it to COMBAT_LOG."""
    print(msg)
    COMBAT_LOG.append(msg)


def view_combat_log():
    """Display COMBAT_LOG with pagination — 20 entries per page.

    Navigation:
        N — next page
        P — previous page
        Q — quit log and return
    Single-page logs just wait for Enter.
    """
    PAGE_SIZE = 20
    entries = COMBAT_LOG if COMBAT_LOG else ["(No combat recorded yet)"]
    total = len(entries)
    page = 0
    total_pages = max(1, -(-total // PAGE_SIZE))  # ceiling division

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
