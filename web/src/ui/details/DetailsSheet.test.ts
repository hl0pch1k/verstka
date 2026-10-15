import { test } from "node:test";
import assert from "node:assert/strict";
import { queueTabs } from "./DetailsSheet";
import { SHEET_TABS } from "./sheetView";
import type { SheetTab } from "../deck/geometry";

/** Подставное окружение очереди: свои часы (таймеры и свободное время — через 1 мс), ход колоды — вручную. */
function bench(open: SheetTab = "quality") {
  let now = 0;
  let seq = 0;
  const tasks: { at: number; n: number; id: number; f: () => void }[] = [];
  const mounted = new Set<SheetTab>([open]);
  const log: string[] = [];
  const moves = new Set<(m: boolean) => void>();
  const add = (f: () => void, ms: number) => {
    const id = ++seq;
    tasks.push({ at: now + ms, n: id, id, f });
    return id;
  };
  const stop = queueTabs({
    rest: () => SHEET_TABS.find((x) => !mounted.has(x.key))?.key,
    mount: (k) => {
      mounted.add(k);
      log.push(`${k}@${now}`);
    },
    settle: () => log.push(`settled@${now}`),
    idle: (f) => void add(f, 1),
    later: add,
    clear: (id) => {
      const i = tasks.findIndex((x) => x.id === id);
      if (i >= 0) tasks.splice(i, 1);
    },
    onMove: (f) => {
      moves.add(f);
      return () => void moves.delete(f);
    },
  });
  /** Часы до `to` (мс от открытия листа). */
  const run = (to: number) => {
    for (;;) {
      tasks.sort((a, b) => a.at - b.at || a.n - b.n);
      const x = tasks[0];
      if (!x || x.at > to) break;
      tasks.shift();
      now = x.at;
      x.f();
    }
    now = to;
  };
  const move = (m: boolean) => moves.forEach((f) => f(m));
  const at = (s: string) => Number(log.find((x) => x.startsWith(`${s}@`))?.split("@")[1] ?? NaN);
  return { run, move, stop, log, at, moves };
}

const REST = SHEET_TABS.map((t) => t.key).filter((k) => k !== "quality");

test("очередь вкладок: без хода — по одной в свободное время после въезда листа, потом «улеглись»", () => {
  const b = bench();
  b.run(700);
  assert.deepEqual(b.log, []);
  b.run(5000);
  assert.deepEqual(b.log.map((x) => x.split("@")[0]), [...REST, "settled"]);
  assert.ok(b.at("why") >= 720);
  assert.ok(b.at("settled") - b.at("files") >= 900);
});

test("очередь вкладок: помощник открыт до первого монтирования — вкладки ждут конца хода", () => {
  const b = bench();
  b.run(200);
  b.move(true);
  b.run(760);
  assert.deepEqual(b.log, []);
  b.move(false);
  b.run(5000);
  assert.deepEqual(b.log.map((x) => x.split("@")[0]), [...REST, "settled"]);
  assert.ok(b.at("why") > 760);
});

test("очередь вкладок: ход посреди монтирования — ни одной вкладки в его кадрах, после — остальные", () => {
  const b = bench();
  b.run(721);
  assert.deepEqual(b.log.map((x) => x.split("@")[0]), ["why"]);
  b.move(true);
  b.run(1281);
  assert.equal(b.log.length, 1);
  b.move(false);
  b.run(5000);
  assert.deepEqual(b.log.map((x) => x.split("@")[0]), [...REST, "settled"]);
  assert.ok(b.at("agent") > 1281);
});

test("очередь вкладок: ход снова пошёл до отложенного шага — шаг ждёт и этот ход", () => {
  const b = bench();
  b.run(600);
  b.move(true);
  b.run(1160);
  b.move(false);
  b.move(true); // шаг после хода ещё не прошёл (свободное время — через 1 мс), а помощник уже снова пошёл
  b.run(1720);
  assert.deepEqual(b.log, []);
  b.move(false);
  b.run(5000);
  assert.ok(b.at("why") > 1720);
});

test("очередь вкладок: «улеглись» не на ходу — ждут его конца", () => {
  const b = bench();
  b.run(1000);
  const files = b.at("files");
  assert.ok(files > 0);
  b.move(true);
  b.run(files + 2000);
  assert.ok(!b.log.some((x) => x.startsWith("settled")));
  b.move(false);
  b.run(files + 2002);
  assert.equal(b.at("settled"), files + 2001);
});

test("очередь вкладок: лист закрыли — ни монтирований, ни «улеглись», ход больше не слушается", () => {
  const b = bench();
  b.run(721);
  b.stop();
  b.run(5000);
  assert.deepEqual(b.log.map((x) => x.split("@")[0]), ["why"]);
  assert.equal(b.moves.size, 0);
  const c = bench();
  c.run(300);
  c.move(true);
  c.stop();
  c.move(false);
  c.run(5000);
  assert.deepEqual(c.log, []);
});

test("очередь вкладок: открытая смонтирована раньше очереди — её очередь пропускает", () => {
  const b = bench("plan");
  b.run(5000);
  assert.deepEqual(b.log.map((x) => x.split("@")[0]), ["quality", "why", "agent", "template", "files", "settled"]);
});
