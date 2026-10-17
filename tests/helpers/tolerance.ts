/** Default relative tolerance for golden-value comparisons. */
export const DEFAULT_REL_TOL = 1e-9

/**
 * True when `actual` is within `relTol` (relative) of `expected`.
 * When `expected` is 0, falls back to an absolute tolerance of `relTol`.
 */
export function isClose(
  actual: number,
  expected: number,
  relTol: number = DEFAULT_REL_TOL,
): boolean {
  if (!Number.isFinite(actual) || !Number.isFinite(expected)) return false
  if (expected === 0) return Math.abs(actual) <= relTol
  return Math.abs(actual - expected) <= relTol * Math.abs(expected)
}
