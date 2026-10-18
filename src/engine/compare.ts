import type { CellValue } from './cells';

/**
 * Comparison and logic helpers for generated formula code.
 *
 * Mirrors the spreadsheet conventions used elsewhere in the engine:
 * - Only numbers are truthy, and 0 is falsy (see `truthy`).
 * - When both operands are strings they compare as strings; otherwise the
 *   comparison is numeric, with null (and, in the mixed case, strings)
 *   coercing to 0 — the same coercion `n()` applies in cells.ts.
 */

/** True only for non-zero numbers. Strings and null are falsy. */
function truthy(x: CellValue): boolean {
  return typeof x === 'number' && x !== 0;
}

/** Numeric coercion for comparisons: numbers pass through; strings and null -> 0. */
function num(x: CellValue): number {
  return typeof x === 'number' ? x : 0;
}

/**
 * Three-way compare: string comparison when both operands are strings,
 * otherwise numeric (null -> 0). Returns < 0, 0, or > 0.
 */
function compare(a: CellValue, b: CellValue): number {
  if (typeof a === 'string' && typeof b === 'string') {
    return a < b ? -1 : a > b ? 1 : 0;
  }
  const x = num(a);
  const y = num(b);
  return x < y ? -1 : x > y ? 1 : 0;
}

/** a == b (string comparison when both are strings; otherwise numeric, null -> 0). */
export function EQ(a: CellValue, b: CellValue): boolean {
  return compare(a, b) === 0;
}

/** a != b (string comparison when both are strings; otherwise numeric, null -> 0). */
export function NE(a: CellValue, b: CellValue): boolean {
  return compare(a, b) !== 0;
}

/** a > b (string comparison when both are strings; otherwise numeric, null -> 0). */
export function GT(a: CellValue, b: CellValue): boolean {
  return compare(a, b) > 0;
}

/** a < b (string comparison when both are strings; otherwise numeric, null -> 0). */
export function LT(a: CellValue, b: CellValue): boolean {
  return compare(a, b) < 0;
}

/** a >= b (string comparison when both are strings; otherwise numeric, null -> 0). */
export function GE(a: CellValue, b: CellValue): boolean {
  return compare(a, b) >= 0;
}

/** a <= b (string comparison when both are strings; otherwise numeric, null -> 0). */
export function LE(a: CellValue, b: CellValue): boolean {
  return compare(a, b) <= 0;
}

/** True when any argument is truthy (a non-zero number). */
export function orN(...args: CellValue[]): boolean {
  return args.some((x) => truthy(x));
}

/** True when every argument is truthy (a non-zero number). */
export function andN(...args: CellValue[]): boolean {
  return args.every((x) => truthy(x));
}

/** Logical negation under engine truthiness (only non-zero numbers are true). */
export function not(x: CellValue): boolean {
  return !truthy(x);
}
