import { test } from "node:test";
import assert from "node:assert/strict";
import { GEN, OUTLINE } from "./details.fixtures";
import { chartData, deckHead, factChips, formulaParts, latexText, planRows, writerHead, writerTexts } from "./plan";

test("формула текстом: знаки, индексы и степени, дроби, пределы, греческие буквы", () => {
  assert.equal(latexText("\\int f(x)\\,dx = F(x) + C"), "∫ f(x) dx = F(x) + C");
  assert.equal(latexText("\\int_a^b f(x)\\,dx = F(b) - F(a)"), "∫ₐᵇ f(x) dx = F(b) − F(a)");
  assert.equal(latexText("\\int_a^b f(x)\\,dx = \\lim_{n \\to \\infty} \\sum_{i=1}^{n} f(x_i)\\,\\Delta x_i"), "∫ₐᵇ f(x) dx = lim n→∞ Σᵢ₌₁ⁿ f(xᵢ) Δxᵢ");
  assert.equal(latexText("\\int x^2 \\, dx = \\frac{x^3}{3} + C"), "∫ x² dx = x³/3 + C");
  assert.equal(latexText("\\varphi = \\frac{1}{4\\pi\\varepsilon_0} \\int \\frac{\\rho(r)}{r}\\,dV"), "φ = 1/(4πε₀) ∫ ρ(r)/r dV");
  assert.equal(latexText("\\iint_D f(x, y)\\,dx\\,dy = V"), "∬_D f(x, y) dx dy = V");
  assert.equal(latexText("\\left[ \\frac{x^3}{3} \\right]_0^2 = \\frac{8}{3} \\approx 2{,}67"), "[ x³/3 ]₀² = 8/3 ≈ 2,67");
  assert.equal(latexText("\\int_\\alpha^\\beta f(\\varphi(t))\\varphi'(t)\\,dt"), "∫_α^β f(φ(t))φ′(t) dt");
  assert.equal(latexText("\\sqrt{x+1} \\cdot \\text{км}"), "√(x+1) · км");
});

test("формулы слайда: каждая $…$ отдельно; без долларов — строка до пояснения", () => {
  assert.deepEqual(formulaParts("Линейность: $\\int (f+g) = \\int f + \\int g$ — пояснение; Аддитивность: $a = b$ — ещё"), ["∫ (f+g) = ∫ f + ∫ g", "a = b"]);
  assert.deepEqual(formulaParts("∫ f(x) dx = F(x) + C — первообразная"), ["∫ f(x) dx = F(x) + C"]);
  assert.deepEqual(formulaParts(null), []);
});

test("строки плана: тип, заголовок, подзаголовок, абзац, пункты, даты чипами, формула, диаграмма", () => {
  const rows = planRows(GEN.variants[0]);
  assert.deepEqual(rows.map((r) => [r.n, r.kind, r.title]), [[1, "Титул", "Интеграл"], [2, "Хронология", "История создания интеграла"], [3, "Список", "Неопределённый интеграл — первообразная F(x) плюс C"], [4, "Диаграмма", "Интеграл равен площади криволинейной трапеции"]]);
  assert.equal(rows[0].sub, "Понятие, свойства, вычисление и приложения интеграла");
  assert.deepEqual(rows[1].chips, [{ v: "1675", l: "Ньютон и Лейбниц сформулировали…" }, { v: "1823", l: "Коши дал строгое определение" }]);
  assert.deepEqual(rows[1].bul, ["Лейбниц заимствовал знак ∫ из латинского слова summa"]);
  assert.deepEqual(rows[1].items, []);
  assert.equal(rows[2].par, "Неопределённый интеграл функции f(x) — это первообразная F(x).");
  assert.deepEqual(rows[2].fx, ["∫ f(x) dx = F(x) + C"]);
  assert.deepEqual(rows[3].charts, [{ type: "Линейный график", rest: " · Геометрический смысл интеграла · 2 значения" }]);
  assert.ok(/slide-002\.jpg\?v=/.test(rows[1].img ?? ""));
});

test("шапка плана и текст агента", () => {
  assert.deepEqual(deckHead(OUTLINE), { title: "Интеграл", sub: "Понятие, свойства, вычисление и приложения интеграла", meta: "4 слайда · аудитория: студенты 1 курса" });
  assert.equal(writerHead(GEN.writer!), "По статье «Интеграл» · 4 слайда");
  assert.deepEqual(writerTexts(GEN.writer!.text!), [{ n: 1, title: "Титульный", t: "Название: «Интеграл»." }, { n: 2, title: "История создания интеграла", t: "Понятие сложилось в XVII веке." }]);
});

test("цифры из текста: значение и подпись без тире в начале, длинная подпись — короче", () => {
  assert.deepEqual(factChips(OUTLINE.facts), [{ v: "1675", l: "Исаак Ньютон" }, { v: "1823", l: "Огюстен Коши сформулировал…" }]);
});

test("данные диаграмм: тип, слайд, название и значения по категориям", () => {
  assert.deepEqual(chartData(OUTLINE), {
    count: "1 ряд",
    charts: [{ key: "sl4-0", type: "Линейный график", rest: " · слайд 4 · Геометрический смысл интеграла", head: ["", "f(x)"], rows: [{ a: "a", b: "0" }, { a: "b", b: "4" }] }],
  });
});

test("цифры из текста: повтор значения в подписи снимается, формула в подписи — текстом, «$» от формулы — не единица", () => {
  const F = (value: string, unit: string | null, label: string) => ({ id: value, value, unit, label, source_span: null });
  assert.deepEqual(factChips([F("1902", null, "— 1902 — Анри Лебег дал определение"), F("67", "$", "$\\frac{8}{3} \\approx 2{,}"), F("2", "x", "$\\int_0^2 x^2 \\")]), [
    { v: "1902", l: "Анри Лебег дал определение" }, { v: "67", l: "8/3 ≈ 2" }, { v: "2 x", l: "∫₀² x²" },
  ]);
});
