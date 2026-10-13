import { test } from "node:test";
import assert from "node:assert/strict";
import { analysisFacts, analysisRows, analysisSteps, ribbonItems, tplMeta, tplShort } from "./ribbon";
import { humanizeJobMessage } from "../../lib/jobText";

const t = (id: string, at: string) => ({ template_id: id, analyzed_at: at } as any);
const list = ["a", "b", "c", "d", "e", "f", "g", "h"].map((id, i) => t(id, `2026-10-0${i + 1}`));

test("новые первыми, шесть штук, остаток", () => {
  const r = ribbonItems(list, "h");
  assert.deepEqual(r.shown.map((x) => x.template_id), ["h", "g", "f", "e", "d", "c"]);
  assert.equal(r.rest, 2);
});
test("выбранный дальше шестого встаёт шестым", () => {
  const r = ribbonItems(list, "a");
  assert.equal(r.shown[5].template_id, "a");
  assert.equal(r.shown.length, 6);
});
test("время разбора числом (сервер шлёт mtime): новые первыми", () => {
  const nums = [{ template_id: "x", analyzed_at: 9 }, { template_id: "y", analyzed_at: 10 }] as any[];
  assert.deepEqual(ribbonItems(nums, null).shown.map((x) => x.template_id), ["y", "x"]);
  assert.equal(ribbonItems(nums, null).rest, 0);
});
test("только что загруженный встаёт первым, даже если разобран раньше (кэш)", () => {
  const r = ribbonItems(list, "b", 6, "b");
  assert.deepEqual(r.shown.map((x) => x.template_id), ["b", "h", "g", "f", "e", "d"]);
  assert.equal(r.rest, 2);
});

// Сообщения разбора — как их шлёт сервер (verstka/analysis/manifest.py) и как их видит activeJob (по-русски, jobText).
const RAW: Array<[string, number]> = [
  ["Открываю файл шаблона", 0],
  ["opened package: 24 slides", 1],
  ["extracted shapes", 2],
  ["rendered slides", 3],
  ["built tokens", 4],
  ["classified slides", 5],
  ["assembled 9 patterns", 6],
  ["derived components and rules", 7],
];
for (const [msg, cur] of RAW) {
  test(`«${msg}» → шаг ${cur + 1} идёт, предыдущие готовы`, () => {
    for (const m of [msg, humanizeJobMessage(msg, (s) => s)]) {
      const s = analysisSteps(m, 0);
      assert.equal(s.length, 8);
      assert.equal(s[cur], "cur", m);
      assert.ok(s.slice(0, cur).every((x) => x === "done"), m);
      assert.ok(s.slice(cur + 1).every((x) => x === "pend"), m);
    }
  });
}
test("конец разбора: все восемь готовы", () => {
  for (const m of ["done", "Готово", "loaded cached manifest"]) assert.ok(analysisSteps(humanizeJobMessage(m, (s) => s), 1).every((x) => x === "done"), m);
});
test("в очереди: идёт первый шаг", () => assert.deepEqual(analysisSteps("В очереди…", 0), ["cur", "pend", "pend", "pend", "pend", "pend", "pend", "pend"]));
test("настоящий порядок сервера не отматывает шаги назад (прогресс не убывает)", () => {
  // сервер: отрисовка (0.2) раньше фигур (0.3) и картинок (0.38)
  const seq: Array<[string, number]> = [["opened package: 24 slides", 0.02], ["rendered slides", 0.2], ["extracted shapes", 0.3], ["extracted 31 assets", 0.38], ["built tokens", 0.45], ["classified slides", 0.8], ["assembled 9 patterns", 0.86], ["derived components and rules", 0.95]];
  let last = -1;
  for (const [m, p] of seq) {
    const cur = analysisSteps(humanizeJobMessage(m, (s) => s), p).indexOf("cur");
    assert.ok(cur >= last, `${m}: ${cur} < ${last}`);
    last = cur;
  }
  assert.equal(last, 7);
});

test("факты разбора копятся из сообщений", () => {
  let f = analysisFacts({}, humanizeJobMessage("opened package: 24 slides", (s) => s));
  f = analysisFacts(f, "extracted 31 assets");
  f = analysisFacts(f, humanizeJobMessage("assembled 9 patterns", (s) => s));
  f = analysisFacts(f, "built tokens");
  assert.deepEqual(f, { slides: 24, pics: 31, lays: 9 });
});
test("строки шагов — как на доске C-analyzing", () => {
  const rows = analysisRows(analysisSteps("built tokens", 0), { slides: 24, pics: 31 });
  assert.deepEqual(rows.map((r) => r.a + (r.b ?? "") + (r.c ?? "")), [
    "открыт файл: 24 слайда", "фигуры и тексты прочитаны", "найдено картинок и иконок: 31", "слайды отрисованы",
    "цвета, шрифты и сетка собраны", "типы слайдов определены", "найдено … макетов слайдов", "правила оформления собраны",
  ]);
  assert.equal(rows[4].state, "cur");
  const done = analysisRows(analysisSteps("Готово", 1), { slides: 24, pics: 31, lays: 9 });
  assert.equal(done[6].a + done[6].b + done[6].c, "найдено 9 макетов слайдов");
});

test("подписи шаблона: «54 слайда» и «54 слайда · Play»", () => {
  const x = { template_id: "v", n_slides: 54, font: "Play" } as any;
  assert.equal(tplShort(x), "54 слайда");
  assert.equal(tplMeta(x), "54 слайда · Play");
  assert.equal(tplMeta({ template_id: "w", n_slides: null, font: null } as any), "");
});
