/**
 * BDK mitigation calculation engine — placeholder.
 *
 * This module will host the TypeScript port of the spreadsheet's calculation
 * logic (Inputs -> Baseline -> {Comparison, +Stat sheets} -> Outputs).
 * Golden fixtures in tests/fixtures/golden/ capture the spreadsheet's cached
 * values and will be used to verify the port cell-by-cell.
 */

export const ENGINE_STATUS = 'pending' as const
