import { test } from "node:test";
import assert from "node:assert/strict";
import { GEN, titleOf } from "./details.fixtures";
import { checkTiles, diffRows, fileRows, fixRowsOf, passport, registryRows, stagesOf } from "./files";

const v = GEN.variants[0];

test("файлы по вариантам: номер и имя, оценка, файл, «на экране» у текущего, ссылки на PowerPoint, PDF и веб", () => {
  const rows = fileRows(GEN, "visual", titleOf);
  assert.deepEqual(rows.map((r) => [r.title, r.score, r.file, r.cur]), [
    ["1 · Структурный", 89, "Интеграл — Структурный.pptx", false], ["2 · Визуальный", 84, "Интеграл — Визуальный.pptx", true], ["3 · Компактный", 89, "Интеграл — Компактный.pptx", false],
  ]);
  assert.equal(rows[0].pptx, "/api/generations/g1/structured/files/deck.pptx");
  assert.equal(rows[0].html, "/api/generations/g1/structured/files/deck.html");
  assert.equal(rows[1].aPdf, "Скачать PDF — Визуальный");
});

test("паспорт запуска: шаблон, когда, версия, кто составил план и какие модели; выключенное — приглушено", () => {
  const p = passport(GEN, v, "VK Tech", titleOf);
  assert.equal(p.badge, "вариант 1 · Структурный");
  assert.deepEqual(p.facts.map((f) => [f.k, f.v, f.dim]), [
    ["Шаблон", "VK Tech", false], ["Собран", p.facts[1].v, false], ["Версия Verstka", "3.1.0", false], ["План составил", "агент", false],
    ["Тексты и план", "Qwen3.6-27B", false], ["Проверка по картинке", "выключена", true], ["Поиск похожего", "без модели", true], ["Проверка", "без модели", true],
  ]);
  assert.ok(/, \d\d:\d\d$/.test(p.facts[1].v));
});

test("время по этапам: этапы варианта, общий план и остаток «Прочее»; доли — от всего времени", () => {
  const s = stagesOf(v.run_manifest!)!;
  assert.deepEqual(s.rows.map((r) => [r.name, r.v]), [
    ["Разбор шаблона", "<1 с"], ["План (общий для вариантов)", "42 с"], ["Сборка PowerPoint", "3 с"], ["Проверка и правки", "1 с"],
    ["Взгляд дизайнера", "34 с"], ["PDF, веб-версия и превью", "5 с"], ["Прочее", "28 с"],
  ]);
  assert.equal(s.total, "≈ 1 мин 52 с");
  assert.equal(s.rows[1].w, "37.1%");
});

test("итог проверки: ошибки, предупреждения, заметки, по картинке, автоисправления — по самим замечаниям отчёта", () => {
  const t = checkTiles(GEN, v);
  assert.equal(t.head, "2 проверки");
  assert.equal(t.score, 89);
  // сводка сервера: warnings 2 (с замечанием модели); здесь предупреждение одно, замечание модели — «по картинке»
  assert.deepEqual(t.tiles.map((x) => [x.label, x.v, x.sub, x.cls, x.span]), [
    ["Ошибки", "0", "", "df-t-ok", 2], ["Предупреждения", "1", "", "df-t-warn", 2], ["Заметки", "0", "", "", 2],
    ["По картинке", "1", "", "", 3], ["Автоисправления", "1", "", "", 3],
  ]);
  // проверка по картинке выключена и замечаний модели нет — «выключена»
  const quiet = { ...v, audit: { ...v.audit!, issues: v.audit!.issues.filter((i) => i.kind !== "model") } };
  assert.deepEqual(checkTiles(GEN, quiet).tiles[3], { label: "По картинке", v: "—", sub: "выключена", cls: "df-t-off", icon: "eye", span: 3 });
});

test("итог проверки и автоисправления — по живому отчёту: после исправлений паспорт запуска устарел", () => {
  const live = {
    ...v,
    audit: { ...v.audit!, summary: { ...v.audit!.summary, checks_run: ["a", "b", "c"] }, applied_fixes: [...v.audit!.applied_fixes, { iteration: 1, action: "move_inside", slide: 2, kind: "move_inside" }] },
  };
  const t = checkTiles(GEN, live);
  assert.equal(t.head, "3 проверки");
  assert.equal(t.tiles[4].v, "2");
  const rows = fixRowsOf(live);
  assert.deepEqual(rows.map((r) => [r.slide, r.title]), [[3, "Сокращён текст"], [2, "Элемент возвращён в кадр"]]);
  // отчёта нет — паспорт запуска
  const old = { ...v, audit: null };
  assert.equal(checkTiles(GEN, old).head, "2 проверки");
  assert.deepEqual(fixRowsOf(old).map((r) => r.title), ["Сокращён текст"]);
});

test("навыки и агенты: версия и как они относятся к этому запуску", () => {
  const rows = registryRows({ skills: [{ name: "deck_designer", version: "2.2.0", role: "llm", sha256: "aaa", description: "", changelog: [] }, { name: "auditor", version: "0.3.0", role: "audit", sha256: "ccc", description: "", changelog: [] }, { name: "new_one", version: "0.1.0", role: "llm", sha256: "d", description: "", changelog: [] }], agents: [] }, v.run_manifest);
  assert.deepEqual(rows.map((r) => [r.name, r.version, r.match]), [["deck_designer", "v2.2.0", "как в запуске"], ["auditor", "v0.3.0", "в запуске v0.2.0"], ["new_one", "v0.1.0", "не участвовал"]]);
});

test("сравнение запусков: что изменилось — вариант, оценка, модели и навыки", () => {
  const rows = diffRows({
    a: { generation: "g1", strategy: "structured", score: 89 }, b: { generation: "g2", strategy: "visual", score: 84 },
    diff: {
      strategy: { from: "structured", to: "visual" }, audit_score: { from: 89, to: 84 },
      providers: { llm: { from: { backend: "chain", model: "a", chain: [{ label: "Qwen3.8-27B" }] } as never, to: null } },
      skills: { auditor: { from: { version: "0.2.0", sha256: "bbbbbbbbbbbb" }, to: null } },
    },
  }, titleOf);
  assert.deepEqual(rows, [
    { label: "Вариант", from: "Структурный", to: "Визуальный" }, { label: "Оценка качества", from: "89", to: "84" },
    { label: "Модель · llm", from: "Qwen3.8-27B", to: "без модели" }, { label: "Навык · auditor", from: "v0.2.0 · bbbbbbbb", to: "не участвовал" },
  ]);
});
