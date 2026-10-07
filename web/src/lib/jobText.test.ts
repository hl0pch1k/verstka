import { test } from "node:test";
import assert from "node:assert/strict";
import { humanizeJobMessage, variantProgress } from "./jobText";

test("the design review step reads in words on the build screen", () => {
  const titleOf = (s: string) => ({ structured: "Структурный" })[s] ?? s;
  assert.equal(humanizeJobMessage("structured: design review", titleOf), "Структурный: взгляд дизайнера");
  assert.deepEqual(variantProgress("structured: design review"), { name: "structured", state: { text: "взгляд дизайнера", done: false, frac: 0.9 } });
});
