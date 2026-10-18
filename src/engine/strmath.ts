import type { CellValue } from './cells';
import { excelNumToStr } from './numstr';

/**
 * String-concatenation and rounding helpers for generated formula code.
 *
 * - `S` mirrors Excel's `&` operator: blanks vanish, numbers render through
 *   `excelNumToStr`, and strings pass through unchanged.
 * - `roundAway` mirrors Excel's ROUND: ties round half away from zero, and a
 *   negative `d` rounds left of the decimal point (d = -2 -> hundreds).
 */

/** Excel `&` concatenation: null -> '', number -> excelNumToStr(x), string -> itself. */
export function S(...parts: CellValue[]): string {
  let out = '';
  for (const p of parts) {
    if (p == null) continue;
    out += typeof p === 'number' ? excelNumToStr(p) : p;
  }
  return out;
}

/**
 * Excel ROUND: half away from zero, `d` decimals (negative `d` rounds left of
 * the decimal point). Non-numbers (strings, blanks) coerce to 0.
 */
export function roundAway(x: CellValue, d: number): number {
  if (typeof x !== 'number') return 0;
  const sign = x < 0 ? -1 : 1;
  const ax = Math.abs(x);
  if (d >= 0) {
    const f = Math.pow(10, d);
    return (sign * Math.round(ax * f)) / f;
  }
  const p = Math.pow(10, -d);
  return sign * Math.round(ax / p) * p;
}
