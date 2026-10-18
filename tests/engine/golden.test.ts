import { beforeAll, describe, expect, it } from 'vitest'
import { evaluateAll } from '../../src/engine/evaluate'
import type { Grid } from '../../src/engine/cells'
import { isClose } from '../helpers/tolerance'

type Fixture = Record<string, unknown>

const fixtures = import.meta.glob<Fixture>('../fixtures/golden/*.json', {
  eager: true,
  import: 'default',
})

function loadFixture(sheet: string): Fixture | undefined {
  return fixtures[`../fixtures/golden/${sheet}.json`]
}

/**
 * Fixture filename -> raw spreadsheet sheet name: a leading '_' becomes '+'
 * and the remaining '_' become spaces ('_Weapon_DPS' -> '+Weapon DPS').
 */
function rawSheetName(file: string): string {
  return file.replace(/^_/, '+').replace(/_/g, ' ')
}

/**
 * Cell entries of a fixture, excluding the "uncached" metadata key and any
 * refs listed among its members (those cells have no cached oracle value).
 */
function cellEntries(f: Fixture): [string, unknown][] {
  const uncached = Array.isArray(f.uncached) ? (f.uncached as string[]) : []
  return Object.entries(f).filter(
    ([k]) => k !== 'uncached' && !uncached.includes(k),
  )
}

// All 14 data sheets (fixture filenames); Instructions is not a data sheet.
const DATA_SHEETS = [
  'Inputs',
  'Outputs',
  'Baseline',
  'Comparison',
  '_Armor',
  '_Avoidance',
  '_Critical_Strike',
  '_Haste',
  '_Leech',
  '_Mastery',
  '_Stamina',
  '_Strength',
  '_Versatility',
  '_Weapon_DPS',
] as const

/** Render an actual grid value for mismatch logs: JSON, capped at 80 chars. */
function showActual(actual: unknown): string {
  const s = JSON.stringify(actual) ?? String(actual)
  return s.length > 80 ? s.slice(0, 79) + '…' : s
}

/**
 * Compare one cell: numbers by relative tolerance (1e-9), everything else
 * (strings, booleans) exactly.
 */
function cellMatches(expected: unknown, actual: unknown): boolean {
  if (typeof expected === 'number') {
    return typeof actual === 'number' && isClose(actual, expected, 1e-9)
  }
  return actual === expected
}

describe('engine grid vs golden fixtures (every evaluated cell)', () => {
  let grid: Grid

  beforeAll(() => {
    grid = evaluateAll()
  })

  for (const file of DATA_SHEETS) {
    const sheet = rawSheetName(file)

    it(`${sheet}: every fixture cell matches the engine grid`, () => {
      const f = loadFixture(file)
      expect(f, `missing fixture for ${file}`).toBeDefined()
      const entries = cellEntries(f!)

      let pass = 0
      let fail = 0
      const mismatches: string[] = []
      for (const [ref, expected] of entries) {
        const actual = grid[`${sheet}!${ref}`]
        if (cellMatches(expected, actual)) {
          pass++
        } else {
          fail++
          if (mismatches.length < 10) {
            mismatches.push(
              `  ${sheet}!${ref}: expected=${JSON.stringify(expected)} actual=${showActual(actual)}`,
            )
          }
        }
      }

      // Log per-sheet counts and the first mismatches BEFORE asserting, so a
      // failure report always carries them.
      console.log(`[${sheet}] pass=${pass} fail=${fail} (of ${entries.length})`)
      for (const m of mismatches) console.log(m)

      expect(
        fail,
        `${sheet}: ${fail}/${entries.length} cells mismatch; first mismatches:\n${mismatches.join('\n')}`,
      ).toBe(0)
    })
  }
})
