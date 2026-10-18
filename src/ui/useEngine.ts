/**
 * React binding for the calculation engine.
 *
 * Holds the user's Inputs overrides (keys are Inputs cell refs like 'C147',
 * values are number|string|null) as React state and re-runs the whole
 * workbook through `evaluateWithInputs` whenever they change, exposing the
 * resulting grid keyed `'Sheet!Ref'` (e.g. `'Baseline!N15'`).
 */
import { useCallback, useMemo, useState } from 'react'
import { evaluateWithInputs } from '../engine/evaluate'
import type { CellValue, Grid } from '../engine/cells'

export function useEngine(): {
  overrides: Record<string, CellValue>
  setOverride: (ref: string, v: CellValue) => void
  clearOverride: (ref: string) => void
  grid: Grid
} {
  const [overrides, setOverrides] = useState<Record<string, CellValue>>({})

  /** Set (or replace) one Inputs override; the grid recomputes. */
  const setOverride = useCallback((ref: string, v: CellValue) => {
    setOverrides((prev) => ({ ...prev, [ref]: v }))
  }, [])

  /** Remove one Inputs override, restoring the saved profile value. */
  const clearOverride = useCallback((ref: string) => {
    setOverrides((prev) => {
      if (!(ref in prev)) return prev
      const next = { ...prev }
      delete next[ref]
      return next
    })
  }, [])

  const grid = useMemo(() => evaluateWithInputs(overrides), [overrides])

  return { overrides, setOverride, clearOverride, grid }
}
