# engine/reference/

Reference material for the Minesweeper engine's design.

## Difficulty canon

The Beginner/Intermediate/Expert presets we ship match the Microsoft
Windows Minesweeper conventions, which bsd-games `mines` also uses:

| Preset       | Width | Height | Mines | Density |
|--------------|-------|--------|-------|---------|
| Beginner     | 9     | 9      | 10    | 12.3%   |
| Intermediate | 16    | 16     | 40    | 15.6%   |
| Expert       | 30    | 16     | 99    | 20.6%   |

Custom boards accept 4..80 wide × 4..40 tall, mines = 1..(W*H - 9)
to preserve the safe-first-click 3×3 clearance.

## Safe-first-click guarantee

When the first cell clicked contains a mine, the engine relocates the
mine to the first mine-free cell in row-major order and recomputes
neighbour counts. Modern Microsoft Minesweeper extends this to the 3×3
neighbourhood so the first reveal always flood-fills. We follow that
convention.

## Flood-fill reveal

When a revealed cell has 0 adjacent mines, recursively reveal its 8
neighbours. Classic BFS — see `_flood_reveal` in the engine.

## Chord operation

"Chord" is the third classic op: when the player middle-clicks on a
revealed numbered cell, if the number of flags among its 8 neighbours
equals its adjacency count, all other neighbours are revealed in one
step. Fast play depends on it.

## Why a pure-Python engine

A 30×16 board with 99 mines is 480 cells. The full reveal-loss cascade
(reveal-all-mines animation) is 99 cells. No perf concern lives here.
See DECISIONS.md for the full rationale on why we did NOT vendor a
native C engine.
