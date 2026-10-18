/**
 * Engine driver: runs every generated module in dependency order against a
 * fresh grid and returns the fully evaluated grid.
 *
 * Order: Inputs first (raw inputs + derived stat ratings), then Baseline and
 * Comparison (the two full model runs), then the 10 +Stat modules (per-stat
 * scaling tables), and Outputs last (summary/Pawn strings).
 */
import { setGrid, getGrid, type Grid, type CellValue } from './cells'
import { evaluateInputs } from './generated/Inputs'
import { evaluateBaseline } from './generated/Baseline'
import { evaluateComparison } from './generated/Comparison'
import { evaluateArmor } from './generated/_Armor'
import { evaluateAvoidance } from './generated/_Avoidance'
import { evaluateCriticalStrike } from './generated/_Critical_Strike'
import { evaluateHaste } from './generated/_Haste'
import { evaluateLeech } from './generated/_Leech'
import { evaluateMastery } from './generated/_Mastery'
import { evaluateStamina } from './generated/_Stamina'
import { evaluateStrength } from './generated/_Strength'
import { evaluateVersatility } from './generated/_Versatility'
import { evaluateWeaponDps } from './generated/_Weapon_DPS'
import { evaluateOutputs } from './generated/Outputs'

/**
 * Evaluate the entire workbook from scratch: reset the grid to empty, run
 * every generated module in order, and return the resulting grid keyed by
 * `'Sheet!Ref'`.
 */
export function evaluateAll(): Grid {
  setGrid({})
  evaluateInputs()
  evaluateBaseline()
  evaluateComparison()
  evaluateArmor()
  evaluateAvoidance()
  evaluateCriticalStrike()
  evaluateHaste()
  evaluateLeech()
  evaluateMastery()
  evaluateStamina()
  evaluateStrength()
  evaluateVersatility()
  evaluateWeaponDps()
  evaluateOutputs()
  return getGrid()
}

/**
 * Sum the number-valued cells `Inputs!C<lo>`…`Inputs!C<hi>` in row order,
 * skipping non-numbers — the same term order the generated Inputs module's
 * SUM uses, so an untouched range reproduces its total bit-identically.
 */
function sumInputsColumnC(grid: Grid, lo: number, hi: number): number {
  let total = 0
  for (let row = lo; row <= hi; row++) {
    const v = grid[`Inputs!C${row}`]
    if (typeof v === 'number') total += v
  }
  return total
}

/**
 * Evaluate the entire workbook with input overrides applied on top of the
 * saved profile: `overrides` maps Inputs cell refs (e.g. `'C147'`) to values
 * (number|string|null) that replace the saved literals in the grid.
 *
 * The two Inputs point totals (`Inputs!C86` = sum of the DK talent ranks
 * C40…C85, `Inputs!C130` = sum of C88…C129) are formulas the saved module
 * computed from the pre-override literals, so they are recomputed from the
 * overridden grid before the rest of the model runs. With no overrides the
 * result matches `evaluateAll()` bit-identically.
 */
export function evaluateWithInputs(overrides: Record<string, CellValue>): Grid {
  setGrid({})
  evaluateInputs()

  // Overwrite the saved literals with the caller's values.
  const grid = getGrid()
  for (const [ref, value] of Object.entries(overrides)) {
    grid[`Inputs!${ref}`] = value
  }

  // Recompute the two Inputs point totals from the (possibly overridden)
  // grid so talent-rank overrides propagate to everything downstream.
  grid['Inputs!C86'] = sumInputsColumnC(grid, 40, 85)
  grid['Inputs!C130'] = sumInputsColumnC(grid, 88, 129)

  evaluateBaseline()
  evaluateComparison()
  evaluateArmor()
  evaluateAvoidance()
  evaluateCriticalStrike()
  evaluateHaste()
  evaluateLeech()
  evaluateMastery()
  evaluateStamina()
  evaluateStrength()
  evaluateVersatility()
  evaluateWeaponDps()
  evaluateOutputs()
  return getGrid()
}
