import { describe, expect, it } from 'vitest';

import { andN, EQ, GE, GT, LT, NE, not, orN } from '../../src/engine/compare';

describe('compare', () => {
  it('compares strings as strings and coerces null to 0 numerically', () => {
    expect(EQ(null, 0)).toBe(true);
    expect(EQ('a', 'a')).toBe(true);
    expect(EQ('a', 'b')).toBe(false);
    expect(GT(2, null)).toBe(true);
    expect(LT(null, 1)).toBe(true);
    expect(GE(2, 2)).toBe(true);
    expect(NE(1, 2)).toBe(true);
  });

  it('treats booleans and non-zero numbers as truthy', () => {
    expect(orN(0, 1)).toBe(true);
    expect(orN(0, null)).toBe(false);
    expect(orN(true, 0)).toBe(true);
    expect(andN(1, 2)).toBe(true);
    expect(andN(1, 0)).toBe(false);
    expect(not(0)).toBe(true);
    expect(not(null)).toBe(true);
    expect(not(1)).toBe(false);
    expect(not('x')).toBe(true);
    expect(not(true)).toBe(false);
    expect(not(false)).toBe(true);
  });
});
