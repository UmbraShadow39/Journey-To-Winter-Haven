"""
score.py — End-of-run scoring system for Journey to Winter Haven
-----------------------------------------------------------------
Mirrors the design philosophy of gold.py — RNG-resistant, tied to
actual difficulty defeated, and rewards engagement with all systems.

Design goals:
  - Score reflects monster threat defeated, not raw fight count
  - Per-fight bonuses for fast clears, close matches, performance triggers
  - Lifetime gold tracking (not current gold) so spending isn't punished
  - Tiered title scoring — easy titles worth 50, true endings worth 500
  - Outcome multipliers reward final-boss kills over interventions
  - Caps prevent grinder/hoarder exploitation
  - Good path gets a slight multiplier bump to compensate for lost gold

Public API:
  threat_value(enemy)                   — compute a monster's threat budget
  record_fight_score(warrior, enemy, turn_count)
                                        — call after each victory; accumulates
                                          a per-fight score on warrior
  show_run_score(warrior, outcome)      — prints the full breakdown + rank
                                          outcome: "chimera_victory" /
                                                   "patronus_victory" /
                                                   "intervention" /
                                                   "defeat" / "gooed"
"""

import math


# ============================================================
# CONFIGURATION
# ============================================================

# Title score values. Tiered by difficulty to actually earn.
TITLE_SCORE_VALUES = {
    # Tier 1 — easy / natural progression
    "jack_of_all_trades":      50,
    "chinker":                 50,
    "death_delver":            50,

    # Tier 2 — mid-game milestone
    "champion_of_the_arena":  150,
    "dual_wielder":           150,   # v0.6.18: equipped two 1H weapons simultaneously

    # Tier 3 — skill mastery, RNG-gated survival, or breadth capstone
    "river_warrior":          250,   # ~30% survival roll AND survive prologue rocks
    "brawl_master":           250,   # Power Strike rank 5
    "combat_medic":           250,   # First Aid rank 5
    "charismatic_speaker":    250,   # War Cry rank 5
    "armor_piercer":          250,   # Defence Break rank 5
    "death_apprentice":       250,   # Death Defier rank 5
    "true_jack_of_all_trades": 250,  # Rank 2+ in every skill — breadth capstone
    "wolf_hide_crafter":      250,   # v0.6.18: craft all 4 Wolf-Hide pieces in a run
    "dire_wolf_crafter":      250,   # v0.6.18: craft all 4 Dire Wolf pieces in a run

    # Tier 4 — true ending titles (final boss kill)
    "guardian":               500,   # Beat Young Chimera
    "dark_champion":          500,   # Beat Patronus
}

FATE_TITLE_SCORE_VALUES = {
    "drowned_one":      50,
    "flayed_one":       50,
    "fallen_champion":  50,
    "coward":           25,    # ran away — least dignified
    "gooed_one":         1,    # the eternal joke
}

# Per-fight bonus thresholds — reuse gold.py's existing cap_rounds tuning
# so we have a single source of truth for "fast clear" / "drag" thresholds.
# This mirrors the import pattern from the gold module.
try:
    from gold import GOLD_CONFIG
except ImportError:
    GOLD_CONFIG = {
        1:          (5,  5,  5),
        2:          (10, 8,  8),
        3:          (15, 12, 12),
        "fallen":   (20, 12, 12),
        "patronus": (30, 12, 12),
        "chimera":  (0,  0,  0),
    }

# Per-fight bonus values
SPEED_BONUS_PCT       = 0.50    # of threat
DRAG_PENALTY_PCT      = 0.30    # of threat
CLOSE_MATCH_BONUS_PCT = 0.50    # of threat
CLOSE_MATCH_HP_PCT    = 0.20    # survive at <=20% HP
BERSERK_BONUS_FLAT    = 20
DEFIER_BONUS_FLAT     = 50

# v0.6.19: Quick-kill thresholds — tighter than GOLD_CONFIG's cap_rounds.
# Where GOLD_CONFIG defines "no penalty" windows (lenient), QUICK_KILL_TURNS
# defines "exceptional play" windows (strict). Hitting these awards:
#   - the existing per-fight speed bonus (+50% threat) for non-boss kills
#   - the new run-wide quick-kill multiplier (+0.10 per qualifying kill)
# Bosses (Patronus, Chimera) count toward the multiplier but skip the
# per-fight bonus — the outcome multiplier already rewards the boss kill
# on its own (2.0×/2.1×), so adding a per-fight spike on top would dwarf
# every other fight.
QUICK_KILL_TURNS = {
    1:          2,   # T1: Slimes, Goblin, Imp, Skeleton, Wolf Pup
    2:          3,   # T2: Red Slime, Ghost, Javelina, Archer, Dire Wolf Pup
    3:          4,   # T3: Wolf Pup Rider, Hydra, Flayed, Drowned, War Blade
    "fallen":   5,   # Fallen Warrior — round-5 arena boss
    "patronus": 6,   # Patronus — tankier than Chimera (40% heal mechanic)
    "chimera":  5,   # Young Chimera — damage-race boss
}

QUICK_KILL_MULTIPLIER_PER_KILL = 0.10   # +0.10 to outcome multiplier per qualifying kill

# Bosses that bypass per-fight speed bonus when quick-killed (they only
# contribute to the run-wide multiplier instead).
SUPPRESS_PER_FIGHT_BONUS_FOR = {"patronus", "chimera"}


def _quick_kill_threshold(enemy):
    """Return the turn-count threshold for this enemy, or None if none defined."""
    config_key = _gold_config_key(enemy)
    return QUICK_KILL_TURNS.get(config_key)

# Run-wide weights
DAMAGE_DEALT_WEIGHT     = 0.50
DAMAGE_BLOCKED_WEIGHT   = 0.50
DAMAGE_DEALT_CAP        = 1000
DAMAGE_BLOCKED_CAP      = 500
GOLD_WEIGHT             = 1.0
LEVEL_WEIGHT            = 25      # per level above 1

# Luck bonuses
JACKPOT_VALUE           = 50
BOOKIE_INTIMIDATED_VALUE = 25

# Potion bonuses
POTION_VALUE                = 5     # per potion remaining
POTION_BONUS_CAP            = 100   # max contribution from regular potions
FROSTPINE_TONIC_SAVED_VALUE = 25    # separate, not in cap

# Outcome multipliers
OUTCOME_MULTIPLIERS = {
    "chimera_victory":   2.1,    # good path — extra 0.1 compensates for no gold
    "patronus_victory":  2.0,    # evil path
    "intervention":      1.5,    # survived 4+ cycles, didn't land kill
    "defeat":            1.0,
    "gooed":             1.0,
    # Fate deaths — runs that ended in the prologue or fled the arena.
    # All currently bypass the normal end-of-run flow but now flow through
    # the leaderboard system so the run is at least scored.
    "flayed_one":        0.5,    # river rocks (refused help in prologue)
    "drowned_one":       0.5,    # waterfall (prologue)
    "coward":            0.3,    # ran from arena, shaman executed you
}

# Post-multiplier flat bonus
GOOED_PITY_BONUS = 1   # the eternal joke

# Rank thresholds (final score after all multipliers)
# v0.6.14: Added S+ ("Demigod Champion") at 6,500. S+ should be achievable
# only on a strong run that triggers most of the bonus systems (berserk +
# defier across many fights, low-HP close-match survival, full gold, saved
# potions, lucky jackpot / bookie wins). Roughly 70% of theoretical max
# (~9,600 on a perfect Chimera path). Future ladder sketched but not
# implemented yet: SS "god champion", SS+ "Elder god champion",
# SSS "God Champion" (uppercase G — the Holy Trinity tier), SSS+ TBD.
RANK_THRESHOLDS = [
    ("S+", 6500),
    ("S",  4500),
    ("A",  3000),
    ("B",  1200),
    ("C",   500),
    ("D",   150),
    ("F",     0),
]

RANK_DESCRIPTIONS = {
    "S+": "Demigod Champion. The Beast Gods themselves take notice.",
    "S":  "Legendary champion. The arena will remember.",
    "A":  "Heroic. A tale worth telling.",
    "B":  "Strong showing. Not the end of the road.",
    "C":  "Respectable. There's room to grow.",
    "D":  "You made it through some of it.",
    "F":  "The arena was unkind today.",
}


# ============================================================
# THREAT VALUE
# ============================================================

def threat_value(enemy):
    """
    Compute a monster's threat budget — used as the base score for defeating it.
    Bigger / more dangerous monsters yield higher threat values.

    Formula:
        HP + (max_atk * 3) + (defence * 2) + (max_ap * 2)

    Why these weights:
      - HP × 1: how much you had to chip through
      - ATK × 3: how dangerous each turn was (multiplied because attacks repeat)
      - DEF × 2: how much it slowed you down
      - AP × 2: how often it could special-move you

    AP is capped at 8 because Chimera uses 99 as a sentinel value (its real
    resource is charges, not AP).
    """
    hp  = max(0, getattr(enemy, "max_hp", getattr(enemy, "hp", 0)))
    atk = max(0, getattr(enemy, "max_atk", 0))
    df  = max(0, getattr(enemy, "defence", 0))
    ap  = min(8, max(0, getattr(enemy, "max_ap", getattr(enemy, "ap", 0))))
    return hp + (atk * 3) + (df * 2) + (ap * 2)


# ============================================================
# PER-FIGHT SCORE RECORDING
# ============================================================

# Cache MONSTER_TYPES tier lookup — populated on first call.
_MONSTER_TIER_CACHE = None


def _tier_from_monster_types(enemy):
    """
    Resolve enemy tier by class lookup in monsters.MONSTER_TYPES.

    v0.6.19: Most monster classes don't set self.tier (only Chimera and
    Patronus do, at tier 5). The previous default of getattr(enemy, "tier", 3)
    silently treated every regular enemy as T3, which was harmless under
    the old lenient cap_rounds (T1=5, T2=8, T3=12 all easy to hit) but
    becomes wrong under the new strict quick-kill thresholds (T1=2, T2=3,
    T3=4). This helper builds a class → tier map from MONSTER_TYPES (the
    canonical encounter table) so every enemy gets its real tier.

    Falls back to 3 if the class can't be located — defensive only.
    """
    global _MONSTER_TIER_CACHE
    if _MONSTER_TIER_CACHE is None:
        try:
            from monsters import MONSTER_TYPES, weight_to_tier
            _MONSTER_TIER_CACHE = {
                cls: weight_to_tier(weight) for cls, weight in MONSTER_TYPES
            }
        except ImportError:
            _MONSTER_TIER_CACHE = {}
    # Prefer enemy.tier if explicitly set (Chimera = 5, Patronus = 5)
    explicit = getattr(enemy, "tier", None)
    if explicit is not None and explicit >= 1:
        return explicit
    return _MONSTER_TIER_CACHE.get(type(enemy), 3)


def _gold_config_key(enemy):
    """Map an enemy to its gold-config key — same logic gold.py uses."""
    name = getattr(enemy, "name", "")
    if name == "Young Chimera":
        return "chimera"
    if name == "Patronus":
        return "patronus"
    if name == "Fallen Warrior":
        return "fallen"
    return _tier_from_monster_types(enemy)


def record_fight_score(warrior, enemy, turn_count):
    """
    Call this immediately after the player defeats an enemy. Computes the
    per-fight score and appends it to warrior.per_fight_scores along with
    a breakdown for end-of-run display.

    Per-fight score formula:
        base          = threat_value(enemy)
        speed bonus   = +threat × 0.5   if turn_count <= QUICK_KILL_TURNS[tier]
                                          (suppressed for Patronus / Chimera —
                                           the outcome multiplier rewards the
                                           boss kill instead)
        drag penalty  = -threat × 0.3   if turn_count > penalty_start
        berserk       = +20             if warrior.berserk_used this fight
        defier        = +50             if warrior.death_defier_used this fight
        close match   = +threat × 0.5   if warrior.hp <= 20% max_hp
        Floor: per-fight never below threat / 2

    Side effects (v0.6.19):
        warrior.quick_kill_count += 1                      (if qualifying kill)
        warrior.quick_kill_multiplier_bonus += 0.10        (per qualifying kill)
        — applied to outcome multiplier at show_run_score()
    """
    if not hasattr(warrior, "per_fight_scores"):
        warrior.per_fight_scores = []
    # v0.6.19: initialize quick-kill accumulators on first call (idempotent)
    if not hasattr(warrior, "quick_kill_count"):
        warrior.quick_kill_count = 0
    if not hasattr(warrior, "quick_kill_multiplier_bonus"):
        warrior.quick_kill_multiplier_bonus = 0.0

    threat = threat_value(enemy)
    if threat <= 0:
        return  # Skip non-scoring enemies (shouldn't happen but defensive)

    config_key = _gold_config_key(enemy)
    base_gold, cap_rounds, penalty_start = GOLD_CONFIG.get(config_key, (5, 5, 5))
    # v0.6.19: separate threshold for quick-kill bonus, tighter than cap_rounds
    quick_kill_threshold = QUICK_KILL_TURNS.get(config_key)
    is_quick_kill = quick_kill_threshold is not None and turn_count <= quick_kill_threshold
    suppress_per_fight = config_key in SUPPRESS_PER_FIGHT_BONUS_FOR

    score = threat
    parts = [("Base threat", threat)]

    # Speed bonus / drag penalty
    # v0.6.19: speed bonus now keyed off QUICK_KILL_TURNS (tighter), and
    # suppressed for Patronus/Chimera (their outcome multiplier handles reward).
    if is_quick_kill and not suppress_per_fight:
        bonus = math.ceil(threat * SPEED_BONUS_PCT)
        score += bonus
        parts.append((f"⚡ Quick kill ({turn_count} turns ≤ {quick_kill_threshold})", bonus))
    elif turn_count > penalty_start:
        penalty = math.ceil(threat * DRAG_PENALTY_PCT)
        score -= penalty
        parts.append((f"Drag penalty ({turn_count} turns)", -penalty))

    # v0.6.19: accumulate quick-kill multiplier bonus (applies to outcome
    # multiplier at end of run). Final bosses also contribute even though
    # per-fight bonus is suppressed.
    if is_quick_kill:
        warrior.quick_kill_count += 1
        warrior.quick_kill_multiplier_bonus += QUICK_KILL_MULTIPLIER_PER_KILL
        parts.append((
            f"   → +{QUICK_KILL_MULTIPLIER_PER_KILL:.2f} run multiplier",
            0,   # zero score contribution at fight level; tracked separately
        ))

    # Performance bonuses
    # v0.6.21: read the *_this_fight flags (reset at battle_inner start), NOT
    # berserk_used / death_defier_used. Those carry across fights by design
    # (berserk_used gates re-trigger until HP recovers; death_defier_used is
    # run-wide), so reading them handed out these bonuses on every subsequent
    # fight after the first trigger. Fall back to the old flags only if the
    # per-fight ones are missing (defensive — shouldn't happen post-init).
    if getattr(warrior, "berserk_used_this_fight",
               getattr(warrior, "berserk_used", False)):
        score += BERSERK_BONUS_FLAT
        parts.append(("Berserk triggered", BERSERK_BONUS_FLAT))

    if getattr(warrior, "death_defier_used_this_fight",
               getattr(warrior, "death_defier_used", False)):
        score += DEFIER_BONUS_FLAT
        parts.append(("Death Defier triggered", DEFIER_BONUS_FLAT))

    # Close match bonus
    max_hp = max(1, getattr(warrior, "max_hp", 1))
    hp_pct = warrior.hp / max_hp if max_hp > 0 else 1.0
    if hp_pct <= CLOSE_MATCH_HP_PCT:
        bonus = math.ceil(threat * CLOSE_MATCH_BONUS_PCT)
        score += bonus
        parts.append(("Close match (low HP survival)", bonus))

    # Floor
    floor = threat // 2
    if score < floor:
        old = score
        score = floor
        parts.append((f"Floor enforced ({old} → {floor})", floor - old))

    warrior.per_fight_scores.append({
        "enemy_name": getattr(enemy, "display_name", getattr(enemy, "name", "?")),
        "threat":     threat,
        "score":      score,
        "parts":      parts,
    })


# ============================================================
# RUN-WIDE SCORE COMPUTATION
# ============================================================

def _compute_title_score(warrior):
    """Sum of points from all earned regular titles."""
    titles = getattr(warrior, "titles", set())
    total = 0
    earned = []
    for key in titles:
        pts = TITLE_SCORE_VALUES.get(key, 0)
        if pts > 0:
            total += pts
            earned.append((key, pts))
    return total, earned


def _compute_fate_title_score(warrior):
    """Sum of points from all earned fate titles."""
    fates = getattr(warrior, "fate_titles", set())
    total = 0
    earned = []
    for key in fates:
        pts = FATE_TITLE_SCORE_VALUES.get(key, 0)
        if pts > 0:
            total += pts
            earned.append((key, pts))
    return total, earned


def _compute_potion_score(warrior):
    """
    Score from unused potions remaining. All regular potions × 5, capped at 100.
    Frostpine Tonic awarded separately at +25 if saved (not in the cap).
    """
    potions = getattr(warrior, "potions", {}) or {}
    regular_keys = (
        "heal", "super_potion", "mega_potion", "full_potion",
        "ap", "super_ap", "mega_ap", "full_ap",
        "antidote", "burn_cream",
        "mana", "greater_mana",
    )
    regular_count = sum(potions.get(k, 0) for k in regular_keys)
    regular_score = min(POTION_BONUS_CAP, regular_count * POTION_VALUE)

    frostpine_count = potions.get("frostpine_tonic", 0)
    frostpine_score = FROSTPINE_TONIC_SAVED_VALUE if frostpine_count > 0 else 0

    return regular_score, regular_count, frostpine_score, frostpine_count


def _rank_for_score(score):
    """Return (rank_letter, description) for a final score."""
    for letter, threshold in RANK_THRESHOLDS:
        if score >= threshold:
            return letter, RANK_DESCRIPTIONS[letter]
    return "F", RANK_DESCRIPTIONS["F"]


# ============================================================
# DISPLAY
# ============================================================

def show_run_score(warrior, outcome="defeat"):
    """
    Print the full end-of-run score breakdown, then the final rank.

    outcome: one of "chimera_victory", "patronus_victory",
             "intervention", "defeat", "gooed"
    """
    # Lazy-import combat_log run stats so this module stays standalone
    try:
        from combat_log import get_run_stats
        stats = get_run_stats()
    except ImportError:
        stats = {
            "total_dmg_dealt":  0,
            "total_dmg_blocked": 0,
            "fights_won":        0,
            "fights_lost":       0,
            "total_turns":       0,
        }

    name = getattr(warrior, "name", "Warrior")

    # ---- Combat performance (capped) ----
    raw_dmg_dealt   = stats.get("total_dmg_dealt", 0)
    raw_dmg_blocked = stats.get("total_dmg_blocked", 0)
    dmg_score      = min(DAMAGE_DEALT_CAP,   math.floor(raw_dmg_dealt   * DAMAGE_DEALT_WEIGHT))
    block_score    = min(DAMAGE_BLOCKED_CAP, math.floor(raw_dmg_blocked * DAMAGE_BLOCKED_WEIGHT))

    # ---- Per-fight bonuses ----
    per_fights = getattr(warrior, "per_fight_scores", []) or []
    per_fight_total = sum(f["score"] for f in per_fights)

    # ---- Resources ----
    total_gold = int(getattr(warrior, "total_gold_earned", getattr(warrior, "gold", 0)))
    gold_score = math.floor(total_gold * GOLD_WEIGHT)

    potion_score, potion_count, frostpine_score, frostpine_count = _compute_potion_score(warrior)

    # ---- Mastery ----
    level = max(1, int(getattr(warrior, "level", 1)))
    level_score = (level - 1) * LEVEL_WEIGHT

    title_score, titles_earned = _compute_title_score(warrior)
    fate_score,  fates_earned  = _compute_fate_title_score(warrior)

    # ---- Luck ----
    jackpot_count = int(getattr(warrior, "jackpot_count", 0))
    jackpot_score = jackpot_count * JACKPOT_VALUE
    bookie_count  = int(getattr(warrior, "bookie_intimidated_count", 0))
    bookie_score  = bookie_count * BOOKIE_INTIMIDATED_VALUE

    # ---- Subtotal & multiplier ----
    subtotal = (
        dmg_score + block_score + per_fight_total
        + gold_score + potion_score + frostpine_score
        + level_score + title_score + fate_score
        + jackpot_score + bookie_score
    )

    base_multiplier = OUTCOME_MULTIPLIERS.get(outcome, 1.0)

    # v0.6.19: additive quick-kill multiplier bonus accumulated during the run.
    # Each qualifying quick kill added +0.10 to warrior.quick_kill_multiplier_bonus.
    # Maximum theoretical with 4 regular rounds + Fallen + Chimera = 0.60 bonus,
    # producing 2.7× ceiling on the good path (2.1 outcome + 0.6 quick kills)
    # or 2.6× on the evil path (2.0 + 0.6).
    qk_bonus = float(getattr(warrior, "quick_kill_multiplier_bonus", 0.0) or 0.0)
    qk_count = int(getattr(warrior, "quick_kill_count", 0) or 0)
    multiplier = round(base_multiplier + qk_bonus, 2)
    multiplied = math.floor(subtotal * multiplier)

    # Post-multiplier flat bonuses
    final_score = multiplied
    if outcome == "gooed":
        final_score += GOOED_PITY_BONUS

    rank_letter, rank_desc = _rank_for_score(final_score)

    # ---- Render ----
    # Use a row helper for consistent alignment: label on left, value right-aligned
    width = 52
    bar = "═" * width
    inner_width = width - 4   # account for "  " indent on both sides

    def _row(label, value, indent=4):
        """Print one aligned row: indent + label, value right-aligned to width."""
        prefix = " " * indent
        line = f"{prefix}{label}"
        # Compute padding so the value aligns at column `width`
        pad = max(1, width - len(line) - len(str(value)))
        print(f"{line}{' ' * pad}{value}")

    print()
    print(bar)
    print(f"  FINAL SCORE — {name}")
    print(bar)

    print("  Combat Performance")
    # Run-wide totals shown up front so the player can see what they actually did
    _row("Total Damage Dealt",   raw_dmg_dealt)
    _row("Total Damage Blocked", raw_dmg_blocked)
    print(f"  {'·' * (width - 4)}")
    cap_dmg = " (capped)" if dmg_score == DAMAGE_DEALT_CAP and raw_dmg_dealt * DAMAGE_DEALT_WEIGHT > DAMAGE_DEALT_CAP else ""
    cap_blk = " (capped)" if block_score == DAMAGE_BLOCKED_CAP and raw_dmg_blocked * DAMAGE_BLOCKED_WEIGHT > DAMAGE_BLOCKED_CAP else ""
    _row(f"Damage Dealt score (×{DAMAGE_DEALT_WEIGHT})",     f"+{dmg_score}{cap_dmg}")
    _row(f"Damage Blocked score (×{DAMAGE_BLOCKED_WEIGHT})", f"+{block_score}{cap_blk}")
    _row(f"Per-Fight Bonuses ({len(per_fights)})",           f"+{per_fight_total}")

    print()
    print("  Resources")
    _row(f"Gold Earned ({total_gold})",     f"+{gold_score}")
    cap_pot = " (capped)" if potion_score == POTION_BONUS_CAP else ""
    _row(f"Potions Saved ({potion_count})", f"+{potion_score}{cap_pot}")
    if frostpine_count > 0:
        _row("Frostpine Tonic Saved",       f"+{frostpine_score}")

    print()
    print("  Mastery")
    _row(f"Player Level ({level})",         f"+{level_score}")
    if titles_earned:
        _row(f"Titles Earned ({len(titles_earned)})", f"+{title_score}")
        for key, pts in sorted(titles_earned, key=lambda kv: -kv[1]):
            display = _title_display_name(key)
            print(f"      • {display} (+{pts})")
    if fates_earned:
        _row(f"Fate Titles ({len(fates_earned)})",    f"+{fate_score}")
        for key, pts in sorted(fates_earned, key=lambda kv: -kv[1]):
            display = _title_display_name(key)
            print(f"      • {display} (+{pts})")

    if jackpot_count > 0 or bookie_count > 0:
        print()
        print("  Luck")
        if jackpot_count > 0:
            _row(f"Jackpots Triggered ({jackpot_count})",     f"+{jackpot_score}")
        if bookie_count > 0:
            _row(f"Bookies Intimidated ({bookie_count})",     f"+{bookie_score}")

    print()
    print(f"  {'─' * (width - 4)}")
    _row("Subtotal", subtotal, indent=2)

    outcome_label = _outcome_label(outcome)
    # v0.6.19: show quick-kill multiplier as a separate breakdown line if any
    # quick kills happened, so the player can see where the bonus came from.
    if qk_count > 0 and qk_bonus > 0:
        _row(
            f"× {base_multiplier} ({outcome_label}) + {qk_bonus:.2f} ({qk_count}× ⚡ quick kill)",
            f"× {multiplier}",
            indent=2,
        )
        _row("= multiplied", multiplied, indent=2)
    elif multiplier != 1.0:
        _row(f"× {multiplier} ({outcome_label})",    multiplied, indent=2)
    else:
        _row(f"({outcome_label})",                   multiplied, indent=2)

    if outcome == "gooed":
        _row(f"+ {GOOED_PITY_BONUS} (Goo Guy pity bonus)",  final_score, indent=2)

    print(f"  {'─' * (width - 4)}")
    _row("FINAL SCORE", final_score, indent=2)
    print()

    # ---- Rank ----
    rank_box_width = 30
    print("  ╔" + "═" * (rank_box_width - 2) + "╗")
    rank_line = f"   RANK:  {rank_letter}"
    print(f"  ║{rank_line}{' ' * (rank_box_width - len(rank_line) - 2)}║")
    print("  ╚" + "═" * (rank_box_width - 2) + "╝")
    print(f"  {rank_desc}")
    print(bar)
    input("\nPress Enter to continue...")

    return final_score


def _outcome_label(outcome):
    return {
        "chimera_victory":  "Chimera victory — good path",
        "patronus_victory": "Patronus victory — evil path",
        "intervention":     "Intervention save",
        "defeat":           "Defeat",
        "gooed":            "Death by Goo",
        "flayed_one":       "Flayed One — river rocks",
        "drowned_one":      "Drowned One — waterfall",
        "coward":           "Coward — fled the arena",
    }.get(outcome, "Unknown outcome")


def _title_display_name(key):
    """Lookup display name for a title key via titles.TITLE_DISPLAY."""
    try:
        from titles import TITLE_DISPLAY
        return TITLE_DISPLAY.get(key, key)
    except ImportError:
        return key
