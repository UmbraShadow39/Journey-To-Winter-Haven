# Journey to Winter Haven — Technical Reference
## v0.5.05 | April 2026

---

## Project Structure

Single-file Python RPG (`Journey_To_Winter_Haven_v_05_05.py`) with two companion modules:
- `combat_log.py` — combat logging system
- `titles.py` — title/achievement definitions

**~10,000+ lines** | Python 3.13 | Terminal-based | Replit-compatible

---

## Class Hierarchy

```
Creator (base)
├── Monster(Creator)
│   ├── Green_Slime, Young_Goblin, Goblin_Archer, Goblin_Warrior
│   ├── Brittle_Skeleton, Imp, Wolf_Pup, Dire_Wolf_Pup
│   ├── Red_Slime, Noob_Ghost, Wolf_Pup_Rider, Javelina
│   ├── Hydra_Hatchling, Flayed_One, Drowned_One
│   ├── Fallen_Warrior (Tier 4 boss)
│   └── Young_Chimera (Tier 5 secret boss)
└── Hero(Creator)
    └── Warrior(Hero)  ← player class

Equipment  (standalone — not in Creator hierarchy)
```

---

## Core Systems

### Combat Loop — `battle_inner(warrior, enemy)`
The main combat engine. Alternates `warrior_turn` boolean each cycle.

**Player turn flow:**
1. DOT ticks (`collect_dot_ticks`)
2. Check berserk trigger
3. Adrenaline update
4. Show UI / action menu
5. Resolve turn stop (blind/paralyze)
6. Player action (attack / skill / accessory / potion / run)
7. Check enemy death → loot → XP → rest

**Enemy turn flow:**
1. Clear warp cooldown
2. Tick Defence Break
3. Check paralyzed/blinded (may skip turn)
4. Calculate Drown gap boost
5. Fire special or basic attack
6. Restore Drown boost
7. Update Defence Warp phases

**Turn counter:** `turn_count` increments only on player turns (`warrior_turn=True` + `turn_spent=True`).

---

### Damage Pipeline

**Player attacks enemy:**
```
warrior_attack_roll() → base roll
+ get_damage_bonuses() → hit bonus, War Cry, adrenaline, berserk
→ player_basic_attack() → apply_defence() on enemy
→ accessory/weapon procs fire after hit lands
```

**Enemy attacks player:**
```
random.randint(min_atk, max_atk) → raw roll
→ warrior.apply_defence(roll, attacker=enemy)
→ warrior.hp -= actual
→ monster_math_breakdown() prints the line
```

**Universal enemy damage handler:**
`monster_deal_damage(attacker, defender, raw_roll, extra_parts, tag)`
Handles defence, HP subtraction, math output in one call. All modern specials use this.

---

### Status Effects

| Effect | Applied by | Tracked on | Ticks in |
|---|---|---|---|
| Poison | Slime spit, Poison Sac | `hero.poison_active/amount/turns` | `collect_dot_ticks` |
| Burn | Fire spit, Fire Sac | `hero.burns[]` list | `collect_dot_ticks` |
| Acid | Acid spit, Acid Sac | `hero.acid_stacks[]` list | `collect_dot_ticks` |
| Bleed (Javelina) | Javelina Tusk | `hero.bleed_turns` | `collect_dot_ticks` |
| Bleed (Savage) | Savage Slash, War Blade | `hero.warrior_bleed_dots[]` | `collect_dot_ticks` |
| Blind (player) | Goblin Dagger | `hero.blind_turns` | Battle loop |
| Blind (enemy) | Player accessory | `enemy.blind_turns` | Battle loop |
| Paralyze (player) | Arrow/Chimera | `hero.turn_stop` | `resolve_player_turn_stop` |
| Paralyze (enemy) | Shortbow proc | `enemy.skip_turns` | Battle loop |
| Psychic Shred | Flayed One | `warrior.psychic_atk/def_debuff` | `collect_dot_ticks` |
| Psychic Drown | Drowned One | `warrior.drown_stacks/turns` | `collect_dot_ticks` |
| Defence Warp | Fallen Warrior | `warrior.defence_warp_phase` | `update_defence_warp_after_enemy_turn` |
| Defence Break | Player skill | `enemy.defence_break_active/turns` | `_tick_defence_break` |

---

### Skill System

**SKILL_DEFS** — master dict defining all player skills:
```python
{
  "key": {
    "name": str,
    "min_level": int,       # level required to unlock
    "max_rank": int,        # cap (all currently 5)
    "upgrade_costs": list,  # SP cost per rank [r0→1, r1→2, ...]
    "tier2_name": str,      # teased at rank 4, shown at rank 5
    "rank_descs": {1..5: str}  # sliding window, 2 ranks visible at a time
  }
}
```

**Skills:**
| Key | Name | Unlock | Max Rank | Tier 2 |
|---|---|---|---|---|
| `power_strike` | Power Strike | Level 1 | 5 | Double Strike |
| `heal` | First Aid | Level 1 | 5 | Triage |
| `war_cry` | War Cry | Level 1 | 5 | War Shout |
| `defence_break` | Defence Break | Level 3 | 5 | Defence Shatter |

**Description window:** `get_skill_desc(key, hero)` — shows ranks `current+1` and `current+2`. At rank 4 shows tier 2 locked hint. At rank 5 shows tier 2 name only.

---

### Equipment System

**Slots:** weapon, armor, accessory, trinket

**Equipment fields (key ones):**
```python
atk_min, atk_max       # weapon ATK bonus
defence                # armor DEF bonus
max_hp                 # HP bonus (can be negative — Light Corrupter)
element/element_damage/element_turns/element_max_dots  # sac DoT procs
paralyze_chance/turns  # Goblin Shortbow weapon proc
blind_chance           # Goblin Dagger accessory
atk_debuff/def_debuff  # Charged Jagged Rock accessory
stone_max_charges/stone_charges/max_ap_bonus  # Waterlogged Stone trinket
```

**Boss drops (fixed, no rarity):**
| Item | Source | Stats |
|---|---|---|
| Lightrender | Fallen Warrior (1H choice) | +4 ATK, +2 DEF |
| Destiny Definer | Fallen Warrior (2H choice) | +5 ATK, +1 DEF |
| Chimera Scale | Young Chimera | +5 DEF |
| Light Corrupter | Patronus (evil path) | +6 DEF, -2 max HP |

---

### Monster System

**Tiers:**
- Tier 1 (weight 1): Green Slime, Young Goblin, Imp, Brittle Skeleton, Wolf Pup
- Tier 2 (weight 2): Red Slime, Noob Ghost, Javelina, Goblin Archer, Dire Wolf Pup
- Tier 3 (weight 3): Wolf Pup Rider, Hydra Hatchling, Flayed One, Drowned One, Goblin Warrior
- Tier 4: Fallen Warrior (boss pool)
- Tier 5: Young Chimera (hidden)

**Spawning:** `select_arena_enemy(round_num)` → `get_round_tier()` → `random_encounter_by_tier()` or `random_tier4_boss()`

**Level scaling:** `apply_level_scaling(monster, tier)` — HP +5/level, ATK/DEF +1/level, XP +50%/level. Re-syncs `psychic_base_*` fields after scaling.

**Hardened variants:** Any monster with `level >= 2` — affects special move damage/duration.

---

### Young Chimera — Special Dispatcher

`chimera_special_dispatcher(enemy, warrior)` picks one of four move slots each turn:

| Slot | Pool | AP Cost | Enhancement |
|---|---|---|---|
| Tier 1 | 5 moves | 1 AP | `chimera_double()` on physical roll |
| Tier 2 | 5 moves | 2 AP | `chimera_double()` on physical roll |
| Tier 3 | 5 moves | 3 AP | `chimera_double()` + `chimera_extra_turns` flag |
| Elemental | Unique | 1 AP | Unchanged |

**Tier 3 enhancements via `chimera_extra_turns` flag:**
- `savage_slash` — doubled bleed dmg, 1 stack only, +1 turn duration
- `psychic_shred` — doubled % reduction, no stacking, +1 turn duration
- `psychic_drown` — doubled AP inflation, max 1 stack, +1 turn duration

---

### Defence Break — Player Skill

```python
defence_break(warrior, enemy, chosen_rank)
```

| Rank | DEF% reduction | Duration | AP Cost |
|---|---|---|---|
| 1 | 10% (min 1) | 2 turns | 2 AP |
| 2 | 20% (min 1) | 2 turns | 2 AP |
| 3 | 30% (min 1) | 3 turns | 3 AP |
| 4 | 40% (min 1) | 3 turns | 3 AP |
| 5 | 50% (min 1) | 3 turns | 4 AP |

- Stores `enemy.defence_break_base_def` — refreshes don't compound
- `_tick_defence_break(enemy)` — called at enemy turn start, restores DEF on expiry
- `_award_defence_break(warrior)` — fires on Fallen Warrior kill (both kill paths)
- 0 DEF enemies: if base DEF was 0, deals 1 true damage; if break eroded to 0, shattered message + 1 true damage

---

### Psychic Drown — AP Tension System

`psychic_drown` inflates all skill AP costs by stack count. ATK boost fires on enemy turn if player can't afford cheapest move:

```python
# In battle loop (enemy turn):
cheapest_cost = 1 + drown_stacks
if warrior.ap < cheapest_cost:
    drown_gap_boost = 2  # flat +2 ATK, not proportional
    enemy.min_atk += 2
    enemy.max_atk += 2
# ... attack fires ...
    enemy.min_atk -= 2   # restored after attack
    enemy.max_atk -= 2
```

Chimera version: fixed +2 inflation, max 1 stack, +1 turn duration above hardened.

---

### Death Defier / River Spirit Split

Two distinct versions tracked by `death_defier_river` flag:

| Version | Name displayed | AP cost | Revival HP | How earned |
|---|---|---|---|---|
| `death_defier_river=True` | River Spirit | 0 AP | 1 HP | River path story choice |
| `death_defier_river=False` | Death Defier | 1 AP (temp) | 1 HP (rank system TBD) | Skill tree (Level 5, rank-based %) |

Note: Death Defier full rank system (10-50% HP revival by rank, 3-5 AP cost) not yet implemented — planned for v5.06.

---

## Key Constants & Tables

| Name | Purpose |
|---|---|
| `MONSTER_TYPES` | Weighted pool for random encounters |
| `TIER4_BOSSES` | Fallen Warrior pool |
| `SKILL_DEFS` | All skill definitions |
| `DEFENCE_BREAK_STATS` | {rank: (pct, turns)} |
| `GOBLIN_SHORTBOW_STATS` | Weapon drop from Goblin Archer |
| `GOBLIN_WAR_BLADE_STATS` | Weapon drop from Goblin Warrior |
| `CHIMERA_TIER1/2/3_POOL` | Move pools for Young Chimera |
| `WEAPON_CORE_ONEHANDED/TWOHANDED_STATS` | Fixed boss drop stats |
| `CHIMERA_SCALE_STATS` | Fixed boss drop stats |
| `TAINTED_CHAMPIONS_SHIELD_STATS` | Fixed boss drop stats (Patronus) |

---

## Debug Menu Quick Reference

| Option | Function |
|---|---|
| 1 | Force Berserk |
| 2 | Clear Berserk |
| 3 | Apply Blindness |
| 4–8 | Apply/clear status effects |
| 9 | Heal to Full |
| 10 | Grant River Spirit |
| 11 | Trigger Death Defier test |
| 12 | Level Up |
| 13 | Grant Defence Break (+1 rank) |
| 14 | Skill Editor |
| 15 | Loot Manager |
| 16 | View Combat Log |
| 17 | Restore AP to Full |
| 18 | Debug Potion Menu |
| 19 | Exit Current Run |
| 20 | Exit Debug Menu |

---

## File Conventions

- **All stat modifications use `min_atk` / `max_atk`** — never `.attack` or `.max_attack`
- **HP changes go through `apply_defence()` or direct subtraction** — never modify HP without going through the pipeline for player-facing damage
- **`show_health(hero)`** — always call after damage to show updated HP bar
- **`wrap(text)`** — use for all narrative/flavour text to respect terminal width
- **`log(text)`** — use for combat log entries, not player-visible output
- **`getattr(obj, "field", default)`** — use for any attribute that might not exist (status effects, flags)

