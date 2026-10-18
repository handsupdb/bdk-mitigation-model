import { describe, expect, it } from 'vitest';
import { S, roundAway } from '../../src/engine/strmath';

describe('S', () => {
  it('concatenates parts: strings as-is, numbers via excelNumToStr, null as empty', () => {
    expect(S('a', 1.5, null)).toBe('a1.5');
  });

  it('returns the empty string for no parts or all-null parts', () => {
    expect(S()).toBe('');
    expect(S(null, null)).toBe('');
  });
});

describe('roundAway', () => {
  it('rounds halves away from zero', () => {
    expect(roundAway(2.5, 0)).toBe(3);
    expect(roundAway(-2.5, 0)).toBe(-3);
  });

  it('rounds to d decimals', () => {
    expect(roundAway(1.2345, 2)).toBe(1.23);
  });

  it('supports negative d (round left of the decimal point)', () => {
    expect(roundAway(1234.5, -2)).toBe(1200);
  });

  it('coerces non-numbers to 0', () => {
    expect(roundAway(null, 2)).toBe(0);
    expect(roundAway('x', 2)).toBe(0);
  });
});
