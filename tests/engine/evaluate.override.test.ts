import { describe, expect, it } from 'vitest'
import { evaluateAll, evaluateWithInputs } from '../../src/engine/evaluate'

describe('engine evaluateWithInputs (input overrides)', () => {
  it('a DTPS override propagates through the reverse cascade', () => {
    const grid = evaluateWithInputs({ C147: 500000 })
    // Baseline!T10 is a direct passthrough of Inputs!C147 (DTPS).
    expect(grid['Baseline!T10']).toBe(500000)
    // Higher DTPS must raise total damage taken above the saved-profile
    // baseline (3720571.088, see evaluate.smoke.test.ts).
    expect(grid['Baseline!O10']).toBeGreaterThan(3720571.088)
  })

  it('with no overrides, reproduces evaluateAll() bit-exactly', () => {
    const fromAll = evaluateAll()['Baseline!N15']
    const fromOverrides = evaluateWithInputs({})['Baseline!N15']
    expect(typeof fromAll).toBe('number')
    expect(fromOverrides).toBe(fromAll)
  })

  it('a DK talent rank override updates the Inputs point total', () => {
    const base = evaluateAll()
    // Saved C40 rank is 1; overriding it to 2 must raise the C40…C85 sum.
    const grid = evaluateWithInputs({ C40: 2 })
    const baseTotal = base['Inputs!C86']
    expect(typeof baseTotal).toBe('number')
    expect(grid['Inputs!C86']).not.toBe(baseTotal)
    expect(grid['Inputs!C86']).toBe((baseTotal as number) + 1)
  })
})
