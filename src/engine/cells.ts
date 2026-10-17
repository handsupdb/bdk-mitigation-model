/**
 * TypeScript runtime for generated engine modules.
 *
 * Generated modules (see tools/formula_ts.py) contain cell-ref consts and call
 * these helpers to read the current grid and do Excel-ish arithmetic:
 *
 *   - `G('Sheet','Ref')`   single-cell lookup
 *   - `R('Sheet','A1','B2')` rectangle expansion (columns outer, rows inner)
 *   - `sum` / `max` / `min`  over values and arrays (non-numbers ignored)
 *   - `if3(c, a, b)`        IF with spreadsheet truthiness (number !== 0)
 *   - `isBlank` / `n`      blank checks and numeric coercion
 *
 * Arithmetic on CellValue in generated code relies on JS coercion
 * (null -> 0 in numeric ops); these helpers keep that convention.
 */

/** A cell value: number, string, or null (null = blank cell). */
export type CellValue = number | string | null

/** Cell grid keyed `'Sheet!Ref'` (e.g. `'Baseline!N15'`). */
export type Grid = Record<string, CellValue>

/** Current grid the generated modules read from. */
let grid: Grid = {}

/** Replace the current grid (e.g. after recomputing inputs). */
export function setGrid(g: Grid): void {
  grid = g
}

/** The current grid (live reference). */
export function getGrid(): Grid {
  return grid
}

/** Look up a single cell. Sheet name and ref are used exactly as given. */
export function G(sheet: string, ref: string): CellValue {
  const v = grid[`${sheet}!${ref}`]
  return v === undefined ? null : v
}

/**
 * Expand the rectangle between two corner refs (either corner order) and
 * return its cell values, iterating columns outer and rows inner:
 * `R('S','A1','B2')` -> [S!A1, S!A2, S!B1, S!B2]. Missing cells -> null.
 */
export function R(sheet: string, a: string, b: string): CellValue[] {
  const ca = lettersToCol(a)
  const ra = rowOf(a)
  const cb = lettersToCol(b)
  const rb = rowOf(b)
  const colLo = Math.min(ca, cb)
  const colHi = Math.max(ca, cb)
  const rowLo = Math.min(ra, rb)
  const rowHi = Math.max(ra, rb)
  const out: CellValue[] = []
  for (let col = colLo; col <= colHi; col++) {
    for (let row = rowLo; row <= rowHi; row++) {
      out.push(G(sheet, colToLetters(col) + row))
    }
  }
  return out
}

/** Flatten args (one array level) keeping only actual numbers. */
function numbers(args: (CellValue | CellValue[])[]): number[] {
  const out: number[] = []
  for (const arg of args) {
    if (typeof arg === 'number') {
      out.push(arg)
    } else if (Array.isArray(arg)) {
      for (const v of arg) {
        if (typeof v === 'number') out.push(v)
      }
    }
  }
  return out
}

/** Sum of all numbers in args (arrays flattened); 0 when there are none. */
export function sum(...args: (CellValue | CellValue[])[]): number {
  let total = 0
  for (const x of numbers(args)) total += x
  return total
}

/** Max of all numbers in args; 0 when there are none. */
export function max(...args: (CellValue | CellValue[])[]): number {
  let best: number | null = null
  for (const x of numbers(args)) {
    if (best === null || x > best) best = x
  }
  return best ?? 0
}

/** Min of all numbers in args; 0 when there are none. */
export function min(...args: (CellValue | CellValue[])[]): number {
  let best: number | null = null
  for (const x of numbers(args)) {
    if (best === null || x < best) best = x
  }
  return best ?? 0
}

/**
 * Excel-style IF: the condition is truthy only when it is a number !== 0.
 * Blank (null) and strings (even 'TRUE'/'0'-like) take the else-branch.
 */
export function if3(c: CellValue, a: CellValue, b: CellValue): CellValue {
  return typeof c === 'number' && c !== 0 ? a : b
}

/** True only for blank cells (null; also tolerates undefined). */
export function isBlank(x: CellValue): boolean {
  return x == null
}

/** Numeric coercion: numbers pass through; strings and null -> 0. */
export function n(x: CellValue): number {
  return typeof x === 'number' ? x : 0
}

/** Column letters of a ref ('B12' -> 2). Case-insensitive; '$' ignored. */
function lettersToCol(ref: string): number {
  const m = /^\$?([A-Za-z]+)/.exec(ref)
  if (!m) throw new Error(`invalid cell ref: ${ref}`)
  let col = 0
  for (const ch of m[1].toUpperCase()) {
    col = col * 26 + (ch.charCodeAt(0) - 64)
  }
  return col
}

/** Row number of a ref ('B12' -> 12). '$' ignored. */
function rowOf(ref: string): number {
  const m = /\$?([0-9]+)$/.exec(ref)
  if (!m) throw new Error(`invalid cell ref: ${ref}`)
  return parseInt(m[1], 10)
}

/** 1-based column index to letters (1 -> 'A', 27 -> 'AA'). */
function colToLetters(col: number): string {
  let s = ''
  let c = col
  while (c > 0) {
    const rem = (c - 1) % 26
    s = String.fromCharCode(65 + rem) + s
    c = Math.floor((c - 1) / 26)
  }
  return s
}
