import { test } from "node:test";
import assert from "node:assert/strict";
import { GEN, TPL, titleOf } from "./details.fixtures";
import { explainError, explainWhy, whyView } from "./why";

const v = GEN.variants[0];

test("навигация: «Слайд 2 / 4 · Хронология» и заголовок; откуда в тексте", () => {
  const w = whyView(GEN, v, 2, TPL, titleOf);
  assert.equal(w.cap, "Слайд 2 / 4 · Хронология");
  assert.equal(w.title, "История создания интеграла");
  assert.equal(w.src, "В вашем тексте — слайд 2");
});

test("почему такая форма: довод словами интерфейса, вывод и сноска", () => {
  const w = whyView(GEN, v, 2, TPL, titleOf);
  assert.equal(w.why, "Хронология из шести дат показывает последовательность событий.");
  assert.equal(whyView(GEN, v, 4, TPL, titleOf).why, "Форма «карточки» показывает площадь.");
  assert.deepEqual(w.dl, [{ t: "Вывод", d: "Развитие интеграла заняло два столетия" }, { t: "Сноска", d: "Даты — по статье" }]);
});

test("другие формы: вариант, который её показывает, — кнопкой с оценкой; текущий — меткой «на экране»", () => {
  const w = whyView(GEN, v, 2, TPL, titleOf);
  assert.deepEqual(w.forms.map((f) => [f.name, f.text, f.variant?.name ?? null, f.variant?.score ?? null, f.onScreen]), [
    ["Таблица", "позволит быстро просмотреть даты", "Компактный", 89, null],
    ["Список", "короткий список вех", null, null, "Структурный · на экране"],
  ]);
});

test("критик и правка по слайду: замечание, его исправление стрелкой и переделка", () => {
  const w = whyView(GEN, v, 2, TPL, titleOf);
  assert.deepEqual(w.crit.map((c) => [c.who, c.text.replace(/\u00a0/g, " "), c.arrow]), [
    ["Критик", "Заголовок повторяет тему слайда", false],
    ["Правка", "Заголовок «Интеграл прошёл путь от Ньютона до Лебега»", true],
    ["Правка", "Хронология (2).", false],
  ]);
});

test("пустой довод дизайнера — спросить объяснение у сервера", () => {
  const w = whyView(GEN, v, 3, TPL, titleOf);
  assert.equal(w.why, null);
  assert.equal(w.ask, true);
  assert.equal(whyView(GEN, v, 2, TPL, titleOf).ask, false);
});

test("как собран: образец шаблона и сходство; лучший из рассмотренных; доводы словами", () => {
  const w = whyView(GEN, v, 4, TPL, titleOf);
  assert.deepEqual(w.sample && { src: w.sample.src, caption: w.sample.caption }, { src: "/api/templates/cbbe3aa6a21d23ce/files/thumbs/slide-014.jpg", caption: "Образец: слайд 14 шаблона" });
  assert.ok(/slide-004\.jpg\?v=/.test(w.own.src ?? ""));
  assert.deepEqual(w.sim, { pct: 82, note: "Лучший из рассмотренных: у остальных сходство 74% и ниже" });
  assert.deepEqual(w.reasons.map((r) => r.good), [true, true]);
  assert.deepEqual(w.alts.map((a) => [a.cap, a.sim]), [["Слайд 23 · Карточки", "сходство 74%"], ["Слайд 38 · Другое", "сходство 62%"]]);
});

test("слайд собран заново: ближайший образец только того же типа, сходства нет, других макетов нет", () => {
  const w3 = whyView(GEN, v, 3, TPL, titleOf);
  assert.deepEqual(w3.sample && w3.sample.caption, "Ближайший образец: слайд 22 шаблона");
  assert.equal(w3.sim, null);
  assert.deepEqual(w3.alts, []);
  const w2 = whyView(GEN, v, 2, TPL, titleOf);
  assert.equal(w2.sample, null);
  assert.equal(w2.sampleCap, "Собран заново по сетке, шрифтам и цветам шаблона");
});

test("сходство больше 100% не бывает; другой шаблон — образцов нет", () => {
  assert.equal(whyView(GEN, v, 1, TPL, titleOf).sim?.pct, 100);
  assert.equal(whyView(GEN, v, 4, { ...TPL, template_id: "other" }, titleOf).sample, null);
});

test("проверка слайда: число замечаний и тон худшего; без замечаний — «замечаний нет»", () => {
  assert.deepEqual(whyView(GEN, v, 3, TPL, titleOf).check, { text: "1 замечание", tone: "warn" });
  assert.deepEqual(whyView(GEN, v, 4, TPL, titleOf).check, { text: "1 замечание", tone: "model" });
  assert.deepEqual(whyView(GEN, v, 1, TPL, titleOf).check, { text: "замечаний нет", tone: null });
});

test("объяснение сервера: строка «Почему так», иначе всё, кроме первой строки", () => {
  assert.equal(explainWhy("Слайд 3 — список: «X».\nПочему так: Четыре карточки соответствуют структуре.\nВёрстка: по образцу."), "Четыре карточки соответствуют структуре.");
  assert.equal(explainWhy("Слайд 1 — титул: «Интеграл».\nВёрстка: по образцу слайда 2 шаблона, совпадение 100%."), "Вёрстка: по образцу слайда 2 шаблона, совпадение 100%.");
  assert.equal(explainWhy(""), null);
});

test("образец собранного по образцу слайда без разбора шаблона: «загружается», «шаблона больше нет» — никогда не «собран с нуля»", () => {
  // разбор ещё грузится
  const loading = whyView(GEN, v, 4, null, titleOf, "loading");
  assert.equal(loading.sample, null);
  assert.equal(loading.composed, false);
  assert.deepEqual(loading.sim, { pct: 82, note: "Образец загружается…" });
  assert.equal(loading.frame, "Образец загружается…");
  // шаблон удалён из библиотеки
  const gone = whyView(GEN, v, 4, null, titleOf, "missing");
  assert.deepEqual(gone.sim, { pct: 82, note: "Шаблона больше нет в библиотеке — образец не показать" });
  assert.equal(gone.frame, "Шаблона больше нет в библиотеке");
  assert.equal(gone.sampleCap, "Образец шаблона");
  // разбор не загрузился
  assert.equal(whyView(GEN, v, 4, null, titleOf, "failed").sim?.note, "Разбор шаблона не загрузился — образец не показать");
  // разбор есть, а такого образца в нём нет (шаблон разобран заново)
  const lost = whyView(GEN, v, 4, { ...TPL, patterns: TPL.patterns.filter((p) => p.id !== "p14") }, titleOf);
  assert.equal(lost.sim?.note, "Образца нет в разборе шаблона — показать его нельзя");
  // ни в одном случае — не слова собранного заново
  for (const w of [loading, gone, lost]) assert.ok(!/с нуля|заново/.test(`${w.sim?.note} ${w.frame} ${w.sampleCap}`));
});

test("слова собранного заново — только у настоящего synth-слайда", () => {
  const w2 = whyView(GEN, v, 2, null, titleOf, "loading");
  assert.equal(w2.composed, true);
  assert.equal(w2.frame, "Готового образца не нашлось");
  assert.equal(w2.sampleCap, "Собран заново по сетке, шрифтам и цветам шаблона");
  const w4 = whyView(GEN, v, 4, TPL, titleOf);
  assert.equal(w4.frame, null);
  assert.equal(w4.sampleCap, "Образец: слайд 14 шаблона");
});

test("объяснение сервера недоступно: шаблон удалён (404) — так и сказано", () => {
  assert.equal(explainError(404, "Вариант не найден"), "Шаблона больше нет — объяснение недоступно");
  assert.equal(explainError(0, "Сеть недоступна: Failed to fetch"), "Не удалось получить объяснение: нет связи с сервером");
  assert.equal(explainError(500, "Internal Server Error"), "Не удалось получить объяснение");
});
