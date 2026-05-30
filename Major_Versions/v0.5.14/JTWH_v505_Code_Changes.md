# Journey to Winter Haven — v5.05 Code Changes
## What changed, where, and why

---

## 1. Bug Fix — `import math` crash (Charged Jagged Rock)

**Where:** Inside `player_basic_attack()`, Goblin War Blade bleed block

**What changed:**
```python
# REMOVED this line from inside the function:
import math
```

**Why:** Python treats any variable that's assigned anywhere in a function as local to the entire function. The `import math` inside the bleed block made Python treat `math` as a local variable throughout all of `player_basic_attack`. So when Charged Jagged Rock tried to call `math.floor()` earlier in the same function, Python looked for the local `math` that hadn't been assigned yet and crashed with `UnboundLocalError`. `math` was already imported at module level (line 5) so the local import was completely redundant.

---

## 2. Bug Fix — Charged Jagged Rock stale stats on Hardened enemies

**Where:** `apply_level_scaling()` and `apply_level_scaling_debug_any()`

**What changed:**
```python
# Added at end of both scaling functions:
monster.psychic_base_min_atk = monster.min_atk
monster.psychic_base_max_atk = monster.max_atk
monster.psychic_base_defence = monster.defence
```

**Why:** `Monster.__init__` sets `psychic_base_*` fields at spawn time. But level scaling runs *after* `__init__` and bumps `min_atk`, `max_atk`, and `defence` directly without updating the psychic base fields. So a Hardened enemy (level 2) had base stats 1 point higher than what the Charged Jagged Rock cap math thought they were. The re-sync at the end of both scaling functions ensures the cap calculations always use the correct post-scaling values.

---

## 3. Bug Fix — Turn counter not advancing on lost player turns

**Where:** Battle loop in `battle_inner()`, four `last_turn_skipped = True` paths

**What changed:**
```python
# Added turn_spent = True before each continue in lost-turn paths:
warrior.last_turn_skipped = True
turn_spent = True          # <-- ADDED
warrior_turn = False
player_turn_started = False
continue
```

**Why:** `turn_count` only increments when `turn_spent = True` AND `warrior_turn = True`. When the player lost their turn to blind or stun, the code set `warrior_turn = False` and `continue`d — but never set `turn_spent = True`. So the turn counter never advanced, causing the enemy to get extra turns at the same turn number. Fixed in all four lost-turn paths (goblin dust blind, First Aid cancel, struggle choice, generic stun).

---

## 4. Psychic Drown punishment rework

**Where:** `check_drown_punishment()`, battle loop enemy turn section

**What changed:**
```python
# OLD: fired when player couldn't afford cheapest move based on max_ap
if warrior.max_ap >= inflated_cost:
    return  # no punishment

# NEW: removed entirely. Replaced with ATK boost in battle loop:
if warrior.ap < cheapest_cost:
    drown_gap_boost = 2
    enemy.min_atk += drown_gap_boost
    enemy.max_atk += drown_gap_boost
    # ... attack fires at boosted ATK ...
    enemy.min_atk -= drown_gap_boost  # restored after attack
    enemy.max_atk -= drown_gap_boost
```

**Why:** The original `max_ap` check meant players with decent AP pools never got punished even when locked out in combat. The punishment should be about *current* AP not max AP. The ATK boost approach is more elegant — the enemy senses your weakness and hits harder, defence still absorbs it, and the counter-play (Waterlogged Stone to restore AP) directly reduces the boost.

---

## 5. Skill system overhaul — SKILL_DEFS

**Where:** `SKILL_DEFS` dictionary, `get_skill_desc()` (new function), `show_skill_tree()`

**What changed:**
```python
# OLD: static desc string
"power_strike": {
    "max_rank": 10,
    "upgrade_costs": [1, 1, 2, 3, 4, 5, 6, 7, 8, 10],
    "desc": "A powerful single attack...",
}

# NEW: rank_descs dict + tier2_name, capped at 5
"power_strike": {
    "max_rank": 5,
    "upgrade_costs": [1, 1, 2, 3, 4],
    "tier2_name": "Double Strike",
    "rank_descs": {
        1: "Bonus damage = half your attack roll (rounded down).  1 AP",
        2: "Bonus damage = half your attack roll (rounded up).    1 AP",
        3: "Bonus damage = ¾ your attack roll (rounded down).     2 AP",
        4: "Bonus damage = ¾ your attack roll (rounded up).       2 AP",
        5: "Bonus damage = your full attack roll.                 3 AP",
    },
}
```

**New function:**
```python
def get_skill_desc(key, hero):
    # Sliding window — shows 2 ranks ahead of current rank
    # Rank 0 → shows ranks 1+2
    # Rank 1 → shows ranks 2+3
    # Rank 4 → shows rank 5 + "🔒 Double Strike — Locked (Demo)"
    # Rank 5 → shows only "🔒 Double Strike — Locked (Demo)"
```

**Why:** The old static string showed all ranks at once, spoiling the progression. The sliding window creates discovery — you only see what's coming next. The tier 2 name tease at rank 4/5 gives long-term players something to chase without explaining what the move does. Max rank reduced from 10 to 5 because the functions were internally clamped at 5 anyway — the extra ranks were phantom.

---

## 6. Defence Break — new player skill

**Where:** New section between `power_strike` and Base Classes

**New code:**
```python
DEFENCE_BREAK_STATS = {
    1: (0.10, 2),   # (pct reduction, turns duration)
    2: (0.20, 2),
    3: (0.30, 3),
    4: (0.40, 3),
    5: (0.50, 3),
}

def defence_break_ap_cost(rank): # R1-2: 2AP, R3-4: 3AP, R5: 4AP

def defence_break(warrior, enemy, chosen_rank):
    # Reduces enemy DEF by pct (min 1 reduction always)
    # Stores base_def so refreshes don't compound
    # 0 DEF: deals 1 true damage instead

def _tick_defence_break(enemy):
    # Called each enemy turn — counts down, restores DEF on expiry

def _clear_defence_break(enemy):
    # Full reset between rounds

def _award_defence_break(warrior):
    # Fallen Warrior kill reward
    # Rank 0 → unlock rank 1 with narrative
    # Rank 1-4 → free rank up
    # Rank 5 → flavour only
```

**Also added:**
- `Monster.__init__`: `defence_break_active/turns/pct/base_def` fields
- `Hero.skill_ranks`: `"defence_break": 0`
- `SKILL_DEFS`: Defence Break entry, min_level 3
- `skill_menu()`: Defence Break option
- `_tick_defence_break()` wired into enemy turn start
- `_award_defence_break()` wired into both Fallen Warrior kill paths
- Debug menu option 13 updated to grant Defence Break

**Why:** Fallen Warrior's Defence Warp already bypassed armour — it made narrative sense for the player to learn a similar technique from defeating him. Unlocking at level 3 gates it behind progression. The percentage system scales cleanly with any enemy DEF value, unlike a flat -1 that would become meaningless on high-DEF enemies later.

---

## 7. River Spirit / Death Defier split

**Where:** `try_death_defier()`, `activate_death_defier()`, `show_combat_stats()`, `show_game_stats()`, `skill_menu()`, debug menu, river unlock message

**What changed:**
```python
# Everywhere Death Defier was displayed, now checks death_defier_river flag:
dd_name = "River Spirit" if getattr(hero, "death_defier_river", False) else "Death Defier"
print(f"💀✨ {dd_name} surges — you refuse to die!")
```

**Why:** The river path reward and the skill tree investment are mechanically different things — river gives 1 HP free, skill gives rank-based % HP at AP cost. Naming them the same thing was confusing. River Spirit clearly communicates "this came from the story, not training."

---

## 8. Boss drops — fixed stats, no rarity rolls

**Where:** `WEAPON_CORE_DEFENSIVE/OFFENSIVE_STATS` replaced, `CHIMERA_SCALE_STATS` simplified, `TAINTED_CHAMPIONS_SHIELD_STATS` added, `_make_weapon_core()` rewritten

**What changed:**
```python
# OLD: 7-tier rarity tables
WEAPON_CORE_DEFENSIVE_STATS = {
    "poor": {"atk_min": 3, "atk_max": 3, "defence": 2},
    ... # 7 rarities
}

# NEW: fixed stats, no rarity
WEAPON_CORE_ONEHANDED_STATS = {"atk_min": 4, "atk_max": 4, "defence": 2}
WEAPON_CORE_TWOHANDED_STATS = {"atk_min": 5, "atk_max": 5, "defence": 1}
CHIMERA_SCALE_STATS = {"defence": 5, "max_hp": 0}
TAINTED_CHAMPIONS_SHIELD_STATS = {"defence": 6, "max_hp": -2}

# Weapon Core renamed:
form_name = "Lightrender"      # one-handed
form_name = "Destiny Definer"  # two-handed
```

**Why:** Boss drops are milestone rewards, not random loot. A player getting a "poor" Weapon Core after defeating the Fallen Warrior would feel terrible. Fixed stats mean the reward always feels earned. The negative `max_hp` on Light Corrupter is intentional — it's corrupted gear with a cost.

---

## 9. Goblin Shortbow — new weapon replacing Paralyzing Arrow

**Where:** `PARALYZING_ARROW_STATS` replaced with `GOBLIN_SHORTBOW_STATS`, loot table entry updated, paralyze proc moved from accessory to weapon slot

**What changed:**
```python
# OLD: Paralyzing Arrow (accessory)
PARALYZING_ARROW_STATS = {
    "poor": {"atk_min": 2, "atk_max": 2, "paralyze_chance": 0.25, "paralyze_turns": 1},
    "normal": {..., "paralyze_turns": 2},  # 2 turns at normal — too strong
    ...
}

# NEW: Goblin Shortbow (weapon)
GOBLIN_SHORTBOW_STATS = {
    "poor":   {"atk_min": 1, "atk_max": 2, "paralyze_chance": 0.15, "paralyze_turns": 1},
    "normal": {"atk_min": 2, "atk_max": 3, "paralyze_chance": 0.25, "paralyze_turns": 1},
    ...  # multi-turn only at rare+
}

# Proc moved from accessory to weapon slot:
weapon = warrior.equipment.get("weapon")
if weapon and actual > 0 and enemy.is_alive():
    paralyze_chance = getattr(weapon, "paralyze_chance", 0.0)
```

**Why:** A paralyze ointment on bare fists makes no narrative sense. A bow the player picks up from the Goblin Archer does. As a weapon it adds ATK directly, the wide min/max spread represents arrow distance variance, and the paralyze proc is built into the weapon rather than an accessory. Multi-turn paralyze locked behind rare+ because 2 turns at normal rarity was too powerful for a tier 2 drop.

---

## 10. Chimera overhaul

**Where:** `CHIMERA_TIER3_POOL`, all borrowed move functions, `chimera_special_dispatcher()`, new helpers `chimera_boost()` and `chimera_double()`

**What changed:**

**Pool expanded:**
```python
CHIMERA_TIER3_POOL = [
    blinding_charge,
    hydra_hatchling_acid_spit,
    savage_slash,       # NEW
    psychic_shred,      # NEW
    psychic_drown,      # NEW
]
```

**New helpers:**
```python
def chimera_boost(enemy):
    # Returns 1 if chimera_extra_turns flag set, else 0
    # Used to add +1 turn duration to tier 3 moves

def chimera_double(enemy, value):
    # Doubles value if chimera_extra_turns flag set
    # Applied to physical roll in every borrowed move
```

**Dispatcher rewritten:**
```python
def chimera_special_dispatcher(enemy, warrior):
    tier_map = {tier1: 1, tier2: 2, tier3: 3, elemental: 1}
    ap_cost = tier  # tier1=1AP, tier2=2AP, tier3=3AP

    enemy.ap -= (ap_cost - 1)  # pre-pay; move deducts its own 1 AP
    enemy.chimera_extra_turns = (tier == 3)  # flag for tier 3 enhancements
```

**Tier 3 move enhancements:**
```python
# savage_slash: doubled bleed dmg, 1 stack only, +1 turn
dmg_min *= 2 if is_chimera else 1
turns = (3 if is_hardened else 2) + (1 if is_chimera else 0)
max_stacks = 1 if is_chimera else 2

# psychic_shred: doubled % reduction, no stacking, +1 turn
debuff_pct = min(0.90, debuff_pct * 2) if is_chimera else debuff_pct
if warrior.psychic_debuff_turns > 0 and not is_chimera:
    # stack (standard only)

# psychic_drown: doubled AP inflation (+2), max 1 stack, +1 turn
inflation = 2  # chimera always +2 instead of +1 per stack
```

**Display names fixed** — all borrowed moves now use `enemy.display_name` instead of hardcoded monster names so they print "Young Chimera" when the Chimera uses them.

**Why:** The Chimera is a lab experiment — it can mimic moves but not with the same precision as the original creature. It hits harder (doubled physical roll) and debuffs last longer (+1 turn), but it can't stack debuffs like the specialists can. The tier-based AP cost creates meaningful resource decisions — a tier 3 move at 3 AP drains the Chimera's 3 AP in one shot, so it has to choose when to use its most powerful moves.

---

## Summary Table

| Change | Lines affected | Category |
|---|---|---|
| Remove `import math` from bleed block | ~7487 | Bug fix |
| Psychic base re-sync after scaling | ~6882, ~6930 | Bug fix |
| `turn_spent = True` on lost turns | ~8137, ~8179, ~8187, ~8194 | Bug fix |
| Drown punishment → ATK gap boost | ~3768, ~8379 | Redesign |
| SKILL_DEFS + `get_skill_desc()` | ~5971–6003 | New feature |
| Defence Break full system | ~4546–4692 | New feature |
| River Spirit / Death Defier split | ~3412, ~4049, ~5603 etc. | Polish |
| Boss drop fixed stats | ~5167–5260 | Design change |
| Goblin Shortbow replaces Paralyzing Arrow | ~5066–5148 | Design change |
| Chimera overhaul | ~6665–7038 | Enhancement |
