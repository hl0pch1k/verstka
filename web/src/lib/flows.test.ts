import { test } from "node:test";
import assert from "node:assert/strict";
import { api } from "../api";
import { endSeen, failMessage, followBuild, improveArrives, uploadTemplateFlow, watchingBuild, type GenerationDeps, type UploadDeps } from "./flows";
import type { Generation, Job } from "../types";

test("сообщение помощника о неудаче задачи: причина по-русски, без технического хвоста", () => {
  assert.equal(failMessage("Не получилось собрать презентацию", { error: "Модель не ответила: ProviderError: 503 Service Unavailable", message: "" }),
    "Не получилось собрать презентацию: модель не ответила");
  assert.equal(failMessage("Не получилось разобрать «Отчёт»", { error: "Traceback (most recent call last):\n  KeyError: 'x'", message: "" }),
    "Не получилось разобрать «Отчёт».");
  assert.equal(failMessage("Не получилось собрать презентацию", { error: null, message: "Сервер перезапустился — задача потеряна" }),
    "Не получилось собрать презентацию: сервер перезапустился — задача потеряна");
});

// ── конец сборки: экран уводит только сборка, на чьём экране человек стоит (B-I1, A9)

test("watchingBuild: только экран «Сборка» и на нём эта сборка", () => {
  assert.equal(watchingBuild("build", "j1", "j1"), true);
  assert.equal(watchingBuild("build", "j2", "j1"), false);
  assert.equal(watchingBuild("create", "j1", "j1"), false);
  assert.equal(watchingBuild("result", "j1", "j1"), false);
  assert.equal(watchingBuild("build", null, "j1"), false);
});

type Hooks = { onDone?: (job: Job) => void | Promise<void>; onFailed?: (job: Job) => void };
function fakeDeps(o: { here: () => boolean; deck?: Generation | null }) {
  const log: string[] = [];
  let hooks: Hooks = {};
  const d: GenerationDeps = {
    runJob: (_id, _label, opts) => { hooks = opts ?? {}; },
    report: () => log.push("report"),
    notify: () => log.push("notify"),
    clearNotice: () => {},
    pushMessage: (_r, text) => log.push(`msg:${text.split("\n")[0]}`),
    dispatch: (a) => log.push(`ui:${a.type === "go" ? a.screen : a.type}`),
    refreshGenerations: async () => { log.push("list"); },
    fetchGeneration: async (gid) => { log.push(`load:${gid}`); return o.deck === undefined ? deck(gid) : o.deck; },
    refreshModelStatus: async () => {},
    titleOf: (s) => s,
    watching: () => o.here(),
    endedAway: (gid, job, ok) => log.push(`away:${gid}:${job}:${ok ? "done" : "failed"}`),
    selectBuilt: (id) => log.push(`tpl:${id}`),
  };
  return { d, log, done: () => hooks.onDone?.({ id: "j1" } as Job), failed: () => hooks.onFailed?.({ id: "j1", error: "Модель не ответила", message: "" } as Job) };
}
const deck = (id: string): Generation => ({ id, template_id: "t1", strategies: ["a"], variants: [], status: "done" } as unknown as Generation);
const target = { jobId: "j1", generation: "g1", strategies: ["a"], template: "t1", slides: 10 };

test("сборка кончилась на её экране: презентация открывается, её шаблон встаёт в «Создать»", async () => {
  const f = fakeDeps({ here: () => true });
  let ended = 0;
  followBuild(target, f.d, () => ended++);
  await f.done();
  assert.deepEqual(f.log.filter((x) => !x.startsWith("msg:")), ["list", "load:g1", "ui:result", "tpl:t1"]);
  assert.equal(ended, 1);
});

test("сборка кончилась, пока человек в другом месте: экран и открытая презентация не трогаются, «Создать» скажет", async () => {
  const f = fakeDeps({ here: () => false });
  let ended = 0;
  followBuild(target, f.d, () => ended++);
  await f.done();
  assert.deepEqual(f.log, ["away:g1:j1:done", "list"]);
  assert.equal(ended, 1);
});

test("ушли с экрана сборки, пока грузилась её презентация: экран не уводится, итог — строкой", async () => {
  let here = true;
  const f = fakeDeps({ here: () => here });
  f.d.fetchGeneration = async (gid) => { here = false; return deck(gid); };
  followBuild(target, f.d);
  await f.done();
  assert.deepEqual(f.log, ["list", "away:g1:j1:done"]);
});

test("сборка упала в другом месте — итог строкой; на её экране — остаётся экран «Сборка»", async () => {
  const away = fakeDeps({ here: () => false });
  followBuild(target, away.d);
  away.failed();
  assert.equal(away.log[0], "away:g1:j1:failed");
  assert.ok(!away.log.some((x) => x.startsWith("ui:")));
  const here = fakeDeps({ here: () => true });
  followBuild(target, here.d);
  here.failed();
  assert.ok(!here.log.some((x) => x.startsWith("away:") || x.startsWith("ui:")));
});

test("итог сборки, кончившейся в другом месте, увидели: её экран «Сборка» или её презентация на результате", () => {
  const end = { gid: "g1", job: "j1" };
  assert.equal(endSeen(end, "build", "j1", null), true);
  assert.equal(endSeen(end, "result", "j1", "g1"), true);
  assert.equal(endSeen(end, "build", "j2", "g1"), false); // на экране другая сборка
  assert.equal(endSeen(end, "result", "j1", "g2"), false); // открыта другая презентация
  assert.equal(endSeen(end, "create", "j1", "g1"), false);
});

test("«Улучшить готовую»: прочитанная презентация открывает «Создать», только когда человек там; иначе ждёт", () => {
  assert.equal(improveArrives("create"), "open");
  assert.equal(improveArrives("result"), "wait");
  assert.equal(improveArrives("build"), "wait");
});

test("сборка кончилась, а её презентация не открылась: на её экране — строка и «Открыть ещё раз», ушли — строка на «Создать» (B-M2)", async () => {
  const here = fakeDeps({ here: () => true, deck: null });
  followBuild(target, here.d);
  await here.done();
  assert.deepEqual(here.log, ["list", "load:g1"]); // экран «Сборка» стоит, его строку пишет загрузка (область «Сборка»)
  let on = true;
  const away = fakeDeps({ here: () => on, deck: null });
  away.d.fetchGeneration = async () => { on = false; return null; };
  followBuild(target, away.d);
  await away.done();
  assert.deepEqual(away.log, ["list", "away:g1:j1:done"]);
});

test("загрузка шаблона и чтение презентации: задача разбора — вызывающему; неудачное чтение обновляет список шаблонов (B-M6, B-M3)", async () => {
  const real = api.uploadTemplate;
  api.uploadTemplate = (async () => ({ job_id: "j9", use_models: true })) as unknown as typeof api.uploadTemplate;
  try {
    for (const improve of [false, true]) {
      const log: string[] = [];
      let hooks: Hooks = {};
      const d: UploadDeps = {
        runJob: (id, _l, opts) => { log.push(`job:${id}`); hooks = opts ?? {}; },
        report: () => log.push("report"), notify: () => log.push("notify"), clearNotice: () => {}, pushMessage: () => log.push("msg"), dispatch: () => {},
        setTemplates: () => {}, adoptManifest: () => {}, refreshTemplates: async () => { log.push("templates"); },
      };
      let job: string | null = null;
      const done = uploadTemplateFlow({ name: "Итоги.pptx" } as File, true, d, improve ? () => {} : undefined, (id) => { job = id; log.push(`own:${id}`); });
      await new Promise((r) => setTimeout(r, 0));
      assert.equal(job, "j9");
      assert.deepEqual(log.slice(0, 2), ["own:j9", "job:j9"]);
      hooks.onFailed?.({ id: "j9", error: "битый файл", message: "" } as Job);
      await done;
      assert.equal(log.includes("templates"), improve);
    }
  } finally {
    api.uploadTemplate = real;
  }
});
