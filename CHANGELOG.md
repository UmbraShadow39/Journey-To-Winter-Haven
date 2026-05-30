# Journey to Winter Haven — Changelog

A high-level summary of major changes across the project's full development history.
For full version-by-version detail see [DEVLOG.md](DEVLOG.md).

**Platform roadmap:** itch.io terminal demo (May 2026) → Pygame port (Dec 2026) → Godot/Steam Early Access (May 2027)

---

---

## v0.6.21 — Bug Fix Pass: Dev Shortcut Safety, Equipment Display, Score Flags, Primordial Surge Exploit
*May 2026*

Five HIGH-severity fixes surfaced by a pre-push code audit. No new features — all five are correctness or safety fixes.

**Monster-select dev shortcut moved behind the `!` prefix.** The global `input()` override triggered a debug monster battle on bare `m` or `monster` typed at any of the ~200 input prompts in the game — yes/no confirms, Press-Enter pauses, even the merchant's "equip now?" prompt. A fat-finger could pull the player into a debug fight mid-session. The v0.6.19 patch added `!`-prefix protection to every other dev shortcut but missed this one. Now `!m` / `!monster` (case-insensitive) emit the existing `__MONSTER_SELECT__` sentinel — which `handle_monster_select_shortcut` resolves combat-aware (swap enemy mid-fight vs. start a debug fight out of combat) — and bare `m` / `monster` / player names pass through as ordinary text. The override no longer calls `battle()` directly, which was wrong anyway since it had no idea whether it was mid-combat. Docstrings for `continue_text`, `check`, and `_try_dev_shortcut` updated to match.

**Equipment lists fixed to use the v0.6.16 slot keys.** Four display loops still iterated the pre-v0.6.16 keys `("weapon", "armor", ...)` instead of the current dict keys `(main_hand, off_hand, armor, helm, cape, ...)`. Weapons, shields, helms, and capes had been invisible in every equipment display since v0.6.16. The most visible was `show_end_summary` — the win/loss screen every player sees, where your weapon simply never appeared. Also fixed: the combat HUD gear line (`show_game_stats`), the detailed stats screen (`show_combat_stats`), and the debug-menu unequip tool (whose slot map is now generated from the slot list so it can't drift again). This pairs with the v0.6.20 dual-wield and set-bonus blocks — between them every equipped item is now visible.

**Berserk / Death Defier score bonuses no longer double-count across fights.** `record_fight_score` awarded +20 for berserk and +50 for Death Defier by reading `berserk_used` / `death_defier_used`. But those flags carry across fights by design — `berserk_used` gates the natural low-HP re-trigger until HP recovers above 20%, and `death_defier_used` only resets at the full-rest interlude. So once either fired, every subsequent fight that round silently collected the bonus again. Added dedicated per-fight flags (`berserk_used_this_fight` / `death_defier_used_this_fight`), set at every trigger site, reset at the start of each fight in `battle_inner`, and read by the score system. The run-wide flags keep their original gating behaviour untouched — only the score read changed.

**Primordial Surge stat restore no longer over-credits (was a permanent stat exploit).** Primordial Surge degrades the player's ATK/DEF/max-HP by 10% per hit and restores it after combat. But the subtraction was floored (`max(1, ...)`/`max(0, ...)`) while the *recorded* loss was the intended pre-floor amount. When a stat was low enough to clamp at the floor, the restore added back more than was taken — a permanent stat *gain* from being attacked. Reproduced: `min_atk` 2 → 4 after three surges and a restore. Fixed by capturing the actual before/after delta, and by tracking min and max ATK separately (they floor against different bounds). A typical level-5 warrior never hit the floor so most runs never saw the drift, but it was a real accounting bug. Verified to net zero across low-stat, typical, and extreme-floor cases.

**Debug menu option 11 no longer crashes.** "Trigger Death Defier (test)" called `try_death_defier(warrior, source="debug")` — but the function takes `reason`, not `source`, so it raised `TypeError`. One-word fix. Dev-only.

**Noted but deferred (from the audit):** off-hand weapon procs don't fire when dual-wielding (needs a design decision on one-swing vs. two-swing); triplicate dead-code class definitions in the main file shadow the `shared.py` imports (refactor hazard, no live bug); two divergent `try_death_defier` definitions; non-atomic leaderboard save; a few dead `TITLE_BUFFS` entries and stale docstrings. Design flag: the Chimera's unconditional 10%-max-HP-per-turn heal can soft-lock under-DPS players — balance review, not a code bug.

---

## v0.6.20 — Stats Visibility & Armor Socket UI Scaffolding
*May 2026*

**Interlude stats clearing instantly.** In `arena_quarters_interlude`, options 9 ("Check your status") and 11 ("View all game stats") printed their output and then immediately looped back to the menu top, which calls `clear_screen()`. Stats flashed and vanished before the player could read them. Both options now pause on `_real_input("Press Enter to return to the menu...")` after printing — matching the pattern already used by option 14 (Waterlogged Stone). Used `_real_input` (the saved-off bypass of the dev-shortcut wrapper) so debug shortcuts can't trigger from the pause prompt and skip the menu reset.

**Wolf-Hide / Dire Wolf set bonus tracker.** Set bonuses were correctly applied at equip time by `apply_all_set_bonuses`, but the only place piece counts were visible was inside the crafter scene. A player at 3/4 pieces had no way to see that +5 HP and +1 AP were active, or that 4pc would unlock +2 DEF/ATK + Pack Hunter. New helper `_format_set_bonus_lines(hero)` builds a status block for both `show_combat_stats` and `show_all_game_stats`:

```
🐺 Wolf-Hide: 3/4 pieces
   • +5 max HP
   • +1 max AP
   (4pc unlocks +2 DEF/ATK + Pack Hunter)
```

Skipped silently when no set pieces are equipped. The bonus thresholds and labels mirror `apply_wolf_set_bonus` and `apply_dire_wolf_set_bonus` exactly — must be kept in sync if either set's bonus table changes. Both Wolf-Hide and Dire Wolf shown independently, since a player shuffling pieces can briefly have items from both sets equipped at once.

**Dual-wield ATK breakdown.** The blended ATK range made it impossible to tell what the off-hand was actually contributing to a build. A player at "ATK 8-19" with sword + dagger had no way to verify that "off-hand halved" was happening — it just looked like a big number. New helper `_format_dual_wield_lines(hero)` shows the math:

```
⚔️  Dual Wielding:
   Main: Iron Sword (5-10 ATK, full)
   Off:  Bone Dagger (3-6 → 1-3 ATK, halved)
   Dual Wielder title: +1/+1 ATK passive
```

Skipped silently when not dual-wielding (single weapon, weapon+shield, no weapons). The halving math (`floor(off_atk / 2)`) mirrors `apply_dual_wield_modifier` — kept in sync if the formula ever changes (e.g. the future Dual Wielder skill that grants full off-hand damage). Title-held variant shows "+1/+1 ATK passive"; title-not-yet-earned shows "(Dual Wielder title unlocks +1/+1 ATK passive)" as a discoverability hint.

**No mechanical changes in this version.** All three fixes are pure visibility — the underlying math (set bonus application, dual-wield halving, Dual Wielder title bonus) was already correct in v0.6.16/v0.6.18. The player just had no way to verify it from the UI.

**Noted but not fixed — equipment list loop still uses old slot names.** `show_combat_stats` and `show_all_game_stats` (and a couple of debug-loot displays) iterate `("weapon", "armor", "accessory", "trinket", "finger_1", "finger_2")` instead of the v0.6.16 dict keys `("main_hand", "off_hand", "armor", "helm", "cape", "accessory", "trinket", "finger_1", "finger_2")`. Weapons and shields haven't appeared in the equipment list since v0.6.16. The new set-bonus and dual-wield blocks partly mitigate this (you can see weapons via the dual-wield block now, and helm/cape via the set-bonus block), but the equipment-list loop is still wrong and should be fixed in a separate pass.

**Armor socket UI scaffolding (Phase 2 preview).** Armor sockets have been discussed since v0.6.16 — `Equipment` items with `slot == "armor"` have been spawning with empty socket lists this whole time (1 socket for Normal/Uncommon, 2 for Rare+), inert because no combat hooks read them. v0.6.20 adds the UI surface without committing to mechanics: the crafter's socketing option now opens a "What to socket?" front-menu (1) Weapon, 2) Armor (💤 coming soon), 0) Back) and the armor branch shows a preview of the player's socketable armor pieces with current socket counts. The crafter flavor line: *"Armor sockets — aye, the thought's there. Got the holes punched, but the runes to make them sing? Not yet. Come back later."* Filtered to chest armor only (`slot == "armor"`) — helms and capes aren't socketable in the Phase 2 design. The old `_socket_loop` (weapon picker) was renamed `_weapon_socket_loop`; the new `_socket_loop` is the front-menu; `_armor_socket_preview` is the new coming-soon screen.

A new "PHASE 2 DESIGN NOTES" comment block in `crafter.py` documents the two planned armor-socket items so future-me doesn't have to reconstruct the design from chat history:

- **Javelina Tusk — retaliation bleed.** When the player is hit by a basic attack that lands physical damage past defence, the attacker takes a bleed DoT. Start at 2 dmg/tick × 2 turns at 75% socket power. Does NOT proc on DoT damage to the player (cascade prevention).
- **Soul Amulet — damage absorb + heal.** When the player takes a hit, absorb a portion of incoming damage and convert it to a small heal. Start at ~20% absorb, half converted to heal. Pairs with weapon-side Soul Pendant (drain on hit) as a lifesteal-build archetype.

Open design questions logged in the same block: should Tusk retaliation count as the player attacking the enemy (bleed mastery title, score)? Should Soul Amulet heal trigger Pack Hunter / Apex Predator multipliers? How does the damage source attribute in combat logs? A future resistance system (poison/fire/acid sacs in armor sockets granting elemental resistance) is explicitly deferred — that's a whole new damage-type-tag system, not part of Phase 2.

---

## v0.6.15 — Score Bug Fix, Blind Unification, Tier-3 Rebalance & QoL
*May 2026*

**Critical score bug — leaderboard was saving every defeat as 0.** The `combat_log.show_run_score()` wrapper (the version actually imported by the main file) was calling through to `score.show_run_score()` but then `return`ing with no value. The full score was computed and displayed correctly on-screen, so it looked like everything was working — but the integer got dropped on the floor before reaching the leaderboard. Every defeat saved with score=0. Detection happened when the player noticed two leaderboard entries (Umbra L3 and beast L5) both showed score=0 despite real damage and bonus accumulation. The fix is a one-line change: `_score_show(...); return` → `return _score_show(...)`. Existing zero-score entries stay as-is in scores.json (they're historical artifacts now); every new run saves the correct score. This was a frustrating bug because everything LOOKED right — the on-screen breakdown showed S/A/B rank assessment, broken-down score components, all the proper numbers. The leaderboard just never received them.

**Blind damage multiplier unified across all attack paths.** Three different blind systems were in flight: Power Strike used an inline 0.5/0.75 table, the `blind_damage_multiplier()` helper returned 0.5/0.25/full, and `player_basic_attack()` ignored blind entirely. User reported a Young Goblin dust hit, then a basic attack landing for 7 damage (max roll) on a 2-6 ATK + walking stick build despite being blinded — that's the bug. Now all three paths funnel through one source of truth: blind_turns=3 → 0.0 (skip turn, handled in turn loop), blind_turns=2 → 0.5, blind_turns≤1 → 1.0. Basic attack and Power Strike both call the helper, both print a "Blinded! Your swing lands at 50% power" line when active.

**Tier 3 + Fallen Warrior rebalance.** Player flagged that hardened tier-3 monsters had more DEF than the Fallen Warrior (prologue boss). On inspection, Goblin Warrior and Drowned One also outhit Fallen on ATK max. Fixed:

| Monster | Old DEF | New DEF | Old ATK | New ATK | HP |
|---|---|---|---|---|---|
| Goblin Warrior | 6 | 5 | 7-11 | 6-10 | 40 |
| Drowned One | 5 | 4 | 7-10 | 6-9 | 37 |
| Hydra Hatchling | 5 | 4 | 5-8 | 5-8 | 35 |
| Flayed One | 4 | 3 | 6-8 | 6-8 | 33 |
| **Fallen Warrior** | **5 → 6** | **6** | **6-10 → 7-11** | **7-11** | **60 → 65** |

Fallen now leads every category at base level. Hardened tier-3 variants can match or barely exceed in one category (hardened Goblin Warrior at DEF 6 ties Fallen, hardened ATK 8-12 at max exceeds Fallen's 11 by 1) but never sweep all three. Boss identity preserved through HP bump and the unique Defence Warp mechanic.

**Interlude potion access bug.** The round 4-5 "day passes" interlude (`arena_quarters_interlude`) had no "Use a potion" option. Player bought a Skill Point Potion from the merchant during the interlude, but had no way to drink it — couldn't use it in combat either (correctly refunded). New option 15 added to the interlude hub menu: "Use a potion". Calls `use_potion_menu(warrior, in_combat=False)` so all 17 potion types work, including the three progression potions (skill_point, stat_point, skill_rank_up) that are out-of-combat only. Full audit of all 17 handlers confirmed correct behavior — healing/AP/MP potions work, status cleansers correctly no-op when not afflicted, Frostpine works fully, progression potions correctly require in_combat=False.

**Debug menu numbering fix.** The debug menu was printing options 1-17 in order, then jumping to 20, then back to 18 and 19. Print order was scrambled, dispatch was correct. Renumbered to clean ascending order: 18 = Title Grant Menu, 19 = Exit Run, 20 = Exit Debug Menu. Dispatch logic updated to match.

**Frostpine Tonic acid_defence_loss "bug" — resolved as not-a-bug.** Previously flagged in v0.6.14 docs: tonics cleared `acid_stacks` but not `acid_defence_loss`. Was suspected as incomplete cleanse. User playtest revealed each new acid stack reapplies its own erosion fresh, so leaving `acid_defence_loss` alone post-tonic is correct behavior — what looked like "tonic didn't work" was actually getting re-acided after the cleanse, with the erosion rebuilding from the new hit. Removed from deferred-bugs list.

---

## v0.6.14 — Combat Fatigue, Hardened Nerfs & Play-Again Prompt
*May 2026*

**New combat fatigue system.** Long fights now apply a focus-streak save mechanic to prevent high-DEF stalemates from grinding into spreadsheet duels. Both player and enemy roll a d20 independently each turn after the threshold (turn 10 for regular fights, turn 15 for Chimera/Patronus boss fights). Save DCs escalate by streak tier: tier 0 needs 10+, tier 1 needs 15+, tier 2 needs 20+. Pass → advance to next tier (tier 2 wraps back to 0). Fail → lose 1 DEF (roll ≤13) or 2 DEF (roll ≥14), tier resets to 0. The streak-and-reset structure means players get satisfying micro-wins (passing DC 15 feels meaningful because DC 20 is next), and the dramatic -2 DEF hit can ONLY happen after a few consecutive passes — so narratively it lands as "you held it together for ages, then finally cracked" rather than random punishment. Rolls are silent; narration only fires on tier 1+ passes ("Your focus holds") and on fails ("Fatigue creeps in"). Monster fatigue gets parallel messaging with the monster's name so the player feels the mutual pressure. State stored in `entity.fatigue_def_loss` (cumulative, fight-only) and `entity.fatigue_save_tier`. Stacks INDEPENDENTLY from acid_defence_loss — both subtract from base DEF in `apply_defence`. Fully cleared via `reset_after_battle` and `reset_between_rounds` between fights.

**Hardened Hydra Hatchling + Goblin Warrior AP nerf.** Hardened (level 2) variants of both monsters now cap at 3 AP (was 4). Higher levels still scale up normally via the existing HP threshold formula. Applied as a name-keyed override inside `apply_level_scaling` — easy to revert. Hardened Hydra's acid spit could chain 4 times in a single fight; even with a Frostpine Tonic mid-fight cleanse, an unlucky player could take 30+ acid tick damage. Capping AP at 3 trims the worst-case tail without removing the threat. Goblin Warrior gets the same treatment for symmetry — its Savage Slash + bleed potential at AP 4 was creating similar burst tails.

**Hardened bleed damage reduced 4-6 → 3-5.** Goblin Warrior's hardened savage_slash bleed now matches the standard bracket per-tick. Hardened still distinguished by 4-turn duration (vs 2 standard) rather than per-tick severity. Was contributing to "level 3 player gets shredded by hardened Goblin Warrior" reports — with AP also dropped from 4 → 3, the old 4-6 bracket made an unlucky double-stack a near-deathblow.

**Hardened acid tick — new softer bracket.** Hardened Hydra Hatchling acid spit now tags its stacks as `hardened=True` and the tick handler rolls 2-4 damage instead of the standard 3-5. Chimera ignores the flag (it has its own x2 multiplier path). Standard hydras unchanged at 3-5. Same logic as bleed: hardened gets longer duration as its identity, not stronger ticks.

**Bug noted (NOT fixed in this version) — Frostpine Tonic and Cure-All Tonic don't clear acid_defence_loss.** Both potions clear `acid_stacks` (the visible DoT) but never touch `acid_defence_loss`. So after drinking the tonic, the sizzling stops and tick damage stops — but effective DEF is still reduced (up to -3) for the rest of the fight. Player thinks the tonic did nothing. Identified during a playtest where the player drank a tonic mid-fight and still succumbed. Logged here so it doesn't get lost; not fixed this version because we wanted to feel-test the AP nerf and fatigue first before stacking changes.

**Demo play-again prompt at all end-points.** All 5 demo end-points (Chimera victory, Chimera defeat, Patronus victory, Patronus defeat, arena death) now end with `prompt_play_again()` instead of `input("Press Enter to close the demo...")`. The prompt loops on invalid input until y or n; yes triggers `os.execv(sys.executable, sys.argv)` which re-execs the script for 100% fresh state. No cleanly exits with a farewell line. os.execv was chosen over an in-process restart because the end-points are nested deep inside `battle_inner` / `chimera_battle` / `patronus_battle` — unwinding to `__main__` from each would require threading a "restart requested" exception or flag through 4 layers of returns. The re-exec sidesteps all of that and guarantees no leftover state (no stale warrior, no leftover combat log, no leftover potions).

**Defensive fatigue cleanup before loot equip.** All 4 loot-equip points (regular monster kill, DoT-kill block, Chimera scale equip, Patronus breastplate equip) now explicitly reset `fatigue_def_loss` and `fatigue_save_tier` to 0 before offering loot. Mirrors the existing defence_warp fix pattern — gear should be evaluated against base DEF, never fight-fatigued DEF. Numerically this wasn't a live bug (equipment is additive on base DEF, and `reset_between_rounds` clears fatigue afterward), but it's defensive scaffolding: if Chimera/Patronus victories ever continue into another fight in the future, this would silently corrupt DEF accounting. Fixed now while the system is fresh.

**New rank — S+ "Demigod Champion" at score 6,500.** Sits above S (4,500), below the eventual SS / SSS tiers sketched as a future roadmap. Description: *"Demigod Champion. The Beast Gods themselves take notice."* Designed to sit at ~70% of the theoretical maximum score (~9,600 on a perfect Chimera path), so S+ is only achievable on a strong run that triggers most of the bonus systems — berserk + Death Defier across many fights, low-HP close-match survival, full gold accumulation, saved potions, jackpot/bookie luck wins. It has to feel earned, not default-great. The `_rank_for_score()` walk-and-return logic handles S+ automatically since the list is now ordered S+ → S → A → B → C → D → F; the rank box display in `show_run_score()` adapts to 2-character ranks via existing dynamic padding. Future tiers sketched in a score.py comment: SS "god champion" (lowercase, greek pantheon tier), SS+ "Elder god champion", SSS "God Champion" (uppercase G — the Holy Trinity tier), SSS+ TBD. Future tiers not implemented — left as a roadmap note for when the run economy supports much higher score ceilings.

---

## v0.6.13 — Progression Potions
*May 2026*

**Three new progression potions.** Added `skill_rank_up`, `stat_point`, and `skill_point` to the potion system. All three are out-of-combat only — using one during a fight refunds it and prints "save it for between battles" rather than disrupting turn flow. The three potions cover the three meta-progression axes: skill ranks, stat points, and skill points.

**Skill Rank-Up Potion.** Player picks one learned skill (rank ≥ 1, not yet at max_rank) from a numbered list; that skill advances by 1 rank. Skips skills already maxed and skips skills the player hasn't learned. Refunds itself if no eligible skills exist. Also clears any partial `skill_progress` on the chosen skill so the next rank starts clean. Useful as a guaranteed rank-up regardless of XP/SP economy.

**Stat Point Potion.** Grants +2 stat points immediately and drops the player into an inline assignment menu (1) +5 Max HP, 2) +1 ATK, 3) +1 DEF, 4) +1 Max AP, 5) Save for later). No per-level cap — the potion is rare and the player paid for it, so they can dump both points into one stat. Max HP gain also bumps current HP and `max_overheal`; Max AP gain bumps current AP. Player can break out of the loop and save remaining points for later if they want.

**Skill Point Potion.** Grants +2 skill points and immediately opens `show_skill_tree()` so the player can spend them right away. The tree handles partial investment, multi-rank, and progress banking — same flow as a level-up. Falls through to a simple "N skill points banked" message if `show_skill_tree` isn't loaded (defensive guard).

**`use_potion_menu` signature change.** Changed from `use_potion_menu(hero)` to `use_potion_menu(hero, in_combat=False)`. Combat-side callers now pass `in_combat=True` so progression potions can detect they're being used mid-fight and refund themselves. Non-combat callers can omit the parameter (defaults to False). The refund path also clears `bonus_action_used` if the potion was being used as a bonus action.

---

## v0.6.12 — Patronus Polish, Death Defier Cinematic, Leaderboard System & Main Menu
*May 2026*

**New module — `leaderboard.py`.** Persistent top 10 leaderboard stored in `scores.json` in the game directory. Captures player name, final score, outcome (Champion / Dark Champion / Intervention / Defeated / Gooed / Flayed / Drowned / Coward), level, final stats snapshot (HP, ATK range, DEF, max AP, gold), and date. Sorts by score descending with date as tiebreaker (newer wins ties). Retains top 10 plus up to 10 most recent non-top-10 runs so a non-qualifying player can still see their placement accurately. Module exposes three public functions: `record_run(warrior, score, outcome)`, `show_leaderboard(highlight_entry=None)`, and `display_at_end_of_run(warrior, score, outcome)` which records + displays together. Includes data validation (corrupted JSON doesn't crash — starts fresh) and graceful disk-write failure handling (warns but doesn't crash the run).

**Score system extended for fate deaths.** `OUTCOME_MULTIPLIERS` in `score.py` now includes three new outcomes for the fate-title deaths that previously bypassed the end-of-run flow entirely: `flayed_one` (0.5×, river rocks in prologue), `drowned_one` (0.5×, waterfall in prologue), and `coward` (0.3×, fled the arena). Coward gets the lowest multiplier — running away is a moral failure on top of dying. `_outcome_label()` extended to match. `show_run_score()` now `return`s the final score so leaderboard can use it (was returning None; backwards-compatible since old callers ignored the return).

**Three fate-death paths refactored to flow through normal end-of-run sequence.** Previously the Coward (`quit()`), Flayed One (`sys.exit(0)`), and Drowned One (`sys.exit(0)`) deaths bypassed the entire wrap-up flow — no `show_end_summary`, no `show_run_score`, no combat log review, no leaderboard. They just dumped raw stats and exited. All three now call the full sequence: `show_end_summary → show_run_score → view_combat_log → display_at_end_of_run` before their final `quit()`/`sys.exit(0)`. Runs that end this way will now show up on the leaderboard (low scores, but visible — and they earn closure).

**New main menu.** Game launch now starts with a simple menu (`[1] New Game  [2] View Leaderboard  [3] Quit`) instead of dropping straight into the prologue. Wraps the existing `intro_story()` call. Leaderboard option lets players check the board without playing — useful for showing off best runs or seeing what they're chasing. The menu loop lets them view the board, return, and then decide whether to start a run.

**End-of-run flow updated across all 5 existing endings.** Chimera victory, Chimera defeat (intervention or overwhelmed), Patronus victory, Patronus defeat (intervention or overwhelmed), and Arena death — all now end with `display_at_end_of_run()` after the existing stats/score/combat-log sequence. Combined with the three fate paths, that's **all 8 run-ending paths** flowing through a single leaderboard hook. Clean, consistent close-out regardless of how the run ended.

**Leaderboard display details.** Board shows rank, name (truncated at 14 chars), level, score (right-aligned), short outcome label, and date in a clean fixed-width layout. If the player's row is in the top 10, it's highlighted with `►...◄` markers. If they didn't make top 10, a divider line appears below the board followed by `Your run: #N` and their highlighted row. First-ever placement gets a `🏆 NEW #1 SCORE!` callout; other top-10 placements get a `🎖️ You placed #N` callout. Empty boards show `(No scores recorded yet — be the first!)`.

**Patronus Death Defier — full cinematic ending now plays correctly (bug fix).** Previously when Patronus hit 0 HP, Death Defier revived him at 30% HP with shield stripped and the battle loop continued (`continue` statement on the death-check branch), forcing the player to kill him a second time. This contradicted the intended cinematic arc — Patronus is a demi-god and **cannot be killed outright**; Death Defier was meant to trigger a full set-piece ending, not a round two. The fight now plays out as designed: Patronus drops, his ancient blood refuses to give out, he RISES (shield gone, intent on continuing) — but the Beast Gods surround the player in a stronger shield. Patronus charges, swings, his strike dies against the barrier without a sound. He understands. The Beast Gods then banish him; he walks out of the arena a shadow of what he was. Patronus survives in the world, weakened and shieldless, setup for hunting him down later on the evil path in a future encounter. Code change: removed the revive-to-30% logic and the `continue` statement, replaced the truncated "He rises, still standing" beat with the full shielded-strike cinematic, then fall through to the existing victory path. The post-fight cutscene was reworked to flow from this ending — no more double "Patronus drops to the sand" beats, the "PATRONUS FALLS" header became "PATRONUS BANISHED," and the "shadow of what he was" line was woven into the exit.

**Beast Gods' death sentence on Patronus.** Banishment alone wasn't enough — Patronus bit the hand that fed him, and the Beast Gods don't forgive that. After "BE GONE" he turns to leave, and just as he's reaching the gate the air changes: *"YOU BIT THE HAND THAT FED YOU, PATRONUS. YOUR TIME IS LIMITED. YOU WILL NOT LONG SURVIVE."* He stops, does not turn around — a century of divine protection withdrawn in a single breath, the mark settling into him like a brand. He glances back once at the player, then walks out disgraced *and under sentence*. This beat does heavy lifting: it (1) makes the banishment land harder — disgrace plus a death prophecy — (2) establishes that the Beast Gods *execute* their fallen champions, deepening their cosmology as not just indifferent harvesters but active enforcers, and (3) sets up the future evil-path hunt as fulfillment of the prophecy rather than convenience. The player isn't just chasing a loose end — they're being used by the Beast Gods to deliver a sentence already spoken.

**Docstrings updated across `Patronus` class, `patronus_fight()` wrapper, and LORE.md** — all three previously described the buggy revival-to-round-2 behavior. All now describe the correct cinematic arc.

**Patronus First Aid — locked at Rank 4, charges reduced to 1, threshold raised to 50% HP.** Previously rolled randomly between rank 1-4 with 2 charges and fired below 40% HP, which made the heal feel inconsistent — sometimes a meaningful sustain phase, sometimes a wasted turn restoring 10% HP. Now it's a single decisive nuke-heal: one charge, guaranteed 40% max HP restore, triggers below 50% so he actually gets to use it before dying. Expected total healing per fight drops from ~50% (2 × random rank avg) to a flat 40%, but the *felt threat* of the heal lands harder when it fires. Earlier 50% threshold also means it triggers in the mid-fight pressure window rather than as a last-ditch panic button.

**Patronus Defence Break — locked at Rank 4 (charges unchanged).** Previously rolled rank 1-4 randomly, averaging rank 2.5 on the opener. Locking at Rank 4 every fight makes the priority opener significantly more punishing — the DEF strip into Double Strike combo lands at maximum strength on every encounter, which lines up with him being the evil-path final boss. The boss should *feel* like a culmination of player skill, not a coin flip on opening tempo. If playtest shows the opener feels too oppressive, easy knob to turn is dropping charges from 3 → 2.

**Design philosophy.** Both changes move Patronus away from "random rank roll = variable difficulty" toward "fixed maximum tier = consistent boss identity." Boss fights should feel designed, not randomized. The randomization made sense early when his kit was being prototyped; now that the rest of his loadout (Double Strike R5, War Cry R5, Power Charge combo, Death Defier) is locked at top-tier, First Aid and Defence Break joining them at max rank completes the picture. The trade-off is on the heal side — one big charge instead of two small ones — which preserves the sustain pressure without letting him cheese low-HP situations indefinitely.

**Docstrings updated** to match the new locked behavior — both functions now explicitly note "locked at Rank 4" in their headers.

---


*May 2026*

**Death Defier — AP cost curve rebalanced.** Old curve was 3/3/4/4/5 AP across ranks 1-5, which felt punitive enough that players saved the skill for emergencies rather than using it. New curve is **1/1/2/3/4**. The skill now feels like an active part of combat decision-making rather than a panic button. Combined with the new Death's Apprentice rebound, this is a meaningful buff — but it's gated by being one-use per tournament and only reachable at level 5.

**River Spirit — discount changed from "always free" to "-1 AP per rank."** The old flat-0 cost made River Spirit functionally identical at every rank, so the path's reward stopped scaling with player investment. Now River Spirit applies a -1 AP discount at every rank, so river-path players still always pay less than regular players, but cost scales with the power of the ability. New river costs: rank 1-2 = 0 AP, rank 3 = 1 AP, rank 4 = 2 AP, rank 5 = 3 AP. The river path's identity (cheap casts, free at low ranks) is preserved while letting SP investment matter.

**New title — Death's Apprentice (renamed from Death Challenger).** The rank-5 Death Defier mastery title got a complete identity overhaul. Old "Death Challenger" framed the skill as defiance against death; new "Death's Apprentice" reframes it — death has *noticed* you, claimed you as a study, and reaches through your body to mark those who tried to kill you. Cold familiarity, not friendship. The mechanical effect is much stronger too: in addition to the existing -1 AP discount on Death Defier, the title now grants a **20% max HP psychic damage rebound** to the enemy whenever Death Defier triggers. Damage ignores defence (it's death's voice itself, not a physical strike). Sets up lore hooks for Game 2.

**Underworld dialogue on rebound.** Five flavor variants picked randomly when the rebound fires. The tone is ancient, bureaucratic, indifferent — death as a *bookkeeper*, not a friend. Each variant has a three-part structure: arena reaction (the ground trembles / pressure settles / dust rises), the voice itself (cold and exact — *"This one is not yours to take" / "The accounting is incomplete" / "I would see what you become"*), and an enemy reaction (psychic damage rendered as flavor — *"a name has just been written down"*). The 🕯️ candle replaces the ⚰️ tombstone — felt more like a vigil than a grave.

**Refactor — single source of truth for Death Defier AP cost.** New `_dd_ap_cost(hero)` helper added in main file. Both `activate_death_defier()` (casting code) and `skill_menu()` (display code) now call the helper instead of duplicating the cost calculation. Previously the same logic existed in two places — a maintenance trap. Discount stacking rule is now centralized: discounts can stack down to 0 AP, but only for River Spirit players. Non-river players always pay at least 1 AP — Death's Apprentice discount alone cannot make the skill free. Free casts remain the unique reward of the river path.

**`try_death_defier()` signature extended.** Added optional `enemy=None` parameter so the rebound knows what to hit. Three call sites updated: special-move death, basic-attack death, and DoT death. DoT case included intentionally — the DoT was inflicted by the enemy, so death still reaches through the apprentice and marks the source. Rebound is guarded by `enemy is not None`, so debug invocations cleanly skip it.

---

---
*May 2026*

**New title — True Jack of All Trades.** Awarded when the player reaches rank 2+ in all five core skills (power_strike, heal, war_cry, defence_break, death_defier). Where Jack of All Trades rewards the first three skills at rank 1 and the breadth pair (Chinker + Death Delver) rewards rank 1 across all five, this is the breadth capstone — the player who chose to spread investment evenly rather than master one. Buffs: +5 Max HP, +1 ATK, +2 DEF, +1 Max AP, +1 Adrenaline, +1 Berserk damage. Tier 3 in the score system, worth 250 points. Fires from both `show_skill_tree()` and `nob_interlude()`, so Nob's free rank-up can be the trigger.

**Endgame title buffs increased.** Guardian (Young Chimera kill) and Dark Champion (Patronus kill) were under-tuned for their tier-4 score value (500 pts). Guardian goes from +2 HP / +2 DEF to **+10 HP / +4 DEF / +1 ATK / +1 Max AP** — the defensive titan identity. Dark Champion goes from +2 ATK / +2 Max AP to **+5 HP / +1 DEF / +4 ATK / +4 Max AP** — the glass-cannon striker identity. Both now feel like the rare, run-defining rewards they're meant to be.

**Removed — Divine Blessing & Beast Gods' Blessing.** Both were dead scaffolding. Defined in `TITLE_DISPLAY`, `TITLE_BUFFS`, and `TITLE_SCORE_VALUES`, but never awarded anywhere in the codebase. Original intent overlapped with the actual ending titles (Guardian / Dark Champion), and the moral-choice "blessing" effect — the full-heal + 2 AP buff granted based on the player's path choice — remains as the in-fight effect it always was. Stripped from all three lookup tables. The tier-3 score header updated from "hereditary blessings" to "breadth capstone."

**River Spirit → Death Defier conversion bug — fixed.** Two related bugs. First, once the player invested any SP into Death Defier, the displayed name still showed as "River Spirit" everywhere — skill menu, HUD, status panel, activation flavour text, post-revival message. Second, and worse: the survive-HP calculation forced rank=1 for any river-flagged hero, so ranking Death Defier from 1 to 2 expecting 10% survive HP still gave 1 HP because the river flag overrode actual rank. Root cause was a flag doing double duty — `death_defier_river` gated both the displayed name AND the 0-AP / -1 SP discounts, and the conversion code intentionally kept it True past rank-up to preserve the discounts. Fixed with two helpers: `_dd_display_as_river(hero)` returns True only when rank == 0, and `_dd_effective_rank(hero)` returns 1 for the rank-0 starter blessing but actual rank once invested. Five display call sites updated. The 0 AP activation cost and -1 SP per rank discount still persist past rank-up — those are the river path's permanent gift, intentional design.

**Nob's training now fires skill mastery.** Bug — Nob's free rank-up bypassed the title-check pipeline, so taking Power Strike from rank 4 to rank 5 via Nob silently skipped the Brawl Master title award. Affected all five mastery titles (Brawl Master, Combat Medic, Charismatic Speaker, Armor Piercer, Death Challenger). `nob_interlude()` now calls `check_skill_mastery(warrior, key)` and `check_true_jack_of_all_trades(warrior)` after applying the rank-up. Both checks idempotent — guard at function top prevents double awards.

**XP curve — level 1→2 raised from 10 to 15.** With the increased XP rewards from the recent monster balance passes, level 5 was being hit before the Fallen Warrior fight, undermining the level-cap-as-pacing-tool design. The 1.75 scaling carries through, so the new curve is 15 → 26 → 45 → 78 (cumulative 164 to hit level 5, was 106). The ~55% bump pushes level 5 reliably past Fallen.

**Walking Staff — `atk_max` lowered from 2 to 1.** Range is now 0 / 1 ATK with +1 DEF. Even the Rusted Sword (poor rarity, 1-2 ATK) felt like only a sidegrade before. Now the staff is clearly the "carried it from home" placeholder it's meant to be — any arena weapon drop is an upgrade.

**Overseer dialogue — temptation rewrite.** The post-Fallen Overseer line "What you are feeling is sentiment. Sentiment is a luxury the arena does not permit." read like a debate-team rebuttal rather than a tempter's voice. Replaced with: *"Their voice settles into your bones, smooth and unhurried. Every word coaxes you toward agreement, as if compliance were the only natural answer."* Better fits the moral-choice tension — the Overseer's words pulling the player toward compliance, almost hypnotic.

**End-of-run score display — total damage prominence.** The score sheet was technically showing `Damage Dealt (350)` next to the `+175` score contribution, but the raw totals were easy to miss as parenthetical labels. The Combat Performance section now leads with prominent **Total Damage Dealt** and **Total Damage Blocked** rows, separated from the weighted score contribution by a divider. Both raw values and scored values are now visible — players can see what they actually did AND how it scored.

**`titles.py` — `award_title_with_buff()` extended.** Previously only handled HP / DEF / ATK / AP stat keys. Now also handles `perm_special` (adrenaline) and `berserk_bonus`, enabling the True Jack of All Trades title to deliver its full buff package via the same standard mechanism.

**File structure.** `Journey_To_Winter_Haven_v_06_08.py` moved to `Old .6 builds/`. New file is `Journey_To_Winter_Haven_v_06_09.py`. `titles.py` and `score.py` updated alongside.

---

### Merchant Shop — full implementation

**New module — `merchant.py`.** The arena merchant in the round 4-5 interlude is now a working shop, replacing the prior "(wip)" placeholder. Single-visit only — the player gets one shot at the catalog, has to plan their gold accordingly. Stock is generated fresh at scene entry and persists for the duration of the visit; sold items stay sold; potion stock decrements per purchase. Closes the long-standing economy loop where gold accumulated with nowhere meaningful to spend it.

**Stock per visit.** 3 weapon types, 2 armors, 2 trinkets, full potion lineup. Weapons drawn from the existing pool (Rusted Sword, Imp Trident, Goblin Dagger, Goblin Shortbow, Goblin War Blade) with variant rolls — Javelina Tusk removed and reclassified as a crafting component. Armors and trinkets are new merchant-only basic items, no rarity variants. Potions cover Heal/Super Potion, AP/Super AP, Antidote, Burn Cream, plus two new types — Cure-All and Elixir.

**Weapon variant rolls — guaranteed normal, optional uncommon and rare.** The merchant has been "holding back the good stock" for late-tournament champions, so he doesn't peddle poor-tier rusted-junk — poor rarity is excluded from the merchant entirely. For each of the 3 weapon types drawn per visit, a normal-rarity listing is guaranteed. On top of that, two independent rolls determine whether the merchant also offers higher tiers of the same weapon: 50% chance of an uncommon variant, 25% chance of a rare variant. This means a single weapon type can appear at 1, 2, or 3 rarity tiers — and the player can pick the rarity their gold can afford. Empirical distribution: ~37% of weapon types appear normal-only, ~37% as normal+uncommon, ~13% as normal+rare, ~13% as all three. Total weapon listings per visit range from 3 (everyone rolls no/no) to 9 (everyone rolls yes/yes), averaging ~5.25. Substantial buff over the prior random-weighted model — rare gear is now a real possibility most visits, but you might also walk in to find three plain normals if luck isn't with you. Single-visit shop means no compounding effect.

**Expandable menu for weapon variants.** With weapon listings potentially expanding to 9 per visit, a flat list would clutter the catalog. Multi-variant weapons now render as a single parent line with a `[+]`/`[-]` indicator and "(N of N variants)" hint — click the parent number to expand the variants inline beneath it, click again to collapse. Variants get sub-letter codes (`1a`, `1b`, `1c`) so the player can tell at a glance which sub-items belong to which parent. Single-variant weapons skip the expand step entirely — they render flat with their price and stat summary visible, and clicking the number goes straight to buy-confirm. Armors, trinkets, and potions also stay flat. Keeps the catalog scannable in both the everyday case (3-5 weapon listings) and the maximum case (9 weapon listings, 4 of which would be Rusted Sword tiers if luck loaded).

**Pricing — anchored against ~60g typical run total.** Equipment by rarity: normal 18g, uncommon 35g, rare 65g. Tier 1 armor 15g through tier 4 80g (Frost-iron — aspirational, more than most runs yield). Trinkets 25-30g flat. Potions 5-30g. Sell-back is half buy-price, rounded down, 1g floor. Sell-back gold goes to `warrior.gold` only — NOT `total_gold_earned` — so reselling gear doesn't artificially inflate the score system's lifetime-earnings bonus.

**Four new merchant-only armors — DEF only, no HP, fixed tiers.** Copper Scale Vest (+1 DEF, 15g), Bronze Hauberk (+2 DEF, 30g), Iron Cuirass (+3 DEF, 50g), Frost-iron Cuirass (+4 DEF, 80g). DEF-only is intentional: the future crafted armor path (using Wolf Pelt et al.) will provide HP. Store-bought is the dependable defensive baseline; crafted is the upgrade path with HP and procs. Tier 1-3 follow copper/bronze/iron metallurgy progression. Tier 4 ties to the world's frost-and-ash atmosphere.

**Four new merchant-only trinkets — single-stat each.** Stoneheart Pendant (+10 max HP, 25g), Tiger Fang (+2 min/max ATK, 30g), Stoneskin (+2 DEF, 25g), Spirit Crystal (+2 max AP, 30g). Drop-table trinkets (Charged Jagged Rock, Waterlogged Stone) keep their rarity rolls and complex charge mechanics — they remain drop-only. Merchant trinkets are the simple, reliable, "I need exactly +2 ATK right now" line.

**Two new potions — Cure-All Tonic and Elixir.** Cure-All (15g) clears poison, burns/fire stacks, acid stacks, paralysis (only paralysis-source `turn_stop` — won't strip psychic-source stops), and blindness. Does NOT clear psychic charge. Elixir (30g) is 50% HP + 50% AP combo restore — the "I need everything right now" premium. Both potions added to `Warrior.__init__`'s default potion dict, the `potion_labels` display map, the use-potion handler in `use_potion_menu`, and the debug potion menu (items 13-14; quick-fill hotkey moved 13 → 15).

**Mega/Full potions deliberately excluded from merchant stock.** Too premium for an arena vendor — those stay in the loot/reward economy.

**Sell-back system.** Player can sell unequipped non-blocked inventory at half price. Crafting components (Wolf Pelt, Dire Wolf Pelt, Poison Sac, Fire Sac, Acid Sac, Soul Pendant, Javelina Tusk) are listed in the sell menu but blocked from sale, with a flavor refusal pointing the player at the future crafter: "*That's a crafter's job, not mine. Take it to the workshop.*" No-resale list also includes boss drops (Tainted Champion's Breastplate, Chimera Scale, Lightrender, Destiny Definer), the prologue Walking Staff (sentimental), and Frostpine Tonic.

**Reclassification of existing drops as crafting components.** Wolf Pelt, Dire Wolf Pelt (previously equippable armor), Poison Sac, Fire Sac, Acid Sac, Soul Pendant (previously equippable accessories), and Javelina Tusk (previously a weapon) are now crafting components. They still drop from the same monsters, still equip into their respective slots if forced, but the merchant won't buy them. The future crafter (currently still a placeholder) will be the destination for selling and combining components. This is groundwork for the crafting system, not a complete implementation.

**Wired into `arena_quarters_interlude`.** The "(wip)" tag dropped from option 5; the placeholder text replaced with `merchant_stock = merchant_scene(warrior, stock=merchant_stock)`. The interlude holds onto the stock dict across choice iterations — first visit rolls fresh inventory, subsequent visits reopen the same catalog with sold items still sold and potion counts decremented. Lets the player leave the merchant to check their bag and come back without losing the catalog or being able to re-roll for better stock.

**Module style.** `merchant.py` follows the same pattern as `gold.py` / `score.py` / `titles.py` — module-level config dicts at top, public functions exposed at the bottom, lazy main-module imports to avoid circular import issues. Documentation comments inline mark the design decisions (why DEF-only armors, why uncommon-leaning rarity, why merchant doesn't refactor `make_loot()`, etc.).

---

---

## v0.6.08 — Score System, Patronus Rebalance & The Gooed One
*May 2026*

**New module — `score.py`.** End-of-run scoring system with a 6-tier rank (S/A/B/C/D/F). Designed to be RNG-resistant, tied to actual difficulty defeated rather than fight count, and rewarding engagement with all systems (combat, gold, titles, potions, luck). Mirrors `gold.py`'s design philosophy — same `cap_rounds` thresholds for speed bonuses, same per-tier weighting principle, same anti-grinder caps.

**Per-fight scoring — threat budget.** Each defeated monster yields a base score equal to its threat value: `HP + (max_atk × 3) + (defence × 2) + (max_ap × 2)`, with AP capped at 8 to handle Chimera's sentinel value. A Hardened Green Slime is worth 40 base; a Goblin Warrior is worth 89; Patronus is worth 205. Five Green Slimes (90 total) is roughly equivalent to one Goblin Warrior — exactly as it should feel.

**Per-fight bonuses.** Speed bonus +threat × 0.5 if cleared within `cap_rounds`. Drag penalty -threat × 0.3 if the fight exceeds `penalty_start`. Berserk +20, Death Defier +50, close-match +threat × 0.5 if surviving at ≤20% HP. Per-fight floor: never below `threat / 2`, so a hard fight is never worthless even if it took forever.

**Run-wide bonuses.** Damage dealt × 0.5 (capped at 1000 contribution to prevent grinder exploits), damage blocked × 0.5 (capped at 500). Gold scored from `total_gold_earned` — a new lifetime field that never decreases on spending, so spending isn't punished. Player level × 25 per level above 1.

**Title scoring — tiered by actual difficulty to earn.** Tier 1 (50 pts each): Jack of All Trades, Chinker, Death Delver — all natural early progression. Tier 2 (150 pts): Champion of the Arena. Tier 3 (250 pts): River Warrior (RNG-gated 30% survival roll), all five skill-mastery titles (rank-5 dedication), and the two hereditary blessings. Tier 4 (500 pts): Guardian and Dark Champion — true ending titles. Fate titles get their own table — most at 50, Coward at 25, **The Gooed One at 1 (the eternal joke).**

**Luck bonuses.** Jackpots × 50 each (level-up specialization rolls). Bookie intimidations × 25 each (both luck and skill — d20 18+ during the bookie encounter).

**Potion bonuses.** All regular potions × 5 each, capped at 100 total contribution — rewards conservation without enabling hoard-and-skip exploits. Frostpine Tonic awarded separately at +25 if saved (Elwyn's gift, unique starting item).

**Outcome multipliers — good path compensated.** Chimera victory ×2.1, Patronus victory ×2.0, Intervention ×1.5, regular Defeat ×1.0. The 0.1 bump on Chimera victory exactly compensates for the no-gold reward on the good path — defying the Beast Gods costs you ~100 gold's worth of score, the multiplier puts it back. **Goo death** also adds a +1 flat pity bonus post-multiplier, because we believe in you. Mostly.

**Rank thresholds.** S 4500+, A 3000+, B 1200+, C 500+, D 150+, F 0+. Tuned to map to outcomes: F-rank is "died early," D-rank is "got somewhere," C-rank is "average run," B-rank is "intervention save," A-rank is "beat the final boss," S-rank is "clean kill with mastery titles."

**Patronus War Cry — converted to percentage scaling.** Was flat +5 ATK; now 50% of `max_atk` (min +1) for 3 turns. Boss-tier scaling exceeds player War Cry Rank 5 (35%). At base stats: +6 ATK (was +5). Future-proofs scaling — if Patronus's base ATK ever rises (sequel/arena tiers), the buff scales automatically.

**Patronus Power Charge — buff scaling fix.** Damage component unchanged (1.5× attack — keeps the "weaker combo" intent). Buff component now applies 25% of base `max_atk` (was flat +3) for 2 turns — half of full War Cry's 50%, reflecting the cost of doing two moves at once. Also fixes a subtle stacking issue: buff calculation now uses base ATK rather than potentially-buffed ATK, so chaining Power Charge with active War Cry math is clean.

**Patronus Victory — +100 gold reward.** The Beast Gods leave 100 gold at your feet. Compensates evil-path payout vs. good-path's score multiplier and gives the dark ending a tangible reward beyond the title and Tainted Breastplate.

**The Gooed One — new fate title.** Awarded when the player dies to a regular (non-Chimera) Green Slime while still having unused healing options (heal/super/mega/full potion, antidote, Frostpine Tonic, or learned First Aid). Replaces the standard Fallen Champion sequence with a custom roast — the crowd boos, the bookkeeper refunds bets, the slime nudges your corpse to ask if you're okay. Designed for the "death by my own stupidity" scenario that became possible after the Hardened Slime tier rebalance gave them real teeth. Death Defier / River Spirit interaction is documented inline — title only fires after Death Defier has had its chance to save the player.

**End-of-run flow consolidation.** Fixed a bug where stats displayed twice on combat death — both `battle_inner` death paths were calling the full end-of-run sequence, then `arena_battle` was calling stats again on top. Now `arena_battle` owns all post-death wrap-up; `battle_inner` death paths only log the death and return False.

**Demo-end "thanks for playing" sequence.** Combat death now ends with a proper demo close: stats → score → optional combat log → "Thank you for playing" banner → tailored retry encouragement → "More content coming soon" → press-Enter exit. Two distinct retry tones — cheeky for Gooed One ("Better luck next time, Goo Guy"), solemn for regular Fallen Champion ("The Beast Gods have claimed another champion").

**"Well fought, warrior" intervention send-off.** When the player survives 4+ cycles against Young Chimera or Patronus and earns the intervention save (without landing the killing blow), they now see a tailored "you proved yourself, care to try again?" message before the standard demo close. Two distinct tones — Chimera's path heroic and hopeful, Patronus's path darker but still encouraging retry. Overwhelmed defeats (cycles < 4) keep the original framing.

**Boss fight close paths fixed.** `chimera_fight` and `patronus_fight` had inverted score order — was thanks-for-playing → score, now score → combat log → thanks-for-playing → press-Enter close. Matches `arena_battle`'s order across all paths.

**`gold.py` — `award_gold(warrior, amount)` helper.** New convenience function that adds to both `warrior.gold` (current pouch) and `warrior.total_gold_earned` (lifetime, never decreases). All 4 bookie sites and all 3 main-file gold sites updated to use it. Single source of truth for gold tracking.

**File structure.** `Journey_To_Winter_Haven_v_06_07.py` moved to `Old .6 builds/`. `score.py` added as a new top-level module alongside `gold.py`, `combat_log.py`, `monsters.py`, `titles.py`, and `shared.py`.

---

## v0.6.07 — Rot System, Weapon Identity Pass & Gold Overhaul
*May 2026*

**New status effect — Rot.** A new damage type distinct from poison and all existing DoTs. Rot drains max HP rather than current HP, making recovery harder as the fight goes on. Two separate versions exist: player-inflicted (Rusted Sword) and enemy-inflicted (Brittle Skeleton / Young Chimera).

**Rusted Sword redesigned around Rot.** Defence removed across all rarities. Poison proc replaced with Rot proc — 15% chance at poor (no proc on other tier 1 weapons at poor, but the payoff is only -1 max HP so it earns the exception), 25% at normal, scaling to 90% at mythril. Each proc applies stacks and HP drain per stack, capped at 30% of the enemy's max HP. Resets between fights.

**Walking Staff — starter rarity, atk_min lowered.** Rarity changed from `poor` to a new `starter` rarity that displays no icon and no rarity prefix — shows as just "Walking Staff." `atk_min` dropped from 1 to 0 so the staff can whiff, making it feel unreliable and giving the Rusted Sword a clearer identity despite both being tier 1.

**Brittle Skeleton special renamed Rot Thrust.** Previously Precise Thrust. 50% chance to apply rot on use — each proc drains 20% of the player's current max HP, stacked, capped at 50% of player base max HP. Stronger variants get 2–3 special uses based on HP tier.

**Young Chimera — Rot Thrust as borrowed move.** When Chimera draws the Brittle Skeleton move it now draws Rot Thrust. Proc chance 75%, cap raised to 60% of player base max HP. Spawn flavour updated when this move is drawn. Defeat intervention only clears rot if Rot Thrust was drawn.

**Rot clearing rules.** Clears on: regular rest (max HP restored, no HP heal), round 4–5 long rest (full restore), Patronus intervention (full restore), Chimera intervention if Rot Thrust was drawn (full restore), Rank 4+ First Aid (max HP restored, no HP heal). Does not clear on level up.

**First Aid rank 4 — rot cure with heal penalty.** 40% heal reduced by the percentage of max HP lost to rot. If 40% of max HP was rotted, the effective heal becomes 24%. Punishing but fair.

**Frostpine Tonic — full rot clear, no penalty.** Clears rot fully before healing so the 40% heal calculates on the restored max HP. No penalty. Mom's recipe beats the rot every time.

**Gold — variant bonus.** Hardened (+5g), Veteran (+10g), Elite (+15g) enemies now pay extra gold per level above normal. Baked into base gold so the floor reflects it. Shows in payout breakdown.

**Goblin Bookie — pickpocket tell removed.** The line revealing the exact amount stolen has been cut. Player sees "something feels off but you can't quite place it." The skim is silent.

**Run score shown on defeat.** `show_all_game_stats()` now fires on both defeat paths. Win or lose, the player sees their full performance rating and rank.

---

## v0.6.05 — shared.py Architecture & Input Standardisation
*May 2026*

**Architecture — shared.py extraction.** Core utilities, constants, and base classes migrated out of the main file into a new `shared.py` module. `SPECIAL_MOVE_NAMES`, `WIDTH`, `DEFENCE_BREAK_STATS`, all utility functions (`wrap`, `space`, `clear_screen`, `continue_text`, `show_health`, `hp_bar`), all combat helpers (`weak_defensive_block` through `full_defensive_block`, `lvl_bonus`, `ap_from_hp`, `scaled_xp_step`, `monster_math_breakdown`, `monster_deal_damage`, `get_ap_inflation`, `inflated_ap_cost`, `apply_turn_stop`, `try_death_defier`), all exception classes, and the `Equipment`, `Creator`, and `Monster` base classes now live in `shared.py` and are imported at the top of the main file. Second major architectural cut of the v0.6 era after `monsters.py`.

**New — End of Run Summary screen.** `show_end_summary()` displays a formatted recap at the end of each run: potions remaining, all equipped gear by slot, and unequipped loot in the bag. Gives players a clear picture of how their run went before the session closes.

**Input standardisation — yes/no → y/n throughout.** All player prompts game-wide switched from `yes`/`no` to single-character `y`/`n` responses. Confirmation prompts, dialogue choices, equip offers, tournament queries, weapon core equip — every interactive prompt updated. Reduces keystrokes and makes input feel snappier.

**Stat cap fix — level-up no longer lets stat dumps at level 5.** Stat cap per category is now `min(2, available points)` instead of a flat 2, preventing level 5's 5-point windfall from being poured entirely into one stat.

---

## v0.6.04 — Monster Balance Pass & Prologue Expansion
*May 2026*

**Balance — Tier 2 monsters buffed across the board.** All five Tier 2 enemies (Red Slime, Noob Ghost, Goblin Archer, Dire Wolf Pup, Javelina) received +5 HP, +1 ATK, +1 DEF, +1 AP, and approximately +10% XP. Previously they were noticeably weaker than Tier 3 enemies introduced earlier.

**Balance — Tier 3 monsters buffed across the board.** All five Tier 3 enemies (Wolf Pup Rider, Hydra Hatchling, Flayed One, Drowned One, Goblin Warrior) received +10 HP, +2 ATK, +2 DEF, +2 AP, and approximately +20% XP.

**Balance — Hardened level scaling doubled.** HP scaling increased from +5 to +10 per level; ATK and DEF scaling from +1 to +2 per level. Hardened enemies now feel meaningfully threatening at higher rounds.

**Balance — DoT hardened values increased.** Poison (Slime), Bleed (Savage Slash), Psychic Shred debuff duration, Psychic Drown damage table, and Acid Spit (Hydra) all received increased damage or duration on hardened variants.

**Story — Aldric sendoff deepened.** A flicker of concern added before "Eyes only" — hints the road to Winter Haven has been too quiet; merchants have mentioned it. Clasp rewritten from a backslap to a held shoulder moment.

**Story — Forest journey expanded to five beats.** Day 1 now opens with eerie animal silence. Day 3 added: no travelers on a road that should have them, slow creeping dread. Day 4 rewritten around deep loneliness. Arrival rewritten: distant city lights and sounds, camps outside rather than pushing through in the dark.

**Story — Elwyn rename and farewell rewrite.** Elwin renamed Elwyn throughout. Farewell scene rewrites her as warm and physical — a hug and a kiss on the cheek — with "Stay out of trouble. And don't dawdle." moved to her line. Aldric's section cleaned accordingly.

**Bug fix — Bo tackle path potion grant corrected.** Tackle path was granting only a heal potion but dialogue implied two potions. Corrected: tackle path grants heal only (dialogue updated to match); tree-branch path correctly grants both heal and AP potion.

**Bug fix — Skill investment loop stale prompt removed.** Phantom `input("Press Enter...")` in `show_skill_tree()` removed; players can now invest stat points back-to-back without an extra keypress.

---

## v0.6.03 — Monster Extraction, Dev Shortcut Refactor & Prologue Polish
*April 30, 2026*

**Architecture — monsters.py extracted.** All 18 monster classes (Green_Slime through Patronus), 51 special-move and AI/encounter functions, and 8 module-level constants moved out of the main file into a new `monsters.py` module. Main file shrank by roughly 2,175 lines (~13,255 → ~11,090). Resolves a latent Python 3.13 partial-module circular-import edge case using an explicit `__all__` export list. First major architectural cut since the v4.x extraction of `combat_log.py` and `titles.py`.

**Developer shortcuts — full parity at every prompt.** New `_try_dev_shortcut()` helper centralizes handling for `q` (restart), `c`/`combat` (jump to arena), and `debug` (open debug menu). Both `continue_text()` and `check()` now route through it, so all three shortcuts work at every story prompt — previously inconsistent (`q` only worked at choice prompts, `debug` only at choice prompts, etc.). Adding a new shortcut is now a one-place edit.

**Bug fix — restart no longer leaks state.** `intro_story()` on `RestartException` now fully replaces `GAME_WARRIOR` with a fresh `Warrior()` and clears the combat log. Previously the existing warrior was reused, leaking the player's name across the restart and causing the framing/name-prompt scene's `name == "warrior"` gate to fail — `q` would land the player mid-prologue with stale state instead of restarting cleanly from the top.

**Story — opening framing scene added.** Three short paragraphs at Ashenveil's eastern gate (cold morning, ash drifting from Frostveil Peak, "first quest — a scouting run") establish tone before the name prompt. Player gets to settle into the world before being asked who they are.

**Story — Aldric scene rewritten for scout mission.** Aldric now checks for buckles that catch light and pack straps that might rattle (visibility/noise hazards) instead of armor weak points (warrior hazards). Mission brief is observe-and-report: "Confirm the dungeon entrance exists. Watch what comes in and out for a day or two. Take notes. Then get back here." Followed by an explicit hard look: "Eyes only. You don't go inside. You don't pick a fight. You don't try to be a hero." Closing line is now "Don't dawdle. And stay out of trouble." Scene split across two screens (advice → exit) so the player isn't scrolling back to re-read.

**Story — forest travel expanded into a four-day trek.** Previously a single afternoon's walk; now five paced beats with daily clear_screen breaks: forest entry, first night camp (sheltered behind a fallen ash trunk, cold rations), day two (something in the trees), day four (rations and aching feet, "you'd trade your boots for a hot meal"), arrival at Winter Haven (legs screaming, ready for warm bed → "you never make it to the dungeon entrance"). Sells the trip's weight and earns the dropped-torch payoff scene.

**Lore canon — Frostveil Peak as semi-active volcano.** The peak vents fine grey ash from somewhere high on the mountain "that has never fully gone quiet." Ash drifts down to Ashenveil and through the Ashen Frost Forest. The "Ashen" naming is now layered: ash trees with pale grey bark + volcanic ash drift. Both meanings real, both canonical. LORE.md updated to reflect.

**Gameplay — Frostpine Tonic replaces starting heal potion.** Elwin's scene now sets `heal=0` and `frostpine_tonic=1`, lampshaded in-fiction: "(It replaces the basic heal flask you'd packed for the trip.)" Player enters the arena with one consumable, not two.

**Word polish.** "In the lee of a fallen ash trunk" → "sheltered behind a fallen ash trunk" (clarity). "Hand on your dagger" / "trade your dagger for a hot meal" → "hand on your walking staff" / "trade your boots for a hot meal" (Umbra carries no real weapons — sells the stripped-on-capture, bare-fisted-tournament setup).

---

## v0.6.02 — Player Name Prompt & Re-prompt Gating
*April 30, 2026*

**New — player names their character at the very start of the prologue.** `get_name_input()` is now called at the top of `ashenveil_prologue()`, gated by `if GAME_WARRIOR.name == "warrior"` (the Warrior() default). Hitting ENTER on an empty prompt defaults to "Umbra" — preserving the canonical name for players who don't want to choose. The hardcoded "You are Umbra" line in the Ash Hall paragraph is now `f"You are {warrior.name}"`.

**Re-prompt gating — name only asked once.** Five legacy `get_name_input()` call sites later in the story (cave/beastman intro, magical darkness, Bo introduction, frigid river rescue, River Warrior path) are now wrapped in the same `if name == "warrior"` gate. NPC dialogue lines that rhetorically ask "What is your name?" still play, but the input prompt itself is skipped when the player already named themselves at the start.

**Cleanup — dead loop removed.** `get_name_input()`'s outer `while True:` loop was unreachable past the first iteration (every branch inside returned). Removed along with an unused `global` declaration.

---

## v0.6.01 — Ashenveil Prologue & Frostpine Tonic
*April 2026*

**New — full pre-arena backstory scene.** `ashenveil_prologue()` introduces Umbra at 19, a greenhorn member of the Ashen Vanguard, sent on his first quest: travel to Winter Haven, confirm the dungeon exists, clear the first floor. His father Aldric (A-rank senior Vanguard) quietly arranged the mission thinking it was a safe first win for his son.

**Aldric sendoff scene.** Gruff, proud handoff at the city gate. Hands over the quest parchment, claps Umbra on the shoulder harder than necessary, and teases him about a girl in the market district before walking away mid-conversation with a "Don't dawdle."

**Elwin sendoff scene.** Quiet, warm. Umbra's mother presses a small flask into his hand. *"I made it myself. Your father never took one when he left for his first quest. You're smarter than he was."* She doesn't say goodbye — she just turns and walks back toward the house.

**New item — Frostpine Tonic.** Unique starting item gifted by Elwin. Restores 40% max HP, clears all status effects, and restores 2 AP. Cannot be bought, crafted, or found in Game 1. One use only. Reflects both parents — the heal and status clear is Elwin's herbalist craft, the AP restore is Aldric's warrior energy. Added to potions dict and fully implemented in `use_potion` handler. Locked from shops and loot tables.

**Ashen Frost Forest travel narrative.** Atmospheric passage from Ashenveil toward Winter Haven. Hints at danger without combat encounters — narrative flavor only. Named for ash-pale trees and frost creeping in from Forstback Mountain. The frost in the name is the first subtle hint of Winter Haven before the player ever arrives.

**Updated — `intro_story_inner()` forest opening.** Text now flows naturally from the new prologue. Umbra is now arriving rather than wandering lost.

---

## v5.13 — Flayed One Bug Fix & Boss Balance
*April 2026*

**Bug fix — Flayed One double-debuff.** `psychic_shred()` was applying a separate 25–50% ATK/DEF reduction on top of the charge system, reducing the player to ATK 1–1 and DEF 0. `psychic_shred()` is now damage-only when called by the Flayed One; all stat drain is handled exclusively by `_flayed_charge_tick()`. The Chimera retains its percentage debuff version.

**Chimera — `psychic_shred` debuff rebalanced.** Reduced from 60% to a flat 30% ATK/DEF for 4 turns. Prevents a death-spiral interaction with the DEF-below-zero 10% damage bonus mechanic.

**Chimera — Oppressive Presence added.** If the Chimera rolls `psychic_shred` as her Tier 3 move, the player starts the fight at –2 ATK / –2 DEF. Stats restored after fight ends.

**Patronus — passive damage reduction confirmed working.** The 30% passive damage reduction tied to the `shield_equipped` flag was already active and verified — no changes needed. Documented for clarity.

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
