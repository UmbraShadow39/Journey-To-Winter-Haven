"""
gold.py — Arena gold reward system for Journey to Winter Haven
--------------------------------------------------------------
Handles:
  - Per-tier base gold payouts
  - Round-based bonuses and penalties (with a floor at base gold)
  - Performance bonuses (berserk, death defier, close match)
  - Goblin bookie d20 encounter (steal / catch / intimidate)
"""

import random
import math

# ------------------------------------------------------------------ #
#  CONFIGURATION                                                       #
# ------------------------------------------------------------------ #

GOLD_CONFIG = {
    # tier: (base_gold, bonus_cap_rounds, penalty_start_rounds)
    1:            (5,  5,  5),
    2:            (10, 8,  8),
    3:            (15, 12, 12),
    "fallen":     (20, 12, 12),
    "patronus":   (30, 12, 12),
    "chimera":    (0,  0,  0),   # No payout — angered the Beast Gods
}

# Performance bonuses
BERSERK_BONUS      = 5
DEATH_DEFIER_BONUS = 10
CLOSE_MATCH_HP_PCT = 0.20   # warrior HP at or below this % = close match

# Bookie d20 thresholds
BOOKIE_CATCH_MIN      = 12   # roll 12+ → catch the skim
BOOKIE_INTIMIDATE_MIN = 18   # roll 18+ → intimidate for bonus
BOOKIE_SKIM_PCT       = 0.10 # 10% stolen on a failed catch
BOOKIE_BONUS_PCT      = 0.10 # 10% bonus on intimidate


# ------------------------------------------------------------------ #
#  GOLD AWARD HELPER                                                   #
# ------------------------------------------------------------------ #

def award_gold(warrior, amount):
    """
    Add gold to the warrior's pouch AND track it for lifetime totals.
    The score system reads `total_gold_earned` so spending gold doesn't
    cost the player score points.

    Use this anywhere gold is added to the player. Negative amounts are
    silently treated as zero — use direct `warrior.gold -= ...` for
    deductions (so they don't reduce lifetime earnings).
    """
    if amount <= 0:
        return
    warrior.gold = getattr(warrior, "gold", 0) + amount
    warrior.total_gold_earned = getattr(warrior, "total_gold_earned", 0) + amount


# ------------------------------------------------------------------ #
#  GOLD CALCULATION                                                    #
# ------------------------------------------------------------------ #

def calculate_gold_reward(enemy, turn_count, warrior):
    """
    Calculate earned gold for a single arena fight.

    Parameters
    ----------
    enemy      : the defeated enemy object (needs .tier and .name)
    turn_count : number of combat turns that elapsed
    warrior    : the Hero/Warrior object

    Returns
    -------
    dict with keys:
        base, round_bonus, round_penalty, performance_bonus,
        close_match, total, breakdown (list of strings for display)
    """

    enemy_name = getattr(enemy, "name", "")

    # --- Chimera: always zero ---
    if enemy_name == "Young Chimera":
        return {
            "base": 0, "round_bonus": 0, "round_penalty": 0,
            "performance_bonus": 0, "close_match": False, "total": 0,
            "breakdown": ["The Beast Gods take everything. 0 gold."]
        }

    # --- Determine tier key ---
    tier = getattr(enemy, "tier", 3)
    if enemy_name == "Patronus":
        config_key = "patronus"
    elif enemy_name == "Fallen Champion":
        config_key = "fallen"
    else:
        config_key = tier

    base_gold, cap_rounds, penalty_start = GOLD_CONFIG.get(config_key, (5, 5, 5))

    breakdown = []

    # --- Round bonuses / penalties ---
    round_bonus   = 0
    round_penalty = 0

    if turn_count <= cap_rounds:
        round_bonus = turn_count - 1          # +1 per round up to cap
        breakdown.append(f"+{round_bonus} gold (fight lasted {turn_count} rounds)")
    else:
        over = turn_count - penalty_start
        if over > 0:
            round_penalty = over              # -1 per round over the cap
            breakdown.append(f"-{round_penalty} gold (fight dragged on {over} rounds too long)")

    # --- Performance bonuses ---
    performance_bonus = 0

    if getattr(warrior, "berserk_used", False):
        performance_bonus += BERSERK_BONUS
        breakdown.append(f"+{BERSERK_BONUS} gold (Berserk triggered)")

    if getattr(warrior, "death_defier_used", False):
        performance_bonus += DEATH_DEFIER_BONUS
        breakdown.append(f"+{DEATH_DEFIER_BONUS} gold (Death Defier triggered)")

    # --- Close match check ---
    close_match = False
    hp_pct = warrior.hp / warrior.max_hp if warrior.max_hp > 0 else 1.0
    if hp_pct <= CLOSE_MATCH_HP_PCT:
        close_match = True
        breakdown.append(f"+{base_gold} gold bonus (close match — you barely survived!)")

    # --- Total with floor ---
    raw_total = base_gold + round_bonus - round_penalty + performance_bonus
    if close_match:
        raw_total += base_gold             # restore base on close match

    total = max(base_gold, raw_total)      # floor: never below base

    if raw_total < base_gold:
        breakdown.append(f"(Minimum payout enforced — floor is {base_gold} gold)")

    return {
        "base":              base_gold,
        "round_bonus":       round_bonus,
        "round_penalty":     round_penalty,
        "performance_bonus": performance_bonus,
        "close_match":       close_match,
        "total":             total,
        "breakdown":         breakdown,
    }


# ------------------------------------------------------------------ #
#  GOLD DISPLAY                                                        #
# ------------------------------------------------------------------ #

def display_gold_earned(result):
    """
    Print the gold breakdown to the terminal after a fight.
    Call this immediately after calculate_gold_reward().
    """
    print("\n🪙 --- Fight Payout ---")
    print(f"   Base reward : {result['base']} gold")
    for line in result["breakdown"]:
        print(f"   {line}")
    print(f"   Earned      : {result['total']} gold (held until the bookie pays out)")
    print()


# ------------------------------------------------------------------ #
#  GOBLIN BOOKIE ENCOUNTER                                             #
# ------------------------------------------------------------------ #

def bookie_encounter(warrior):
    """
    The goblin bookie d20 encounter — call this from arena_quarters_interlude
    when the player chooses option 1 (Talk to goblin bookie).

    Reads  warrior.pending_bookie_gold  (set after each round win).
    Writes warrior.gold on payout.
    Clears warrior.pending_bookie_gold after paying out.

    d20 results:
      1–11  : Bookie skims 10% — player doesn't catch it
      12–17 : Player catches the skim — full amount paid
      18–20 : Player intimidates bookie — full amount + 10% bonus
    """
    from shared import wrap, continue_text   # keep import local so gold.py stays portable

    pending = getattr(warrior, "pending_bookie_gold", 0)

    if pending <= 0:
        print(wrap("The goblin bookie glances at you sideways. "
                   "'No winnings to collect yet, friend.'"))
        continue_text()
        return

    print(wrap(
        "The goblin bookie is hunched over a small table, coins "
        "stacked in neat towers. He looks up with a too-wide grin."
    ))
    print(wrap(f"'Ah, the champion! I've been counting your winnings — "
               f"{pending} gold. Let me just... tally that up.'"))
    print()

    # --- Second visit: bookie remembers what happened last time ---
    prior = getattr(warrior, "bookie_result", None)
    if prior is not None:
        _bookie_second_visit(warrior, prior)
        continue_text()
        return

    roll = random.randint(1, 20)

    # ---- FAIL: bookie skims ----
    if roll < BOOKIE_CATCH_MIN:
        skim        = math.floor(pending * BOOKIE_SKIM_PCT)
        paid        = pending - skim
        award_gold(warrior, paid)
        warrior.pending_bookie_gold = 0
        warrior.bookie_result = "stolen"

        print(wrap(
            "His fingers move with practiced speed. Something feels off "
            "but you can't quite place it."
        ))
        print(wrap(f"'There you are — {paid} gold, counted true!' He beams."))
        print(wrap(f"(You didn't notice the {skim} gold that vanished into his sleeve.)"))
        print(f"\n🪙 Received {paid} gold.  Total: {warrior.gold} gold.")

    # ---- CATCH: player notices ----
    elif roll < BOOKIE_INTIMIDATE_MIN:
        paid        = pending
        award_gold(warrior, paid)
        warrior.pending_bookie_gold = 0
        warrior.bookie_result = "caught"

        print(wrap(
            "You watch his hand drift toward a hidden pocket. "
            "You clear your throat loudly."
        ))
        print(wrap("The goblin freezes. 'I was just — ah — checking the count. "
                   "Yes. All there.'"))
        print(wrap(f"He slides the full {paid} gold across the table without another word."))
        print(f"\n🪙 Received {paid} gold.  Total: {warrior.gold} gold.")

    # ---- INTIMIDATE: bonus payout ----
    else:
        bonus       = math.ceil(pending * BOOKIE_BONUS_PCT)
        paid        = pending + bonus
        award_gold(warrior, paid)
        warrior.pending_bookie_gold = 0
        warrior.bookie_result = "intimidated"
        # Track intimidated bookies for score luck bonus
        warrior.bookie_intimidated_count = getattr(warrior, "bookie_intimidated_count", 0) + 1

        print(wrap(
            "You catch his hand mid-skim. You lean in close and say nothing — "
            "just stare."
        ))
        print(wrap(
            "The goblin goes pale green. His voice cracks. "
            "'S-sorry, sorry! Here — take a little extra, no hard feelings!'"
        ))
        print(wrap(f"He shoves {paid} gold at you and backs away slowly."))
        print(f"\n🪙 Received {paid} gold (+{bonus} intimidation bonus).  "
              f"Total: {warrior.gold} gold.")

    # v0.6.16: pause so the player can read the outcome before returning
    # to the interlude (which would otherwise clear_screen immediately).
    continue_text()


# ------------------------------------------------------------------ #
#  BOOKIE SECOND VISIT DIALOGUES                                       #
# ------------------------------------------------------------------ #

def _bookie_second_visit(warrior, prior_result):
    """
    Called when the player talks to the bookie a second time.
    Dialogue varies based on what happened during the first visit.
    """
    from shared import wrap, continue_text

    if prior_result == "stolen":
        # He got away with it — emboldened, gleam in his eye
        print(wrap(
            "You notice a gleam in his eye the moment you approach. "
            "He grins wide, teeth too many and too sharp."
        ))
        print(wrap(
            "'Ah, back again! Always a pleasure. I do hope we'll be "
            "seeing you out there again...'"
        ))
        print(wrap(
            "He taps the coin purse at his hip slowly. "
            "'Very good for business.'"
        ))

    elif prior_result == "caught":
        # You called him out — he's nervous, overly eager
        print(wrap(
            "He straightens up the moment he sees you, "
            "both hands flat and visible on the table."
        ))
        print(wrap(
            "'Champion. Good fight out there. I — I really do hope "
            "you go again. Truly.'"
        ))
        print(wrap(
            "He laughs once, too short, and doesn't quite meet your eyes."
        ))

    elif prior_result == "intimidated":
        # You scared him properly — part fear, part reverence
        print(wrap(
            "He goes very still the moment you walk in. "
            "Something between fear and reverence crosses his face."
        ))
        print(wrap("'...Good luck out there.'"))
        print(wrap("A pause."))
        print(wrap("'I mean that. I'm genuinely glad I'm not the one fighting you.'"))
        print()
        print(wrap(
            "He slides a single coin across the table without being asked. "
            "Just to have something to do with his hands."
        ))
        award_gold(warrior, 1)
        print(f"🪙 +1 gold.  Total: {warrior.gold} gold.")


# ------------------------------------------------------------------ #
#  HELPER: store pending gold after a fight                           #
# ------------------------------------------------------------------ #

def award_pending_gold(warrior, result):
    """
    Store calculated gold on the warrior after a fight.
    The bookie will pay it out when the player visits him in the quarters.
    Also initialises bookie tracking attributes if not already set.
    """
    if not hasattr(warrior, "pending_bookie_gold"):
        warrior.pending_bookie_gold = 0
    if not hasattr(warrior, "bookie_result"):
        warrior.bookie_result = None

    warrior.pending_bookie_gold += result["total"]


# ------------------------------------------------------------------ #
#  RUN SCORING SYSTEM                                                  #
# ------------------------------------------------------------------ #

# Score thresholds → rank
RANK_THRESHOLDS = [
    (125, "S", "🌟 EXCEPTIONAL",  "A performance the Beast Gods will remember."),
    (100, "A", "⭐ IMPRESSIVE",   "Few fighters leave the arena looking that good."),
    ( 75, "B", "✅ SOLID",        "A good run. You know what you're doing."),
    ( 50, "C", "🔷 AVERAGE",      "Decent showing. Room to grow."),
    ( 30, "D", "⚠️  ROUGH",        "You survived. Barely counts, but it counts."),
    (  0, "F", "💀 FAIL",         "The crowd has already forgotten your name."),
]

# Damage scoring
DMG_DEALT_DIVISOR   = 5    # 1 point per 5 damage dealt
DMG_BLOCKED_DIVISOR = 3    # 1 point per 3 damage blocked (harder to build, worth more)

# Points per item equipped (out of 4 slots)
LOOT_PER_ITEM   = 8
# Points per unused potion (any type)
POTION_PER_UNIT = 3
# Points per title earned
TITLE_PER_TITLE = 5
# Gold scoring: 1 point per 3 gold earned above starting funds
GOLD_DIVISOR    = 3
STARTING_GOLD   = 3
# Skill mastery bonuses
SKILL_RANK3_BONUS   = 5    # per skill at rank 3 or 4
SKILL_MAXRANK_BONUS = 10   # per skill at max rank (5)


def calculate_run_score(warrior):
    """
    Calculate a final run score and letter rank.

    Returns a dict with:
        score        — total integer score
        rank         — letter (S/A/B/C/D/F)
        label        — emoji + rank name
        flavour      — one-line flavour text
        breakdown    — list of (label, points) tuples for display
    """
    from combat_log import get_run_stats
    run_stats = get_run_stats()

    breakdown = []

    # --- Damage dealt ---
    dmg_dealt = run_stats.get("total_dmg_dealt", 0)
    dealt_score = dmg_dealt // DMG_DEALT_DIVISOR
    breakdown.append((f"Damage dealt ({dmg_dealt})", dealt_score))

    # --- Damage blocked ---
    dmg_blocked = run_stats.get("total_dmg_blocked", 0)
    blocked_score = dmg_blocked // DMG_BLOCKED_DIVISOR
    breakdown.append((f"Damage blocked ({dmg_blocked})", blocked_score))

    # --- Gold score (above starting funds) ---
    earned_gold = max(0, warrior.gold - STARTING_GOLD)
    gold_score  = earned_gold // GOLD_DIVISOR
    breakdown.append((f"Gold ({warrior.gold}g earned)", gold_score))

    # --- Loot score: equipped items ---
    equipped    = getattr(warrior, "equipment", {})
    items_on    = sum(1 for v in equipped.values() if v is not None)
    loot_score  = items_on * LOOT_PER_ITEM
    breakdown.append((f"Loot ({items_on}/4 slots filled)", loot_score))

    # --- Potion efficiency: unused potions ---
    potions     = getattr(warrior, "potions", {})
    unused      = sum(v for v in potions.values() if isinstance(v, int))
    potion_score = unused * POTION_PER_UNIT
    breakdown.append((f"Potions unused ({unused})", potion_score))

    # --- Titles bonus ---
    titles      = getattr(warrior, "titles", set())
    title_score = len(titles) * TITLE_PER_TITLE
    breakdown.append((f"Titles ({len(titles)} earned)", title_score))

    # --- Jackpot bonus ---
    jackpots    = getattr(warrior, "jackpot_count", 0)
    jackpot_score = jackpots * 8
    if jackpots:
        breakdown.append((f"Jackpot! ({jackpots}x double reward)", jackpot_score))

    # --- Skill mastery bonus ---
    skill_ranks  = getattr(warrior, "skill_ranks", {})
    skill_score  = 0
    maxed_skills = 0
    boosted_skills = 0
    for rank in skill_ranks.values():
        if rank >= 5:
            skill_score += SKILL_MAXRANK_BONUS
            maxed_skills += 1
        elif rank >= 3:
            skill_score += SKILL_RANK3_BONUS
            boosted_skills += 1
    if skill_score > 0:
        breakdown.append((
            f"Skill mastery ({maxed_skills} maxed, {boosted_skills} boosted)",
            skill_score
        ))

    # --- Total ---
    score = (dealt_score + blocked_score + gold_score + loot_score
             + potion_score + title_score + skill_score + jackpot_score)

    # --- Rank ---
    rank, label, flavour = "F", "💀 FAIL", "The crowd has already forgotten your name."
    for threshold, r, l, f in RANK_THRESHOLDS:
        if score >= threshold:
            rank, label, flavour = r, l, f
            break

    return {
        "score":     score,
        "rank":      rank,
        "label":     label,
        "flavour":   flavour,
        "breakdown": breakdown,
    }


def display_run_score(warrior):
    """
    Print the end-of-run score card.
    Call this after show_all_game_stats() and before show_run_score().
    """
    result = calculate_run_score(warrior)

    print("\n" + "=" * 40)
    print("       📊 ARENA PERFORMANCE RATING")
    print("=" * 40)

    for label, pts in result["breakdown"]:
        bar = "█" * min(pts, 30)
        print(f"  {label:<28} +{pts:>3}  {bar}")

    print("-" * 40)
    print(f"  {'TOTAL SCORE':<28}  {result['score']:>3}")
    print("=" * 40)
    print(f"\n  RANK: {result['label']}")
    print(f"  {result['flavour']}")
    print("\n" + "=" * 40 + "\n")
