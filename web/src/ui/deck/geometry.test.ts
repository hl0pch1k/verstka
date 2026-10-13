import { test } from "node:test";
import assert from "node:assert/strict";
import { deckGeometry, uiReducer, UI0 } from "./geometry";

// Числа — из boards/V2.dc.html, renderVals (`const Y = …`, `y4`, `s4Cls`).
test("создать: открыт текст", () => assert.deepEqual(deckGeometry(UI0).y, [0, 144, 556, 812]));
test("создать: открыт шаблон", () => assert.deepEqual(deckGeometry({ ...UI0, open: "tpl" }).y, [0, 524, 668, 812]));
test("все параметры", () => assert.deepEqual(deckGeometry({ ...UI0, more: true }).y, [0, 40, 80, 812]));
test("улучшить готовую: плита 02 на 40", () => assert.equal(deckGeometry({ ...UI0, improve: true }).y[1], 40));
test("сборка", () => {
  const g = deckGeometry({ ...UI0, screen: "build" });
  assert.deepEqual(g.y, [0, 40, 80, 80]);
  assert.equal(g.s4, "off");
});
test("результат", () => {
  const g = deckGeometry({ ...UI0, screen: "result" });
  assert.deepEqual(g.y, [0, 40, 80, 120]);
  assert.equal(g.s4, "on");
});
test("результат из «Создать» поднимается снизу", () => assert.equal(deckGeometry({ ...UI0, screen: "result", rise: true }).s4, "up"));
test("возврат на «Создать»: плита 04 уходит вниз непрозрачной", () => assert.equal(deckGeometry({ ...UI0, down: true }).s4, "down"));
test("go закрывает листы и разделы", () => {
  const s = uiReducer({ ...UI0, screen: "result", sheet: "plan", sect: "hist", remarks: true }, { type: "go", screen: "create" });
  assert.equal(s.sheet, null);
  assert.equal(s.sect, null);
  assert.equal(s.screen, "create");
  assert.equal(s.open, "text");
});
test("лист помнит последнюю вкладку", () => {
  const s = uiReducer(uiReducer(UI0, { type: "sheet", tab: "why" }), { type: "sheet", tab: null });
  assert.equal(s.sheetLast, "why");
});

// Сверх брифа: остальные действия ведут себя как обработчики V2.
test("шапки и полосы: «Создать» — шапки, «Все параметры» и другие экраны — полосы", () => {
  assert.deepEqual([deckGeometry(UI0).heads, deckGeometry(UI0).strips], [true, false]);
  const more = deckGeometry({ ...UI0, more: true });
  assert.deepEqual([more.heads, more.strips], [false, true]);
  const build = deckGeometry({ ...UI0, screen: "build" });
  assert.deepEqual([build.heads, build.strips], [false, true]);
});
test("улучшить готовую не трогает свёрнутую колоду и плиту 03", () => {
  assert.deepEqual(deckGeometry({ ...UI0, improve: true }).y, [0, 40, 556, 812]);
  assert.deepEqual(deckGeometry({ ...UI0, improve: true, more: true }).y, [0, 40, 80, 812]);
  assert.deepEqual(deckGeometry({ ...UI0, improve: true, screen: "result" }).y, [0, 40, 80, 120]);
});
test("go сбрасывает слои, но не помощника, «Улучшить готовую» и открытый шаг вне «Создать»", () => {
  const busy = {
    ...UI0, open: "tpl" as const, more: true, improve: true, helper: true, pattern: 3, textLayer: true, lightbox: true,
    remarks: true, tplPreview: "a", tplDelete: "b", sheet: "files" as const,
  };
  const s = uiReducer(busy, { type: "go", screen: "build" });
  assert.equal(s.screen, "build");
  assert.equal(s.open, "tpl");
  assert.equal(s.helper, true);
  assert.equal(s.improve, true);
  assert.deepEqual(
    [s.more, s.pattern, s.textLayer, s.lightbox, s.remarks, s.tplPreview, s.tplDelete, s.sheet, s.sheetLast],
    [false, null, false, false, false, null, null, null, "quality"],
  );
});
test("открыть шаг сворачивает «Все параметры»; «Все параметры» возвращают к тексту", () => {
  const s = uiReducer({ ...UI0, more: true }, { type: "open", step: "tpl" });
  assert.deepEqual([s.open, s.more], ["tpl", false]);
  const m = uiReducer({ ...UI0, open: "tpl" }, { type: "more" });
  assert.deepEqual([m.open, m.more], ["text", true]);
  assert.equal(uiReducer(m, { type: "more" }).more, false);
  assert.equal(uiReducer(m, { type: "more", on: true }).more, true);
});
test("лист открывается на вкладке и запоминает её; set меняет поля", () => {
  const s = uiReducer(UI0, { type: "sheet", tab: "agent" });
  assert.deepEqual([s.sheet, s.sheetLast], ["agent", "agent"]);
  assert.equal(uiReducer(UI0, { type: "sect", sect: "tpls" }).sect, "tpls");
  assert.equal(uiReducer(UI0, { type: "pattern", n: 4 }).pattern, 4);
  const t = uiReducer(UI0, { type: "set", patch: { helper: true, rise: true } });
  assert.deepEqual([t.helper, t.rise, t.screen], [true, true, "create"]);
});

// Раунд правок 1: «Улучшить готовую» живёт только на открытом шаге «Текст» (V2: `txImpOn = txOpen && …`).
test("улучшить готовую при открытом шаге «Шаблон» не двигает плиту 02", () => {
  assert.deepEqual(deckGeometry({ ...UI0, improve: true, open: "tpl" }).y, [0, 524, 668, 812]);
});
test("улучшить готовую при открытых «Все параметры» не двигает колоду", () => {
  assert.deepEqual(deckGeometry({ ...UI0, improve: true, more: true }).y, [0, 40, 80, 812]);
});
test("шаг «Шаблон» гасит «Улучшить готовую» (V2 txBack); шаг «Текст» его не трогает", () => {
  assert.equal(uiReducer({ ...UI0, improve: true }, { type: "open", step: "tpl" }).improve, false);
  assert.equal(uiReducer({ ...UI0, improve: true, open: "tpl" }, { type: "open", step: "text" }).improve, true);
});
test("go сбрасывает rise; down — только уход с результата на «Создать» (V2 go(): keep4, down)", () => {
  const s = uiReducer({ ...UI0, rise: true, down: true }, { type: "go", screen: "result" });
  assert.deepEqual([s.rise, s.down], [false, false]);
  const c = uiReducer({ ...UI0, screen: "result", rise: true }, { type: "go", screen: "create" });
  assert.deepEqual([c.rise, c.down], [false, true]);
  // со сборки и с «Создать» плите 04 уезжать нечего
  assert.equal(uiReducer({ ...UI0, screen: "build" }, { type: "go", screen: "create" }).down, false);
  assert.equal(uiReducer(UI0, { type: "go", screen: "create" }).down, false);
  // на «Создать» ещё раз, пока плита уезжает: флаг держится (содержимое не пропадает посреди хода)
  assert.equal(uiReducer({ ...UI0, down: true }, { type: "go", screen: "create" }).down, true);
  // на сборку с результата — флага нет
  assert.equal(uiReducer({ ...UI0, screen: "result" }, { type: "go", screen: "build" }).down, false);
});

test("другая вкладка листа закрывает слой «Слайд N шаблона» (D-2); та же вкладка и закрытие листа — нет", () => {
  const open = { ...UI0, screen: "result" as const, sheet: "template" as const, pattern: 4 };
  assert.equal(uiReducer(open, { type: "sheet", tab: "why" }).pattern, null);
  assert.equal(uiReducer(open, { type: "sheet", tab: "template" }).pattern, 4);
  // лист закрывается — слой уезжает вместе с ним, снимает его сам лист
  assert.equal(uiReducer(open, { type: "sheet", tab: null }).pattern, 4);
});
