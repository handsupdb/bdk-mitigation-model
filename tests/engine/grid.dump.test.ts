import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { evaluateAll } from '../../src/engine/evaluate'

describe('grid dump', () => {
  it('dump grid', () => {
    const grid = evaluateAll()

    // Diagnostic artifact: the fully evaluated grid as {"<Sheet!Ref>": value}.
    // (NaN values serialize to null in JSON.)
    const outPath = path.join(import.meta.dirname, '../fixtures/grid_dump.json')
    fs.writeFileSync(outPath, JSON.stringify(grid, null, 2))

    const entries = Object.entries(grid)
    const total = entries.length
    const nanCount = entries.filter(
      ([, value]) => typeof value === 'number' && Number.isNaN(value),
    ).length
    const stringCount = entries.filter(
      ([, value]) => typeof value === 'string',
    ).length

    console.log(`total cells: ${total}`)
    console.log(`NaN cells: ${nanCount}`)
    console.log(`string-value cells: ${stringCount}`)

    expect(total).toBeGreaterThan(15000)
  })
})
