# DOGFOOD — minesweeper-tui

_Session: 2026-04-23T10:31:51, driver: pty, duration: 8.0 min_

**PASS** — ran for 4.5m, captured 75 snap(s), 1 milestone(s), 0 blocker(s), 0 major(s).

## Summary

Ran a rule-based exploratory session via `pty` driver. Found no findings worth flagging. Game reached 357 unique state snapshots. Captured 1 milestone shot(s); top candidates promoted to `screenshots/candidates/`. 1 coverage note(s) — see Coverage section.

## Findings

### Blockers

_None._

### Majors

_None._

### Minors

_None._

### Nits

_None._

### UX (feel-better-ifs)

_None._

## Coverage

- Driver backend: `pty`
- Keys pressed: 2254 (unique: 21)
- State samples: 368 (unique: 357)
- Score samples: 0
- Milestones captured: 1
- Phase durations (s): A=216.1, B=7.5, C=48.1
- Snapshots: `/tmp/tui-dogfood-H9cTqF/reports/snaps/minesweeper-tui-20260423-102647`

Unique keys exercised: /, 3, :, ?, H, R, c, down, enter, escape, h, left, n, p, question_mark, r, right, shift+slash, space, up, z

### Coverage notes

- **[CN1] Phase B exited early due to saturation**
  - State hash unchanged for 10 consecutive samples during the stress probe; remaining keys skipped.

## Milestones

| Event | t (s) | Interest | File | Note |
|---|---|---|---|---|
| first_input | 0.1 | 0.0 | `minesweeper-tui-20260423-102647/milestones/first_input.txt` | key=right |
