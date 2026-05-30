# Journey to Winter Haven — Developer Log

Full version-by-version development history. For a quick overview see [CHANGELOG.md](CHANGELOG.md).

Entries are ordered newest to oldest. Era headers mark major version milestones.

---

# ── v0.6 ERA — Prologue, Architecture & Modularisation ──────────────────────

## v0.6.21 — Bug Fix Pass: Dev Shortcut Safety, Equipment Display, Score Flags, Primordial Surge Exploit
*May 2026 | main: ~14,560 lines | monsters.py: ~2,530 lines | crafter.py: ~1,400 lines*

Five HIGH-severity fixes from a pre-push code audit (3 rounds, covered every module). No new features — pure correctness/safety.

- AUDIT METHODOLOGY:
  - Round 1: main file structure, equip/unequip math, refusal/restart paths
  - Round 2: merchant flow, crafter, titles, shared.py class duplication, gold/score paths
  - Round 3: Death Defier / River Spirit conversion, save/load (leaderboard), DoT handling, Chimera/Patronus boss fights
  - Bugs ranked HIGH (fix before push) / MEDIUM (defer with note) / LOW (cosmetic)
  - All 5 HIGH-severity items addressed in v0.6.21; MEDIUMs documented for future passes

- FIX 1 — '!m'/'!monster' DEV SHORTCUT (input override safety):
  - BUG: line 84 global input() override triggered battle(GAME_WARRIOR, monster) on bare 'm' or 'monster' at any of the ~200 input() prompts in the game
  - REPRO: type 'm' at the merchant's "equip now? (y/n)" prompt → debug battle starts mid-purchase, equipment state mid-flux
  - WHY MISSED IN v0.6.19: v0.6.19 added '!' protection to all dev shortcuts in _try_dev_shortcut, but the monster-select path lived in input() itself — a different code path that the v0.6.19 pass didn't touch. Comment at _try_dev_shortcut line ~585-589 acknowledged this and justified leaving it bare ("non-destructive — opens a menu, no state nuke") — but the comment was wrong, it DID call battle() which is very state-affecting
  - FIX: input() now recognizes '!m'/'!monster' (case-insensitive via cleaned = raw.strip().lower()) and emits the existing __MONSTER_SELECT__ sentinel. handle_monster_select_shortcut() at the consumer side resolves it combat-aware
  - SENTINEL > DIRECT-CALL: emitting the sentinel was the architecturally correct choice all along — the override has no idea whether it's mid-combat, and the sentinel-handler path was already combat-aware (continue_text uses in_combat=False; battle_inner uses in_combat=True for enemy swap)
  - CONSUMERS UNCHANGED: handle_monster_select_shortcut at lines 670 (continue_text) and 10461 (battle_inner) already do the right thing with the sentinel — only the producer changed
  - DOCSTRING DRIFT: continue_text, check, and _try_dev_shortcut docstrings all updated to reflect the '!' convention (they still listed bare 'q'/'c'/'m'/'monster' as valid)

- FIX 2 — EQUIPMENT LIST STALE SLOT KEYS (visibility regression since v0.6.16):
  - BUG: 4 display loops iterated ("weapon", "armor", "accessory", "trinket", "finger_1", "finger_2") — the pre-v0.6.16 equipment dict keys. v0.6.16 renamed to (main_hand, off_hand, armor, helm, cape, accessory, trinket, finger_1, finger_2), so the loops silently matched ZERO weapon slots
  - PLAYER-VISIBLE: show_end_summary (win/loss screen — every player every run), show_game_stats (combat HUD gear line — every fight), show_combat_stats (detailed stats screen)
  - DEV-ONLY: debug menu unequip-slot tool (rare, but the same wrong-keys pattern)
  - FIX: all 4 loops now iterate the correct 9 slot keys ("main_hand", "off_hand", "armor", "helm", "cape", "accessory", "trinket", "finger_1", "finger_2"). Labels updated to "Main Hand"/"Off Hand"/"Helm"/"Cape"
  - DEBUG TOOL HARDENING: slot_map = {str(i): s for i, s in enumerate(slots, 1)} generated from the slots list, so future slot additions can't desync the choice→slot map
  - SYNERGY WITH v0.6.20: the v0.6.20 dual-wield breakdown and set-bonus blocks already exposed weapons (via dual-wield) and helm/cape (via set-bonus) from a different angle — fix 2 closes the last gap. Verified both v0.6.20 helpers still render alongside the corrected equipment list

- FIX 3 — BERSERK / DEATH DEFIER SCORE FLAGS RESET PER-FIGHT:
  - BUG: record_fight_score read warrior.berserk_used (+20) and warrior.death_defier_used (+50). Both flags are RUN-WIDE by design:
    * berserk_used: gates the natural <=20% HP re-trigger; only resets when HP recovers above 20%
    * death_defier_used: only resets at full-rest interlude
  - EFFECT: once either fires in fight 1, every subsequent fight that round silently collected the bonus. Berserk especially nasty — if the player stayed below 20% HP across multiple fights (plausible mid-arena), every fight got +20 free
  - DESIGN CONFLICT: the flags have two purposes (gating + scoring) that need different lifetimes. Can't reset berserk_used per-fight (would break the gate); can't track only per-fight (would break the gate). Solution: separate flags
  - FIX: added berserk_used_this_fight / death_defier_used_this_fight
    * Set True alongside the run-wide flags at every trigger site (natural berserk trigger, Trinket of Berserk consumable, Death Defier revival)
    * Reset False at battle_inner start (next to existing bonus_action_used = False)
    * Initialized False on Warrior.__init__ so the first fight and first score read never hit a missing attr
    * score.py reads the per-fight flags with getattr(..., fallback=run_wide_flag) — defensive in case any old save state lacks them
  - RUN-WIDE FLAGS UNCHANGED: berserk_used / death_defier_used keep their original gating semantics — only the score read changed
  - TRIGGER SITE COVERAGE: confirmed all 3 berserk sites (natural HP trigger at ~7918, Trinket of Berserk at ~4586) and the death_defier site in try_death_defier (~4347) set the new flag. The 4576 berserk site (also sets berserk_used = True) is one of the same two trigger paths

- FIX 4 — PRIMORDIAL SURGE STAT RESTORE OVER-CREDIT:
  - BUG: Primordial Surge degrades player stats by 10% with a floor (max(1,...)/max(0,...)) but records the INTENDED loss (pre-floor) for later restore. When a stat hits the floor, the restore over-credits by the difference → permanent stat GAIN from being attacked
  - REPRO (verified empirically): warrior at min_atk=2, hit by 3 Primordial Surges, ends at min_atk=1 (lost 1, floored). primordial_atk_loss records 3. Restore adds 3 → min_atk = 4. Net +2 gain from being damaged. Same pattern dragged max_atk up via the max(min_atk, ...) coupling
  - WHY USUALLY NOT NOTICED: a typical L5 warrior has min_atk ~14, atk_loss ~2 → no flooring. Only low-ATK builds or extreme repeated surges hit the bug
  - FIX: capture the ACTUAL floored delta:
        _old_min = warrior.min_atk
        warrior.min_atk = max(1, warrior.min_atk - atk_loss)
        actual_min_atk_loss = _old_min - warrior.min_atk
        warrior.primordial_atk_loss += actual_min_atk_loss
  - MIN/MAX TRACKED SEPARATELY: min and max ATK floor against different bounds (min floors at 1, max floors at the new min). A single shared tracker couldn't faithfully restore both. Added primordial_max_atk_loss alongside the existing primordial_atk_loss (which now means MIN atk loss specifically). Lazy-init guarded with hasattr to keep backward compat with mid-run saves
  - _restore_primordial_stats UPDATED: reads both trackers, applies them to the right stat, clears both. Docstring notes the asymmetry
  - DISPLAY: the player-facing message now shows the actual loss (`-{actual_max_atk_loss}` etc.) not the intended loss, so when flooring kicks in the message accurately reflects what happened
  - VERIFICATION: smoke test exercises 4 cases (low/typical/extreme-floor/mid) with 2-5 surges each, all net to (0,0,0,0)

- FIX 5 — DEBUG OPTION 11 TYPEERROR CRASH (dev-only):
  - BUG: debug menu "Trigger Death Defier (test)" called try_death_defier(warrior, source="debug"). Both versions of the function take `reason`, not `source`. Raised TypeError, made the debug hook untestable
  - FIX: source="debug" → reason="debug". One word
  - VERIFIED: smoke test calls the corrected path, confirms it revives correctly

- TEST COVERAGE (_smoke_v0_6_21.py, 7 assertion blocks):
  - Fix 1: '!m'/'!monster' emit sentinel; bare 'm'/'monster'/'Marcus' pass through as text (case-insensitive verified)
  - Fix 2a/2b: weapons appear in show_combat_stats and show_end_summary; v0.6.20 dual-wield block still renders alongside
  - Fix 3: per-fight flags reset correctly between fights (run-wide stays True, per-fight goes False, score reads per-fight)
  - Fix 3b: per-fight flags initialized on Warrior creation
  - Fix 4: Primordial degrade+restore nets to zero across low-stat / typical-L5 / extreme-floor cases
  - Fix 5: try_death_defier(reason='debug') works without TypeError

- DEFERRED ITEMS (documented in audit, not fixed in v0.6.21):
  - MEDIUM: off-hand weapon procs don't fire when dual-wielding — get_weapon() returns main-hand only. Needs design decision (one swing blended vs. two swings per turn) before code change
  - MEDIUM: triplicate dead-code class definitions (Equipment, Creator, Monster) in main file shadow the shared.py imports. No live bug (verified: all instances derive from shared versions) but refactor hazard — drift is already visible (turns_survived field present in shared, absent in main)
  - MEDIUM: two divergent try_death_defier definitions (shared 2-param vs. main 3-param). Main version wins; shared is effectively unused. Consolidate later
  - LOW: leaderboard save is non-atomic (write-in-place, no temp+rename). Corrupt-on-interrupt resets the board cleanly (load handles it), but the player loses their history
  - LOW: chinker / death_delver TITLE_BUFFS entries are dead code (buffs applied inline in check_breadth_titles); award_title_with_buff silently ignores min_atk-only buffs (latent gap); merchant variant comment math transposed; sell-back fallback single-slot iteration; player DoT fade messages are third-person ("fades from Umbra" instead of "from your body"); collect_dot_ticks stale docstring (says 2 return values, actual 3)
  - DESIGN FLAG: Chimera passive heal at 10% max HP per turn is unconditional (fires even when blinded/skipping). If player's net DPS is below this, the fight is mathematically unwinnable. Worth a balance check against a realistic L5 warrior's sustained DPS

- BACKWARD COMPATIBILITY:
  - No save-format changes
  - primordial_max_atk_loss is lazy-initialized via hasattr — old warriors mid-fight will not crash on first surge
  - berserk_used_this_fight / death_defier_used_this_fight initialized on Warrior.__init__ AND defended with getattr in score.py — safe against any stale state
  - Display fixes are purely cosmetic — no game logic depends on what the equipment list prints
  - The '!m' change is the most user-visible behaviour change: muscle memory for bare 'm'/'monster' breaks. Documented in patch notes for any returning testers

---

## v0.6.20 — Stats Visibility & Armor Socket UI Scaffolding
*May 2026 | main: ~14,500 lines | monsters.py: ~2,490 lines | crafter.py: ~1,365 lines*

- INTERLUDE STATS PAUSE BUG:
  - arena_quarters_interlude options 9 (Check your status) and 11 (View all game stats) printed and then looped
  - Loop top calls clear_screen() unconditionally — stats vanished before player could read them
  - show_combat_stats / show_all_game_stats themselves were correct; the bug was purely missing pause in the caller
  - Fix: added `_real_input("Press Enter to return to the menu...")` after each stats call
  - Used _real_input (not input) so dev shortcuts can't fire from the pause prompt and skip the clear_screen
  - Pattern matches existing option 14 (Waterlogged Stone) which already had the pause
  - Option 10 (Spend points) and option 12 (Inventory) not touched — spend_points_menu and inventory_menu both have their own internal loop control, so they handle pause natively

- SET BONUS TRACKER (_format_set_bonus_lines):
  - New module-level helper, placed just above the Hero class (line ~6538 in main file)
  - Returns list[str]; empty list when no set pieces equipped → section skipped entirely
  - Reads piece counts via crafter.wolf_set_active_pieces / dire_wolf_set_active_pieces
  - Reads "full set active" via crafter.pack_hunter_active / apex_predator_active
  - Bonus tables mirror apply_wolf_set_bonus and apply_dire_wolf_set_bonus exactly:
    - Wolf-Hide: 2pc +5 HP, 3pc +1 AP, 4pc +2 DEF/ATK + Pack Hunter (+10% basic atk, 50% bleed-on-hit)
    - Dire Wolf: 2pc +8 HP, 3pc +2 AP, 4pc +3 DEF/ATK + Apex Predator (+10% basic atk, 5% lifesteal)
  - Active bonuses shown as bullet list; next-threshold preview shown as parenthetical hint
  - Both sets rendered independently (mixed wolf + dire wolf shows both lines) because piece-shuffling can briefly have items from both equipped
  - Wrapped in try/except ImportError around the crafter import so the helper degrades gracefully if crafter.py is missing (returns [])

- DUAL-WIELD BREAKDOWN (_format_dual_wield_lines):
  - New module-level helper, also placed just above the Hero class
  - Returns list[str]; empty list when not dual-wielding (single weapon, weapon+shield, no weapons)
  - Detection: both main_hand AND off_hand must have slot=="weapon" (slot=="shield" correctly skipped)
  - Math: floor(off_atk / 2) for both atk_min and atk_max — mirrors apply_dual_wield_modifier
  - Display includes title-held vs title-not-held variants:
    - Title held: "Dual Wielder title: +1/+1 ATK passive"
    - Title not held: "(Dual Wielder title unlocks +1/+1 ATK passive)" — acts as discoverability hint
  - If future Dual Wielder skill grants full off-hand damage, this helper needs the same update as apply_dual_wield_modifier

- INTEGRATION POINTS:
  - show_combat_stats: helpers called after equipment-list block, before Death Defier block
  - show_all_game_stats: helpers called between gold line and War Cry block (gear-related, belongs near top stats)
  - Both helpers wrapped: `if lines: print(); for line in lines: print(line)` — silent skip when empty
  - Order: set bonuses before dual-wield (gear → weapon-specific)

- NOTED BUT NOT FIXED:
  - show_combat_stats equipment-list loop iterates ("weapon", "armor", "accessory", "trinket", "finger_1", "finger_2")
  - show_all_game_stats has no equipment list at all
  - Since v0.6.16 the equipment dict uses main_hand/off_hand/helm/cape — none of which are in the old loop
  - Result: weapons, shields, helms, and capes have been invisible in stats since v0.6.16
  - The new set-bonus and dual-wield blocks partly mitigate (you can SEE the wolf cape / sword now via the set/dual-wield blocks)
  - Equipment-list loop should be fixed in a separate pass — left alone here to keep the v0.6.20 patch surgical
  - Same bug pattern appears at lines ~3205 and ~3569 in debug-loot displays (just noted, untouched)

- SMOKE TEST:
  - _smoke_test_v0_6_20.py covers 8 cases: empty equipment, 1/3/4 wolf pieces, 4 dual-wield states, mixed wolf+dire wolf, no-mutation
  - _visual_smoke.py renders both show_combat_stats and show_all_game_stats with realistic equipment for visual review
  - Confirmed: ATK math reads correctly as base(1-5) + main(5-10) + off-half(1-3) + title(+1/+1) = 8-19

- NO MECHANICAL CHANGES:
  - apply_wolf_set_bonus, apply_dire_wolf_set_bonus, apply_dual_wield_modifier untouched
  - Set bonuses still applied at equip time (no live recalc per turn)
  - Dual-wield halving math unchanged (floor(off_atk / 2))
  - Dual Wielder title bonus unchanged (+1/+1 ATK passive, awarded on first dual-wield observed)
  - Pack Hunter / Apex Predator basic-atk multiplier still read live from crafter helpers in warrior_attack_roll
  - This is a pure UI surface — all three fixes just expose existing state that was already correct

- ARMOR SOCKET UI SCAFFOLDING (Phase 2 preview, no mechanics):
  - User asked about armor sockets discussed back in v0.6.16; confirmed they were deferred to "Phase 2" with the foundation already in place but combat hooks never wired up
  - Equipment class already has _SOCKETABLE_SLOTS = {"weapon", "armor"} and _SOCKET_COUNTS_ARMOR table — armor items have been spawning with empty socket lists since v0.6.16, inert because no combat code reads them
  - v0.6.20 decision: add UI surface that says "this is a planned thing" without committing to mechanics
  - FRONT-MENU: Old _socket_loop (weapon picker) renamed to _weapon_socket_loop. New _socket_loop is a "What to socket?" front-menu with 1) Weapon, 2) Armor (💤 coming soon), 0) Back
  - PREVIEW: New _armor_socket_preview shows the player's socketable armor pieces (equipped + bag) with current socket counts and a crafter flavor line. Read-only — no charges, no mutation. Returns to front-menu on Enter
  - HELPER: New _armor_with_sockets_in_inventory(warrior) mirrors _weapons_with_sockets_in_inventory. Currently filters slot=="armor" only (chest piece) — helm/cape excluded from Phase 2 design. Update this filter when expanding Phase 2 slot coverage
  - SOCKET COUNTS UNCHANGED: _SOCKET_COUNTS_ARMOR stays at Normal 1, Uncommon 1, Rare/Epic/Legendary/Mythril 2. Player decided "leave it alone, close enough"

- ARMOR SOCKET PHASE 2 DESIGN NOTES (in crafter.py, ~50 lines):
  - Two planned armor-socket items documented:
    * Javelina Tusk — RETALIATION BLEED on incoming hits, start 2 dmg/tick × 2 turns at 75% socket power, no proc on DoT-to-player (cascade prevention)
    * Soul Amulet — DAMAGE ABSORB + HEAL on incoming hits, start ~20% absorb with half converted to heal, pairs with weapon-side Soul Pendant as lifesteal archetype
  - Open design questions logged for Phase 2:
    * Does Tusk retaliation count as the player attacking (bleed mastery title, score attribution)?
    * Does Soul Amulet heal trigger Pack Hunter / Apex Predator basic-atk multipliers?
    * Damage source attribution in combat log — separate line on application or just bleed ticks?
    * Future resistance system (sacs in armor sockets granting elemental resistance) — explicitly deferred, would need damage-type tags on all DoTs

- IMPLEMENTATION NOTES FOR PHASE 2 (when revisiting):
  - Mirror Phase 1 architecture: SOCKETABLE_INTO_ARMOR set, get_armor_socket_procs(armor) aggregator, socket_nerf_chance / socket_nerf_damage reused as-is
  - Combat hook: armor procs fire from inside apply_defence (or just after — TBD based on the absorb-vs-bleed timing question)
  - Crafter UI: add the armor side of _socket_item_into_X and _show_socket_menu_for_X mirroring the weapon versions; the menu plumbing is mostly UI copy-paste with "armor" swapped for "weapon"
  - Test coverage: armor proc smoke tests should cover the cascade case (Tusk proc on DoT-to-player must NOT chain into another retaliation)

- TEST COVERAGE:
  - _smoke_armor_sockets.py: 7 tests covering front-menu rendering, both branches, empty + populated armor state, no-mutation, source-level design-notes presence, Phase 1 weapon flow not broken
  - _visual_armor_sockets.py: renders both populated and empty armor preview screens for design review
  - All 7 tests pass; visual output reads cleanly

---

## v0.6.15 — Score Bug Fix, Blind Unification, Tier-3 Rebalance & QoL
*May 2026 | main: ~13,286 lines | monsters.py: ~2,490 lines | combat_log.py: ~263 lines*

- SCORE BUG FIX (CRITICAL):
  - combat_log.show_run_score() wrapper was: `_score_show(warrior, outcome); return`
  - Now: `return _score_show(warrior, outcome)`
  - The wrapper had been dropping the integer return value, so callers got None
  - Every `_final_score or 0` collapsed to 0, leaderboard saved every defeat as score=0
  - On-screen score breakdown worked correctly the whole time — bug was ONLY in the leaderboard save path
  - Detection: user noticed two leaderboard entries both showed L3/L5 + score 0
  - Initial suspicion was OUTCOME_MULTIPLIERS — confirmed defeat=1.0, not the cause
  - Traced via grep on `record_run` → `display_at_end_of_run` → `show_run_score` import chain
  - Smoke test verified fix: wrapper now returns int (190 in fake-warrior test)

- BLIND DAMAGE MULTIPLIER UNIFIED:
  - blind_damage_multiplier(hero) is now the single source of truth:
    - blind_turns >= 3 → 0.0  (skip turn — handled in turn loop, defensive value here)
    - blind_turns == 2 → 0.5  (50% damage)
    - blind_turns <= 1 → 1.0  (full damage)
  - power_strike: was using inline `0.5 if turns >= 2 else 0.75` table — now calls helper
  - player_basic_attack: was completely ignoring blind_turns — now calls helper with inline message
  - User-reported: blinded by goblin dust, skipped turn, then basic attack landed for 7 (max roll) on a 2-6 ATK + walking stick build

- TIER 3 + FALLEN STAT REBALANCE (monsters.py):
  - Goblin Warrior:  ATK 7-11 → 6-10, DEF 6 → 5
  - Drowned One:     ATK 7-10 → 6-9,  DEF 5 → 4
  - Hydra Hatchling: DEF 5 → 4 (ATK unchanged at 5-8)
  - Flayed One:      DEF 4 → 3 (ATK unchanged at 6-8)
  - Fallen Warrior:  ATK 6-10 → 7-11, DEF 5 → 6, HP 60 → 65
  - Hardened scaling unchanged (+1 DEF, +2 ATK per level via apply_level_scaling)
  - Fallen now leads tier-3 in every base stat category
  - Hardened Goblin Warrior at DEF 6 ties Fallen — acceptable since Goblin lacks Fallen's Defence Warp mechanic and Weapon Core drop

- INTERLUDE POTION ACCESS:
  - arena_quarters_interlude (round 4-5 day-rest) had no Use-a-Potion option
  - Player could buy progression potions (skill_point, stat_point, skill_rank_up) but had no way to drink them — combat refunded them correctly, but interlude had no path either
  - NEW: Option 15 "Use a potion" added to interlude hub menu (line ~2425)
  - Calls use_potion_menu(warrior, in_combat=False)
  - All 17 potion handlers audited for out-of-combat correctness — no other gaps found
  - Frostpine Tonic, Cure-All, antidote, burn_cream all correctly handle "no effect to clear" cases

- DEBUG MENU NUMBERING FIX:
  - Print order was: 1, 2, ..., 17, 20, 18, 19 (Title Grant printed before Exit Run/Exit Debug)
  - Renumbered: 17 = Debug Potion Menu, 18 = Title Grant Menu, 19 = Exit Current Run, 20 = Exit Debug Menu
  - Dispatch updated to match new numbers

- "FROSTPINE TONIC BUG" RESOLVED AS NOT-A-BUG:
  - v0.6.14 flagged Frostpine and Cure-All as not clearing acid_defence_loss
  - User playtest revealed: each new acid stack reapplies its own erosion fresh
  - "Tonic didn't work" was actually "got re-acided post-tonic, erosion rebuilt from new hit"
  - Behavior is correct as-is; removed from deferred-bugs list

- FILES MODIFIED:
  - Journey_To_Winter_Haven_v_06_15.py (renamed from v_06_14.py)
  - monsters.py (5 monster stat blocks updated)
  - combat_log.py (one-line return fix in show_run_score wrapper)

---

## v0.6.14 — Combat Fatigue, Hardened Nerfs & Play-Again Prompt
*May 2026 | main: ~13,265 lines | monsters.py: ~2,490 lines*

- COMBAT FATIGUE — new focus-streak save mechanic to end stalemates:
  - Triggers after turn 10 for regular fights, turn 15 for Chimera/Patronus
  - Both player and enemy roll independent d20s at start of their respective turns
  - Save DC escalates by streak tier: tier 0 = DC 10, tier 1 = DC 15, tier 2 = DC 20
  - Pass → advance one tier (tier 2 passing wraps back to 0)
  - Fail → lose 1 DEF if roll ≤13, lose 2 DEF if roll ≥14, tier resets to 0
  - State stored as `entity.fatigue_def_loss` (cumulative, fight-only) and `entity.fatigue_save_tier`
  - Cleared on fight end via `reset_after_battle` / `reset_between_rounds`

- NEW HELPERS:
  - `init_fatigue(entity)` — lazy-initialises fatigue state on warrior or monster
  - `fatigue_threshold_for(enemy)` — returns 15 for Chimera/Patronus, 10 otherwise
  - `roll_fatigue_save(entity, turn_count, enemy, is_player)` — core mechanic
  - All three placed just above `clear_all_status_effects()` in the main file

- APPLY_DEFENCE INTEGRATION:
  - `effective_def = max(0, self.defence - acid_loss - fatigue_loss)`
  - Fatigue stacks independently with acid_defence_loss
  - Negative-DEF bonus damage penalty (-10% per point below 0) now factors fatigue too

- ACID TICK INTEGRATION:
  - `effective_def` for tick scaling now includes fatigue_loss
  - Acid ticks see the same fully-drained DEF the player feels in combat

- TURN-LOOP HOOKS:
  - Player save fires at start of `if not player_turn_started:` block (line ~9305)
  - Monster save fires at start of `else:` enemy turn block (line ~9952)
  - Both gated by their respective thresholds

- NARRATION (silent rolls — no dice numbers shown):
  - Pass tier 0 → silent (would spam otherwise)
  - Pass tier 1 → 🧘 "Your focus holds — you steady your stance."
  - Pass tier 2 → 🧘 "Through the haze of exhaustion, you find a second wind!"
  - Fail -1 → 💨 "Fatigue creeps in — your guard wavers. (-1 DEF)"
  - Fail -2 → 💨 "The long fight catches up with you — your stance breaks! (-2 DEF)"
  - Monster fatigue narrated with enemy.display_name and parallel phrasing

- MATH VALIDATION (10k trial simulation):
  - 5 turns in fatigue: avg DEF lost ~3 (min 0, max 5)
  - 10 turns in fatigue: avg DEF lost ~6 (min 2, max 10)
  - Pass rates match design: 55% / 30% / 5%

- HARDENED HYDRA + GOBLIN WARRIOR — AP cap at 3:
  - Override added inside `apply_level_scaling` for name == "Hydra Hatchling" or "Goblin Warrior" at level == 2
  - Higher levels still scale via HP threshold formula (lvl 3: AP 4-5, lvl 4: AP 5, etc.)
  - WHY: Hardened Hydra acid spit at AP 4 could chain 4 times in a fight — even mid-fight Frostpine Tonic cleanse left 30+ acid tick damage potential

- HARDENED BLEED — Goblin Warrior savage_slash:
  - dmg_min / dmg_max reduced from 4-6 → 3-5 (now matches standard bracket)
  - Duration unchanged at 4 turns (vs 2 standard) — hardened still distinguished by duration

- HARDENED ACID — Hydra Hatchling acid spit:
  - Stack now tagged `"hardened": True` at apply time (only on hardened non-chimera)
  - Tick handler rolls 2-4 if hardened-flagged, otherwise standard 3-5
  - Chimera ignores the flag (it has its own x2 multiplier path)

- BUG NOTED (NOT fixed this version) — Frostpine Tonic + Cure-All:
  - Both potions clear `acid_stacks` but NEVER clear `acid_defence_loss`
  - Sizzling + tick damage stops, but effective DEF stays reduced (up to -3) for rest of fight
  - Identified during a hardened Hydra playtest — logged for future fix
  - Deferred so we could feel-test fatigue + AP nerf in isolation first

- DEMO PLAY-AGAIN PROMPT:
  - New `prompt_play_again()` helper just above `main_menu()`
  - Replaces `input("\\nPress Enter to close the demo...")` at all 5 endpoints
  - y/yes → `os.execv(sys.executable, [sys.executable] + sys.argv)` → fresh process
  - n/no → "Until next time, warrior. ⚔️" → `sys.exit(0)`
  - Loops on invalid input
  - Endpoints: Chimera victory, Chimera defeat, Patronus victory, Patronus defeat, arena death
  - WHY: Re-exec sidesteps the deeply-nested control flow issue (endings are inside battle_inner/chimera_battle/patronus_battle — unwinding would require threading a custom exception or "restart requested" flag through 4 layers of returns)

- DEFENSIVE FATIGUE CLEANUP BEFORE LOOT:
  - 4 loot-equip points now explicitly zero out fatigue_def_loss and fatigue_save_tier before offering loot:
    - Regular monster kill (player-turn block, ~line 9904)
    - DoT-kill block (~line 10021)
    - Chimera scale equip (~line 8506)
    - Patronus breastplate equip (~line 8931)
  - WHY: Mirrors existing defence_warp fix pattern. Equipment is additive on base DEF, and reset_between_rounds clears fatigue afterward, so this isn't a live bug — but if Chimera/Patronus victories ever continue into another fight in the future, this prevents silent DEF corruption.

- FILES MODIFIED:
  - Journey_To_Winter_Haven_v_06_14.py (renamed from v_06_13.py)
  - monsters.py (apply_level_scaling override, savage_slash bracket, acid spit hardened tag)
  - score.py (S+ rank threshold + description)

- NEW RANK — S+ "Demigod Champion" at score 6,500:
  - Added to RANK_THRESHOLDS top of list: ("S+", 6500)
  - Added to RANK_DESCRIPTIONS: "Demigod Champion. The Beast Gods themselves take notice."
  - Sits at ~70% of theoretical max (~9,600 on a perfect Chimera path) — must trigger most bonus systems to hit
  - _rank_for_score() walks list top-to-bottom and returns first match; S+ now catches scores ≥6,500 before falling through to S
  - Rank box display in show_run_score() adapts to 2-char ranks via existing dynamic padding (no change needed)
  - Verified rendering: ║   RANK:  S+                ║ (fits cleanly in 30-char box)

- FUTURE RANK LADDER (sketched, NOT implemented):
  - SS    "god champion"        — lowercase g, peer with the greek-pantheon-style Beast Gods
  - SS+   "Elder god champion"  — beyond pantheon-level
  - SSS   "God Champion"        — uppercase G, Holy Trinity tier (Nathan's intentional distinction)
  - SSS+  TBD — only nameable when someone actually achieves it
  - Sketched in a score.py comment for future expansion. Awaiting higher score ceilings.

---

## v0.6.13 — Progression Potions
*May 2026*

- THREE NEW PROGRESSION POTIONS — all out-of-combat only:
  - `skill_rank_up` — picks one learned skill (rank ≥ 1, not maxed) and advances it by 1 rank
  - `stat_point` — grants +2 stat points, immediately opens inline assignment menu
  - `skill_point` — grants +2 skill points, immediately opens show_skill_tree() to spend them
  - All three refund themselves if used during combat (with `bonus_action_used` cleared if applicable)

- SKILL RANK-UP POTION:
  - Builds list of learned skills (`hero.skill_ranks[key] >= 1` and `rank < max_rank`)
  - Refunds and bails if list is empty
  - Player picks from numbered list with "Cancel" option (refunds)
  - On confirm: `hero.skill_ranks[chosen_key] += 1`, adds to `hero.skills`, clears `hero.skill_progress[chosen_key]`
  - Calls `check_jack_of_all_trades(hero)` if available (defensive guard for cross-skill achievements)

- STAT POINT POTION:
  - `hero.stat_points += 2`
  - Inline while loop: 1) +5 Max HP, 2) +1 ATK, 3) +1 DEF, 4) +1 Max AP, 5) Save remaining
  - HP option also bumps current HP and recalculates `max_overheal`
  - AP option also bumps current AP
  - No per-level cap — player can dump both into one stat

- SKILL POINT POTION:
  - `hero.skill_points += 2`
  - Immediately calls `show_skill_tree(hero)` if available (uses globals() guard for safety)
  - Falls through to a simple "N skill points banked" message if tree isn't loaded

- USE_POTION_MENU SIGNATURE CHANGE:
  - `use_potion_menu(hero)` → `use_potion_menu(hero, in_combat=False)`
  - Combat callers pass `in_combat=True`
  - The three new potions inspect this flag and refund + bail if True
  - Non-combat callers can omit (defaults to False)

- DEFAULT POTIONS DICT UPDATED:
  - `frostpine_tonic: 0` (existing, gifted in prologue)
  - `skill_rank_up: 0` (new)
  - `stat_point: 0` (new)
  - `skill_point: 0` (new)

- FILES MODIFIED:
  - Journey_To_Winter_Haven_v_06_13.py — three new potion handlers, signature change, default dict update

---

> **DEVLOG GAP NOTE:** Entries for v0.6.06, v0.6.08, v0.6.11, and v0.6.12 are missing from the dev log
> — these are documented in CHANGELOG.md but never got the bullet-format treatment here. Backfill on a
> future cleanup pass if desired; CHANGELOG.md is the authoritative high-level history.

---

## v0.6.10 — Death Defier Rebalance, Death's Apprentice Title & Underworld Dialogue
*May 2026 | main: ~12,415 lines | titles.py: ~340 lines | score.py: updated*

- DEATH DEFIER — AP cost curve rebalanced:
  - Old curve: rank 1-2 cost 3 AP, rank 3-4 cost 4 AP, rank 5 cost 5 AP
  - New curve: rank 1-2 cost 1 AP, rank 3 costs 2 AP, rank 4 costs 3 AP, rank 5 costs 4 AP
  - Rationale: old curve was punitive enough that players saved the skill for emergencies rather than using it actively in combat
  - Combined with the new Death's Apprentice rebound damage, the lower cost makes Death Defier feel like a real combat decision point rather than a panic button

- RIVER SPIRIT — discount changed from flat-0 to per-rank:
  - Old behavior: River Spirit path = 0 AP regardless of rank (gate inside an if/else, river bypassed rank scaling entirely)
  - New behavior: River Spirit applies -1 AP discount at every rank (additive, not override)
  - New river costs: rank 1-2 = 0 AP, rank 3 = 1 AP, rank 4 = 2 AP, rank 5 = 3 AP
  - Rationale: flat-0 made River Spirit functionally identical at every rank, so the path's reward stopped scaling with player investment
  - Discount structure preserves river identity (cheap casts, free at low ranks) while letting SP investment matter

- NEW HELPER — _dd_ap_cost(hero):
  - Single source of truth for Death Defier AP cost calculation
  - Returns base cost from rank table (1/1/2/3/4), then subtracts 1 for River Spirit, subtracts 1 for Death's Apprentice mastery
  - Floor rule: max(0, cost) if death_defier_river, else max(1, cost) — non-river players always pay at least 1 AP
  - Both `activate_death_defier()` and `skill_menu()` now call this helper
  - Previously: same cost-calculation logic existed in both functions, a maintenance trap where edits to one could drift from the other

- DEATH CHALLENGER → DEATH'S APPRENTICE rename:
  - Internal key: `death_challenger` → `death_apprentice`
  - Display name: "Death Challenger" → "Death's Apprentice"
  - Files touched: `titles.py` (TITLE_DISPLAY, MASTERY_MAP, MASTERY_NAMES, MASTERY_DESC, comments, docstrings), `score.py` (TITLE_SCORE_VALUES), main file (`_dd_ap_cost` helper, rebound block, docstrings, comments)
  - Save-file compatibility: hard rename — existing saves with `death_challenger` in `hero.titles` will no longer recognize the title. Acceptable given playtest-stage development.
  - Old `Major_Versions/` and `Old .6 builds/` files left unchanged (frozen archive snapshots)

- DEATH'S APPRENTICE — psychic rebound damage:
  - Triggers inside `try_death_defier()` after the survival HP message
  - Guarded by `enemy is not None and "death_apprentice" in getattr(hero, "titles", set())`
  - Damage: `max(1, int(hero.max_hp * 0.20))`
  - Ignores defence — applied directly to `enemy.hp` (not through `apply_defence()`)
  - Tagged thematically as psychic damage in the mechanical readout
  - Does NOT interact with `psychic_exposed` bonus — the rebound is death acting through the apprentice, not a player attack, so existing psychic-vulnerability mechanics are sidestepped
  - Skipped if enemy.hp already <= 0 (no damage logged against an already-dead target)

- UNDERWORLD DIALOGUE on rebound:
  - Five variants stored as tuples of (setup, voice, enemy_reaction)
  - `random.choice()` picks one per trigger for variety across multiple Death Defier uses in a run
  - Tone: ancient, bureaucratic, indifferent — death as a bookkeeper
  - Sample voice lines: "This one is not yours to take." / "The accounting is incomplete." / "I would see what you become." / "Mark this one. The ledger is not yet closed." / "Not yet. I am still watching."
  - Enemy reaction lines render psychic damage as flavor: "a name has just been written down" / "something in their mind tears" / "the voice has touched something in them that was never meant to be touched"
  - Caps formatting (PRESENT, KNOWN, LOOKED) used for weight rather than volume — suggesting italics in a terminal context

- try_death_defier() signature extended:
  - New optional parameter: `enemy=None`
  - Three call sites updated to pass enemy: special-move death (line ~7103), basic-attack death (line ~7140), DoT death (line ~8910)
  - DoT case included intentionally — DoT was inflicted by an enemy, so the rebound still has a target
  - Debug invocation at line 2526 left without enemy arg (intentional — debug tests the survival logic in isolation)

- DOCSTRING CORRECTIONS:
  - `activate_death_defier()` docstring was stale — claimed AP costs of 1/2/0 (rank 1-2/3-4/5), but the code was actually 3/4/5 with -1 mastery discount
  - Updated to reflect the new 1/1/2/3/4 curve with full discount tables for all four player paths (Normal / Normal+DA / River / River+DA)
  - `MASTERY_DESC["death_apprentice"]` updated to describe both the AP discount AND the psychic rebound

- v0.6.10 IS A MINOR VERSION BUMP because no new player-facing systems were added — this is a balance + lore polish pass on existing Death Defier mechanics. Crafting (the next major feature) will likely push to v0.7.x.

---

## v0.6.09 — Merchant Shop, Title Polish, River Spirit Fix & Score Display
*May 2026 | main: ~12,150 lines | titles.py: ~340 lines | score.py: updated*

- NEW TITLE: True Jack of All Trades — breadth capstone:
  - Awarded when `all(hero.skill_ranks.get(s, 0) >= 2 for s in ["power_strike", "heal", "war_cry", "defence_break", "death_defier"])`
  - Added to `TITLE_DISPLAY` and `TITLE_BUFFS` in titles.py
  - Buffs: `{"max_hp": 5, "max_atk": 1, "min_atk": 1, "defence": 2, "max_ap": 1, "perm_special": 1, "berserk_bonus": 1}`
  - `check_true_jack_of_all_trades(hero)` function added between `check_breadth_titles` and `check_skill_mastery`
  - Idempotent — guards on `"true_jack_of_all_trades" in hero.titles` at top
  - Awarded via `award_title_with_buff()` for consistent buff display
  - Imported into main.py from titles
  - Called from `show_skill_tree()` after upgrade (alongside existing checks) and from `nob_interlude()` after rank-up

- TITLES.PY — `award_title_with_buff()` extended:
  - Previously handled `max_hp`, `defence`, `max_atk`/`min_atk`, `max_ap`
  - Added: `perm_special` (adrenaline) and `berserk_bonus`
  - Uses `getattr(hero, "perm_special", 0)` / `getattr(hero, "berserk_bonus", 0)` defaults to be safe on hero objects without those attributes set
  - Buff lines added: "+N Adrenaline" and "+N Berserk"

- ENDGAME TITLE BUFFS — Guardian and Dark Champion:
  - `TITLE_BUFFS["guardian"]`: `{"max_hp": 2, "defence": 2}` → `{"max_hp": 10, "defence": 4, "max_atk": 1, "min_atk": 1, "max_ap": 1}`
  - `TITLE_BUFFS["dark_champion"]`: `{"max_atk": 2, "min_atk": 2, "max_ap": 2}` → `{"max_hp": 5, "defence": 1, "max_atk": 4, "min_atk": 4, "max_ap": 4}`
  - Award sites unchanged — both still flow through `award_title_with_buff()` at the boss-victory scenes (main.py lines ~7895 and ~8267)

- REMOVED: divine_blessing and beast_gods_blessing:
  - Stripped from `TITLE_DISPLAY` (titles.py)
  - Stripped from `TITLE_BUFFS` (titles.py)
  - Stripped from `TITLE_SCORE_VALUES` (score.py)
  - Tier-3 comment header in `TITLE_SCORE_VALUES`: "hereditary blessings" → "breadth capstone"
  - Both were never referenced in any award call site — pure dead entries
  - Historical changelog entry in `_PATCH_NOTES` (v0.6.08 block) left untouched as historical record

- RIVER SPIRIT → DEATH DEFIER NAME/RANK FIX:
  - Bug 1: Name display checked `getattr(hero, "death_defier_river", False)` directly — flag stayed True after rank-up to preserve 0 AP cost, so name never updated
  - Bug 2: Survive-HP rank lookup pattern was `hero.skill_ranks.get("death_defier", 0) if not getattr(hero, "death_defier_river", False) else 1` — forced rank=1 forever for river-blessed heroes, making rank-up survive-HP changes invisible
  - Two helpers added in main.py just above `activate_death_defier`:
    - `_dd_display_as_river(hero)`: returns True only when `death_defier_river` AND `skill_ranks.get("death_defier", 0) == 0`
    - `_dd_effective_rank(hero)`: returns 1 for rank-0 starter blessing, actual rank once invested
  - Display sites updated (5 total): `apply_death_defier_save()` (~line 3561), `activate_death_defier()` (~3795), `Hero.show_combat_panel()` (~5689), `Hero.show_status()` (~5810), `skill_menu` Death Defier branch (~6395)
  - Activation flavour branch: was gated on `death_defier_river` (always-True) — now gated on `_dd_display_as_river(hero)`, so post-rank-up activation correctly falls through to good/evil/neutral path-aware flavour
  - PRESERVED: 0 AP cost (line ~3795) and -1 SP discount (line ~6225) still check `death_defier_river` directly — those persist past rank-up by design
  - Rank-up message in `show_skill_tree` ("The River Spirit's blessing evolves into Death Defier rank 1.") was already correct — left unchanged

- NOB INTERLUDE — TITLE CHECK FIX:
  - `nob_interlude()` mutated `warrior.skill_ranks[key]` directly without firing any title checks
  - Affected all five mastery titles: Brawl Master, Combat Medic, Charismatic Speaker, Armor Piercer, Death Challenger
  - Fix: added `check_skill_mastery(warrior, key)` and `check_true_jack_of_all_trades(warrior)` calls after the rank-up announcement
  - `check_jack_of_all_trades` and `check_breadth_titles` not called — Nob's eligibility filter requires existing rank > 0, so those rank-1 breadth checks would be no-ops; flagged in comment for future-proofing if Nob's rules ever change to teach new skills

- XP CURVE — LEVEL 1 → 2 RAISED:
  - `Warrior.__init__`: `self.xp_to_lvl = 10` → `self.xp_to_lvl = 15`
  - 1.75 scaling unchanged — new curve: 15, 26, 45, 78
  - Cumulative XP to hit level 5: 106 → 164 (+55%)
  - level_up() logic unchanged — only the starting bucket increased

- WALKING STAFF — atk_max LOWERED:
  - `walking_staff = Equipment(...atk_max=2...)` → `atk_max=1`
  - New range: 0 / 1 ATK, +1 DEF — was 0 / 2, +1 DEF
  - Rusted Sword (poor: 1-2 ATK, +rot proc) is now an unambiguous upgrade

- OVERSEER DIALOGUE — TEMPTATION REWRITE:
  - Removed: `"What you are feeling is sentiment. Sentiment is a luxury the arena does not permit."` (line ~7466)
  - Replaced with single narrative paragraph: `"Their voice settles into your bones, smooth and unhurried. Every word coaxes you toward agreement, as if compliance were the only natural answer."`
  - Surrounding choice prompt and good/evil branches unchanged
  - Iteration: drafted three versions (long Overseer-voiced, short narrative, longer hybrid) — short narrative chosen for tone and pacing

- SCORE DISPLAY — TOTAL DAMAGE PROMINENCE (score.py):
  - Combat Performance section: previously `_row(f"Damage Dealt ({raw_dmg_dealt})", f"+{dmg_score}{cap_dmg}")` — raw totals buried in parenthetical labels
  - New layout: two leading rows showing raw totals up front, divider line (`'·' * (width - 4)`), then weighted score contribution rows labeled with the weight multiplier (`Damage Dealt score (×0.5)`)
  - All other sections (Resources, Mastery, Luck, Subtotal, multiplier, Final Score, Rank) unchanged
  - Cap detection logic (`cap_dmg`, `cap_blk`) still applied to score-contribution rows, not raw rows

- FILE STRUCTURE:
  - `Journey_To_Winter_Haven_v_06_08.py` → `Old .6 builds/`
  - New file: `Journey_To_Winter_Haven_v_06_09.py`
  - `titles.py` updated (new title, removed blessings, extended `award_title_with_buff`, buffed Guardian/Dark Champion)
  - `score.py` updated (removed blessings, added True Jack to TITLE_SCORE_VALUES, score display rework)
  - `combat_log.py`, `monsters.py`, `gold.py`, `shared.py` unchanged

### Merchant Shop (added late in v0.6.09)

- NEW MODULE: `merchant.py` (~600 lines) — full implementation of the round 4-5 interlude shop:
  - Module-level config: `EQUIPMENT_RARITY_PRICES`, `POTION_PRICES`, `POTION_STOCK_COUNT`, `SELL_BACK_RATE`, `MERCHANT_VARIANT_CHANCE`
  - `MERCHANT_ARMORS` — list of (name, defence, max_hp, price) tuples for the 4 new fixed-tier basics
  - `MERCHANT_TRINKETS` — list of (name, defence, max_hp, atk_min, atk_max, max_ap_bonus, price) tuples for the 4 new fixed-stat basics
  - `CRAFTING_COMPONENT_NAMES` — set blocking sell-back of components (placeholder hint pointing at future crafter)
  - `NO_RESALE_NAMES` — set blocking boss drops, prologue Walking Staff, Frostpine Tonic from sale
  - `_find_main_module()` helper — robust main.py discovery via `__main__` then `sys.modules` scan; tolerates non-`__main__` import paths for testing
  - `_FACTORIES_CACHE` — lazy-built factory registry, scoped to first scene call
  - `_make_fixed_armor_factory()` / `_make_fixed_trinket_factory()` — closure builders, isolate Equipment construction from data tuples
  - `_build_factories()` — produces slot → list of (name, factory) registry; uses main's existing STATS dicts for weapon factories (no refactor of `make_loot`'s lambdas — parallel registry by design)
  - `_roll_weapon_variants()` — returns a list of rarities for a single weapon type. Normal always included; uncommon and rare are independent yes/no rolls per `MERCHANT_VARIANT_CHANCE`
  - `generate_merchant_stock()` — public entry; returns dict shape: `{"weapon_groups": [{"type_name", "variants": [...], "expanded"}], "armors": [{"item", "price", "sold"}], "trinkets": [...], "potions": {key: {"price", "stock"}}}`. Per-item `sold` flags live in the data structure rather than a parallel array
  - `merchant_scene(warrior)` — top-level loop; clears screen, generates stock, runs `_show_main_menu()` → parse input → dispatch loop. Handles "0" (leave), "S/s" (sell menu), and parsed (number, suffix) tuples for buy/toggle actions
  - `_show_main_menu()` — renders weapons (with parent rows + indented variants when expanded), armors, trinkets, potions. Returns `{code: (action_type, action_key)}` dict. Action types: `toggle_weapon`, `buy_weapon_variant`, `buy_armor`, `buy_trinket`, `buy_potion`. Codes are strings ("1", "1a", etc.) for uniform lookup
  - `_parse_menu_choice(raw)` — splits input into (number, suffix); accepts plain digits, digits+single-letter, returns None for everything else. Case-insensitive on suffix
  - `_buy_variant(warrior, variant_dict)` — unified buy handler for weapon variants, armors, and trinkets (all share `{"item", "price", "sold"}` shape). Confirm screen with `full_detail()`, gold deduction, inventory append, in-place `sold = True` flag flip
  - `_buy_potion()` — no confirm screen (potions are cheap and fast), stock decrement, gold deduction, `warrior.potions` increment
  - `_sell_back_menu()` — separate UI loop; lists unequipped non-blocked items with sell prices, components flagged "(crafting — see crafter)" and refused
  - `_sell_price()` — half of EQUIPMENT_RARITY_PRICES based on item.rarity, 1g floor
  - `_label_for_catalog()` — strips multi-line short_label() output for single-row display

- MENU UX — EXPANDABLE WEAPON VARIANTS:
  - Multi-variant weapons (2+ rarity tiers) render as a parent line with `[+]` (collapsed) or `[-]` (expanded) indicator and `(N of N variants)` hint (or `── ALL SOLD ──` if every variant is gone)
  - Single-variant weapons (normal only) render flat with full short_label and price, no expand step — clicking the parent number goes straight to `_buy_variant()`
  - Variant rows display indented (6-space prefix) with sub-letter codes: `1a`, `1b`, `1c`. Codes generated via `chr(ord('a') + var_idx)` so they match the parent number's position
  - Expand state lives on the weapon group dict (`group["expanded"]`); toggling is a one-line state flip, menu re-renders next loop iteration
  - Single visit means expand state doesn't need to persist across visits — fresh stock each merchant_scene call resets all expanded flags to False
  - Action map registers BOTH the parent code (e.g. "1") AND each variant code (e.g. "1a", "1b") when expanded, so a player can click the parent again to collapse OR click a sub-letter to buy without un-expanding first

- WEAPON VARIANT ROLLS (`merchant.MERCHANT_VARIANT_CHANCE`):
  - `{"uncommon": 0.50, "rare": 0.25}` — guaranteed normal listing per weapon type, independent yes/no rolls for higher tiers
  - POOR removed entirely from merchant pool
  - For each of 3 weapon types drawn per visit, the same weapon can appear at 1-3 rarity tiers
  - Possible outcomes per weapon type:
    - normal only:                  37.5% target
    - normal + uncommon:             37.5% target
    - normal + rare:                 12.5% target
    - normal + uncommon + rare:      12.5% target
  - Total weapon listings per visit:
    - Min 3 (every type rolls no/no)
    - Max 9 (every type rolls yes/yes)
    - Avg 5.25 (3 + 1.5 + 0.75)
  - 1000-roll empirical distribution: 35.3% normal-only, 39.3% normal+uncommon, 13.0% normal+rare, 12.4% all three (within target tolerance)
  - 100-visit empirical avg weapons/visit: 5.51 (target 5.25); observed range 3-8

- WEAPON POOL:
  - 5 items: Rusted Sword, Imp Trident, Goblin Dagger, Goblin Shortbow, Goblin War Blade
  - Javelina Tusk REMOVED — reclassified as crafting component
  - `random.sample(pool, k=3)` — guaranteed 3 distinct weapons per visit (no duplicates)

- NEW MERCHANT-ONLY ARMORS (`MERCHANT_ARMORS`):
  - All 4 are DEF-only with `max_hp=0` — crafted armors will provide HP
  - Copper Scale Vest: defence=1, 15g
  - Bronze Hauberk: defence=2, 30g
  - Iron Cuirass: defence=3, 50g
  - Frost-iron Cuirass: defence=4, 80g (rarity flagged "rare" for visual prestige despite no rolling)
  - Factory closures use Equipment with `rarity="normal"` (or "rare" for Frost-iron) and zero out non-relevant fields
  - `random.sample(pool, k=2)` — 2 distinct armors per visit

- NEW MERCHANT-ONLY TRINKETS (`MERCHANT_TRINKETS`):
  - All 4 are single-stat, no rarity variants
  - Stoneheart Pendant: max_hp=10, 25g
  - Tiger Fang: atk_min=2, atk_max=2, 30g
  - Stoneskin: defence=2, 25g (matches Bronze Hauberk DEF for slot-cost trade-off)
  - Spirit Crystal: max_ap_bonus=2, 30g (uses existing Equipment.max_ap_bonus field, applied via existing equip_item path)
  - `random.sample(pool, k=2)` — 2 distinct trinkets per visit
  - Drop trinkets (Charged Jagged Rock, Waterlogged Stone) untouched — keep rarity rolls and complex effects via `make_loot`

- NEW POTIONS (in main.py):
  - `cure_all` and `elixir` keys added to `Warrior.__init__`'s default potion dict
  - `potion_labels` display dict updated (display name "Cure-All Tonic", "Elixir")
  - `use_potion_menu()` extended with two new branches:
    - `cure_all`: clears `poison_active`/`poison_amount`/`poison_turns`/`poison_skip_first_tick`; clears `fire_stacks`/`burns`; clears `acid_stacks` list; clears `paralyzed` and `turn_stop`/`turn_stop_reason` IFF `turn_stop_reason == "paralyzed"` (preserves psychic-source stops); clears `blind_turns`/`blind_long`. Tracks list of cleared statuses for output line.
    - `elixir`: prints lead-in line, calls `heal_percent(hero, 0.50)` (which prints its own "+N HP" line), then `ap_percent(hero, 0.50)` returning recovered amount, then prints "+N AP" and current HP/AP totals
  - Both potions get `is_bonus` tracking and return value semantics matching antidote/burn_cream pattern
  - Debug potion menu (`_debug_potion_menu`): items 13 ("Cure-All Tonic") and 14 ("Elixir") added to POTION_LIST; "Add ALL potions x3" hotkey moved from 13 to 15

- ARENA_QUARTERS_INTERLUDE WIRED IN (main.py):
  - Menu line "5) Talk to merchant (wip)" → "5) Talk to merchant"
  - Handler: was 7 lines of placeholder dialogue; now 4 lines: clear, conditional `merchant_scene(warrior)` if not yet talked, second-visit "settled up" message, space(2)
  - `from merchant import merchant_scene` — local import inside the elif block (not at module top) to mirror the pattern shared.py and gold.py use; avoids circular-import risks
  - `merchant_stock` (local in interlude) holds the stock dict across choice iterations — `merchant_stock = merchant_scene(warrior, stock=merchant_stock)` rolls fresh on first call (stock=None) and reuses on subsequent calls. Sold items stay sold, potion counts persist. Re-roll exploit prevented, natural "leave and come back" workflow supported.

- SELL-BACK IMPLEMENTATION:
  - `_sell_back_menu(warrior)` — invoked from main menu choice "S" (case-insensitive)
  - Filter pipeline: walk `warrior.inventory`, exclude items present in any `warrior.equipment[slot]`, exclude items in `NO_RESALE_NAMES`
  - Components in the filtered list are still SHOWN (for player awareness) but flagged uncolored "(crafting — see crafter)" instead of price; selecting them shows the refusal flavor and loops
  - Confirmed sale flow: prompt with item label and price, confirm y/n, on yes: `warrior.gold += price` (NOT `total_gold_earned` — sell-back is repurposed wealth, not new earnings), `warrior.inventory.remove(item)`
  - Loop continues until player picks 0 or empty input — "Press Enter to go back" if no candidates

- ARMOR/ACCESSORY RECLASSIFICATION (no code change to drop tables):
  - Wolf Pelt, Dire Wolf Pelt — were equippable armor in v0.6.x, now treated as crafting components by the merchant logic (still drop, still equip if forced)
  - Poison Sac, Fire Sac, Acid Sac, Soul Pendant — were equippable accessories, now treated as crafting components by the merchant logic
  - Javelina Tusk — was a weapon drop, now reclassified
  - `make_loot` table in main.py UNCHANGED — these still mint with their original slot/stats. The reclassification is merchant-side only (sell-block + exclusion from merchant pool). Future crafter implementation will define their actual component behavior.

- TESTING:
  - Stock generation: 3 visits, varied rarity rolls and item picks, no duplicates within a visit
  - Distribution sanity: 2000 rolls vs target weights — within 2% tolerance
  - Purchase flow: gold deduction confirmed, `total_gold_earned` preserved, item lands in inventory, sold-flag set, second click on sold item shows refusal
  - Sell-back: bought-item resells at half-price (correct rounding), Wolf Pelt sell attempt refused with crafter message, lifetime gold preserved
  - Broke-player edge case: insufficient gold shows "need N more" inline label, purchase blocked
  - All tests run with `random.seed` for reproducibility

---

## v0.6.07 — Rot System, Weapon Identity Pass & Gold Overhaul
*May 2026 | main: ~11,600 lines | monsters.py: ~2,400 lines | gold.py: updated*

- NEW STATUS EFFECT: Rot — drains enemy/player max HP rather than current HP
  - Two variants: player-inflicted (Rusted Sword, flat stack drain) and enemy-inflicted (Brittle Skeleton / Chimera, percentage-based)
  - Player rot fields: `rot_max_hp_loss`, `rot_base_max_hp` added to `Hero.__init__`
  - Enemy rot fields: `rot_stacks_applied`, `rot_max_hp_loss` set dynamically on proc
  - `clear_rot(hero, restore_hp, source)` helper added — handles all clearing paths cleanly
  - Rot shown in combat HUD: `🟫 Rot: Max HP -X (base Y → current Z, cap %)`

- RUSTED SWORD REDESIGN:
  - Defence removed across all rarities (0 across the board)
  - Poison proc replaced with Rot proc
  - `RUSTED_SWORD_STATS` updated: `rot_chance`, `rot_stacks`, `rot_hp_per_stack` per rarity
  - poor: 15% / 1 stack / 1 HP | normal: 25% / 2 stacks / 1 HP | uncommon: 40% / 3 stacks / 1 HP
  - rare: 55% / 4 stacks / 2 HP | epic: 65% / 5 stacks / 3 HP | legendary: 75% / 6 stacks / 4 HP | mythril: 90% / 7 stacks / 5 HP
  - Cap: 30% of enemy max HP. Resets between fights
  - `Equipment.__init__` gains `rot_chance`, `rot_stacks`, `rot_hp_per_stack` params (default 0)
  - `stat_lines()` displays: `🟫 X% chance to rot (N stack(s), -Y max HP/stack)`
  - Combat proc block added after blind_chance check: applies stacks, prints drain message

- WALKING STAFF CHANGES:
  - Rarity: `poor` → `starter`
  - `atk_min`: 1 → 0 (can now whiff — makes the staff feel unreliable)
  - `starter` rarity added to `RARITY_ICONS` as empty string
  - `short_label()` and `full_detail()` updated: `starter` rarity skips icon and rarity word entirely
  - Displays as just "Walking Staff" with no prefix

- BRITTLE SKELETON SPECIAL — Rot Thrust:
  - Renamed from `brittle_skeleton_thrust` to `rot_thrust` in monsters.py
  - Old name kept as alias (`brittle_skeleton_thrust = rot_thrust`) for backwards compatibility
  - 50% proc chance on special use
  - Each proc: -20% of player current max HP, stacks, capped at 50% of `rot_base_max_hp`
  - Stronger variants get 2–3 special uses; proc chance stays the same
  - `CHIMERA_TIER1_POOL` updated to reference `rot_thrust`
  - `__all__` updated to export both `rot_thrust` and `brittle_skeleton_thrust`

- CHIMERA — ROT THRUST BORROWED MOVE:
  - When Chimera draws rot_thrust: proc chance 75%, cap 60% of player base max HP
  - Spawn flavour appends rot hint when rot_thrust is drawn
  - Defeat intervention: rot only cleared if `chimera.chimera_tier1.__name__ == "rot_thrust"`
  - `clear_all_status_effects` already calls `clear_rot(restore_hp=True)` — all other intervention paths covered

- ROT CLEARING RULES (wired in this version):
  - Regular rest → `reset_between_rounds` calls `clear_rot(restore_hp=False)` — max HP lifts, no heal
  - Long rest (rounds 4–5) → explicit `clear_rot(restore_hp=True)` before full heal
  - Patronus / win intervention → `clear_all_status_effects` covers it (restore_hp=True)
  - Chimera defeat intervention → conditional (only if rot_thrust drawn)
  - Rank 4+ First Aid → `clear_rot(restore_hp=False)` with heal penalty (see below)
  - Level up → does NOT clear rot; max HP stays reduced

- FIRST AID RANK 4 — ROT HEAL PENALTY:
  - Rot cleared before heal; `heal_penalty = rot_loss / rot_base_max_hp`
  - Effective heal: `0.40 * (1.0 - heal_penalty)`
  - Example: 40% rot loss → 24% effective heal instead of 40%
  - Message updated to show penalty percentage and effective heal rate
  - Status curing block moved before heal application so rot is cleared first

- FROSTPINE TONIC — ROT CLEAR (NO PENALTY):
  - `clear_rot(restore_hp=False, source="frostpine_tonic")` fires before heal
  - Max HP restored first so 40% heal calculates on full restored max HP
  - No heal penalty — unique item, handmade, one use only

- GOLD SYSTEM — VARIANT BONUS (gold.py):
  - `monster_lvl = getattr(enemy, "level", 1)`
  - `variant_bonus = max(0, (monster_lvl - 1) * 5)`
  - Hardened (lvl 2): +5g | Veteran (lvl 3): +10g | Elite (lvl 4+): +15g
  - Baked into `base_gold` so floor also reflects the variant
  - Breakdown line added: `+X gold (Veteran variant)`

- GOBLIN BOOKIE — PICKPOCKET TELL REMOVED (gold.py):
  - `print(wrap(f"(You didn't notice the {skim} gold...)"))` removed
  - Player now only sees "Something feels off but you can't quite place it."

- BUG FIX — RUN SCORE ON DEFEAT:
  - `warrior.show_all_game_stats()` (calls `display_run_score`) added to both defeat paths
  - DoT death path (line ~8593) and regular death path (line ~9344) both updated
  - Player now sees full performance rating and rank on loss, not just on win

---

## v0.6.05 — shared.py Architecture & Input Standardisation
*May 4, 2026 | main: ~11,100 lines | shared.py: new | monsters.py: ~2,300 lines*

- ARCHITECTURE: shared.py extracted from main file
  - Constants moved: `WIDTH`, `SPECIAL_MOVE_NAMES`, `DEFENCE_BREAK_STATS`
  - Utility functions moved: `wrap`, `space`, `clear_screen`, `continue_text`, `show_health`, `hp_bar`
  - Block functions moved: `weak_defensive_block`, `solid_defensive_block`, `strong_defensive_block`, `full_defensive_block`
  - Combat helpers moved: `lvl_bonus`, `ap_from_hp`, `scaled_xp_step`, `monster_math_breakdown`, `monster_deal_damage`, `get_ap_inflation`, `inflated_ap_cost`, `apply_turn_stop`, `try_death_defier`
  - Exception classes moved: `RestartException`, `QuickCombatException`, `GameOverException`
  - Base classes moved: `Equipment`, `Creator`, `Monster`
  - Main file imports all via `from shared import (...)`
- NEW: `show_end_summary(warrior)` — end-of-run summary screen
  - Displays potions remaining (labelled), equipped gear by slot (weapon/armor/accessory/trinket), and unequipped inventory (bag items)
  - Excludes equipped items from bag list to avoid duplication
- INPUT STANDARDISATION: all yes/no prompts game-wide → y/n
  - Confirmation prompts, equip offers, dialogue choices, tournament queries, weapon core equip, combat log prompts
  - `"Incorrect input, please enter yes or no."` → `"Incorrect input, please enter y or n."`
- BUG FIX: stat cap at level-up — `stat_cap = min(2, hero.stat_points)` replaces flat `stat_cap = 2`
  - Prevents level 5's 5-point windfall from being fully dumped into one stat

---

## v0.6.04 — Monster Balance Pass & Prologue Expansion
*May 4, 2026 | main: ~13,300 lines | monsters.py: ~2,300 lines*

- BALANCE: Tier 2 monster stat buff (+5 HP, +1 ATK, +1 DEF, +1 AP, ~+10% XP)
  - Red Slime: 16→21 HP, 2-4→3-5 ATK, 1→2 DEF, 2→3 AP, 16→18 XP
  - Noob Ghost: 16→21 HP, 3-6→4-7 ATK, 0→1 DEF, 2→3 AP, 13→15 XP
  - Goblin Archer: 15→20 HP, 3-5→4-6 ATK, 1→2 DEF, 2→3 AP, 17→19 XP
  - Dire Wolf Pup: 16→21 HP, 4-6→5-7 ATK, 3→4 DEF, 2→3 AP, 19→21 XP
  - Javelina: 18→23 HP, 3-6→4-7 ATK, 2→3 DEF, 2→3 AP, 18→20 XP
- BALANCE: Tier 3 monster stat buff (+10 HP, +2 ATK, +2 DEF, +2 AP, ~+20% XP)
  - Wolf Pup Rider: 21→31 HP, 3-7→5-9 ATK, 3→5 DEF, 2→4 AP, 23→28 XP
  - Hydra Hatchling: 25→35 HP, 3-6→5-8 ATK, 3→5 DEF, 2→4 AP, 27→33 XP
  - Flayed One: 23→33 HP, 4-6→6-8 ATK, 2→4 DEF, 2→4 AP, 25→30 XP
  - Drowned One: 27→37 HP, 5-8→7-10 ATK, 3→5 DEF, 3→5 AP, 30→36 XP
  - Goblin Warrior: 30→40 HP, 5-9→7-11 ATK, 4→6 DEF, 3→5 AP, 33→40 XP
- BALANCE: Hardened level scaling doubled
  - HP: +5/level → +10/level; ATK: +1/level → +2/level; DEF: +1/level → +2/level
- BALANCE: Hardened DoT values increased
  - Poison (Slime): 1-2 dmg/2 turns → 3-4 dmg/4 turns
  - Bleed (Savage Slash): 4-6 dmg/3 turns → 6-8 dmg/5 turns
  - Psychic Shred debuff duration: 3 turns → 4 turns
  - Psychic Drown: damage table 3/4/5 per stack → 5/6/7 per stack; duration 4 turns → 6 turns
  - Acid Spit (Hydra): 3 turn duration → 4 turn duration
- STORY: Aldric sendoff — flicker of concern added before "Eyes only" line; clasp rewritten from backslap to held-shoulder moment
- STORY: Forest journey — Day 1 adds eerie animal silence beat; Day 3 added (empty road, slow dread); Day 4 rewritten around loneliness; arrival rewritten with distant city lights and overnight camp
- STORY: Elwyn rename — Elwin → Elwyn throughout; farewell rewritten as warm hug + cheek kiss; "Stay out of trouble. And don't dawdle." moved to Elwyn's line; Aldric's section cleaned
- BUG FIX: Bo tackle path — was granting only heal potion despite dialogue implying two; corrected to heal only with matching dialogue (tree-branch path correctly grants both)
- BUG FIX: Skill investment loop — stale `input("Press Enter...")` removed from `show_skill_tree()`; back-to-back stat investment now works as intended

---

## v0.6.03 — Monster Extraction & Dev Shortcut Refactor
*April 30, 2026 | main: ~11,090 lines | monsters.py: ~2,300 lines*

- ARCHITECTURE: monsters.py extracted from main file
  - 18 classes: Green_Slime, Young_Goblin, Goblin_Archer, Goblin_Warrior, Brittle_Skeleton, Imp, Wolf_Pup, Dire_Wolf_Pup, Red_Slime, Fallen_Warrior, Noob_Ghost, Wolf_Pup_Rider, Javelina, Hydra_Hatchling, Flayed_One, Drowned_One, Young_Chimera, Patronus
  - 51 functions moved covering all special moves, AI, psychic/drown/chimera/patronus systems, and encounter helpers
  - 8 module-level constants: MONSTER_TYPES, TIER4_BOSSES, LEVEL_TITLES, CHIMERA_TIER1/2/3_POOL, CHIMERA_ELEMENTS, HEAL_PERCENTS_ENEMY
  - Main file: 13,255 → 11,090 lines (–2,175)
  - Explicit `__all__` list resolves Python 3.13 partial-module circular-import edge case
- DEV SHORTCUTS: `_try_dev_shortcut(raw)` helper centralises `q` (restart), `c/combat` (arena jump), `debug` (debug menu) — now works at every story prompt via both `continue_text()` and `check()`
- BUG FIX: restart now replaces `GAME_WARRIOR` with fresh `Warrior()` and clears `COMBAT_LOG` — previously leaked player name across restart causing name gate to fail
- STORY: Opening framing block added before name prompt — cold morning, eastern gate, ash drift from Frostveil Peak
- STORY: Aldric rewritten for scout mission — "Eyes only. You don't go inside. You don't pick a fight." Scene split across two screens
- STORY: Forest travel expanded from one afternoon to four-day trek with daily clear_screen beats
- LORE: Frostveil Peak canonised as semi-active volcano; ash etymology layered (ash trees + volcanic drift); LORE.md updated
- GAMEPLAY: Frostpine Tonic now replaces starting heal potion; lampshaded in-fiction

---

## v0.6.02 — Player Name Prompt & Re-prompt Gating
*April 30, 2026 | ~13,260 lines*

- NEW: `get_name_input()` called at top of `ashenveil_prologue()` — player names character at very first beat; defaults to "Umbra" on empty input
- UPDATED: hardcoded "You are Umbra" → `f"You are {warrior.name}"` in Ash Hall paragraph
- GATED: 5 legacy `get_name_input()` call sites wrapped in `if GAME_WARRIOR.name == "warrior":` — NPC dialogue still plays rhetorically, input prompt skipped when name already set
- CLEANUP: `get_name_input()` dead `while True:` loop and unused `global` declaration removed

---

## v0.6.01 — Ashenveil Prologue & Frostpine Tonic
*April 2026 | ~13,250 lines*

- NEW: `ashenveil_prologue()` — pre-arena backstory function with three sub-scenes: Aldric sendoff, Elwyn sendoff, Ashen Frost Forest travel
- NEW: Aldric sendoff scene — quest parchment handoff at city gate, shoulder clap, market-district girl tease, walks away mid-conversation
- NEW: Elwyn sendoff scene — presses small flask into player's hand, quiet farewell, no goodbye, walks back to house
- NEW: Frostpine Tonic — restores 40% max HP + clears all status effects + restores 2 AP; one use only; locked from shops and loot tables; unique item
- NEW: Ashen Frost Forest travel narrative — atmospheric single-afternoon walk in this version
- UPDATED: `intro_story_inner()` opening text flows from prologue arrival instead of old "wandering lost" framing

---

# ── v5 ERA — Arena & Systems Overhaul ───────────────────────────────────────

## v5.13 — Flayed One Bug Fix & Boss Balance
*April 2026 | ~12,800 lines*

- BUG FIX: `psychic_shred()` was applying a separate 25–50% ATK/DEF reduction on top of the charge system when called by Flayed One — reduced player to ATK 1–1 and DEF 0 in some scenarios; now damage-only when called by Flayed One; all stat drain handled exclusively by `_flayed_charge_tick()`; Chimera retains percentage-debuff version
- BALANCE: Chimera `psychic_shred` debuff reduced from 60% to flat 30% ATK/DEF for 4 turns — 60% interacted badly with the DEF-below-zero 10% damage bonus, creating a death spiral
- NEW: Chimera Oppressive Presence — if `psychic_shred` rolled as `chimera_tier3` at spawn, player begins fight at –2 ATK / –2 DEF; restored after fight via `_restore_primordial_stats()`
- VERIFIED: Patronus 30% passive damage reduction tied to `shield_equipped` — confirmed working, documented for clarity

---

## v5.12 — Chimera Carapace Passive & Bug Fixes
*April 2026 | ~13,038 lines*

- NEW: `chimera_atk_reduction` float in `Young_Chimera.__init__` — set to `0.20` always, bumped to `0.35` if `chimera_tier3 is psychic_shred`
- `monster_deal_damage`: reads `getattr(defender, "chimera_atk_reduction", 0.0)` before defence calc; reduces `raw_roll` to `max(1, int(raw_roll * (1.0 - reduction)))`; all non-Chimera enemies unaffected
- Chimera spawn flavour appends "🩸 Its hide pulses with corrupted energy — your strikes feel dulled..." when Flayed draw active
- BUG FIX: Charismatic Speaker ATK drift — `warrior.charismatic_speaker_bonus` now stored on apply; `reset_between_rounds` reads it back; was silently inflating ATK by +1 per fight at `max_atk ≥ 14`
- BUG FIX: Patronus DEF restore — `battle(warrior, patronus)` wrapped in `try/finally`; `_restore_patronus_def()` now guaranteed to fire even on unhandled exception
- WORD WRAP: Five bare `print()` calls in `arena_quarters_interlude` now use `wrap()` — were breaking layout on narrow tablet viewports

---

## v5.11 — Chimera Move Overhaul & Title System Expansion
*April 2026 | ~12,650 lines*

- OVERHAUL: Chimera borrowed move system fully rebuilt
  - Replaced broken `chimera_double`/`chimera_extra_turns` pattern with `hasattr(enemy, "chimera_tier1")` identity checks and dedicated helpers
  - `chimera_triple()` added — triples flat damage values on tier 1 moves (Brittle Thrust, Imp Sneak Attack)
  - All 13 borrowed moves now scale correctly with Chimera ATK: Poison Spit, Fire Spit, Goblin Cheap Shot, Wolf Pup Bite, Impact Bite, Devouring Bite, Ghost Life Leech, Paralyzing Shot, Blinding Charge, Savage Slash, Hydra Acid Spit, Psychic Shred, Psychic Drown
  - Savage Slash: `is_chimera` check fixed; bleed 6–10 for 3 turns now fires correctly
  - Hydra Acid Spit: `multiplier: 2` key added; tick handler reads it for 6–10/tick; DEF erosion -2 per hit (was -1)
  - Psychic Shred/Drown: `is_chimera` checks fixed; debuff % doubles and duration extends +1 correctly
- NEW: `chimera_combo_bonus` tiered by pool — tier 1: 2–5, tier 2: 5–10, tier 3: 8–14; pure damage tier 1 moves skip combo follow-up
- NEW: Blind — First Aid rank 2+ shows cure prompt during blind turns (same pattern as paralysis)
- CHANGE: Psychic debuffs removed from First Aid rank 5 clear — now uncleansable mid-combat by any demo-accessible skill; still clears in `reset_between_rounds`
- BALANCE: Skill costs rebalanced — Defence Break: 1/2/3/4/4 SP; Death Defier: 2/3/3/4/5 SP (was 2/2/3/4/5)
- NEW: Five skill mastery titles (rank 5, full game only)
  - Brawl Master (Power Strike 5): +2 min/max ATK permanently
  - Combat Medic (First Aid 5): passive 10% max HP regen end of each player turn
  - Charismatic Speaker (War Cry 5): +2 ATK for entire fight, stripped in `reset_between_rounds`
  - Armor Piercer (Defence Break 5): basic attacks reduce enemy DEF by 1 per hit
  - Death Challenger (Death Defier 5): Death Defier costs 1 less AP (floor 1)
- NEW: Two skill breadth titles (demo-reachable)
  - Chinker: 4th skill is Defence Break → +1 ATK
  - Death Delver: 4th skill is Death Defier → +5 Max HP
  - `check_breadth_titles(hero, skill_key)` replaces old separate functions; both always awarded regardless of build order
- NEW: `check_skill_mastery()` in `titles.py` — fires after every skill upgrade, awards mastery title if skill just hit rank 5

---

## v5.09 — Polish & Systems Pass
*April 2026 | ~12,365 lines*

- REFACTOR: `offer_loot()` helper centralised — all three drop points (main kill, DoT kill, Fallen Warrior) now show full stat card and immediate equip prompt with current slot comparison
- CHANGE: Charged Jagged Rock moved from accessory to trinket slot — can now coexist with Waterlogged Stone
- OVERHAUL: Charged Jagged Rock rebuilt with pool-based charge system, per-rarity charge cap, live HUD charge bar using rarity colours
- NEW: Death Defier dialogue is path-aware — River Spirit prayer (good path), Beast Gods chant (evil path), neutral otherwise
- NEW: `show_run_score()` on demo end screen — grand total damage breakdown split by basic, special, and DoT
- NEW: Debug title grant menu added
- FIX: Level-up stat cap scales with points available — double level-up correctly allows two points per category
- BUG FIX: `dd_name` scope bug (UnboundLocalError on Death Defier available state) resolved
- BUG FIX: Chimera tier 5 special never firing — fixed
- BUG FIX: Fallen Warrior XP not granted via `animate_xp_results` — fixed

---

## v5.08 — Moral Choice & Final Bosses
*April 2026 | ~12,000 lines*

- NEW: `fallen_warrior_moral_choice()` — Fallen Warrior death scene with Beast God intervention
  - Crush essence (evil) vs return essence (good) — locks player path permanently
  - Good path → `chimera_fight()` (true final boss)
  - Evil path → `patronus_fight()` (gated behind choice)
- OVERHAUL: Chimera rebuilt as true final boss — 80 HP / DEF 8 / ATK 14–18, charge-based AI, Primordial Surge as active move; full cinematic entry with heal + 2 temp AP + status clear
- OVERHAUL: Patronus fight properly gated behind evil moral choice
- NEW: Tainted Blade — corrupts Weapon Core in place on evil path (Duskbringer or Destiny Destroyer)
- NEW: Divine intervention threshold raised to 4 cycles for both boss fights
- NEW: Detailed round-by-round combat log — attack names, damage dealt/blocked, per-effect DoT sources

---

## v5.07 — Patronus Build
*April 2026 | ~11,000 lines*

- NEW: Patronus fully implemented as evil path final boss
  - Stats: 85 HP (+6 shield = 91 effective), DEF 4 (+6 shield effective), ATK 5–9, AP 7
  - Moveset: Double Strike R5, War Cry R5, Power Charge combo, First Aid (random rank), Defence Break (random rank)
  - Desperation scaling: 50/60/75/90% special chance at HP thresholds
  - Death Defier revives at 30% HP with shield stripped
  - Cycle-based Beast Gods intervention after 3 full cycles
- OVERHAUL: Chimera AI — strict special/rest alternation, 25% basic feint on special turns, `combat_cycles` tracker added (reused by Patronus)

---

## v5.06 — Chimera Overhaul & Defence Break Skill
*April 2026 | ~10,000 lines*

- BALANCE: Chimera stats updated — HP 75, ATK 7–12, DEF 6, AP 7
- OVERHAUL: Chimera move selection — weighted pool with turn-count escalation, last-used penalty, AP filtering
- NEW: Primordial Surge — signature breath attack; 3 charges, no recharge, rest-turn only; permanent stat degradation per charge
- NEW: Defence Break skill fully built — SKILL_DEFS entry, combat function, tick, `_award_defence_break()` wired into both Fallen Warrior kill paths
- RENAME: River Spirit renamed from Death Defier on the good path
- CHANGE: Goblin Shortbow replaces Paralyzing Arrow as weapon drop
- CHANGE: Boss drops given fixed stats — no rarity variance

---

## v5.05 — Bug Fixes & Skill System Upgrade
*April 2026*

- BUG FIX: `import math` crash in `player_basic_attack` — local import was shadowing module-level import
- BUG FIX: Charged Jagged Rock stale stats on hardened enemies — fixed
- CHANGE: All four skills capped at rank 5
- OVERHAUL: SKILL_DEFS upgraded with `rank_descs` dict and `tier2_name` field per skill
- NEW: `get_skill_desc()` helper — sliding two-rank lookahead window; tier 2 locked hint shown at rank 5

---

## v5.04 — Goblin Warrior (Tier 3)
*April 2026 | ~9,400 lines*

- NEW: Goblin Warrior — 30 HP, 5–9 ATK, DEF 4, AP 3; completes goblin tier ladder
- NEW: Savage Slash special — 33% independent proc after basic attack; bonus damage equal to half the basic roll (bypasses defence); applies 2 bleed stacks
- NEW: `warrior_bleed_dots` stack system — separate from Javelina tusk bleed
- NEW: Goblin War Blade weapon drop — per-rarity bleed scaling

---

## v5.03 — Drowned One, Waterlogged Stone & Inventory Overhaul
*April 2026 | ~9,100 lines*

- NEW: Drowned One — Tier 3, 27 HP, 5–8 ATK, DEF 3, AP 3
- NEW: Psychic Drown special — inflates all skill AP costs +1 per stack (max 3); flat true damage punishment if player can't afford any skill
- NEW: Waterlogged Stone trinket — absorbs 1 charge per enemy special; player spends turn to release and restore AP; persists between rounds
- NEW: Trinket equipment slot added to Hero
- NEW: `Equipment.full_detail()` loot card method
- NEW: `inventory_menu` inspect commands — `i#`, `iweapon`, etc.
- NEW: `_stone_usable()` helper wires stone into both rest menus dynamically

---

## v5.02 — Flayed One & Psychic Shred
*April 2026 | ~8,900 lines*

- NEW: Flayed One — Tier 3, 23 HP, 4–6 ATK, DEF 2, AP 2
- NEW: Psychic Shred special — 25% ATK+DEF reduction (30% hardened), 2-turn duration, stacks to 50%/60% on second hit, 90% ceiling, max 3 uses per fight
- NEW: Charged Jagged Rock accessory — Flayed One drop; ATK+DEF debuff proc
- OVERHAUL: `show_combat_stats()` debuff section fully rewritten — all active debuffs shown with tactical detail including pending tags and before/after values

---

## v5.01 — Title System & Fallen Warrior Desperation
*April 2026 | ~8,700 lines*

- ARCHITECTURE: Title system extracted to `titles.py` — first module split since `combat_log.py`
- NEW: `active_title` attribute added to Hero; titles carry display names via `TITLE_DISPLAY`
- NEW: Jack of All Trades title — unlocks when Power Strike, First Aid, and War Cry all reach rank 1; grants +1 to HP/ATK/DEF/AP
- NEW: `_switch_title_menu()` added to rest menu when 2+ titles owned
- OVERHAUL: Fallen Warrior desperation system — Defence Warp trigger chance scales with HP thresholds (10/25/50/75%) via `fallen_warp_should_trigger()`; replaces flat 33% roll; guaranteed 1-turn cooldown after each trigger

---

# ── v4 ERA — Loot System, Classes & Combat Foundation ───────────────────────

## v4.27 — Loot System Complete, Acid Sac Redesign
*April 2026 | ~8,700 lines*

- Acid Sac redesigned — poor: 3 dmg/1 turn/no DEF erosion; normal: 3 dmg/2 turns/-1 DEF; uncommon: 4 dmg/2 turns/-2 DEF; DEF restores after 2 turns; reapplying resets clock
- `element_erosion` added as proper Equipment parameter
- Hydra Hatchling acid tick bumped from 2–4 to flat 3–5 per tick
- All three combat log yes/no prompts now loop on invalid input
- Fallen Warrior HP raised to 60, AP raised to 5

---

## v4.26 — Debug Menu Overhaul
*April 2026*

- Debug menu Loot Manager — unified Give Loot and Equip Loot into one sub-menu: Give to Inventory, Equip Directly, Unequip Slot
- Loot Manager shows current equipped gear and live stats at top on every pass
- Debug Potion Menu — all 12 potion types, add any quantity, quick fill adds ×3 of everything
- Restore AP debug option added
- Level-up debug grants all levels silently in one pass
- Fallen Warrior defence lowered from 5 → 4

---

## v4.25 — Polish Pass
*April 2026*

- Acid Sac turn scaling fixed to match Poison and Fire Sac
- Quarters interlude spend points option hidden if no unspent points available
- Duplicate combat log option removed from quarters interlude menu

---

## v4.24 — Loot Key Audit
*March 2026*

- Javelina loot table key corrected from "javelina" to "Javelina" — Tusk was silently not dropping
- Full audit of all 14 monster names against loot table keys confirmed

---

## v4.23 — Weapon Core, Bug Pass & Reset Fixes
*March 2026*

- Weapon Core split into Defensive and Offensive forms; player chooses permanently on drop
- `burn_cream` now clears `hero.burns` list — burn DoT was continuing after potion use
- Level-up jackpot loop fixed — hardcoded `range(2)` changed to `range(num_p1_rolls)`
- `ALLOW_MONSTER_SELECT` declared at module level — was potential NameError
- Duplicate `simple_trainer_reaction()` removed — second definition was shadowing the correct one
- Chimera Scale equip now routes through `equip_item()` — direct assignment was giving double defence stats
- `weight_to_tier()` given fallback return 1 — was returning None silently
- `reset_between_rounds()` now clears acid, paralyze, and bleed between rounds

---

## v4.22 — Hidden Boss & Paralyze Overhaul
*March 2026*

- Paralyze rebuilt as true multi-turn lockdown; `chain_guard` and `post_paralyze_guard` added
- First Aid R4+ gives player choice during paralyze: cure and act, or struggle
- Young Chimera hidden boss added — random element on spawn; divine intervention at 5+ turns survived
- `chimera_fight()` wrapper added; turn survival tracked via `enemy.turns_survived`
- Player can view combat log on death
- Nob NPC increases one ranked skill

---

## v4.21 / v4.21.5 — Class Refactor & Combat Log Module
*March 2026*

- `combat_log.py` extracted as first separate module
- Hero stripped to universal base class; Warrior-specific systems moved to Warrior subclass
- Full combat log wired into `battle_inner()` — turn headers, choices, actions, DoT, death all logged
- Combat log accessible from all five exit points and debug menu

---

## v4.20.3 — First Aid Rename & HUD Fix
*March 2026*

- Skill "Heal" renamed to "First Aid" throughout; max rank reduced from 10 to 5
- Default player name changed from "Adventurer" to "Umbra"
- HUD gap between HP bar and berserk meter fixed

---

## v4.20.2 — Combat HUD Redesign
*March 2026*

- Combat HUD redesigned to two-column layout
- `arena_quarters_interlude` now has Inventory & Equipment option
- Both rest periods allow equipping between rounds

---

## v4.20.1 — Multi-dot Sacs
*March 2026*

- `element_max_dots` added to Equipment class
- Multi-dot sacs added — rare+ can apply multiple independent stacks up to cap
- `collect_dot_ticks` processes `poison_dots` list for extra poison ticks

---

## v4.19.3 — Equipment Routing & Loot Expansion
*2025 | ~7,460 lines*

- `equip_item()` and `unequip_item()` added — all equipment routing now goes through proper handlers
- Goblin Archer loot added (Paralyzing Arrow), Dire Wolf Pup loot added (Dire Wolf Pelt)
- `collect_dot_ticks()` updated with `is_player` flag
- Elem tags now show stack count e.g. "Burn stack 2/2!" for rare+ sacs

---

## v4.16 — Weapon vs Accessory Attack Split
*2025 | ~7,130 lines*

- `player_basic_attack()` split via `use_accessory` parameter — weapon attack vs accessory attack now handled cleanly and separately

---

## v4.15 — Round Number & Loot Scaling
*2025 | ~7,100 lines*

- `round_num` parameter added throughout — drop quality now scales dynamically with round progression
- `monster_level_for_round()` added — stronger monster variants appear in later rounds

---

## v4.14 — Monster Loot Expansion
*2025 | ~7,090 lines*

- Wolf Pup (Wolf Pelt), Brittle Skeleton (Rusted Sword), Imp (Imp Trident), Young Goblin (Goblin Dagger) loot entries added
- `proc_chance` and `blind_chance` added as Equipment parameters

---

## v4.12–v4.13 — Equipment Class & First Loot Drops
*2025 | ~6,840–6,920 lines*

- Equipment class introduced — weapons, armor, and accessories with rarity scaling
- `make_loot()` and `roll_rarity()` added — first working loot drop system
- Rarity ladder extended to 6 tiers: poor → normal → uncommon → rare → epic → legendary
- Green Slime (Poison Sac), Red Slime (Fire Sac), Hydra Hatchling (Acid Sac) loot added

---

## v4.11 — Combat Function Extraction
*2025 | ~6,710 lines*

- `battle()` and `battle_inner()` fully separated
- `collect_dot_ticks()` and `player_basic_attack()` extracted as standalone functions
- Codebase restructured in preparation for the loot system

---

# ── EARLY ERA — Prototype & Foundation ──────────────────────────────────────

## v3.15 — War Cry, First Aid & Debug Skill Editor
*2025 | ~5,400 lines*

- War Cry and First Aid added as rankable skills
- Blind damage multiplier implemented
- Debug skill editor added

---

## v3.12–v3.13 — Skill Tree, Power Strike & Death Defier
*2025 | ~4,800–4,920 lines*

- Power Strike fully implemented with rank scaling and AP costs
- Skill tree and `spend_points_menu()` added
- Death Defier and `activate_death_defier()` added
- `GameOverException`, `reset_between_rounds()`, War Cry tick system added
- Arena trainer stat point scene and goblin bookie payout added

---

## v3.2–v3.4 — Full Monster Roster
*2025 | ~4,150 lines*

- Full Tier 1 and Tier 2 monster roster finalised — 12 monsters all with unique special moves
- Berserk meter in place

---

## v0.144 — Turn Stop System & New Monster Moves
*2025 | ~3,650 lines*

- Goblin Archer, Wolf Pup Rider, Javelina, Brittle Skeleton added
- `apply_turn_stop()` and `resolve_player_turn_stop()` introduced — paralyze/stun foundation
- `show_health()` helper added; full and partial block flavour text functions added

---

## v0.143 — Warrior Subclass & Tier 2 Monsters Begin
*2024–2025 | ~3,430–3,490 lines*

- Warrior subclass split from Hero — first dedicated player class
- Ghost / Noob Ghost, Wolf Pup Rider, Red Slime added; Tier 2 monster work begins

---

## v0.141–v0.142 — Monster Expansion & Berserk Refinements
*2024 | ~3,200–3,400 lines*

- Monster roster expanding with differentiated names
- Berserk system refinements; potion and level-up menus stabilised; poison status in place

---

## v0.136 — Berserk Meter, Poison & Name Input
*2024 | ~2,930 lines*

- Berserk meter UI introduced; poison status effect added
- `get_name_input()` added — player can name their character
- Level-up menu and potion menu formalised

---

## v0.12 — Rage System & Developer Shortcuts
*2024 | ~1,920 lines*

- Rage system implemented — HP-based tiers at 75%/50%/25%/10% with escalating bonus damage
- Berserk mode introduced as rage peak state
- Rest mechanic added between rounds
- Universal developer shortcuts: `q` to restart, `c` to jump to arena
- `RestartException`, `QuickCombatException`, `GAME_WARRIOR` global all introduced

---

## v0.09 — Combat Stability Pass
*2023–2024 | ~725 lines*

- Double damage print bug, alternating turn logic, NoneType attacker crash, bloodlust stacking all fixed
- Monster weights adjusted; combat loop structure cleaned up

---

## v0.08 — First Structured Arena Combat
*2024 | ~660–715 lines*

- First structured arena combat loop
- Creator → Monster / Hero class hierarchy established
- Monster roster: Slime, Goblin, Skeleton, Wolf, Fallen Hero
- Basic attack rolls, XP, gold, defence, essence tracking; potions; three-item inventory
- Foundation that everything since has been built on

---

## October 2, 2025 — Stable Checkpoint
*763 lines*

- Near-identical to September build — saved as stable checkpoint before major architecture push

---

## September 17, 2025 — Story Text & Utility Functions
*763 lines*

- `clear_screen()`, `continue_text()`, and `check()` introduced — utility functions still present today
- `main()` function added; tournament intro story appears for the first time
- `textwrap` used for the first time for readable story text

---

## August 6, 2025 — Earliest Surviving Build
*590 lines*

- Creator base class exists but Skeleton is just `pass` — OOP still being learned
- Combat is standalone functions: `slime_battle()`, `skelton_battle()`, `ghost_battle()`
- Global variables track gold, HP, and essence — no class-based state management yet
- Comments show active learning throughout
- This is where Journey to Winter Haven began
