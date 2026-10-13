import { test } from "node:test";
import assert from "node:assert/strict";
import { designEyeLine, EYES_SKIP, eyesSkipEvent, eyesSkipMessage, problemsText } from "./designEye";
import type { DesignEye, DesignEyeSlide } from "../types";

const slide = (status: DesignEyeSlide["status"], problems: DesignEyeSlide["problems"]): DesignEyeSlide => ({ outline_id: "sl", slide: 2, status, problems, reason: "", before: null, after: null });

test("the counts line says what the designer's eye looked at and did", () => {
  const eye: DesignEye = {
    looked: 9,
    slides: [
      slide("fixed", [{ code: "word_broken", label: "слова разорваны посередине", severity: "major", where: "карточки", evidence: "" }]),
      slide("fixed", [{ code: "unbalanced", label: "пустоты и перекос композиции", severity: "major", where: "", evidence: "" }]),
      slide("kept", [{ code: "leftover", label: "пустая рамка или лишний элемент", severity: "major", where: "", evidence: "" }]),
      slide("seen", [{ code: "cramped", label: "текст набит слишком плотно", severity: "minor", where: "", evidence: "" }]),
    ],
  };
  assert.equal(designEyeLine(eye), "посмотрел на 9 слайдов · пересобрал 2 · 1 оставил как было");
  assert.equal(designEyeLine({ looked: 1, slides: [] }), "посмотрел на 1 слайд · замечаний нет");
  assert.equal(designEyeLine({ looked: 3, slides: [slide("seen", [])] }), "посмотрел на 3 слайда");
});

test("a slide's problems: the serious ones with where they are, else every one", () => {
  const s = slide("fixed", [
    { code: "word_broken", label: "слова разорваны посередине", severity: "major", where: "карточки", evidence: "" },
    { code: "cramped", label: "текст набит слишком плотно", severity: "minor", where: "", evidence: "" },
  ]);
  assert.equal(problemsText(s, true), "слова разорваны посередине (карточки)");
  assert.equal(problemsText(s, false), "слова разорваны посередине (карточки); текст набит слишком плотно");
  assert.equal(problemsText(slide("seen", [{ code: "cramped", label: "текст набит слишком плотно", severity: "minor", where: "", evidence: "" }]), true), "текст набит слишком плотно");
});

test("a skipped review: the reason by its code in Russian, never the server's English", () => {
  assert.equal(eyesSkipMessage("no_time"), "Взгляд дизайнера пропущен: не хватило времени на сборку.");
  assert.equal(eyesSkipMessage("failed"), "Взгляд дизайнера пропущен: не получилось посмотреть на слайды.");
  assert.equal(eyesSkipMessage("something_new"), "Взгляд дизайнера пропущен.");
  assert.equal(eyesSkipMessage(null), "Взгляд дизайнера пропущен.");
  for (const words of Object.values(EYES_SKIP)) assert.ok(!/[a-z]/i.test(words), words);
});

test("a run that skipped the review without a line on the timeline gets the line the server says now", () => {
  const skipped = { looked: 0, skipped: "no time left in the generation's model budget", skipped_code: "no_time", slides: [] };
  const v = { strategy: "compact", eyes: skipped, agent: { log: [], critic: [], events: [{ step: "analyst", message: "Нашёл 3 слайда.", slide: null, variant: null }] } };
  assert.deepEqual(eyesSkipEvent(v), { step: "eyes", message: "Взгляд дизайнера пропущен: не хватило времени на сборку.", slide: null, variant: "compact" });
  // the timeline said it already (newer servers), or the model did not answer (the review says so itself) — nothing added
  const said = { step: "eyes", message: "Взгляд дизайнера пропущен: не хватило времени на сборку.", slide: null, variant: "compact" };
  assert.equal(eyesSkipEvent({ ...v, agent: { log: [], critic: [], events: [said] } }), null);
  assert.equal(eyesSkipEvent({ ...v, eyes: { ...skipped, skipped: "the model did not answer", skipped_code: "no_answer" } }), null);
  // another variant's lines are not this one's
  assert.ok(eyesSkipEvent({ ...v, agent: { log: [], critic: [], events: [{ ...said, variant: "visual" }] } }));
  // it looked, or there is no record
  assert.equal(eyesSkipEvent({ ...v, eyes: { looked: 12, skipped: null, slides: [] } }), null);
  assert.equal(eyesSkipEvent({ ...v, eyes: null }), null);
  // no code (a server before the code): the line without a reason, never the English
  assert.equal(eyesSkipEvent({ ...v, eyes: { ...skipped, skipped_code: null } })?.message, "Взгляд дизайнера пропущен.");
});
