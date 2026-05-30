# Journey to Winter Haven — Developer Log

Full version-by-version development history. For a quick overview see [CHANGELOG.md](CHANGELOG.md).

---

## v5.12 — v05_14
*April 2026 | ~13,038 lines*

- Young Chimera: `chimera_atk_reduction` float added in `__init__` — set to `0.20` always, bumped to `0.35` if `chimera_tier3 is psychic_shred`
- `monster_deal_damage`: reads `getattr(defender, "chimera_atk_reduction", 0.0)` before defence calc; reduces `raw_roll` to `max(1, int(raw_roll * (1.0 - reduction)))` when non-zero; all non-Chimera enemies unaffected (default 0.0)
- Chimera spawn flavour appends `"🩸 Its hide pulses with corrupted energy — your strikes feel dulled..."` when Flayed draw active
- BUG FIX: Charismatic Speaker ATK drift — apply now stores `warrior.charismatic_speaker_bonus = bonus`; `reset_between_rounds` reads it back instead of hardcoded `- 2`; silently inflated ATK by +1 per fight at max_atk ≥ 14
- BUG FIX: Patronus DEF restore — `battle(warrior, patronus)` wrapped in `try/finally`; `_restore_patronus_def()` now guaranteed to fire even on unhandled exception
- WORD WRAP: Five bare `print()` calls in `arena_quarters_interlude` now use `wrap()` — goblin bookie repeat, orc guard first/second lines, crafter first/second lines; were breaking layout on narrow tablet viewports

---

## v4.27
*April 2026 | ~8,700 lines*

- Acid Sac redesigned — poor: 3 dmg/1 turn/no DEF erosion; normal: 3 dmg/2 turns/-1 DEF immediately; uncommon: 4 dmg/2 turns/-2 DEF immediately; DEF restores after 2 turns; reapplying resets clock
- `element_erosion` added as a proper Equipment parameter; poor carries 0 so no behaviour change at poor tier
- Acid application in combat uses `element_erosion` for immediate DEF reduction, consistent with Hydra acid spit
- Hydra Hatchling acid tick bumped from 2–4 to flat 3–5 per tick regardless of DEF erosion state
- All three combat log yes/no prompts now loop with "Incorrect input, please enter yes or no."
- Fallen Warrior HP raised to 60, AP raised to 5

---

## v4.26
*April 2026*

- Debug menu Loot Manager — unified Give Loot and Equip Loot into one sub-menu with three modes: Give to Inventory, Equip Directly, Unequip Slot
- Loot Manager shows current equipped gear and live stats at top of menu on every pass
- Debug Potion Menu — all 12 potion types, add any quantity, quick fill adds ×3 of everything
- Restore AP debug option — instantly fills AP to max
- Level-up debug grants all levels silently in one pass; stat snapshot shown before spend prompt
- Fallen Warrior defence lowered from 5 → 4

---

## v4.25
*April 2026*

- Acid Sac turn scaling fixed to match Poison and Fire Sac
- Quarters interlude spend points option hidden if no unspent points available
- Duplicate combat log option removed from quarters interlude menu

---

## v4.24
*March 2026*

- Javelina loot table key corrected from "javelina" to "Javelina" — Tusk was silently not dropping
- Full audit of all 14 monster names against loot table keys confirmed all other entries correct

---

## v4.23
*March 2026*

- Weapon Core split into Defensive and Offensive forms; player chooses permanently on drop
- burn_cream now clears hero.burns list — burn DoT was continuing after potion use
- Level-up jackpot loop fixed — hardcoded range(2) changed to range(num_p1_rolls)
- ALLOW_MONSTER_SELECT declared at module level — was potential NameError
- Duplicate simple_trainer_reaction() removed — second definition was shadowing the correct one
- Chimera Scale equip now routes through equip_item() — direct assignment was giving double defence stats
- weight_to_tier() given fallback return 1 — was returning None silently
- Dead xp_reward calls removed after victories — XP already awarded inside battle_inner
- reset_between_rounds() now clears acid, paralyze, and bleed between rounds
- Removed unused `from ast import If` import

---

## v4.22
*March 2026*

- Paralyze rebuilt as true multi-turn lockdown; chain_guard and post_paralyze_guard added
- First Aid R4+ gives player choice during paralyze: cure and act, or struggle
- paralyzing_shot accepts paralyze_turns parameter for future enemy use
- Equipment __init__ fixed for paralyze_chance and paralyze_turns parameters
- Young Chimera hidden boss added — random element on spawn; divine intervention at 5+ turns survived
- chimera_fight() wrapper added; turn survival tracked via enemy.turns_survived
- Wolf Pup Rider essence corrected to its own essence
- Player can view combat log on death
- Nob NPC increases one ranked skill

---

## v4.21 / v4.21.5
*March 2026*

- combat_log.py extracted as first separate module
- Hero stripped to universal base class; Warrior-specific systems moved to Warrior subclass
- Creator.apply_defence() uses getattr(..., False) instead of hasattr for berserk check
- Full combat log wired into battle_inner() — turn headers, choices, actions, DoT, death all logged
- Combat log accessible from all five exit points and debug menu
- Green Slime / Red Slime duplicate DoT message fixed
- Paralyzing Arrow turn skip correctly firing
- Champion ending log prompt added

---

## v4.20.3
*March 2026*

- Skill "Heal" renamed to "First Aid" throughout
- First Aid max rank reduced from 10 to 5; status cures unlocked by rank
- Death Defier debug changed from "Activate" to "Grant Skill"
- Default player name changed from "Adventurer" to "Umbra"
- HUD gap between HP bar and berserk meter fixed

---

## v4.20.2
*March 2026*

- Combat HUD redesigned to two-column layout
- arena_quarters_interlude now has Inventory & Equipment option
- Both rest periods allow equipping between rounds

---

## v4.20.1
*March 2026*

- element_max_dots added to Equipment class
- Sac stat tables updated for rare/epic/legendary tiers
- Multi-dot sacs added — rare+ can apply multiple independent stacks up to cap
- collect_dot_ticks processes poison_dots list for extra poison ticks

---

## v4.19.3 (journey_4_19_3.py)
*2025 | ~7,460 lines*

- equip_item() and unequip_item() added — all equipment routing now goes through proper handlers instead of direct assignment
- Goblin Archer loot entry added (Paralyzing Arrow — accessory with paralyze chance)
- Dire Wolf Pup loot entry added (Dire Wolf Pelt — armor)
- collect_dot_ticks() updated with is_player flag to distinguish player vs enemy ticks
- Multi-dot poison uses separate poison_dots list independent of poison_active
- collect_dot_ticks processes poison_dots for extra independent ticks
- elem tags now show stack count e.g. "Burn stack 2/2!" for rare+ sacs
- Item stat description wrapping fixed — each stat on its own line

---

## v4.16 (Journey_To_Winter_Haven_v_04_16.py)
*2025 | ~7,130 lines*

- player_basic_attack() split into two modes via use_accessory parameter
- use_accessory=False: weapon bonus + procs, no elemental (weapon attack)
- use_accessory=True: basic roll + elemental effect, no weapon bonus or procs (accessory attack)
- Combat menu now routes weapon and accessory attacks through correct mode separately

---

## v4.15 (Journey_To_Winter_Haven_v_04_15.py)
*2025 | ~7,100 lines*

- round_num parameter added to battle(), battle_inner(), make_loot(), and roll_rarity()
- Round 1 loot odds updated — better chance of normal/uncommon quality on first round
- monster_level_for_round() added — stronger monster variants appear in later rounds
- Drop quality now scales dynamically with round progression

---

## v4.14 (Journey_To_Winter_Haven_v_04_14.py)
*2025 | ~7,090 lines*

- Wolf Pup loot entry added (Wolf Pelt — armor with defence and HP bonus)
- Brittle Skeleton loot entry added (Rusted Sword — weapon with defence bonus)
- Imp loot entry added (Imp Trident — weapon with proc chance bonus damage on hit)
- Young Goblin loot entry added (Goblin Dagger — weapon with blind chance on hit)
- proc_chance and blind_chance added as Equipment parameters
- WOLF_PELT_STATS, RUSTED_SWORD_STATS, IMP_TRIDENT_STATS, GOBLIN_DAGGER_STATS tables added

---

## v4.12–v4.13 (Journey_To_Winter_Haven_v_04_12/13.py)
*2025 | ~6,840–6,920 lines*

- Equipment class introduced — weapons, armor, and accessories with rarity scaling
- make_loot() and roll_rarity() added — first working loot drop system
- Green Slime loot entry added (Poison Sac — accessory with poison DoT)
- Red Slime loot entry added (Fire Sac — accessory with fire DoT)
- Hydra Hatchling loot entry added (Acid Sac — accessory with acid DoT and DEF restore)
- element_restore added to Equipment for timed DEF recovery on acid items
- POISON_SAC_STATS, FIRE_SAC_STATS, ACID_SAC_STATS stat tables added
- short_label() and stat_lines() display methods added to Equipment

---

## v4.11 (Journey_To_Winter_Haven_v_04_11.py)
*2025 | ~6,710 lines*

- battle() and battle_inner() fully separated — battle() is the outer wrapper, battle_inner() owns the combat loop
- collect_dot_ticks() extracted as a standalone function
- player_basic_attack() extracted as a standalone function
- Codebase restructured and cleaned up in preparation for the loot system

---



- Rarity ladder extended to 6 tiers: poor → normal → uncommon → rare → epic → legendary
- All item stat tables updated with entries for all 6 rarities
- RARITY_ORDER list added as single source of truth
- Debug Give Loot menu shows all 6 rarities with icons

---

## v0.5.1
*2025*

- show_game_stats rebuilt to stacked layout — fixed display on 65-char phone width
- Removed hardcoded name truncation and side-by-side layout
- Gear lines print one per row with wrap()

---

## v0.5 (journey_4_19.py)
*2025*

- Combat menu rebuilt with dynamic slot numbers based on equipped gear
- Rarity word added to item names
- Player sac DoTs now use sac stats directly, not monster move values
- Poison, Fire, and Acid Sac mechanics fully implemented with reapply/reset logic

---

## v0.4
*2025*

- Hydra Hatchling added with acid spit special move
- Equipment system introduced — weapons, armor, accessories
- Tier 1 monster loot tables completed
- Rarity system introduced with roll_rarity()
- Hard level cap set to 5
- Animated XP bar added
- Potion dictionary expanded — super, mega, full potions; AP potions added
- Monsters can gain levels; drop rates increase for stronger variants
- Player restricted to 1 stat point per stat per level until level 5

---

## v3.15 (journey_to_winter_haven_v_03_15.py)
*2025 | ~5,400 lines*

- War Cry added as a rankable skill with AP cost and turn duration
- Heal (First Aid) added as a rankable skill
- Blind damage multiplier implemented
- Debug skill editor added
- choose_heal_rank_smart() and choose_war_cry_rank_smart() added

---

## v3.12–v3.13 (journey_to_winter_haven_v_03_12/13.py)
*2025 | ~4,800–4,920 lines*

- battle() / battle_inner() separation formalised
- Power Strike fully implemented with rank scaling and AP costs
- Skill tree and spend_points_menu() added
- Death Defier and activate_death_defier() added
- GameOverException introduced
- Arena trainer stat point scene added
- Goblin bookie payout added
- reset_between_rounds() introduced
- War Cry tick system added

---

## v3.2–v3.4 (journey_to_winter_haven_v_03_2/4.py)
*2025 | ~4,150 lines*

- Full Tier 1 and Tier 2 monster roster finalised: Green Slime, Young Goblin, Goblin Archer, Brittle Skeleton, Imp, Wolf Pup, Dire Wolf Pup, Red Slime, Fallen Warrior, Noob Ghost, Wolf Pup Rider, Javelina — all with unique special moves
- Berserk meter in place
- Debug menu covers all current moves

---

## v0.144 (ai_helps__144.py)
*2025 | ~3,650 lines*

- Goblin Archer, Wolf Pup Rider, Javelina, Brittle Skeleton added
- apply_turn_stop() and resolve_player_turn_stop() introduced — paralyze/stun foundation
- paralyzing_shot() added for Goblin Archer
- blinding_charge() added for Wolf Pup Rider
- impact_bite(), wolf_pup_bite(), brittle_skeleton_thrust(), imp_sneak_attack() added
- Full and partial block flavour text functions added
- show_health() helper added

---

## v0.143 (ai_helps__143.py / 143_1 / 143_2)
*2024–2025 | ~3,430–3,490 lines*

- Warrior subclass split from Hero — first dedicated player class
- Ghost/Noob Ghost added
- Wolf Pup Rider added
- Red Slime introduced
- Tier 2 monster work begins

---

## v0.141–v0.142 (ai_helps__141/142.py)
*2024 | ~3,200–3,400 lines*

- Monster roster expanding with differentiated names (Green_Slime, Young_Goblin vs generic types)
- Berserk system refinements
- Potion and level-up menus stabilised
- Poison status effect in place

---

## v0.136 (ai_helps__136.py)
*2024 | ~2,930 lines*

- Berserk meter UI introduced
- Poison status effect added
- Debug menu expanded
- get_name_input() added — player can name their character
- Level-up menu and potion menu formalised
- Monster names differentiated: Green_Slime, Young_Goblin etc.

---

## v0.12 (ai_helps_rage_universal_commands_12.py)
*2024 | ~1,920 lines*

- Rage system implemented — HP-based tiers at 75%, 50%, 25%, 10% with escalating bonus damage
- Berserk mode introduced as rage peak state
- Rest mechanic added between rounds
- Universal developer shortcuts: q to restart, c to jump to arena
- RestartException and QuickCombatException introduced
- GAME_WARRIOR global reference created
- use_potion_menu() and level_up_menu() added
- Defence block flavour text added

---

## v0.09 (ai_helps_build_battler_09.py)
*2023–2024 | ~725 lines*

- Combat stability pass — double damage print bug fixed, alternating turn logic fixed
- NoneType attacker crash in defensive messages fixed
- Bloodlust stacking bug fixed
- Monster weights adjusted — Fallen Hero appears less often
- Combat loop structure cleaned up

---

## v0.08 (ai_helps_build_battler_08.py / ai_helps_build_arena_battler_08.py)
*2024 | ~660–715 lines*

- First structured arena combat loop
- Creator → Monster / Hero class hierarchy established
- Monster roster: Slime, Goblin, Skeleton, Wolf, Fallen Hero
- Basic attack rolls, XP, gold, defence (informational), essence tracking
- Potions: heal, ap, mana
- Three-item inventory system
- Foundation that everything since has been built on

---

## October 2, 2025 (arena_battler_October_2_2025.py)
*763 lines*

- Near-identical to September build — stable checkpoint before the major architecture push
- No new functions added; confirms September build was solid enough to save as-is

---

## September 17, 2025 (arena_battler_sept_17_2025.py)
*763 lines*

- clear_screen(), continue_text(), and check() introduced — utility functions still present in v4.28
- main() function added to wrap the game loop
- Tournament intro story text appears for the first time — explains the premise, memory wipe, and freedom
- Gold and essence tracking working via global variables
- textwrap used for the first time for readable story text

---

## August 6, 2025 (battle_simulater_pc_update_August62025.py)
*590 lines — earliest surviving build*

- Creator base class exists but Skeleton is just `pass` — OOP still being learned
- Combat is a series of standalone functions: slime_battle(), skelton_battle(), ghost_battle()
- Global variables track gold, HP, and essence — no class-based state management yet
- Comments throughout show active learning: notes on how super() works, what pass does, questions about gold tracking
- Warrior class has gold attribute — first appearance of the gold system
- endings and monster_essence lists already present as globals
- This is where Journey to Winter Haven began
