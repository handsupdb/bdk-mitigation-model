import { describe, expect, it } from 'vitest';
import { excelNumToStr } from '../../src/engine/numstr';

interface NumStrCase {
  x: number;
  expected: string;
}

// Spec table: tests/fixtures/numstr_cases.json — every case must pass.
// Loaded via import.meta.glob (as in golden.test.ts; this repo has no
// @types/node, so node:fs in tests does not typecheck).
const modules = import.meta.glob<NumStrCase[]>('../fixtures/numstr_cases.json', {
  eager: true,
  import: 'default',
});
const cases = modules['../fixtures/numstr_cases.json'];

describe('excelNumToStr (Excel & number→text coercion)', () => {
  it('loads the full 74-case spec table', () => {
    expect(cases, 'missing fixture table numstr_cases.json').toBeDefined();
    expect(cases.length).toBe(74);
  });

  for (const [i, c] of cases.entries()) {
    it(`case ${i + 1}/74: ${c.x} -> ${JSON.stringify(c.expected)}`, () => {
      expect(excelNumToStr(c.x)).toBe(c.expected);
    });
  }
});
