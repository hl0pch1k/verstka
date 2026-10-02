import { test } from "node:test";
import assert from "node:assert/strict";
import { foldJobEvent, type ActiveJob } from "./jobState";
import type { JobEvent } from "../types";

const start: ActiveJob = { id: "j", label: "", progress: 0, message: "", status: "queued", kind: "generate", startedAt: 0 };
const titleOf = (n: string) => (n === "structured" ? "Структурный" : n);
const msg = (message: string, progress = 0.5): JobEvent => ({ job_id: "j", status: "running", progress, message, t: 1 });
const agent = (seq: number, step: string, message: string, slide: number | null = null): JobEvent => ({ ...msg(message, 0.3), type: "agent", step, slide, variant: null, seq });

test("an agent event is added once and becomes the stage line", () => {
  let j = foldJobEvent(start, agent(1, "designer", "«Итоги» — список (3 пункта).", 4), titleOf);
  j = foldJobEvent(j, agent(1, "designer", "«Итоги» — список (3 пункта).", 4), titleOf);
  assert.equal(j.agent?.length, 1);
  assert.equal(j.phase, "designer");
  assert.equal(j.line?.slide, 4);
  assert.equal(j.line?.n, 1);
});

test("the layout keeps the planned count and counts the laid slides", () => {
  let j = foldJobEvent(start, msg("structured: planned 12 slides, rendering"), titleOf);
  assert.deepEqual([j.variants?.structured.of, j.variants?.structured.laid], [12, 0]);
  j = foldJobEvent(j, msg("structured: rendered slide 3/12"), titleOf);
  assert.deepEqual([j.variants?.structured.of, j.variants?.structured.laid], [12, 3]);
  assert.equal(j.line?.slide, 3);
  j = foldJobEvent(j, msg("structured: audit"), titleOf);
  assert.deepEqual([j.variants?.structured.of, j.variants?.structured.laid, j.variants?.structured.text], [12, 12, "проверка качества"]);
});

test("progress never goes back; a repeated poll does not retype the line", () => {
  let j = foldJobEvent(start, msg("structured: rendered slide 3/12", 0.6), titleOf);
  const n = j.line?.n;
  j = foldJobEvent(j, msg("structured: rendered slide 3/12", 0.4), titleOf);
  assert.equal(j.progress, 0.6);
  assert.equal(j.line?.n, n);
});

test("a polled record repeating the agent's words does not take the stage line", () => {
  let j = foldJobEvent(start, agent(1, "analyst", "Нашёл в тексте 12 слайдов."), titleOf);
  j = foldJobEvent(j, msg("Нашёл в тексте 12 слайдов."), titleOf);
  assert.equal(j.line?.n, 1);
});
