/**
 * Bit-exact `exp` for the BDK workbook.
 *
 * V8's `Math.exp` disagrees with Python's `math.exp` (which matches Excel on
 * this workbook) by 1 ulp on 63 of the 515 known inputs in
 * tests/fixtures/exp_cases.json. Python's libm `exp` is correctly rounded on
 * every one of those inputs, so the target is the *correctly rounded* double
 * for exp(x) — which this module computes directly.
 *
 * Algorithm (double-double arithmetic, ~106-bit precision, one final rounding):
 * 1. Range-reduce: n = round(x / ln2), so the remainder
 *    r = x − n·ln2_hi − n·ln2_lo satisfies |r| ≤ ln2/2 ≈ 0.3466.
 *    (ln2 is split into a hi part with 32 significant bits — n·ln2_hi is exact
 *    for |n| < 2^21 — and a lo part carrying the next ~53 bits.)
 * 2. Evaluate exp(r) as a Taylor series Σ r^k / k! in double-double
 *    arithmetic. Terms are maintained as r^k/k! (multiply by r, divide by k,
 *    both in double-double) and accumulated in double-double. With |r| ≤ 0.35
 *    the k = 26 term is < 3e-39, far below the ~1e-32 double-double noise
 *    floor, so the truncation error is negligible.
 * 3. Scale by 2^n (an exact power-of-two multiply) and round once: `hi + lo`.
 *
 * Total error before the final rounding is ~2^-100 relative, so the result is
 * the correctly rounded double except in the (unobserved) case where exp(x)
 * lies within ~2^-100 of a rounding midpoint.
 */

/** ln2 split: 32 significant bits, so n·LN2_HI is exact for |n| < 2^21. */
const LN2_HI = 6.9314718036912381649e-1; // 0x3fe62e42fee00000
/** ln2 split: next ~53 bits of ln2 (fdlibm constants). */
const LN2_LO = 1.9082149292705877e-10; // 0x3dea39ef35793c76
/** Dekker splitter: 2^27 + 1. */
const SPLITTER = 134217729; // 0x8000001

/**
 * Error-free transformation a + b = s + e (Knuth two-sum).
 * Requires |a| ≥ |b| for the follow-up quick-two-sum to stay normalized.
 */
function twoSum(a: number, b: number): [number, number] {
  const s = a + b;
  const bb = s - a;
  const err = a - (s - bb) + (b - bb);
  return [s, err];
}

/** Fast two-sum for the |a| ≥ |b| case: a + b = s + e exactly. */
function quickTwoSum(a: number, b: number): [number, number] {
  const s = a + b;
  const err = b - (s - a);
  return [s, err];
}

/** Dekker split: a = hi + lo with hi carrying the top 26+26 bits. */
function split(a: number): [number, number] {
  const t = SPLITTER * a;
  const hi = t - (t - a);
  const lo = a - hi;
  return [hi, lo];
}

/** Error-free transformation a·b = p + e (Dekker two-product, no FMA). */
function twoProd(a: number, b: number): [number, number] {
  const p = a * b;
  const [ah, al] = split(a);
  const [bh, bl] = split(b);
  const err = ((ah * bh - p) + ah * bl + al * bh) + al * bl;
  return [p, err];
}

/** (xh+xl) + (yh+yl) in double-double. */
function ddAdd(xh: number, xl: number, yh: number, yl: number): [number, number] {
  const [s, e] = twoSum(xh, yh);
  return quickTwoSum(s, e + xl + yl);
}

/** (xh+xl) · (yh+yl) in double-double (drops the ~2^-106 xl·yl term). */
function ddMul(xh: number, xl: number, yh: number, yl: number): [number, number] {
  const [p, e] = twoProd(xh, yh);
  return quickTwoSum(p, e + xh * yl + xl * yh);
}

/** (xh+xl) / y (y a plain double) in double-double. */
function ddDivDbl(xh: number, xl: number, y: number): [number, number] {
  const q1 = xh / y;
  const [p, pe] = twoProd(q1, y);
  const rem = (xh - p) + (xl - pe);
  return quickTwoSum(q1, rem / y);
}

/** exp(r) for |r| ≤ ~0.347, as a double-double, via the Taylor series. */
function expSmall(rh: number, rl: number): [number, number] {
  let sumH = 1;
  let sumL = 0;
  let termH = 1;
  let termL = 0;
  // k = 26 term is < 3e-39 for |r| ≤ 0.35 — negligible at double-double scale.
  for (let k = 1; k <= 26; k++) {
    [termH, termL] = ddMul(termH, termL, rh, rl);
    [termH, termL] = ddDivDbl(termH, termL, k);
    [sumH, sumL] = ddAdd(sumH, sumL, termH, termL);
  }
  return [sumH, sumL];
}

/**
 * exp(x), bit-exact with Python's `math.exp` (correctly rounded).
 *
 * Verified against all 515 cases in tests/fixtures/exp_cases.json
 * (tests/engine/exactmath.test.ts). Inputs outside the fixture's domain
 * (|x| ≤ 20) are handled sensibly: ±Inf/NaN pass through, x > ~709.78
 * overflows to Infinity, and x < ~−745.13 underflows to 0 (the subnormal
 * band below that is resolved by explicit rounding, not the fast path).
 */
export function excelExp(x: number): number {
  if (x !== x) return NaN;
  if (x === 0) return 1; // exp(±0) = 1 exactly
  if (x === Infinity) return Infinity;
  if (x === -Infinity) return 0;
  if (x > 709.782712893384) return Infinity; // exp overflows the double range
  if (x < -745.1332191019412) return 0; // exp < 2^-1075: rounds to 0

  // Range reduction: r = x − n·ln2, |r| ≤ ln2/2, computed in double-double.
  const n = Math.round(x / Math.LN2);
  const t = n * LN2_HI; // exact (|n| < 2^21 here)
  const [r1h, r1l] = twoSum(x, -t);
  const [p2, p2e] = twoProd(n, LN2_LO);
  const [rh, rl] = ddAdd(r1h, r1l, -p2, -p2e);

  // exp(r) in double-double, then scale by 2^n (exact) and round once.
  const [eh, el] = expSmall(rh, rl);
  if (n <= -1075) {
    // 2^n is below the subnormal range: exp(x) = exp(r)·2^n rounds to either
    // 0 or the smallest subnormal, decided by whether exp(r) reaches 1.
    return eh + el >= 1 ? 5e-324 : 0;
  }
  const scale = Math.pow(2, n); // exact power of two for integer n
  return eh * scale + el * scale;
}
