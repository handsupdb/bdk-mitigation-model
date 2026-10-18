/**
 * Engine driver: runs every generated module in dependency order against a
 * fresh grid and returns the fully evaluated grid.
 *
 * Order: Inputs first (raw inputs + derived stat ratings), then Baseline and
 * Comparison (the two full model runs), then the 10 +Stat modules (per-stat
 * scaling tables), and Outputs last (summary/Pawn strings).
 */
import { setGrid, getGrid, type Grid } from './cells'
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
