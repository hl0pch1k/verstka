import { test } from "node:test";
import assert from "node:assert/strict";
import {
  asEditResult, asFixResult, bubbleBlocks, chatFailText, chatTarget, chipsFor, describeFixes, editFailText, feedDelay, feedItems, feedProgress, introFor,
  latestRefreshNote, noteView, openTabSteps, placeholderFor, planActions, reloadFailText, typeset, OTHER_DECK, REFRESHED, type FeedJob,
} from "./chat";
import type { ChatAction, ChatResponse } from "../../types";
import { ApiError } from "../../api";

// ── open_tab: старые имена вкладок сервера → шаги экрана (бывший store.setTab)
test("open_tab: «audit» на результате — лист «Подробнее» на «Качестве», экран тот же", () => {
  assert.deepEqual(openTabSteps("audit", { screen: "result", hasDeck: true }), [{ type: "sheet", tab: "quality" }]);
});
test("open_tab: «export» и «run» — вкладка «Файлы»; «why», «plan», «agent» — свои", () => {
  for (const [tab, sheet] of [["export", "files"], ["run", "files"], ["why", "why"], ["plan", "plan"], ["agent", "agent"]] as const) {
    assert.deepEqual(openTabSteps(tab, { screen: "result", hasDeck: true }), [{ type: "sheet", tab: sheet }], tab);
  }
});
test("open_tab: с «Создать» и со сборки — сначала результат, потом лист", () => {
  assert.deepEqual(openTabSteps("plan", { screen: "create", hasDeck: true }), [{ type: "go", screen: "result" }, { type: "sheet", tab: "plan" }]);
  assert.deepEqual(openTabSteps("agent", { screen: "build", hasDeck: true }), [{ type: "go", screen: "result" }, { type: "sheet", tab: "agent" }]);
});
test("open_tab: презентации нет — лист не открывается", () => {
  assert.deepEqual(openTabSteps("plan", { screen: "create", hasDeck: false }), []);
  assert.deepEqual(openTabSteps("variants", { screen: "create", hasDeck: false }), []);
});
test("open_tab: «template» — на результате вкладка «Шаблон», на «Создать» — шаг «Шаблон», на сборке — ничего", () => {
  assert.deepEqual(openTabSteps("template", { screen: "result", hasDeck: true }), [{ type: "sheet", tab: "template" }]);
  assert.deepEqual(openTabSteps("template", { screen: "create", hasDeck: true }), [{ type: "open", step: "tpl" }]);
  assert.deepEqual(openTabSteps("template", { screen: "create", hasDeck: false }), [{ type: "open", step: "tpl" }]);
  assert.deepEqual(openTabSteps("template", { screen: "build", hasDeck: true }), []);
});
test("open_tab: «brief» — шаг «Текст» на «Создать»; «variants» — результат без листа", () => {
  assert.deepEqual(openTabSteps("brief", { screen: "result", hasDeck: true }), [{ type: "go", screen: "create" }]);
  assert.deepEqual(openTabSteps("brief", { screen: "create", hasDeck: false }), [{ type: "open", step: "text" }]);
  assert.deepEqual(openTabSteps("variants", { screen: "build", hasDeck: true }), [{ type: "go", screen: "result" }]);
  assert.deepEqual(openTabSteps("variants", { screen: "result", hasDeck: true }), [{ type: "sheet", tab: null }]);
});
test("open_tab: незнакомая вкладка — ничего", () => {
  assert.deepEqual(openTabSteps("whatever", { screen: "result", hasDeck: true }), []);
});

// ── результаты задач
test("asEditResult: ответ правки — как есть; без reply — null", () => {
  assert.deepEqual(asEditResult({ reply: "Готово.", changed: true, slide: 6, strategy: "s", score: 91, kind: "replace" }),
    { reply: "Готово.", changed: true, slide: 6, strategy: "s", score: 91, kind: "replace" });
  assert.equal(asEditResult({ changed: true }), null);
  assert.equal(asEditResult(null), null);
  assert.deepEqual(asEditResult({ reply: "Не понял." }), { reply: "Не понял.", changed: false, slide: null, strategy: undefined, score: null, kind: undefined });
});
test("asFixResult: только с числом оценки", () => {
  assert.deepEqual(asFixResult({ score: 92, errors: 0, warnings: 2, applied: [{}] }), { score: 92, errors: 0, warnings: 2, applied: [{}] });
  assert.equal(asFixResult({ errors: 1 }), null);
});

// ── итог исправлений «Исправь всё»
const title = (s: string) => ({ s: "Структурный", v: "Визуальный" } as Record<string, string>)[s] ?? s;
test("describeFixes: все готовы — оценка было → стало, без ошибок, предупреждения", () => {
  const t = describeFixes([
    { strategy: "s", before: 84, done: true, result: { score: 91, errors: 0, warnings: 2, applied: [] }, error: null },
    { strategy: "v", before: 90, done: true, result: { score: 90, errors: 1, warnings: 0, applied: [] }, error: null },
  ], title);
  assert.equal(t, [
    "Исправления готовы: 2 варианта обновлены.",
    "• Структурный — оценка 84 → 91, без ошибок, 2 предупреждения",
    "• Визуальный — оценка 90, 1 ошибка",
    "Слайды и файлы пересобраны, оставшиеся замечания — в «Подробнее» на вкладке «Качество».",
  ].join("\n"));
});
test("describeFixes: неудача — причина по-русски, без технического хвоста", () => {
  const t = describeFixes([
    { strategy: "s", before: null, done: false, result: null, error: "Вариант занят: RuntimeError: busy" },
  ], title);
  assert.ok(/^Исправить автоматически не получилось\./.test(t), t);
  assert.ok(/• Структурный — не получилось: Вариант занят\n/.test(t), t);
  assert.ok(!/RuntimeError/.test(t), t);
});
test("describeFixes: английская причина — общее «не получилось»", () => {
  const t = describeFixes([{ strategy: "v", before: null, done: false, result: null, error: "Traceback: KeyError 'x'" }], title);
  assert.ok(/• Визуальный — не получилось\n/.test(t), t);
});

// ── тексты неудач
test("editFailText: причина задачи через humanError", () => {
  assert.equal(editFailText("Модель недоступна: ProviderError: 503"), "Не получилось поменять: модель недоступна. Попробуйте сказать иначе или повторите позже.");
  assert.equal(editFailText("KeyError: 'slides'"), "Не получилось поменять. Попробуйте сказать иначе или повторите позже.");
});
test("chatFailText: нет связи — просьба повторить; иначе причина по-русски", () => {
  assert.equal(chatFailText(new ApiError(0, "Сеть недоступна: Failed to fetch")), "Не получилось ответить: нет связи с сервером. Повторите, когда связь вернётся.");
  assert.equal(chatFailText(new ApiError(500, "Internal Server Error")), "Не получилось ответить. Попробуйте ещё раз.");
  assert.equal(chatFailText(new ApiError(422, "Сообщение пустое")), "Не получилось ответить: сообщение пустое.");
});

// ── пузырь ответа: абзацы и список
test("bubbleBlocks: строка и пункты «• » — абзац и список", () => {
  assert.deepEqual(bubbleBlocks("Слайд 3 — определение, поэтому:\n• форма — «формула с пояснением»;\n• образец — слайд 17"), [
    { kind: "p", text: "Слайд 3 — определение, поэтому:" },
    { kind: "ul", items: ["форма — «формула с пояснением»;", "образец — слайд 17"] },
  ]);
});
test("bubbleBlocks: пункты с «- » и «· », текст после списка, пустые строки пропускаются", () => {
  assert.deepEqual(bubbleBlocks("Итог:\n\n- раз\n· два\n\nДальше — сами."), [
    { kind: "p", text: "Итог:" },
    { kind: "ul", items: ["раз", "два"] },
    { kind: "p", text: "Дальше — сами." },
  ]);
});
test("bubbleBlocks: «— » в начале строки — не пункт (тире в речи)", () => {
  assert.deepEqual(bubbleBlocks("— Готово."), [{ kind: "p", text: "— Готово." }]);
});
test("typeset: число и слово, «слайд 5», короткие предлоги не отрываются", () => {
  assert.equal(typeset("на слайде 5 и 3 шага в 900 000"), "на\u00a0слайде\u00a05\u00a0и\u00a03\u00a0шага в\u00a0900\u00a0000");
});

// ── лента: сообщения и задачи по времени
const m = (id: string, ts: number, role: "user" | "assistant" = "user") => ({ id, role, text: id, ts });
test("feedItems: задачи встают между сообщениями по времени", () => {
  const jobs: FeedJob[] = [{ id: "j1", label: "Меняю презентацию", ts: 15, progress: 0.4, status: "run" }];
  const f = feedItems([m("a", 10), m("b", 20, "assistant")], jobs);
  assert.deepEqual(f.map((x) => (x.kind === "job" ? x.job.id : x.kind === "msg" ? x.msg.id : x.note.id)), ["a", "j1", "b"]);
});
test("feedItems: при равном времени сообщение раньше задачи (ответ «Меняю…» перед полосой)", () => {
  const f = feedItems([m("a", 10, "assistant")], [{ id: "j", label: "x", ts: 10, progress: 0, status: "run" }]);
  assert.deepEqual(f.map((x) => x.kind), ["msg", "job"]);
});
test("feedItems: строка «Это другая презентация…» — после ответа, к которому она относится", () => {
  const f = feedItems([m("a", 10, "assistant")], [{ id: "j", label: "x", ts: 5, progress: 1, status: "done" }], [{ id: "n", text: OTHER_DECK, ts: 10 }]);
  assert.deepEqual(f.map((x) => x.kind), ["job", "msg", "note"]);
});

// ── ход задач из чата: у каждой своя полоса («Исправь всё» — по задаче на вариант, идут рядом)
test("feedProgress: полосы растут по идущим задачам хранилища — каждая по своей", () => {
  const jobs: FeedJob[] = [
    { id: "a", label: "Исправляю: Структурный", ts: 1, progress: 0.1, status: "run" },
    { id: "b", label: "Исправляю: Визуальный", ts: 1, progress: 0, status: "run" },
    { id: "c", label: "Меняю презентацию", ts: 0, progress: 1, status: "done" },
  ];
  const next = feedProgress(jobs, [{ id: "a", progress: 0.5 }, { id: "b", progress: 0.3 }, { id: "c", progress: 0.2 }]);
  assert.deepEqual(next.map((j) => j.progress), [0.5, 0.3, 1]);
});
test("feedProgress: полоса не идёт назад; нового нет — тот же список (без лишней перерисовки)", () => {
  const jobs: FeedJob[] = [{ id: "a", label: "x", ts: 1, progress: 0.6, status: "run" }];
  assert.equal(feedProgress(jobs, [{ id: "a", progress: 0.4 }]), jobs);
  assert.equal(feedProgress(jobs, []), jobs);
});

// ── действия ответа: только для презентации, о которой ответ (её прислал сервер или о ней спросили)
const reply = (actions: ChatAction[], gid: string | null = null): ChatResponse => ({ reply: "", intent: "", actions, template_id: null, generation_id: gid });
const at = (open: string | null, sent: string | null = open, screen: "create" | "build" | "result" = "result") => ({ sent, open, screen, hasDeck: !!open });
test("planActions: open_tab — открытая презентация та, о которой ответ: лист и слайд", () => {
  assert.deepEqual(planActions(reply([{ type: "open_tab", tab: "why", slide: 3 }], "A"), at("A")),
    [{ kind: "open", steps: [{ type: "sheet", tab: "why" }], slide: 3 }]);
});
test("planActions: open_tab — пока ждали ответ, открыли другую презентацию: ничего не открывается", () => {
  assert.deepEqual(planActions(reply([{ type: "open_tab", tab: "audit", slide: 2 }], "A"), at("B", "A")), []);
  // сервер не назвал презентацию — о ней спрашивали (sent)
  assert.deepEqual(planActions(reply([{ type: "open_tab", tab: "audit" }]), at("B", "A")), []);
});
test("planActions: open_tab без презентации ответа — по месту (шаг «Шаблон» на «Создать»)", () => {
  assert.deepEqual(planActions(reply([{ type: "open_tab", tab: "template" }]), at(null, null, "create")),
    [{ kind: "open", steps: [{ type: "open", step: "tpl" }], slide: null }]);
});
test("planActions: правка — со своей презентацией, исправления — с презентацией ответа, сборка — с задачей", () => {
  const edit = { type: "edit" as const, job_id: "e1", strategy: "visual", generation_id: "A", slide: 6 };
  const fixes = { type: "jobs" as const, jobs: [{ strategy: "visual", job_id: "f1" }] };
  const build = { type: "generation_started" as const, job_id: "g1", generation_id: "N" };
  assert.deepEqual(planActions(reply([edit, fixes, build], "A"), at("B", "A")), [
    { kind: "edit", action: edit },
    { kind: "fixes", jobs: fixes.jobs, gid: "A" },
    { kind: "build", gid: "N", job: "g1" },
  ]);
});
test("planActions: исправления — сервер не назвал презентацию: та, о которой спросили (не открытая сейчас)", () => {
  const fixes = { type: "jobs" as const, jobs: [{ strategy: "s", job_id: "f" }] };
  assert.deepEqual(planActions(reply([fixes]), at("B", "A")), [{ kind: "fixes", jobs: fixes.jobs, gid: "A" }]);
  assert.deepEqual(planActions(reply([{ type: "jobs", jobs: [] }]), at("A")), []);
});

test("reloadFailText: нет связи — так и сказано; иначе причина по-русски", () => {
  const offline = reloadFailText(new ApiError(0, "Failed to fetch"));
  assert.ok(/не обновилась: нет связи с сервером/.test(offline), offline);
  const busy = reloadFailText(new Error("Сервер занят: try later"));
  assert.ok(/не обновилась: сервер занят\./.test(busy), busy);
  assert.ok(!/Internal/.test(reloadFailText(new Error("Internal Server Error"))));
  assert.ok(!/другая презентация/.test(reloadFailText(new Error("x"))));
});

// ── каскад появления при открытии (G-helper-open): 200…400 по 40; закрыт — 240 у всех
test("feedDelay: короткая лента — 200 + 40·i", () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5].map((i) => feedDelay(i, 6, true)), [200, 240, 280, 320, 360, 400]);
});
test("feedDelay: длинная — каскад у последних шести (они на виду), выше — 200", () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5, 6, 7].map((i) => feedDelay(i, 8, true)), [200, 200, 200, 240, 280, 320, 360, 400]);
});
test("feedDelay: закрытие — сброс после того, как плита погасла", () => {
  assert.equal(feedDelay(3, 6, false), 240);
});

// ── подсказки, приветствие, поле
const base = { pending: false, busy: false, empty: true, edited: null, deck: true, open: "g1", slide: 3, template: true, fixable: false };
test("chipsFor: пустая лента на результате — «Почему слайд N такой?» и «Как работал агент?»", () => {
  assert.deepEqual(chipsFor(base), ["Почему слайд 3 такой?", "Как работал агент?"]);
});
test("chipsFor: есть что исправить — «Исправь всё» вместо агента", () => {
  assert.deepEqual(chipsFor({ ...base, fixable: true }), ["Почему слайд 3 такой?", "Исправь всё"]);
});
test("chipsFor: после правки — «Верни как было» и вопрос о изменённом слайде", () => {
  assert.deepEqual(chipsFor({ ...base, empty: false, edited: { gid: "g1", slide: 6 } }), ["Верни как было", "Почему слайд 6 такой?"]);
  assert.deepEqual(chipsFor({ ...base, empty: false, edited: { gid: "g1", slide: null } }), ["Верни как было"]);
});
test("chipsFor: правка другой презентации — ни «Верни как было», ни вопроса о её слайде (они были бы о чужой)", () => {
  // открыли другую из «Мои презентации»
  assert.deepEqual(chipsFor({ ...base, empty: false, open: "g2", edited: { gid: "g1", slide: 6 } }), []);
  // ушли на «Создать» или «Сборку» — презентации на экране нет
  assert.deepEqual(chipsFor({ ...base, empty: false, deck: false, open: null, edited: { gid: "g1", slide: 6 } }), []);
  // вернулись к ней — подсказки снова на месте
  assert.deepEqual(chipsFor({ ...base, empty: false, open: "g1", edited: { gid: "g1", slide: 6 } }), ["Верни как было", "Почему слайд 6 такой?"]);
});
test("chipsFor: пока ждём ответ или идёт задача — ничего; разговор идёт — ничего", () => {
  assert.deepEqual(chipsFor({ ...base, pending: true }), []);
  assert.deepEqual(chipsFor({ ...base, busy: true, edited: { gid: "g1", slide: 2 } }), []);
  assert.deepEqual(chipsFor({ ...base, empty: false }), []);
});
test("chipsFor: без презентации — о шаблоне; без шаблона — «Что ты умеешь?»", () => {
  assert.deepEqual(chipsFor({ ...base, deck: false }), ["Что в шаблоне?", "Что ты умеешь?"]);
  assert.deepEqual(chipsFor({ ...base, deck: false, template: false }), ["Что ты умеешь?"]);
});
test("introFor и placeholderFor: по экрану", () => {
  assert.equal(introFor({ building: false, deck: true }), "Спросите про любой слайд или попросите его изменить.");
  assert.equal(introFor({ building: true, deck: true }), "Собираю презентацию — спросите, что сейчас делает агент.");
  assert.equal(introFor({ building: false, deck: false }), "Спросите про шаблон или пришлите текст — соберу три варианта.");
  assert.equal(placeholderFor({ screen: "result", deck: true, slide: 3 }), "Что поменять на слайде 3?");
  assert.equal(placeholderFor({ screen: "build", deck: true, slide: 3 }), "Вопрос о сборке");
  assert.equal(placeholderFor({ screen: "create", deck: true, slide: 3 }), "Вопрос или текст презентации");
});

test("вопрос помощнику — о презентации на экране: результат — открытая, «Сборка» — собираемая, «Создать» — никакая (A6)", () => {
  const ctx = { open: "A", strategy: "visual", slide: 3, building: "B" };
  assert.deepEqual(chatTarget({ ...ctx, screen: "result" }), { generation_id: "A", strategy: "visual", slide: 3 });
  assert.deepEqual(chatTarget({ ...ctx, screen: "build" }), { generation_id: "B", strategy: null, slide: null });
  assert.deepEqual(chatTarget({ ...ctx, screen: "create" }), { generation_id: null, strategy: null, slide: null });
  assert.deepEqual(chatTarget({ ...ctx, screen: "build", building: null }), { generation_id: null, strategy: null, slide: null });
});

test("reloadFailText не обещает того, чего нет: путь — «Обновить» рядом со строкой, без отсылок", () => {
  const t = reloadFailText(new ApiError(0, "Failed to fetch"));
  assert.equal(t, "Изменения сохранены, но презентация на экране не обновилась: нет связи с сервером.");
});

test("noteView: строка о несвежей презентации — с «Обновить», пока она несвежая; перечиталась — «обновлена»; открыта другая — как записана", () => {
  const n = { id: "n", text: "старая причина", ts: 1, refresh: "g1" };
  const L = { latest: true };
  assert.deepEqual(noteView(n, { stale: { gid: "g1", text: "новая причина" }, open: "g1", ...L }), { text: "новая причина", refresh: true });
  assert.deepEqual(noteView(n, { stale: null, open: "g1", ...L }), { text: REFRESHED, refresh: false });
  assert.deepEqual(noteView(n, { stale: null, open: "g2", ...L }), { text: "старая причина", refresh: false });
  assert.deepEqual(noteView(n, { stale: { gid: "g2", text: "x" }, open: "g2", ...L }), { text: "старая причина", refresh: false });
  assert.deepEqual(noteView({ id: "o", text: OTHER_DECK, ts: 1 }, { stale: { gid: "g1", text: "x" }, open: "g1", ...L }), { text: OTHER_DECK, refresh: false });
});

test("в ленте живая только самая новая строка о несвежей презентации — прежние остаются как записаны (S5)", () => {
  const notes = [
    { id: "a", text: "причина 1", ts: 1, refresh: "g1" },
    { id: "o", text: OTHER_DECK, ts: 2 },
    { id: "b", text: "причина 2", ts: 3, refresh: "g1" },
    { id: "c", text: "другая", ts: 4, refresh: "g2" },
  ];
  assert.equal(latestRefreshNote(notes, "g1"), "b");
  assert.equal(latestRefreshNote(notes, "g2"), "c");
  assert.equal(latestRefreshNote(notes, undefined), null);
  const stale = { gid: "g1", text: "новая причина" };
  assert.deepEqual(noteView(notes[0], { stale, open: "g1", latest: false }), { text: "причина 1", refresh: false });
  assert.deepEqual(noteView(notes[2], { stale, open: "g1", latest: true }), { text: "новая причина", refresh: true });
  // перечиталась — «обновлена» говорит только новая, прежняя — как была
  assert.deepEqual(noteView(notes[0], { stale: null, open: "g1", latest: false }), { text: "причина 1", refresh: false });
});
