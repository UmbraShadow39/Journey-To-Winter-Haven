# Journey to Winter Haven — Changelog

A high-level summary of major changes across the project's full development history.
For full version-by-version detail see [DEVLOG.md](DEVLOG.md).

**Platform roadmap:** itch.io terminal demo (May 2026) → Pygame port (Dec 2026) → Godot/Steam Early Access (May 2027)

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
