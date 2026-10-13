import { test } from "node:test";
import assert from "node:assert/strict";
import { TPL } from "./details.fixtures";
import { patternView } from "./pattern";

test("слайд шаблона: заголовок, фон, картинка в полный размер и запасная миниатюра", () => {
  const p = patternView(TPL, 14)!;
  assert.equal(p.title, "Слайд 14 шаблона · Карточки");
  assert.equal(p.desc, "Светлый фон");
  assert.equal(p.img, "/api/templates/cbbe3aa6a21d23ce/files/slides/slide-014.jpg");
  assert.equal(p.fallback, "/api/templates/cbbe3aa6a21d23ce/files/thumbs/slide-014.jpg");
  assert.equal(p.q, 92);
  assert.equal(patternView(TPL, 5), null);
});

test("как определён тип: голоса источников, согласие и уверенность", () => {
  const p = patternView(TPL, 14)!;
  assert.equal(p.agree, "согласие 2 из 3");
  assert.deepEqual(p.votes, [
    { src: "правила", kind: "Карточки", p: "88 %", agree: true }, { src: "языковая модель", kind: "Карточки", p: "94 %", agree: true },
    { src: "модель зрения", kind: "Список", p: "60 %", agree: false },
  ]);
  assert.equal(p.decor, "4 декоративных элемента сохраняются как в образце");
});

test("места для содержания: по положению сверху вниз, группа — диапазоном номеров, поле примечания — с подсказкой", () => {
  const p = patternView(TPL, 14)!;
  assert.equal(p.placesH, "6 мест для содержания");
  assert.deepEqual(p.places.map((x) => [x.num, x.role, x.extra, x.sample, x.note]), [
    ["1", "заголовок", "", "«Интеграл сохраняет линейные комбинации»", null],
    ["2", "подзаголовок", "", "«Определённый интеграл подчиняется правилам»", null],
    ["3–4", "2 карточки", "· заголовок + текст", "2 ячейки · колонка · от 2 до 4", null],
    ["5", "список", "", "«Линейность позволяет вынести множители»", null],
    ["6", "поле примечания", "", "«Линейность и аддитивность превращают интеграл»", "сюда встанет вывод слайда"],
    ["", "1 иконка", "", "", null],
  ]);
  assert.deepEqual(p.places.map((x) => x.c), ["#2563EB", "#5A6272", "#5A6272", "#5A6272", "#5A6272", "#B45309"]);
});

test("рамки на образце: свои места — сплошные с номером, ячейки группы — пунктиром", () => {
  const p = patternView(TPL, 14)!;
  assert.deepEqual(p.frames.map((f) => [f.n, f.id, f.dash, f.x, f.y]), [
    ["1", "title_1", false, "2.5%", "6.3%"], ["2", "sub_1", false, "2.5%", "25%"],
    ["3", "g1", true, "2.6%", "35.9%"], ["4", "g1", true, "2.6%", "51.1%"],
    ["5", "list_1", false, "2.5%", "68.1%"], ["6", "note_1", false, "2.5%", "79.3%"],
  ]);
});

test("листание: соседние образцы шаблона и место в шаблоне", () => {
  const p = patternView(TPL, 14)!;
  assert.deepEqual([p.prev, p.next, p.pos], [4, 22, "14 / 54"]);
  const first = patternView(TPL, 1)!;
  assert.deepEqual([first.prev, first.next], [null, 2]);
  assert.equal(first.desc, "Тёмный фон");
  assert.deepEqual(first.frames, []);
  assert.equal(first.decor, "Декоративных элементов нет");
});
