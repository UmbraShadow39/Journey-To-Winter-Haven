# Journey to Winter Haven — Changelog

A high-level summary of major changes across the project's full development history.
For full version-by-version detail see [DEVLOG.md](DEVLOG.md).

**Platform roadmap:** itch.io terminal demo (May 2026) → Pygame port (Dec 2026) → Godot/Steam Early Access (May 2027)

---

## v5.12 — Chimera Carapace Passive, Bug Fixes & Word Wrap Pass
*April 2026*

**Young Chimera — Chimera Carapace passive added.** The Chimera now has a permanent 20% reduction on all incoming player physical ATK rolls, applied before defence is calculated. If the Chimera's tier 3 draw is `psychic_shred` (Flayed One's move), the reduction increases to 35%. The higher tier is announced in the spawn flavour text. `chimera_atk_reduction` stored as a float on the enemy and read in `monster_deal_damage` via `getattr` default 0.0 — zero overhead on all non-Chimera enemies.

**Bug fix — Charismatic Speaker ATK drift.** `reset_between_rounds` was stripping a hardcoded flat 2 from player ATK after each fight, but the title applies `ceil(max_atk * 0.15)` which is 3 at ATK ≥ 14. Over a full run this caused permanent silent ATK inflation. Fixed by storing the exact bonus as `warrior.charismatic_speaker_bonus` at apply time and reading it back at strip time.

**Bug fix — Patronus Defence Break restore hardened.** `_restore_patronus_def()` is now called inside a `finally` block wrapping `battle(warrior, patronus)` — guarantees the DEF restore fires even if an unhandled exception escapes the fight.

**Word wrap pass — arena quarters NPC dialogue.** Five bare `print()` calls in the arena quarters interlude menu were missing `wrap()`: goblin bookie repeat line, orc guard both lines, crafter both lines. All wrapped. These were rendering without line breaks on narrow viewports (tablet/mobile).

---

## v5.11 — Chimera Move Overhaul & Title System Expansion
*April 2026*

**Chimera borrowed move system fully rebuilt.** Every move in the three tier pools now scales correctly when the Young Chimera uses it. The core fix was replacing the broken `chimera_double`/`chimera_extra_turns` pattern (which never fired for tier 1 or 2 moves) with consistent `hasattr(enemy, "chimera_tier1")` identity checks and dedicated helpers.

`chimera_triple()` added as a new helper — triples flat damage values on tier 1 moves. Used by Brittle Skeleton Thrust (base damage tripled, defence now applies when Chimera uses it) and Imp Sneak Attack (max ATK + 3 flat through defence, replaces the broken 54-damage chimera_triple bug).

**Per-move changes:**
- *Poison Spit* — physical hit uses Chimera ATK (14–18); poison DOT is 3–6/turn for 3 turns
- *Fire Spit* — fire DOT doubled to 4–6; burn stack extended to 3 turns
- *Goblin Cheap Shot* — 2 full missed turns; max ATK through defence
- *Wolf Pup Bite* — base roll replaced by Chimera ATK; bite bonus tripled via `chimera_triple`
- *Impact Bite* — Chimera ATK through defence + 4–8 true damage from doubled impact roll
- *Devouring Bite* — Chimera ATK through defence; heals half the pre-defence roll regardless of how much damage defence reduced
- *Ghost Life Leech* — 14–18 through defence + half the roll as true drain; Chimera can overheal to 1.5x
- *Paralyzing Shot* — uses Chimera ATK roll (was never scaling); 2 lost turns via dispatcher unchanged
- *Blinding Charge* — Chimera max ATK through defence; 2 full missed turns; dead `chimera_double` call removed from hobgoblin branch
- *Savage Slash* — is_chimera check fixed; bonus damage is half of 14–18 roll (7–9 true damage); bleed 6–10 for 3 turns now correctly fires
- *Hydra Acid Spit* — Chimera ATK through defence; acid stacks carry a `multiplier: 2` key; tick handler reads it for 6–10 per tick; defence erosion is -2 per hit (was -1)
- *Psychic Shred* — is_chimera check fixed; debuff % now correctly doubles; duration correctly extends +1
- *Psychic Drown* — is_chimera check fixed; AP inflation duration correctly extends +1

**Combo follow-through tiered.** `chimera_combo_bonus` now accepts a `tier` parameter. Tier 1 follow-through is 2–5, tier 2 is 5–10, tier 3 is 8–14. Dispatcher resolves tier from which pool the chosen move belongs to and passes it in. Pure damage tier 1 moves (Thrust, Wolf Bite) do not trigger combo follow-up — their 3x multiplier is punishment enough.

**Blind — First Aid prompt added.** While blinded, players with First Aid rank 2+ now see the same choice prompt as paralysis — use First Aid to cure it or struggle and lose the turn. Rank 1 or no First Aid still loses the turn with no option.

**Psychic debuffs removed from First Aid rank 5 clear.** `clear_all_status_effects` no longer calls `_clear_psychic_debuff` or `_clear_psychic_drown`. Psychic status effects are now uncleansable mid-combat by any current skill — reserved for Triage (rank 6+, full game). They still clear correctly in `reset_between_rounds` between fights. Rank 5 description updated to reflect this.

**Skill costs rebalanced.** Defence Break: 1/2/3/4/4 SP per rank. Death Defier: 2/3/3/4/5 SP per rank (was 2/2/3/4/5).

**Five skill mastery titles added** (full game rewards — require rank 5, effectively out of reach in the demo):
- *Brawl Master* (Power Strike 5) — +2 min/max ATK permanently
- *Combat Medic* (First Aid 5) — passive 10% max HP regen at end of each player combat turn
- *Charismatic Speaker* (War Cry 5) — +2 ATK for the entire fight, applied at fight start, stripped in `reset_between_rounds`
- *Armor Piercer* (Defence Break 5) — basic attacks reduce enemy DEF by 1 each hit
- *Death Challenger* (Death Defier 5) — Death Defier costs 1 less AP (floored at 1)

**Two skill breadth titles added** (realistic demo rewards — require rank 1 in qualifying skills):
- *Chinker* — unlocks when 4th skill is Defence Break: +1 ATK. If 5th skill unlocks it instead, awards alongside Death Delver.
- *Death Delver* — unlocks when 4th skill is Death Defier: +5 Max HP. If 5th skill unlocks it instead, awards alongside Chinker.
Both titles always awarded eventually regardless of build order. `check_breadth_titles(hero, skill_key)` replaces the old separate `check_chinker` / `check_death_delver` functions.

`check_skill_mastery()` added to `titles.py` — fires after every skill upgrade, checks if the upgraded skill just hit rank 5, and awards the matching mastery title.

---

## v5.09 — Polish & Systems Pass
*April 2026 | ~12,365 lines*

`offer_loot()` helper centralised all three drop points (main kill, DoT kill, Fallen Warrior) so players always see a full stat card and an immediate equip prompt with their current slot shown for comparison. Charged Jagged Rock moved from accessory to trinket slot so it can coexist with Waterlogged Stone, and rebuilt with a pool-based charge system, per-rarity charge cap, and a live HUD charge bar using rarity colours. Death Defier dialogue is now path-aware — River Spirit prayer on the good path, Beast Gods chant on evil, neutral otherwise. `show_run_score()` added to the demo end screen with a grand total damage breakdown split by basic, special, and DoT. Debug title grant menu added. Level-up stat cap scales with points available so a double level-up correctly allows two points per category. Fixed `dd_name` scope bug (UnboundLocalError on Death Defier available state), Chimera tier 5 special never firing, and Fallen Warrior XP not being granted via `animate_xp_results`.

---

## v5.08 — Moral Hook & Final Bosses
*April 2026 | ~12,000 lines*

`fallen_warrior_moral_choice()` implemented — the Fallen Warrior death scene with Beast God intervention and a crush/return essence split that locks in the player's path. Good path routes to `chimera_fight()` rebuilt as a true final boss (80 HP / 8 DEF / ATK 14–18, charge-based AI, Primordial Surge as an active move). Evil path routes to `patronus_fight()` now properly gated behind the choice. Tainted Blade corrupts Weapon Core in place on the evil path (Duskbringer or Destiny Destroyer). Both boss fights have full cinematic entry scenes with a heal, +2 temp AP, and status clear. Divine intervention threshold raised to 4 cycles for both fights. Detailed round-by-round combat log breakdown added including attack names, damage dealt/blocked, and per-effect DoT sources.

---

## v5.07 — Patronus Build
*April 2026 | ~11,000 lines*

Patronus fully implemented as the evil path final boss — 85 HP (+6 shield = 91 effective), DEF 4 (+6 shield effective), ATK 5–9, AP 7. Moveset includes Double Strike R5, War Cry R5, Power Charge combo, First Aid (random rank), and Defence Break (random rank). Desperation scaling at 50/60/75/90% special chance by HP threshold. Death Defier revives at 30% HP with shield stripped. Cycle-based Beast Gods intervention after 3 full cycles. Chimera AI overhauled with strict special/rest alternation, 25% basic feint on special turns, and a combat_cycles tracker reused by Patronus.

---

## v5.06 — Chimera Overhaul & Defence Break
*April 2026 | ~10,000 lines*

Chimera stats updated (HP 75, ATK 7–12, DEF 6, AP 7). Weighted move selection with turn-count escalation, last-used penalty, and AP filtering. Primordial Surge added as a signature breath attack — 3 charges, no recharge, rest-turn only, with permanent stat degradation per charge. Defence Break skill fully built with SKILL_DEFS entry, combat function, tick, and `_award_defence_break()` wired into both Fallen Warrior kill paths. River Spirit renamed from Death Defier for the river path. Goblin Shortbow replaces Paralyzing Arrow as a weapon drop. Boss drops given fixed stats with no rarity variance.

---

## v5.05 — Bug Fixes & Skill System Upgrade
*April 2026*

Critical `import math` crash in `player_basic_attack` fixed (local import shadowed module-level import). Charged Jagged Rock stale stats on hardened enemies fixed. All four skills capped at rank 5. SKILL_DEFS upgraded with `rank_descs` dict and `tier2_name` field per skill. `get_skill_desc()` helper added with sliding two-rank lookahead window and tier 2 locked hint at rank 5.

---

## v5.04 — Goblin Warrior (Tier 3)
*April 2026 | ~9,400 lines*

Goblin Warrior added (30 HP, 5–9 ATK, DEF 4, AP 3) — completes the goblin ladder. Savage Slash special move: 33% independent proc after basic attack, bonus damage equal to half the basic roll bypassing defence, plus 2 bleed stacks. `warrior_bleed_dots` stack system added separately from Javelina tusk bleed. Goblin War Blade weapon drop added with per-rarity bleed scaling.

---

## v5.03 — Drowned One, Waterlogged Stone & Inventory Overhaul
*April 2026 | ~9,100 lines*

Drowned One added (Tier 3 — 27 HP, 5–8 ATK, DEF 3, AP 3). Psychic Drown special inflates all skill AP costs by +1 per stack (max 3 stacks); punishment fires flat true damage if player can't afford any skill. Waterlogged Stone trinket added — absorbs 1 charge per enemy special move from any enemy; player spends a turn to release charges and restore AP; persists between rounds. Trinket equipment slot added to Hero. `Equipment.full_detail()` loot card method added. `inventory_menu` inspect commands added (`i#`, `iweapon`, etc.). `_stone_usable()` helper wires the stone into both rest menus dynamically.

---

## v5.02 — Flayed One & Psychic Shred
*April 2026 | ~8,900 lines*

Flayed One added (Tier 3 — 23 HP, 4–6 ATK, DEF 2, AP 2). Psychic Shred special: 25% ATK+DEF reduction (30% hardened), 2-turn duration, stacks to 50%/60% on second hit, hard 90% ceiling, max 3 uses per fight. Charged Jagged Rock accessory added (Flayed One drop) with ATK+DEF debuff proc. `show_combat_stats()` debuff section fully rewritten — all active debuffs now shown with tactical detail including pending tags and before/after values.

---

## v5.01 — Title System & Fallen Warrior Desperation
*April 2026 | ~8,700 lines*

Title system extracted to `titles.py` module. `active_title` attribute added to Hero; titles carry display names via `TITLE_DISPLAY`. Jack of All Trades title added — unlocks when Power Strike, First Aid, and War Cry all reach rank 1, grants +1 to HP/ATK/DEF/AP. `_switch_title_menu()` added to rest menu when 2+ titles owned. Fallen Warrior desperation system added — Defence Warp trigger chance now scales with HP thresholds (10/25/50/75%) via `fallen_warp_should_trigger()`, replacing the flat 33% roll, with guaranteed 1-turn cooldown after each trigger.

---

## v4.27 — Loot System Complete, Balance Tuning
*April 2026 | ~8,700 lines*

The loot system is now fully functional across all 14 monsters. The Acid Sac was redesigned with a tiered DEF erosion mechanic that mirrors how the Hydra Hatchling's own acid spit works. Hydra tick damage bumped up. Fallen Warrior HP raised to 60 with 5 AP. Debug menu expanded with a unified Loot Manager, full Potion Menu, and Restore AP option.

---

## v4.22–v4.23 — Hidden Boss, Paralyze Overhaul, Major Bug Pass
*March 2026 | ~8,400 lines*

Young Chimera added as a hidden optional boss with a random elemental attack and a divine intervention mechanic for close fights. Paralyze rebuilt as a true multi-turn lockdown with chain guards and a mid-combat First Aid cure option. Weapon Core split into two player-chosen forms on drop (Defensive or Offensive) with narrative weight. Major bug pass fixed burn cream, level-up jackpot, double armour stacking, and several silent failures.

---

## v4.21 — Class Refactor, Combat Log, Module Split
*March 2026 | ~7,400 lines*

First time the project used multiple files. The Hero/Warrior/Creator class hierarchy was cleaned up so Warrior properly owns its own systems, laying groundwork for future Mage and Thief classes. A full combat log system was wired into every stage of battle — turn headers, player choices, enemy actions, DoT ticks, and death events all recorded and viewable in-game.

---

## v4.11–v4.20 — Loot System Built from Scratch
*2025–2026 | ~6,700–7,500 lines*

The entire loot and equipment system was built across this stretch. `Equipment` class introduced with weapons, armor, and accessories. `make_loot()` and `roll_rarity()` added. Sac accessories (Poison Sac, Fire Sac, Acid Sac) implemented first, then all Tier 1 weapon and armor drops. `equip_item()` / `unequip_item()` added for proper routing. Accessory attacks split from weapon attacks so elemental procs and weapon procs are handled cleanly. Round number wired into the loot system so drop quality scales with progression. Multi-dot rare+ sacs and 6-tier rarity ladder finalised.

---

## v3.18 — Last Stable GitHub Release
*Early 2026 | ~5,600 lines*

Last pushed version before the v4 development cycle. Complete game loop across 5 rounds with a full Tier 1 and Tier 2 monster lineup, working skill tree, berserk/rage system, rest phase, Death Defier, and basic potion system. Equipment framework in early stages.

---

## v3.12–v3.15 — Skills, War Cry, Heal & Debug Tools
*2025–2026 | ~4,800–5,400 lines*

Power Strike, War Cry, and Heal (later renamed First Aid) added as fully rankable skills with AP costs. Death Defier skill introduced. Skill editor added to debug menu. Blind damage multiplier and goblin bookie payout added. `battle()` / `battle_inner()` separation formalised.

---

## v3.2–v3.4 — Full Monster Roster Complete
*2025 | ~4,150 lines*

Full Tier 1 and Tier 2 monster lineup finalised: Green Slime, Young Goblin, Goblin Archer, Brittle Skeleton, Imp, Wolf Pup, Dire Wolf Pup, Red Slime, Fallen Warrior, Noob Ghost, Wolf Pup Rider, Javelina. All monsters have unique special moves. Berserk meter, Death Defier, and trainer stat point scene in place. `GameOverException` added.

---

## v0.144 — Tier 2 Monster Line Complete & Special Moves
*2025 | ~3,650 lines*

Goblin Archer, Wolf Pup Rider, Javelina, and Brittle Skeleton added. Turn stop / paralyze system introduced with `apply_turn_stop()` and `resolve_player_turn_stop()`. Full and partial block flavour text functions added. Individual monster special moves implemented across the full roster.

---

## v0.141–v0.143 — Warrior Class & Tier 2 Roster Begins
*2024–2025 | ~3,200–3,500 lines*

`Warrior` subclass split from `Hero` — first appearance of the dedicated player class. Ghost/Noob Ghost, Wolf Pup Rider added. Red Slime introduced. Tier 2 monster work begins. Build numbers at this stage tracked as sequential file versions (141, 142, 143).

---

## v0.136 — Berserk Meter, Poison & Debug Menu
*2024 | ~2,930 lines*

Berserk meter UI added. Poison status effect introduced. Debug menu expanded. Level-up menu, potion menu formalised. Monster names begin differentiating (Green_Slime, Young_Goblin etc. replacing generic Slime/Goblin).

---

## v0.12 — Rage System, Berserk & Rest Mechanic
*2024 | ~1,920 lines*

Rage system implemented — HP-based tiers at 75%, 50%, 25%, 10% with escalating damage bonuses. Berserk mode introduced as the rage peak state. Rest mechanic added between rounds. Universal developer shortcuts added (q to restart, c to jump to arena). `RestartException` and `QuickCombatException` introduced.

---

## v0.08–v0.09 — Arena Combat & Class Foundation
*Late 2024 | ~660–725 lines*

First structured arena combat loop. Creator → Monster / Hero class hierarchy established. Basic monster roster: Slime, Goblin, Skeleton, Wolf, Fallen Hero. Attack rolls, XP, gold, defence (informational), and essence tracking in place. Foundation that everything since has been built on.

---

## The Origin — Pre-Architecture Prototype
*August–October 2025*

Three dated files mark the true starting point of the project before the proper class hierarchy took shape.

**August 6** (`battle_simulater_pc_update_August62025.py`, 590 lines) — The earliest surviving build. A `Creator` base class exists but `Skeleton` is just `pass`. Combat is a series of standalone functions. Global variables track gold and HP. Comments show active learning in progress — notes about how `super()` works, questions about gold tracking. This is where it all started.

**September 17** (`arena_battler_sept_17_2025.py`, 763 lines) — `clear_screen()`, `continue_text()`, and `check()` introduced — utility functions that still exist in the game today. A `main()` function wraps the game loop. The tournament intro story appears for the first time. Gold and essence tracking via globals.

**October 2** (`arena_battler_October_2_2025.py`, 763 lines) — Near-identical to the September build, a stable checkpoint before the architecture push that followed.
