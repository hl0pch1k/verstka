// The node modules the pure functions' tests use (web/scripts/test.mjs runs them); declared here so `tsc` checks
// the tests without @types/node. node:fs, node:path and `process.cwd()` — for the tests that read index.html and the
// styles (ui/shell/layout.test.ts; npm test runs from web/).
declare module "node:test" {
  export function test(name: string, fn: () => void | Promise<void>): void;
}
declare module "node:assert/strict" {
  const assert: {
    equal(actual: unknown, expected: unknown, message?: string): void;
    deepEqual(actual: unknown, expected: unknown, message?: string): void;
    ok(value: unknown, message?: string): asserts value;
  };
  export default assert;
}
declare module "node:fs" {
  export function readFileSync(path: string, encoding: "utf8"): string;
  export function readdirSync(path: string): string[];
}
declare module "node:path" {
  export function join(...parts: string[]): string;
}
declare const process: { cwd(): string };
