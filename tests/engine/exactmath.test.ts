import { describe, expect, it } from 'vitest';
import { excelExp } from '../../src/engine/exactmath';

interface ExpCase {
  x: number;
  expected_hex: string;
}

// Spec table: tests/fixtures/exp_cases.json — every case must pass bit-exactly.
// Loaded via import.meta.glob (as in numstr.test.ts; this repo has no
// @types/node, so node:fs in tests does not typecheck).
const modules = import.meta.glob<ExpCase[]>('../fixtures/exp_cases.json', {
  eager: true,
  import: 'default',
});
const cases = modules['../fixtures/exp_cases.json'];

const view = new DataView(new ArrayBuffer(8));

/** Raw IEEE-754 bit pattern of a double, as a bigint (−0 ≠ +0). */
function bitsOf(x: number): bigint {
  view.setFloat64(0, x, true);
  return view.getBigUint64(0, true);
}

/**
 * Parse a C99 hex-float literal of the exact form the fixture uses:
 * `0x1.<13 hex digits>p<±decimal exponent>` (a normal, positive double).
 * Bit assembly: mantissa = 0x<digits> (52 bits), biased exponent = e + 1023.
 */
function parseHexFloat(s: string): number {
  const m = /^0x1\.([0-9a-f]{13})p([+-]?\d+)$/.exec(s);
  if (!m) throw new Error(`unexpected expected_hex format: ${s}`);
  const mantissa = BigInt(`0x${m[1]}`); // exactly 52 bits
  const biasedExp = BigInt(m[2]) + 1023n;
  if (biasedExp < 1n || biasedExp > 2046n) {
    throw new Error(`expected_hex not a normal double: ${s}`);
  }
  const bits = (biasedExp << 52n) | mantissa;
  view.setBigUint64(0, bits, true);
  return view.getFloat64(0, true);
}

describe('excelExp (bit-exact exp, spec: tests/fixtures/exp_cases.json)', () => {
  it('loads the full 515-case spec table', () => {
    expect(cases, 'missing fixture table exp_cases.json').toBeDefined();
    expect(cases.length).toBe(515);
  });

  it('parses hex-float literals exactly', () => {
    // 1.0, 0.5, and the first fixture case exp(-0.3049149868854626).
    expect(parseHexFloat('0x1.0000000000000p+0')).toBe(1);
    expect(parseHexFloat('0x1.0000000000000p-1')).toBe(0.5);
    expect(parseHexFloat('0x1.797072ecb6743p-1')).toBe(0.7371860422092386);
  });

  it('handles specials', () => {
    expect(excelExp(0)).toBe(1);
    expect(bitsOf(excelExp(-0))).toBe(bitsOf(1)); // exp(−0) = +1
    expect(excelExp(NaN)).toBeNaN();
    expect(excelExp(Infinity)).toBe(Infinity);
    expect(excelExp(-Infinity)).toBe(0);
  });

  for (const [i, c] of cases.entries()) {
    const expected = parseHexFloat(c.expected_hex);
    it(`case ${i + 1}/515: exp(${c.x}) -> ${c.expected_hex}`, () => {
      expect(bitsOf(excelExp(c.x))).toBe(bitsOf(expected));
    });
  }
});
