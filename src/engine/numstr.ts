/**
 * Excel-style number→text coercion (the rendering used by `&` concatenation).
 *
 * Algorithm (spec: tests/fixtures/numstr_cases.json, 74 cases):
 * 1. Start from the shortest round-trip decimal, `String(x)`.
 * 2. Round to 15 significant digits, ties half away from zero.
 * 3. Trim trailing zeros (and any resulting trailing '.').
 * 4. Small magnitudes — 0 < |x| < 1e-4, tested on the pre-rounding value —
 *    render in scientific notation: uppercase 'E', no '+', no leading zeros
 *    in the exponent. (0.0001 stays plain, 9.99e-5 → 9.99E-5, and
 *    9.999999999999999e-5 → 1E-4 rather than 0.0001.)
 * 5. Everything else renders plain; integers without a decimal point.
 */

const MAX_SIG = 15;

/** A parsed decimal: value = sign · digits · 10^exp, digits has no leading zeros. */
interface Decimal {
  sign: string;
  digits: string;
  exp: number;
}

/** Parse a `String(x)` form (plain or exponential) into sign/digits/exponent. */
function parseDecimal(s: string): Decimal {
  let sign = '';
  let t = s;
  if (t.startsWith('-')) {
    sign = '-';
    t = t.slice(1);
  }
  let eExp = 0;
  const eIdx = t.search(/[eE]/);
  if (eIdx >= 0) {
    eExp = parseInt(t.slice(eIdx + 1), 10);
    t = t.slice(0, eIdx);
  }
  const dot = t.indexOf('.');
  const intPart = dot >= 0 ? t.slice(0, dot) : t;
  const fracPart = dot >= 0 ? t.slice(dot + 1) : '';
  // Leading zeros carry no value: "000163"·10^e === "163"·10^e.
  const digits = (intPart + fracPart).replace(/^0+/, '');
  return { sign, digits, exp: eExp - fracPart.length };
}

/** Round to 15 significant digits, half away from zero (rest[0] >= '5' rounds up). */
function roundSig(d: Decimal): Decimal {
  if (d.digits.length <= MAX_SIG) return d;
  const rest = d.digits.slice(MAX_SIG);
  let kept = d.digits.slice(0, MAX_SIG);
  if (rest[0] >= '5') kept = (BigInt(kept) + 1n).toString();
  return { ...d, digits: kept, exp: d.exp + (d.digits.length - MAX_SIG) };
}

/** Trim trailing zeros, value-preserving ("1200"·10^-3 → "12"·10^-1). */
function trimZeros(d: Decimal): Decimal {
  let digits = d.digits;
  let exp = d.exp;
  while (digits.length > 1 && digits.endsWith('0')) {
    digits = digits.slice(0, -1);
    exp++;
  }
  return { ...d, digits, exp };
}

/** Plain decimal rendering; integers (exp >= 0) get no decimal point. */
function renderPlain(d: Decimal): string {
  if (d.exp >= 0) return d.sign + d.digits + '0'.repeat(d.exp);
  const intLen = d.digits.length + d.exp; // digits left of the decimal point
  if (intLen > 0) {
    return d.sign + d.digits.slice(0, intLen) + '.' + d.digits.slice(intLen);
  }
  return d.sign + '0.' + '0'.repeat(-intLen) + d.digits;
}

/** Scientific rendering: d[0]('.'rest)'E'exponent — no '+', no leading zeros. */
function renderSci(d: Decimal): string {
  const exponent = d.digits.length - 1 + d.exp;
  const mantissa =
    d.digits.length === 1 ? d.digits : d.digits[0] + '.' + d.digits.slice(1);
  return d.sign + mantissa + 'E' + exponent;
}

export function excelNumToStr(x: number): string {
  if (!Number.isFinite(x)) return String(x); // NaN / ±Infinity: out of spec
  const d = trimZeros(roundSig(parseDecimal(String(x))));
  if (d.digits === '') return '0'; // 0 and -0 (String(-0) has no sign)
  return x !== 0 && Math.abs(x) < 1e-4 ? renderSci(d) : renderPlain(d);
}
