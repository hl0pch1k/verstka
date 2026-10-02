// The pure functions' tests without a test framework: each src/**/*.test.ts is bundled by esbuild (Vite's own) into
// an ES module and run by node's built-in runner.
import { build } from "esbuild";
import { readdirSync, rmSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const out = join(root, "node_modules/.cache/verstka-tests");
const found = [];
const walk = (dir) => {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else if (name.endsWith(".test.ts")) found.push(p);
  }
};
walk(join(root, "src"));
rmSync(out, { recursive: true, force: true });
const files = [];
for (const entry of found) {
  const file = join(out, relative(join(root, "src"), entry).replace(/\.ts$/, ".mjs"));
  await build({ entryPoints: [entry], outfile: file, bundle: true, platform: "node", format: "esm", logLevel: "error" });
  files.push(file);
}
// without files `node --test` would go looking for tests of its own (this very script among them)
if (files.length === 0) {
  console.log("no tests");
  process.exit(0);
}
const run = spawnSync(process.execPath, ["--test", ...files], { stdio: "inherit" });
process.exit(run.status ?? 1);
