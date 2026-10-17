import { beforeEach, describe, expect, it } from 'vitest'
import {
  G,
  R,
  getGrid,
  if3,
  isBlank,
  max,
  min,
  n,
  setGrid,
  sum,
  type Grid,
} from '../../src/engine/cells'

const grid: Grid = {
  'Sheet1!A1': 1,
  'Sheet1!A2': 2,
  'Sheet1!B1': 3,
  'Sheet1!B2': 4,
  'Sheet1!C1': 'text',
  // 'Sheet1!C2' intentionally missing
  'Inputs!B2': 10,
}

beforeEach(() => {
  setGrid(grid)
})

describe('setGrid/getGrid', () => {
  it('getGrid returns the grid that was set', () => {
    expect(getGrid()).toBe(grid)
  })

  it('setGrid replaces the grid', () => {
    setGrid({ 'Other!A1': 7 })
    expect(getGrid()).toEqual({ 'Other!A1': 7 })
    expect(G('Other', 'A1')).toBe(7)
  })
})

describe('G', () => {
  it('looks up cells by Sheet!Ref', () => {
    expect(G('Sheet1', 'A1')).toBe(1)
    expect(G('Inputs', 'B2')).toBe(10)
    expect(G('Sheet1', 'C1')).toBe('text')
  })

  it('returns null for missing cells', () => {
    expect(G('Sheet1', 'C2')).toBeNull()
    expect(G('Nope', 'A1')).toBeNull()
  })

  it('uses the sheet name exactly as given (case-sensitive)', () => {
    expect(G('sheet1', 'A1')).toBeNull()
  })
})

describe('R', () => {
  it('expands a 2x2 rectangle, columns outer and rows inner', () => {
    expect(R('Sheet1', 'A1', 'B2')).toEqual([1, 2, 3, 4])
  })

  it('accepts corners in either order', () => {
    expect(R('Sheet1', 'B2', 'A1')).toEqual([1, 2, 3, 4])
  })

  it('includes strings and nulls for missing cells', () => {
    expect(R('Sheet1', 'A1', 'C2')).toEqual([1, 2, 3, 4, 'text', null])
  })

  it('returns all nulls for a sheet not in the grid', () => {
    expect(R('Nope', 'A1', 'B2')).toEqual([null, null, null, null])
  })

  it('degenerates to a single cell when both corners match', () => {
    expect(R('Sheet1', 'B2', 'B2')).toEqual([4])
  })
})

describe('sum', () => {
  it('flattens arrays and keeps only numbers', () => {
    expect(sum(1, '2', null, [3])).toBe(4)
  })

  it('returns 0 when there are no numbers', () => {
    expect(sum()).toBe(0)
    expect(sum('a', null, ['b'])).toBe(0)
  })

  it('adds negatives and array contents', () => {
    expect(sum(-1, [-2, 5])).toBe(2)
  })
})

describe('max/min', () => {
  it('pick the largest/smallest number across values and arrays', () => {
    expect(max(1, [5, 2], 3)).toBe(5)
    expect(min(2, [1, 9])).toBe(1)
  })

  it('return 0 when there are no numbers', () => {
    expect(max('a', null, ['b'])).toBe(0)
    expect(min()).toBe(0)
  })

  it('do not clamp negative-only inputs to 0', () => {
    expect(max(-5, -1)).toBe(-1)
    expect(min(-5, -1)).toBe(-5)
  })
})

describe('if3', () => {
  it('takes the then-branch only for numbers !== 0', () => {
    expect(if3(1, 'yes', 'no')).toBe('yes')
    expect(if3(-1, 'yes', 'no')).toBe('yes')
    expect(if3(2, 10, 20)).toBe(10)
  })

  it('takes the else-branch for 0, null, and strings', () => {
    expect(if3(0, 'yes', 'no')).toBe('no')
    expect(if3(null, 'yes', 'no')).toBe('no')
    expect(if3('x', 'yes', 'no')).toBe('no')
  })
})

describe('isBlank', () => {
  it('is true only for null', () => {
    expect(isBlank(null)).toBe(true)
  })

  it('is false for 0, empty string, and other values', () => {
    expect(isBlank(0)).toBe(false)
    expect(isBlank('')).toBe(false)
    expect(isBlank('x')).toBe(false)
    expect(isBlank(5)).toBe(false)
  })
})

describe('n', () => {
  it('passes numbers through', () => {
    expect(n(5)).toBe(5)
    expect(n(0)).toBe(0)
    expect(n(-2.5)).toBe(-2.5)
  })

  it('maps strings and null to 0', () => {
    expect(n('x')).toBe(0)
    expect(n('5')).toBe(0)
    expect(n(null)).toBe(0)
  })
})
