import { test } from "node:test";
import assert from "node:assert/strict";
import type { VariantEdit } from "../../types";
import { agentCap, agentRoles, editRows, editTitle } from "./agentTab";
import { GEN, titleOf } from "./details.fixtures";

const nb = (s: string) => s.replace(/ /g, " ");
const v = GEN.variants[0];

test("шапка ленты: слайды и что на них — «4 слайда · 1 формула»", () => {
  assert.equal(agentCap(v), "4 слайда · 1 диаграмма, 1 формула");
});

test("роли по порядку: автор, аналитик, дизайнер, критик, правка, вёрстка, проверка; значки и итоги", () => {
  const roles = agentRoles(GEN, v, titleOf);
  assert.deepEqual(roles.map((r) => [r.name, r.icon, r.skip]), [
    ["Автор", "pen", false], ["Аналитик", "search", false], ["Дизайнер", "layout", false], ["Критик", "chat-check", false],
    ["Правка", "refresh", false], ["Вёрстка", "layers", false], ["Проверка", "list-check", false],
  ]);
  assert.equal(nb(roles[0].sum ?? ""), "Текст на 4 слайда по статье «Интеграл» в Википедии");
  assert.equal(roles[2].sum, "2 слайда");
  assert.equal(roles[5].sum, "4 слайда по макетам и стилю шаблона");
  assert.equal(roles[6].sum, "оценка 89, без ошибок, исправлено автоматически: 1");
  assert.equal(roles[0].delay, "280ms");
  assert.equal(roles[6].delay, "520ms");
  assert.ok(roles[6].last && !roles[5].last);
});

test("строки роли: номер слайда у первой строки слайда, исправление критика — стрелкой, сверка цифр — галочкой", () => {
  const roles = agentRoles(GEN, v, titleOf);
  const critic = roles[3];
  assert.deepEqual(critic.lines.map((l) => [l.n, nb(l.a), l.arrow]), [
    [2, "Заголовок повторяет тему слайда", false],
    [null, "Заголовок «Интеграл прошёл путь от Ньютона до Лебега»", true],
  ]);
  const check = roles[5].lines.find((l) => /^Сверил цифры/.test(l.a));
  assert.equal(check?.mark, "ok");
  assert.equal(roles[2].lines[0].n, 1);
});

test("пропущенный шаг: серый прочерк, метка «пропущен» и причина", () => {
  const events = [{ step: "analyst", message: "Нашёл в тексте 2 слайда.", slide: null, variant: null }, { step: "critic", message: "Критик пропущен: план пришёл без модели.", slide: null, variant: null }];
  const roles = agentRoles({ ...GEN, writer: null }, { ...v, agent: { log: [], events, critic: [] } }, titleOf);
  const critic = roles.find((r) => r.name === "Критик")!;
  assert.equal(critic.skip, true);
  assert.equal(critic.icon, "dash");
  assert.equal(nb(critic.sum ?? ""), "План пришёл без модели");
});

const E = (over: Partial<VariantEdit>): VariantEdit => ({ at: 1, request: "", reply: "", kind: "slide", slides: [], score_before: null, score_after: null, ...over });

test("ваши правки: по порядку; отменённые помечены; «Вернуть как было» — пока есть что вернуть", () => {
  const r = editRows([
    E({ request: "на слайде 3 покажи расходы таблицей", reply: "Слайд 3 переделан.", version: 1 }),
    E({ request: "верни как было", kind: "undo", undo_of: 1 }),
    E({ request: "Исправь замечания на слайде 4", reply: "Слайд 4 исправлен.", kind: "fix", version: 1 }),
    E({ request: "Исправить выбранные замечания", kind: "fix_all", version: 2, fixed: ["a", "b"], score_before: 84, score_after: 89 }),
  ]);
  assert.deepEqual(r.rows.map((x) => [x.q, x.a, x.off]), [
    ["на слайде 3 покажи расходы таблицей", "Слайд 3 переделан.", true],
    ["Исправь замечания на слайде 4", "Слайд 4 исправлен.", false],
    ["Исправить выбранные замечания", "Исправлено 2 замечания · оценка 84 → 89", false],
  ]);
  assert.equal(r.active, 2);
  assert.equal(r.canUndo, true);
  assert.equal(r.hint, "Что вы меняли в чате после сборки. «Вернуть как было» отменит последнюю правку.");
});

test("всё отменено — нечего возвращать; правок нет — своя подсказка", () => {
  const r = editRows([E({ request: "x", reply: "y", version: 1 }), E({ kind: "undo", undo_of: 1 })]);
  assert.equal(r.canUndo, false);
  assert.equal(r.active, 0);
  assert.equal(r.hint, "Все правки отменены — слайды такие, как после сборки.");
  const none = editRows([]);
  assert.equal(none.canUndo, false);
  assert.equal(none.hint, "После сборки слайды не меняли. Правки из помощника и исправления замечаний появятся здесь.");
});

test("«Взгляд дизайнера», пропущенный сервером: прочерк, «пропущен» и причина по-русски — и у старых сборок без строки в ленте", () => {
  const eyes = { looked: 0, skipped: "no time left in the generation's model budget", skipped_code: "no_time", slides: [] };
  const roles = agentRoles(GEN, { ...v, eyes }, titleOf);
  const eye = roles.find((r) => r.key === "eyes")!;
  assert.equal(eye.name, "Взгляд дизайнера");
  assert.equal(eye.skip, true);
  assert.equal(eye.icon, "dash");
  assert.equal(nb(eye.sum ?? ""), "Не хватило времени на сборку");
  assert.equal(eye.lines.length, 0);
  assert.ok(eye.last);
  // в ленте строка уже есть (новый сервер) — та же роль, без второй строки
  const said = { step: "eyes", message: "Взгляд дизайнера пропущен: не хватило времени на сборку.", slide: null, variant: v.strategy };
  const again = agentRoles(GEN, { ...v, eyes, agent: { ...v.agent!, events: [...(v.agent?.events ?? []), said] } }, titleOf).find((r) => r.key === "eyes")!;
  assert.deepEqual([again.skip, nb(again.sum ?? "")], [true, "Не хватило времени на сборку"]);
  // английская причина без кода на экран не попадает
  const bare = agentRoles(GEN, { ...v, eyes: { ...eyes, skipped_code: null } }, titleOf).find((r) => r.key === "eyes")!;
  assert.equal(bare.skip, true);
  assert.ok(!/[a-z]/i.test(bare.sum ?? ""));
});

test("журнал правок: пересборка слайда — «Пересборка слайда 4 — полосы», а не «Правка»", () => {
  assert.equal(editTitle({ kind: "rebuild", request: "Пересобери слайд 4 так: полосы", slides: [4] }), "Пересборка слайда 4 — полосы");
  assert.equal(editTitle({ kind: "rebuild", request: "", slides: [4] }), "Пересборка слайда 4");
  assert.equal(editTitle({ kind: "edit", request: "", slides: [] }), "Правка");
  // в кавычках — только слова человека
  const r = editRows([E({ kind: "rebuild", request: "Пересобери слайд 4 так: полосы", slides: [4], version: 1 }), E({ request: "покажи таблицей", version: 2 }), E({ kind: "edit" })]);
  assert.deepEqual(r.rows.map((x) => [x.q, x.quoted]), [["Пересборка слайда 4 — полосы", false], ["покажи таблицей", true], ["Правка", false]]);
});
