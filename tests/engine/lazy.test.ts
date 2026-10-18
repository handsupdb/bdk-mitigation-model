import { describe, expect, it } from 'vitest';
import { ifL, memo } from '../../src/engine/lazy';

describe('ifL', () => {
  it('returns the then-branch for a nonzero number condition', () => {
    expect(ifL(1, () => 1, () => 2)).toBe(1);
  });

  it('returns the then-branch for a boolean true condition', () => {
    expect(ifL(true, () => 1, () => 2)).toBe(1);
  });

  it('returns the else-branch for a boolean false condition', () => {
    expect(ifL(false, () => 1, () => 2)).toBe(2);
  });

  it('returns the else-branch for 0, null, and string conditions', () => {
    expect(ifL(0, () => 1, () => 2)).toBe(2);
    expect(ifL(null, () => 1, () => 2)).toBe(2);
    expect(ifL('x', () => 1, () => 2)).toBe(2);
  });

  it('evaluates only the taken branch', () => {
    let thenCalls = 0;
    let elseCalls = 0;
    const then = (): number => {
      thenCalls += 1;
      return 1;
    };
    const else_ = (): number => {
      elseCalls += 1;
      return 2;
    };

    ifL(1, then, else_);
    expect(thenCalls).toBe(1);
    expect(elseCalls).toBe(0);

    ifL(0, then, else_);
    expect(thenCalls).toBe(1);
    expect(elseCalls).toBe(1);
  });
});

describe('memo', () => {
  it('invokes fn exactly once across two calls', () => {
    let calls = 0;
    const cached = memo(() => {
      calls += 1;
      return 42;
    });

    expect(cached()).toBe(42);
    expect(cached()).toBe(42);
    expect(calls).toBe(1);
  });
});
