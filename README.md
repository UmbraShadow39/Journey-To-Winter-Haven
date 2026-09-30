# Journey to Winter Haven: A New Champion Rises

A choice-driven dark fantasy RPG built in Python. You enter a monster tournament as a captured adventurer, fight your way through increasingly dangerous opponents, and face a moral decision that will define your legacy — and your child's destiny.

## Current Version: v0.8.04

## Play Now

- **Windows Executable** — [Download on itch.io](https://umbra41.itch.io/journey-to-winter-haven)
- **Browser Version** — [Play on Replit](https://replit.com/@Umbra41/Winter-Haven-Journey)
- **Source Code** — [Latest Release](https://github.com/UmbraShadow39/Journey-To-Winter-Haven/releases/latest)
- **GitHub Repository** — [UmbraShadow39/Journey-To-Winter-Haven](https://github.com/UmbraShadow39/Journey-To-Winter-Haven)

## Features

### Combat
- Turn-based combat with attack, defence, AP, and special moves
- Three difficulty modes: Noob, Warrior, Champion — with full stat/score/gold scaling at 1.5x on Champion
- Sex-based stat profiles — Male (30 HP, ATK 1-6, 0 DEF, 3 AP) vs Female (27 HP, ATK 2-4, 1 DEF, 4 AP)
- Full monster roster (18+) with unique special attack patterns, charge-based bosses, and tier-5 hidden bosses (Young Chimera, Patronus)
- Patronus Smite meter system — charges from player skills, fires defence-ignoring 1.5x strike at 100%
- Difficulty-exclusive monsters (Giant Diseased Rat on Noob, framework for Warrior/Champion exclusives)
- Magic resistance stat — reduces elemental damage by 1 per point (flat)

### Progression
- Level-up system with stat points, skill points, and a full 5-skill tree (Power Strike, Heal, War Cry, Defence Break, Death Defier)
- Assassin's Strike hidden capstone (Power Strike R5 + Dual Wielder R5)
- Mastery system — Rank 5 unlocks permanent passive titles (Brawl Master +20% ATK, Combat Medic +10% HP regen, Charismatic Speaker +15% ATK buff, Armor Piercer -1 DEF on hit, Death's Apprentice cheaper Death Defier)
- Title system — equippable titles mid-run (River Warrior, Jack of All Trades, Big Spender, Penny Pincher, and more)
- Bestiary with per-difficulty tracking, auto-scaled stats, completion titles (Noob/Warrior/Champion Bestiary Master)
- Color-shifting XP bar — dim cyan through gold sparkle, with shimmer animation on level-up

### Equipment & Crafting
- Full armor socket system — Cured Pelts (+DEF/HP), Elemental Sacs (resistance), Reinforcement Crystals (full stat bonuses), Javelina Tusks (retaliation bleed), Soul Pendants (heal on hit)
- Socket-based armor renaming — socketing adds prefixes (Spiked, Venomous, Scorched, etc.)
- Crafting system — Wolf-Hide and Dire Wolf armor sets, pelt curing, weapon socketing, helm and cape slots
- Dual-wield system with visibility helpers and combat detail toggle
- Equipment and loot system with rarity tiers (poor through mythril)
- Merchant shop with persistent inventory between rounds
- Recipe cost estimates in crafter menu

### Story & World
- Moral choice system — Guardian and Dark Champion endings with distinct stat identities
- Branching Dark Forest path with multiple sub-paths (run/stay/fight/submit)
- Sex-specific story branches (quest-giver swap, unique Aldric/Elwyn sendoff dialogue)
- Rich lore and world building — Chapter 1 of a planned trilogy

### Seasonal Events
- Real-world month detection with persistent collection tracking
- October (Halloween): 3 seasonal monsters (Jack O'Lantern T1, Trickster T2, Female Werewolf T3), Tom vendor NPC, candy currency, 4-piece Dread Aura set, lycanthropy conversion meter, gear upgrade system
- August: Birthday Cake collectible (full restore + Sugar Rush buff)
- March: Book of Lost Secrets (learn any skill)
- December: Winter Solstice event (planned)
- Collection Book with permanent score multipliers (up to +0.70)

### Pygame Visual Port (in progress)
- Title screen with pixel art backdrop (deep navy sky, alien moons, starfield)
- Scene manager system — single window with scene routing
- Ashenvale Gate cutscene with pixel art backdrop and visual-novel text boxes
- Sex selection menu with mouse/touch/keyboard support
- Tablet-compatible responsive scaling

### Other
- Gold and scoring economy with rank ladder (F through SS "God Champion")
- Leaderboard system (Supabase-powered)
- Full combat log with pagination
- Color-coded HP/AP bars (via rich library)
- Python lessons module (unlocks after first victory)
- Universal !q/!c/!debug input override from any prompt
- Profanity filter for leaderboard names

## How to Play

### Windows Executable (Recommended)
Download the `.exe` from the [itch.io page](https://umbra41.itch.io/journey-to-winter-haven) — no installation required.

For the best experience with full visuals, use **Windows Terminal** (free on the Microsoft Store).

### Running From Source

Requires **Python 3.11+**. All `.py` files must be in the same folder.

```
pip install -r requirements.txt
python Journey_To_Winter_Haven_v_08_04.py
```

### Required Files

| File | Purpose |
|------|---------|
| `Journey_To_Winter_Haven_v_08_04.py` | Main game |
| `combat.py` | Combat engine, boss fights, arena loop (7,558 lines) |
| `combat_log.py` | Combat logging and run stats |
| `collectibles.py` | Seasonal events, Halloween/Birthday/Solstice content, Tom vendor (2,990 lines) |
| `crafter.py` | Crafting system, pelt curing, sockets (2,998 lines) |
| `debug.py` | Debug menu and dev tools (1,617 lines) |
| `equipment.py` | Equipment, loot, inventory, socketing (1,748 lines) |
| `gold.py` | Currency tracking |
| `hero.py` | Hero class and stat management (1,736 lines) |
| `leaderboard.py` | Leaderboard system |
| `merchant.py` | Merchant shop system (1,357 lines) |
| `monsters.py` | Monster classes and encounter logic (3,040 lines) |
| `score.py` | Run scoring system |
| `shared.py` | Shared utilities and display helpers |
| `story.py` | Story sequences and narrative (3,863 lines) |
| `titles.py` | Title and achievement system |
| `bestiary.py` | Per-difficulty bestiary with completion titles |
| `ui.py` | UI utilities |
| `ui_bars.py` | Rich HP/AP/SP bar rendering |
| `python_lessons.py` | Python lessons module (unlocks on first win) |
| `python_exercises.py` | Python exercises and quizzes |

**Pygame files (visual port):**

| File | Purpose |
|------|---------|
| `game.py` | Pygame master loop and scene manager |
| `title_screen.py` | Pixel art title screen with navigable menu |
| `ashenvale_gate.py` | First cutscene — visual novel style with backdrop |

**Data files:**

| File | Purpose |
|------|---------|
| `scores.json` | Local leaderboard data |
| `bestiary.json` | Bestiary discovery tracking |
| `seasonal_data.json` | Seasonal collection persistence |
| `python_progress.json` | Python lessons progress |
| `custom_badwords.txt` | Profanity filter additions |
| `requirements.txt` | Python dependencies |

### Dependencies

```
colorama          # Terminal colors
pygame            # Visual port (title screen, cutscenes)
rich              # HP/AP bar rendering (optional — falls back to plain text)
better-profanity  # Chat filter for leaderboard names
supabase          # Global leaderboard
python-dotenv     # Environment variable management
```

Dev tools (not required to play):
```
ruff              # Python linter
```

## Project Structure

```
Journey To Winter Haven v0.08/
├── Journey_To_Winter_Haven_v_08_04.py   # Main game file (1,508 lines)
├── combat.py                             # Combat engine (7,558 lines)
├── collectibles.py                       # Seasonal events & vendor (2,990 lines)
├── crafter.py                            # Crafting system (2,998 lines)
├── story.py                              # Story & narrative (3,863 lines)
├── monsters.py                           # Monster roster (3,040 lines)
├── hero.py                               # Hero class (1,736 lines)
├── equipment.py                          # Equipment & loot (1,748 lines)
├── debug.py                              # Debug tools (1,617 lines)
├── merchant.py                           # Merchant shop (1,357 lines)
├── score.py                              # Scoring system
├── shared.py                             # Shared utilities
├── bestiary.py                           # Bestiary system
├── combat_log.py                         # Combat logging
├── gold.py                               # Gold system
├── leaderboard.py                        # Leaderboard
├── titles.py                             # Title system
├── ui.py                                 # UI utilities
├── ui_bars.py                            # Rich bar rendering
├── python_lessons.py                     # Python lessons
├── python_exercises.py                   # Python exercises
├── game.py                               # Pygame scene manager
├── title_screen.py                       # Pygame title screen
├── ashenvale_gate.py                     # Pygame cutscene
├── Art assets/                           # Pixel art (Aseprite source + PNG)
├── generated_audio/                      # Suno music tracks
├── Major_Versions/                       # Archive of major milestones
│   ├── v0.1.2/
│   ├── v0.5.14/
│   ├── v0.6.21/
│   ├── v0.7.19/
│   ├── v3.18/
│   └── v4.28/
├── Old V.08 builds/                      # Previous v0.08 sub-versions
├── Code changes/                         # Historical code change docs
├── Session Summaries/                    # Dev session summaries
├── Original blueprints/                  # Early prototypes
├── CHANGELOG.md
├── DEVLOG.md
├── LORE.md
├── QUEST_DESIGN.md
├── TECHNICAL_DOC.md
├── TODO.md
├── README.md
└── LICENSE
```

## Roadmap

### v0.8.04 — Current
- Sex-based stat profiles and branching story ✅
- Full Dark Forest path with multiple sub-paths ✅
- Pygame scene manager and title screen ✅
- Ashenvale Gate cutscene with pixel art ✅
- Sex selection menu (keyboard + mouse + touch) ✅
- Aldric/Elwyn sex-specific sendoff dialogue ✅
- Seasonal collectibles system (Birthday/Halloween/Solstice) ✅
- Halloween monsters: Jack O'Lantern, Trickster, Female Werewolf ✅
- Tom vendor NPC with candy shop, upgrades, premium buyback ✅
- Bestiary rewrite with per-difficulty tracking ✅
- Magic resistance stat ✅
- Difficulty-exclusive monster framework ✅
- Giant Diseased Rat (Noob-exclusive) ✅
- Patronus Smite meter system ✅
- Color-shifting XP bar with level-up animation ✅
- Socket-based armor renaming ✅
- Crystals full value in armor sockets ✅
- Tusk retaliation (spiked armor) ✅
- Reinforcement Crystal armor socketing ✅
- Soul Pendant armor socket ✅
- Universal !q/!c/!debug input override ✅
- Defence Break and War Cry rank selection menus ✅
- Warrior difficulty loot boost ✅
- Crafter recipe cost estimates ✅
- Numerous bug fixes across all systems ✅

### Beyond v0.8
- Finish Halloween content (Headless Horseman boss, remaining wiring)
- Winter Solstice seasonal event (December)
- More pygame scenes (forest travel, river scene, campfire)
- Weapon points system (post-arena leveling track)
- Supply/demand economy system
- Book of Monster Secrets (Blue Mage system)
- Save/load functionality
- Roguelike arena mode with multi-arena progression
- Multiple playable classes (Mage, Thief)
- Pygame full port — targeting March 2027
- Godot 2D / Steam Early Access — targeting 2027
- Game 2 — playing as the child, inheriting parent's legacy via genetic signature

## License

All Rights Reserved.
See the LICENSE file for details.
