import type { CellValue } from './cells';

/**
 * Lazy conditional for cell values.
 *
 * A condition is considered truthy when it is a boolean `true` or a
 * nonzero number. Strings (including non-empty ones) and null are
 * falsy, mirroring spreadsheet IF semantics: comparison results
 * (EQ/GT/ISBLANK/NOT) arrive as JS booleans.
 *
 * Only the taken branch is evaluated.
 */
export function ifL(
  c: CellValue | boolean,
  a: () => CellValue,
  b: () => CellValue,
): CellValue {
  const truthy =
    (typeof c === 'boolean' && c) || (typeof c === 'number' && c !== 0);
  return truthy ? a() : b();
}

/**
 * Memoize a cell-value computation.
 *
 * The wrapped function is evaluated at most once, on the first call;
 * every subsequent call returns the cached result. A `cached` flag is
 * used (rather than inspecting the value) so a cached `null` result
 * is still treated as computed.
 */
export function memo(fn: () => CellValue): () => CellValue {
  let cached = false;
  let value: CellValue = null;
  return (): CellValue => {
    if (!cached) {
      value = fn();
      cached = true;
    }
    return value;
  };
}
