import { describe, expect, it } from 'vitest'
import { isClose } from './helpers/tolerance'

type Fixture = Record<string, unknown>

const fixtures = import.meta.glob<Fixture>('./fixtures/golden/*.json', {
  eager: true,
  import: 'default',
})

function loadFixture(sheet: string): Fixture | undefined {
  return fixtures[`./fixtures/golden/${sheet}.json`]
}

/** Cell entries of a fixture, excluding the "uncached" metadata key. */
function cellEntries(f: Fixture): [string, unknown][] {
  return Object.entries(f).filter(([k]) => k !== 'uncached')
}

// All data sheets of the spreadsheet. (The task brief said "13 data sheets",
// but Inputs, Outputs, Baseline, Comparison + the 10 +Stat sheets = 14;
// Instructions is the only non-data sheet.)
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

describe('golden fixtures', () => {
  it('has a fixture with >100 entries for every data sheet', () => {
    for (const sheet of DATA_SHEETS) {
      const f = loadFixture(sheet)
      expect(f, `missing fixture for ${sheet}`).toBeDefined()
      const n = cellEntries(f!).length
      expect(n, `${sheet} has only ${n} cell entries`).toBeGreaterThan(100)
    }
  })

  it('Baseline N15 is ~0.99966 (rel tol 1e-9)', () => {
    const f = loadFixture('Baseline')!
    expect(isClose(f.N15 as number, 0.9996620211)).toBe(true)
  })

  it('Baseline O10 is ~3720571 (rel tol 1e-9)', () => {
    const f = loadFixture('Baseline')!
    expect(isClose(f.O10 as number, 3720571.088)).toBe(true)
  })

  it('some Outputs cell contains a Pawn string', () => {
    const f = loadFixture('Outputs')!
    const hit = cellEntries(f).some(
      ([, v]) => typeof v === 'string' && v.includes('Pawn:'),
    )
    expect(hit, 'no Outputs value contains "Pawn:"').toBe(true)
  })
})
