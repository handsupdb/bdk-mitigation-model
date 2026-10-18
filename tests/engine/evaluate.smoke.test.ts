import { describe, expect, it } from 'vitest'
import { evaluateAll } from '../../src/engine/evaluate'
import { isClose } from '../helpers/tolerance'

describe('engine evaluateAll smoke', () => {
  it('runs the full engine without throwing', () => {
    expect(() => evaluateAll()).not.toThrow()
  })

  it('produces a populated grid matching golden cells', () => {
    const grid = evaluateAll()
    const cellCount = Object.keys(grid).length
    console.log(`total grid cell count: ${cellCount}`)
    expect(cellCount).toBeGreaterThan(0)

    const golden: Array<{ key: string; expected: number }> = [
      { key: 'Baseline!N15', expected: 0.9996620210884503 },
      { key: 'Baseline!O10', expected: 3720571.088 },
      { key: 'Baseline!T42', expected: 0.4013494365 },
    ]
    for (const { key, expected } of golden) {
      const actual = grid[key]
      // Print the actual value before asserting so a mismatch is visible.
      console.log(`${key}: actual=${String(actual)} expected=${expected}`)
      expect(
        typeof actual === 'number' && isClose(actual, expected, 1e-9),
        `${key}: actual=${String(actual)} expected=${expected}`,
      ).toBe(true)
    }
  })
})
