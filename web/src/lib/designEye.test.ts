import { test } from "node:test";
import assert from "node:assert/strict";
import { designEyeLine, problemsText } from "./designEye";
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
