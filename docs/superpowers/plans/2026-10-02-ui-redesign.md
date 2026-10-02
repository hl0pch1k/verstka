# Редизайн интерфейса Verstka — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** светлый продуктовый интерфейс в духе PresentSimple и тёмная «сцена Verstka» во время сборки, без потери
функций (спецификация: `docs/superpowers/specs/2026-10-02-ui-redesign-design.md`).

**Architecture:** только `web/`. Чистая логика сцены (`lib/stage.ts`) и свёртка событий задачи (`lib/jobState.ts`)
выносятся в тестируемые функции; стор и dev-повтор используют одну свёртку. Экраны перестраиваются поверх прежней
логики: экран создания — герой + композер + галерея, сборка — три колонки (лента, сцена, журнал), результат — лента
миниатюр слева. Переход сборка → результат — View Transitions с парами имён `vt-title`, `vt-rail`, `vt-stage`,
`vt-aside`.

**Tech Stack:** React 18, TypeScript 5.6, Vite 6, Tailwind 3.4, lucide-react; тесты чистых функций — `node:test`
поверх сборки `esbuild` (уже есть в `node_modules` как зависимость Vite, новых пакетов нет).

**Как читать план.** Логика и тесты даны полным кодом. Код визуальных компонентов пишется прямо в файлы при
выполнении (его окончательный вид определяет визуальная проверка); для них план фиксирует файл, контракт (пропсы и
типы), структуру, классы токенов, поведение и критерии приёмки.

## Global Constraints

- Только фронтенд (`web/`); API и бэкенд не меняются.
- Минимальная ширина 1200 px; проверка на 1280×720, 1440×900, 1920×1080.
- Контраст текста ≥ 4,5:1, видимый фокус с клавиатуры, `prefers-reduced-motion` выключает циклы и перемещения.
- Циклические анимации работают только пока идёт их работа.
- Тексты интерфейса — безличные, по-русски, с «ё»; без названий бэкендов моделей.
- Git: `/Library/Developer/CommandLineTools/usr/bin/git`, ветка `next`, сообщения по-русски, без строки
  `Co-Authored-By`, без push (GitHub-репозиторий заморожен).
- Сервер владельца на :8000 и его рабочую папку не трогать; проверка — приватные API :8767 и Vite :5181
  (`.claude/launch.json`: `verstka-ui2-api`, `verstka-ui2-web`).

## Карта файлов

| Файл | Ответственность |
|---|---|
| `web/scripts/test.mjs` (новый) | собирает `src/**/*.test.ts` через esbuild и запускает `node --test` |
| `web/src/lib/stage.ts` (новый) | заголовки этапов, разбор слов дизайнера в эскиз, состояние плиток ленты, строки журнала |
| `web/src/lib/stage.test.ts` (новый) | тесты `stage.ts` |
| `web/src/lib/jobState.ts` (новый) | тип `ActiveJob`, `foldJobEvent` — свёртка события задачи в состояние |
| `web/src/lib/jobState.test.ts` (новый) | тесты свёртки |
| `web/src/lib/jobText.ts` | `VariantProgress` получает `laid` и `of` |
| `web/src/store.tsx`, `web/src/lib/flows.ts` | стор использует `foldJobEvent`; задача знает `generation` и `slides` |
| `web/tailwind.config.js`, `web/src/index.css`, `web/index.html` | токены: тёплый фон, градиент, сцена, `text-hero`, тени, ключевые кадры |
| `web/src/components/ui/Button.tsx` | вариант `brand`, форма `pill` |
| `web/src/components/shell/{Logo,Header}.tsx` | градиентный знак, фон шапки |
| `web/src/components/simple/Typewriter.tsx` (новый) | `TypewriterHint` — печатающиеся примеры |
| `web/src/components/simple/Composer.tsx` (новый) | карточка композера: поле, подсказка, панель, настройки |
| `web/src/components/simple/CreateScreen.tsx` | герой, композер, строка состояния, галерея, плавающая панель |
| `web/src/components/simple/TemplatePicker.tsx` | галерея крупных карточек, плитка загрузки, удаление, открытие предпросмотра |
| `web/src/components/simple/TemplatePreview.tsx` (новый) | модальное окно со всеми слайдами шаблона |
| `web/src/components/simple/SlideThumb.tsx` (новый) | `ThumbImg`, `ThumbBadge` (из `SlideStrip.tsx`) |
| `web/src/components/simple/SlideRail.tsx` (новый) | вертикальная лента миниатюр результата |
| `web/src/components/simple/SlideStrip.tsx` | удаляется |
| `web/src/components/simple/ResultScreen.tsx` | три колонки, пересчёт размеров, скелет, кнопка `brand`, имена переходов |
| `web/src/components/build/{BuildStage,Blueprint,StageRail,AgentLog,VariantChips}.tsx` (новые) | сцена сборки |
| `web/src/components/BuildScreen.tsx` | раскладка сцены, данные из `ActiveJob`, имена переходов |
| `web/src/dev/StageReplay.tsx` (новый), `web/src/main.tsx` | dev-повтор `/?replay=<gid>` |

---

### Task 1: Тестовый прогон чистых функций

**Files:**
- Create: `web/scripts/test.mjs`
- Modify: `web/package.json` (скрипт `test`)

**Interfaces:**
- Produces: `npm test` — собирает каждый `src/**/*.test.ts` в `node_modules/.cache/verstka-tests/*.mjs` и запускает
  `node --test`; ненулевой код выхода при падении.

- [ ] **Step 1: Скрипт**

```js
// web/scripts/test.mjs — the pure functions' tests without a test framework: each src/**/*.test.ts is bundled by
// esbuild (Vite's own) into an ES module and run by node's built-in runner.
import { build } from "esbuild";
import { readdirSync, rmSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { spawnSync } from "node:child_process";

const root = new URL("..", import.meta.url).pathname;
const out = join(root, "node_modules/.cache/verstka-tests");
const found = [];
const walk = (dir) => {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else if (name.endsWith(".test.ts")) found.push(p);
  }
};
walk(join(root, "src"));
rmSync(out, { recursive: true, force: true });
const files = [];
for (const entry of found) {
  const file = join(out, relative(join(root, "src"), entry).replace(/\.ts$/, ".mjs"));
  await build({ entryPoints: [entry], outfile: file, bundle: true, platform: "node", format: "esm", logLevel: "error" });
  files.push(file);
}
const run = spawnSync(process.execPath, ["--test", ...files], { stdio: "inherit" });
process.exit(run.status ?? 1);
```

- [ ] **Step 2: Скрипт в `package.json`**: `"test": "node scripts/test.mjs"` рядом с `typecheck`.
- [ ] **Step 3: Типы для `tsc`** (пакета `@types/node` нет): `web/src/test-env.d.ts`

```ts
// The two node modules the pure functions' tests use (web/scripts/test.mjs runs them); declared here so `tsc` checks
// the tests without @types/node.
declare module "node:test" {
  export function test(name: string, fn: () => void | Promise<void>): void;
}
declare module "node:assert/strict" {
  const assert: {
    equal(actual: unknown, expected: unknown, message?: string): void;
    deepEqual(actual: unknown, expected: unknown, message?: string): void;
    ok(value: unknown, message?: string): void;
  };
  export default assert;
}
```

- [ ] **Step 4:** `npm test` без тестов печатает «tests 0» и выходит с кодом 0; `npm run typecheck` без ошибок.
- [ ] **Step 5: Commit** — «Прогон тестов чистых функций фронтенда без новых зависимостей».

### Task 2: `lib/stage.ts` — слова агента для сцены

**Files:**
- Create: `web/src/lib/stage.ts`, `web/src/lib/stage.test.ts`

**Interfaces:**
- Consumes: `eventParts`, `phaseOfStep`, `PhaseKey` из `lib/agent.ts`; `AgentEvent` из `types.ts`.
- Produces:
  - `type SketchKind = "cover" | "bars" | "hbars" | "pie" | "line" | "table" | "numbers" | "cards" | "list" | "timeline" | "compare" | "quote" | "image" | "agenda" | "section" | "text"`
  - `interface Sketch { slide: number; kind: SketchKind; headline: string | null }`
  - `quoted(text: string): string | null` — первая «…» с вложенными кавычками
  - `stripQuoted(text: string): string` — текст без «…»
  - `sketchKind(text: string): SketchKind`
  - `sketchOf(e: AgentEvent): Sketch | null` — эскиз из строки дизайнера или правки (у правки — только когда строка начинается с названия формы)
  - `STAGE_TITLE: Record<PhaseKey | "queued", string>`, `ROLE: Record<PhaseKey, string>`
  - `type RailMark = "note" | "fixed" | null`, `interface RailSlide { n: number; sketch: Sketch | null; mark: RailMark; laid: boolean }`
  - `railSlides(events: AgentEvent[], variant: string | null, count: number, laid: number): RailSlide[]`
  - `interface LogLine { key: string; time: string | null; phase: PhaseKey; role: string; slide: number | null; text: string }`
  - `logLines(events: AgentEvent[]): LogLine[]`
  - `clock(seconds: number): string` — «1:05»

- [ ] **Step 1: Тесты**

```ts
// web/src/lib/stage.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { clock, logLines, quoted, railSlides, sketchKind, sketchOf, stripQuoted } from "./stage";
import type { AgentEvent } from "../types";

const ev = (step: string, message: string, slide: number | null = null, variant: string | null = null): AgentEvent => ({ step, message, slide, variant });
const plain = (s: string | null) => (s ?? "").replace(/ /g, " ");

test("quoted keeps nested quotes", () => {
  assert.equal(quoted("«Компания «Ромашка» растёт» — таблица"), "Компания «Ромашка» растёт");
  assert.equal(quoted("без кавычек"), null);
  assert.equal(stripQuoted("Обложка «А «Б»», мелким текстом").trim(), "Обложка , мелким текстом");
});

test("sketchKind reads the form words", () => {
  assert.equal(sketchKind("— таблица 3×4."), "table");
  assert.equal(sketchKind("— круговая диаграмма (5 категорий)."), "pie");
  assert.equal(sketchKind("— горизонтальная диаграмма (5 категорий)."), "hbars");
  assert.equal(sketchKind("— столбчатая диаграмма (4 категории)."), "bars");
  assert.equal(sketchKind("— два линейных графика."), "line");
  assert.equal(sketchKind("— список (2 пункта)."), "list");
  assert.equal(sketchKind("— ряд чисел (3 числа)."), "numbers");
  assert.equal(sketchKind("— хронология (5)."), "timeline");
  assert.equal(sketchKind("— что-то новое"), "text");
});

test("sketchOf: designer lines give the slide, its form and its headline", () => {
  const t = sketchOf(ev("designer", "«Средняя месячная выручка на одного клиента составит 5 050 рублей» — таблица 3×4.", 5));
  assert.equal(t?.slide, 5);
  assert.equal(t?.kind, "table");
  assert.equal(plain(t?.headline ?? null), "Средняя месячная выручка на одного клиента составит 5 050 рублей");
  // a dash inside the headline is not the form's dash
  assert.equal(sketchOf(ev("designer", "«Цель — 250 клиентов и 225 000 ₽ прибыли к шестому месяцу» — список (2 пункта).", 2))?.kind, "list");
  assert.equal(sketchOf(ev("designer", "Обложка «Открытие фитнес-студии», мелким текстом — условность данных.", 1))?.kind, "cover");
  assert.equal(sketchOf(ev("designer", "без слайда — таблица")), null);
});

test("sketchOf: a revision counts only when it names a form", () => {
  assert.equal(sketchOf(ev("revise", "Столбчатая диаграмма (2 категории).", 6))?.kind, "bars");
  assert.equal(sketchOf(ev("revise", "Добавил из текста ключевые цифры или вывод, которых на слайде не было.", 6)), null);
  assert.equal(sketchOf(ev("critic", "На слайде нет ключевой цифры из текста: «3 000 000 рублей»", 10)), null);
});

test("railSlides: shared plan, own critic and revision, laid out slides", () => {
  const events = [
    ev("designer", "Обложка «Старт», мелким текстом — условность.", 1),
    ev("designer", "«Доли рынка» — круговая диаграмма (3 категории).", 2),
    ev("designer", "«Итоги» — список (3 пункта).", 4),
    ev("critic", "Заголовок повторяет тему слайда", 2, "visual"),
    ev("critic", "На слайде нет ключевой цифры", 4, "structured"),
    ev("revise", "Таблица 2×3.", 4, "structured"),
  ];
  const rail = railSlides(events, "structured", 3, 2);
  assert.equal(rail.length, 4); // the designer planned slide 4: the rail grows to it
  assert.deepEqual(rail.map((s) => s.sketch?.kind ?? null), ["cover", "pie", null, "table"]);
  assert.deepEqual(rail.map((s) => s.mark), [null, null, null, "fixed"]); // the visual variant's note is not ours
  assert.deepEqual(rail.map((s) => s.laid), [true, true, false, false]);
  assert.equal(railSlides(events, "visual", 3, 0)[1].mark, "note");
});

test("logLines: time from the start, role and text", () => {
  const lines = logLines([{ step: "analyst", message: "Нашёл в тексте 12 слайдов.", slide: null, variant: null, t: 65.2 }, { step: "designer", message: "«Итоги» — список (3 пункта).", slide: 4, variant: null }]);
  assert.equal(lines[0].time, "1:05");
  assert.equal(lines[0].role, "аналитик");
  assert.equal(lines[1].time, null);
  assert.equal(lines[1].slide, 4);
  assert.equal(clock(0), "0:00");
  assert.equal(clock(301), "5:01");
});
```

- [ ] **Step 2:** `npm test` → FAIL (`Could not resolve "./stage"`).
- [ ] **Step 3: Реализация**

```ts
// web/src/lib/stage.ts — the planning agent's words for the build stage: which form a slide gets (a sketch the stage
// draws and the rail shows), what each phase is called on the stage, the rail's per-slide state and the log's lines.
// Pure functions, no React.
import type { AgentEvent } from "../types";
import { eventParts, phaseOfStep, withPhases, type PhaseKey } from "./agent";

export type SketchKind = "cover" | "bars" | "hbars" | "pie" | "line" | "table" | "numbers" | "cards" | "list" | "timeline" | "compare" | "quote" | "image" | "agenda" | "section" | "text";

export interface Sketch { slide: number; kind: SketchKind; headline: string | null }

/** The big words of the stage per phase (the queue before the first event too). */
export const STAGE_TITLE: Record<PhaseKey | "queued", string> = {
  queued: "Готовлюсь к сборке",
  writer: "Пишу текст по теме",
  analyst: "Читаю ваш текст",
  architect: "Выстраиваю сюжет",
  designer: "Продумываю слайды",
  critic: "Сверяю план с текстом",
  revise: "Переделываю слабые места",
  layout: "Собираю в вашем шаблоне",
  check: "Проверяю каждое число",
};

/** Who speaks in the log («ДИЗАЙНЕР»). */
export const ROLE: Record<PhaseKey, string> = {
  writer: "автор", analyst: "аналитик", architect: "архитектор", designer: "дизайнер",
  critic: "критик", revise: "правка", layout: "вёрстка", check: "проверка",
};

/** The first «…» of a text, nested quotes kept («Компания «Ромашка» растёт»); null without a closed one. */
export function quoted(text: string): string | null {
  const start = text.indexOf("«");
  if (start < 0) return null;
  let depth = 0;
  for (let i = start; i < text.length; i++) {
    if (text[i] === "«") depth += 1;
    else if (text[i] === "»" && --depth === 0) return text.slice(start + 1, i).trim() || null;
  }
  return null;
}

/** The text without its «…» parts: what the agent says about the slide, not the slide's own words. */
export function stripQuoted(text: string): string {
  let depth = 0;
  let out = "";
  for (const ch of text) {
    if (ch === "«") depth += 1;
    else if (ch === "»") depth = Math.max(0, depth - 1);
    else if (depth === 0) out += ch;
  }
  return out;
}

// the first match wins: «горизонтальная диаграмма» before «диаграмма», «две диаграммы: круговая и …» reads as a pie
const KINDS: Array<[RegExp, SketchKind]> = [
  [/обложк|титул/i, "cover"],
  [/горизонтальн|линейчат/i, "hbars"],
  [/кругов|кольцев/i, "pie"],
  [/линейн|график|с областями/i, "line"],
  [/столбч|гистограмм|диаграмм/i, "bars"],
  [/таблиц/i, "table"],
  [/числ|цифр|показател|метрик/i, "numbers"],
  [/хронолог|таймлайн|процесс|шаг|этап/i, "timeline"],
  [/сравнен|колонк|до и после/i, "compare"],
  [/карточ/i, "cards"],
  [/список|пункт|тезис/i, "list"],
  [/цитат/i, "quote"],
  [/картинк|фото|иллюстрац|изображен/i, "image"],
  [/повестк|содержани/i, "agenda"],
  [/раздел/i, "section"],
];

export function sketchKind(text: string): SketchKind {
  for (const [re, kind] of KINDS) if (re.test(text)) return kind;
  return "text";
}

// a revision line that is a form («Столбчатая диаграмма (2 категории).»), not a note on what was added
const FORM_FIRST = /^(?:обложк|титул|горизонтальн|линейчат|кругов|кольцев|линейн|график|столбч|гистограмм|диаграмм|две\s|два\s|таблиц|ряд\s|больш|крупн|хронолог|таймлайн|процесс|сравнен|карточ|список|цитат|повестк)/i;

/** The sketch of a designer's line (««Заголовок» — круговая диаграмма (5 категорий).») or of a revision that names
 *  its new form; null for anything else. */
export function sketchOf(e: AgentEvent): Sketch | null {
  if (e.slide === null || e.slide === undefined) return null;
  const step = (e.step ?? "").toLowerCase();
  if (step !== "designer" && step !== "revise") return null;
  const { text } = eventParts(e);
  if (step === "revise" && !FORM_FIRST.test(text.trim())) return null;
  return { slide: e.slide, kind: sketchKind(stripQuoted(text)), headline: quoted(text) };
}

export type RailMark = "note" | "fixed" | null;
export interface RailSlide { n: number; sketch: Sketch | null; mark: RailMark; laid: boolean }

/** The rail of one variant: a tile per slide (`count` at least, more when the designer planned more), its sketch,
 *  whether the critic left a note on it (and whether it was then revised), and whether it is laid out already. */
export function railSlides(events: AgentEvent[], variant: string | null, count: number, laid: number): RailSlide[] {
  const sketches = new Map<number, Sketch>();
  const marks = new Map<number, RailMark>();
  let top = count;
  for (const e of events) {
    if (e.variant != null && e.variant !== variant) continue;
    const n = e.slide;
    if (n === null || n === undefined || n < 1) continue;
    const step = (e.step ?? "").toLowerCase();
    const sk = sketchOf(e);
    if (sk) sketches.set(n, sk);
    if (step === "designer") top = Math.max(top, n);
    if (step === "critic" && marks.get(n) !== "fixed") marks.set(n, "note");
    if (step === "revise") marks.set(n, "fixed");
  }
  return Array.from({ length: Math.max(0, top) }, (_, i) => ({ n: i + 1, sketch: sketches.get(i + 1) ?? null, mark: marks.get(i + 1) ?? null, laid: i + 1 <= laid }));
}

export const clock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export interface LogLine { key: string; time: string | null; phase: PhaseKey; role: string; slide: number | null; text: string }

/** Every line of the agent, in order, as the log shows it. */
export function logLines(events: AgentEvent[]): LogLine[] {
  return withPhases(events).map((e, i) => ({
    key: e.seq !== undefined && e.seq !== null ? `#${e.seq}` : `${i}`,
    time: typeof e.t === "number" ? clock(e.t) : null,
    phase: e.phase,
    role: ROLE[phaseOfStep(e.step) ?? e.phase],
    slide: e.slide ?? null,
    text: eventParts(e).text,
  }));
}
```

- [ ] **Step 4:** `npm test` → все тесты `stage.test.ts` PASS; `npm run typecheck` без ошибок.
- [ ] **Step 5: Commit** — «Сцена: разбор слов дизайнера в эскиз слайда, лента и журнал агента».

### Task 3: `lib/jobState.ts` — одна свёртка событий задачи

**Files:**
- Create: `web/src/lib/jobState.ts`, `web/src/lib/jobState.test.ts`
- Modify: `web/src/lib/jobText.ts` (`VariantProgress`), `web/src/store.tsx` (тип и `runJob`), `web/src/lib/flows.ts`

**Interfaces:**
- Consumes: `humanizeJobMessage`, `variantProgress` (`lib/jobText.ts`); `addAgentEvent`, `laterPhase`, `phaseOfEvent`, `phaseOfMessage`, `toAgentEvent`, `eventParts` (`lib/agent.ts`).
- Produces:
  - `VariantProgress { text: string; done: boolean; frac: number; laid?: number; of?: number }`
  - `interface StageLine { text: string; slide: number | null; variant: string | null; n: number }`
  - `interface ActiveJob { …прежние поля…; generation?: string | null; slides?: number | null; line?: StageLine | null }`
  - `foldJobEvent(cur: ActiveJob, ev: JobEvent, titleOf: (name: string) => string): ActiveJob`
  - `store.tsx` реэкспортирует `type ActiveJob`; `RunJobOptions` получает `generation?: string | null; slides?: number | null`.

- [ ] **Step 1: Тесты**

```ts
// web/src/lib/jobState.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { foldJobEvent, type ActiveJob } from "./jobState";
import type { JobEvent } from "../types";

const start: ActiveJob = { id: "j", label: "", progress: 0, message: "", status: "queued", kind: "generate", startedAt: 0 };
const titleOf = (n: string) => (n === "structured" ? "Структурный" : n);
const msg = (message: string, progress = 0.5): JobEvent => ({ job_id: "j", status: "running", progress, message, t: 1 });
const agent = (seq: number, step: string, message: string, slide: number | null = null): JobEvent => ({ ...msg(message, 0.3), type: "agent", step, slide, variant: null, seq });

test("an agent event is added once and becomes the stage line", () => {
  let j = foldJobEvent(start, agent(1, "designer", "«Итоги» — список (3 пункта).", 4), titleOf);
  j = foldJobEvent(j, agent(1, "designer", "«Итоги» — список (3 пункта).", 4), titleOf);
  assert.equal(j.agent?.length, 1);
  assert.equal(j.phase, "designer");
  assert.equal(j.line?.slide, 4);
  assert.equal(j.line?.n, 1);
});

test("the layout keeps the planned count and counts the laid slides", () => {
  let j = foldJobEvent(start, msg("structured: planned 12 slides, rendering"), titleOf);
  assert.deepEqual([j.variants?.structured.of, j.variants?.structured.laid], [12, 0]);
  j = foldJobEvent(j, msg("structured: rendered slide 3/12"), titleOf);
  assert.deepEqual([j.variants?.structured.of, j.variants?.structured.laid], [12, 3]);
  assert.equal(j.line?.slide, 3);
  j = foldJobEvent(j, msg("structured: audit"), titleOf);
  assert.deepEqual([j.variants?.structured.of, j.variants?.structured.laid, j.variants?.structured.text], [12, 12, "проверка качества"]);
});

test("progress never goes back; a repeated poll does not retype the line", () => {
  let j = foldJobEvent(start, msg("structured: rendered slide 3/12", 0.6), titleOf);
  const n = j.line?.n;
  j = foldJobEvent(j, msg("structured: rendered slide 3/12", 0.4), titleOf);
  assert.equal(j.progress, 0.6);
  assert.equal(j.line?.n, n);
});
```

- [ ] **Step 2:** `npm test` → FAIL (`Could not resolve "./jobState"`).
- [ ] **Step 3: `jobText.ts`** — в `VariantProgress` добавить `laid?: number; of?: number`; `variantProgress` отдаёт
  `{ …, of: N, laid: 0 }` для «planned N slides» и `{ …, laid: i, of: n }` для «rendered slide i/n».
- [ ] **Step 4: Реализация `jobState.ts`**

```ts
// web/src/lib/jobState.ts — the state of a running job as the interface sees it, and the one fold of a job event into
// it: the store folds the stream (and the polled record) with it, the dev replay folds a recorded build the same way.
import type { AgentEvent, JobEvent, JobKind, JobStatus } from "../types";
import { addAgentEvent, eventParts, laterPhase, phaseOfEvent, phaseOfMessage, toAgentEvent, type PhaseKey } from "./agent";
import { humanizeJobMessage, variantProgress, type VariantProgress } from "./jobText";

/** What the stage says now: the agent's newest line or the pipeline's newest step. `n` counts the changes (a repeat
 *  of the same words is no change). */
export interface StageLine { text: string; slide: number | null; variant: string | null; n: number }

export interface ActiveJob {
  id: string; label: string; progress: number; message: string; status: JobStatus; kind: JobKind; startedAt: number; items?: string[]; variants?: Record<string, VariantProgress>;
  /** The planning agent's steps so far (Agent v2) and the latest phase of the timeline the job has reached. */
  agent?: AgentEvent[]; phase?: PhaseKey | null;
  /** The template a generation is built from (the build screen names it under its title). */
  template?: string | null;
  /** The slide a job works on (a slide fix): the stage and the thumbnails mark it. */
  target?: { generation: string; strategy: string; slide: number };
  /** The generation being built (its slide previews appear on the rail once rendered) and the slide count asked for. */
  generation?: string | null; slides?: number | null;
  line?: StageLine | null;
}

const clamp01 = (n: number) => Math.min(1, Math.max(0, Number.isFinite(n) ? n : 0));

/** A variant's new status over its last: the planned count stays; checking and fixing mean every slide is laid out. */
function mergeVariant(prev: VariantProgress | undefined, next: VariantProgress): VariantProgress {
  const of = next.of ?? prev?.of;
  const laid = next.laid ?? (next.done || /^(проверка|исправляю)/.test(next.text) ? of : prev?.laid);
  return { ...next, of, laid };
}

function nextLine(cur: StageLine | null | undefined, text: string, slide: number | null, variant: string | null): StageLine | null | undefined {
  if (!text || (cur && cur.text === text && cur.slide === slide && cur.variant === variant)) return cur;
  return { text, slide, variant, n: (cur?.n ?? 0) + 1 };
}

export function foldJobEvent(cur: ActiveJob, ev: JobEvent, titleOf: (name: string) => string): ActiveJob {
  const isAgent = ev.type === "agent";
  // the agent speaks plain Russian already; the pipeline's own messages are for logs and get translated
  const message = isAgent ? ev.message : ev.message ? humanizeJobMessage(ev.message, titleOf) : "";
  const step = !isAgent && ev.message ? variantProgress(ev.message) : null;
  const agent = isAgent ? addAgentEvent(cur.agent, toAgentEvent(ev)) : cur.agent;
  let line = cur.line;
  if (isAgent && agent !== cur.agent) line = nextLine(line, eventParts(toAgentEvent(ev)).text, ev.slide ?? null, ev.variant ?? null);
  // only the pipeline's own steps speak on the stage (a polled record repeats the agent's last words as its message)
  else if (!isAgent && ev.message && phaseOfMessage(ev.message)) line = nextLine(line, message, step?.state.laid || null, step?.name ?? null);
  return {
    ...cur,
    status: ev.status,
    progress: Math.max(cur.progress, clamp01(ev.progress)),
    message: message || cur.message,
    variants: step ? { ...cur.variants, [step.name]: mergeVariant(cur.variants?.[step.name], step.state) } : cur.variants,
    agent,
    phase: laterPhase(cur.phase, phaseOfEvent(ev)),
    line,
  };
}
```

- [ ] **Step 5: Стор.** В `store.tsx`: удалить локальный `interface ActiveJob` и `clamp01`, импортировать
  `foldJobEvent` и `type ActiveJob` из `./lib/jobState`, добавить `export type { ActiveJob } from "./lib/jobState";`.
  `onEvent` становится `setActiveJob((cur) => (cur && cur.id === jobId ? foldJobEvent(cur, ev, (n) => titleIn(latest.current.strategies, n)) : cur))`
  (терминальные события по-прежнему пропускаются). `RunJobOptions` и стартовое состояние получают
  `generation: opts?.generation ?? null, slides: opts?.slides ?? null`.
- [ ] **Step 6: `flows.ts`** — `CommonDeps.runJob` принимает `generation?`/`slides?`; `generationFlow` передаёт
  `generation: res.generation_id, slides: req.slides ?? null`.
- [ ] **Step 7:** `npm test` PASS, `npm run typecheck` без ошибок.
- [ ] **Step 8: Commit** — «Одна свёртка событий задачи: строка сцены, план и свёрстанные слайды каждого варианта».

### Task 4: Визуальная система, кнопки, логотип, шапка

**Files:**
- Modify: `web/tailwind.config.js`, `web/src/index.css`, `web/index.html`, `web/src/components/ui/Button.tsx`,
  `web/src/components/shell/Logo.tsx`, `web/src/components/shell/Header.tsx`

**Interfaces:**
- Produces: классы `bg-canvas` (#F4F3EF), `bg-brand`, `text-brand`, `shadow-brand`, `shadow-float`, `bg-stage`,
  `bg-stage-raised`, `text-hero`; `animate-word-rise`, `animate-word-out`, `animate-fill-in`, `animate-stage-glow`,
  `animate-scan-down`, `animate-grow-y`, `animate-grow-x`, `animate-draw`, `animate-tile-pulse`;
  `<Button variant="brand">`, `<Button shape="pill">`, `LogoMark` с градиентом.

- [ ] **Step 1: tailwind.config.js** — `colors.canvas: "#F4F3EF"`; `colors.stage: { DEFAULT: "#0B0D12", raised: "#141821" }`;
  `backgroundImage.brand: "linear-gradient(100deg, #0066F5 0%, #3858FF 55%, #6A4DFF 100%)"`;
  `boxShadow.brand: "0 10px 30px -10px rgba(56, 88, 255, 0.55)"`, `boxShadow["brand-hover"]: "0 14px 36px -10px rgba(56, 88, 255, 0.7)"`,
  `boxShadow.float: "0 0 0 1px rgba(16, 24, 40, 0.05), 0 2px 4px rgba(16, 24, 40, 0.04), 0 24px 56px -24px rgba(16, 24, 40, 0.24)"`;
  `fontSize.hero: ["64px", { lineHeight: "68px", letterSpacing: "-0.035em" }]`; ключевые кадры:
  `word-rise {from: opacity 0, translateY(0.45em)}`, `word-out {to: opacity 0, translateY(-0.35em)}`,
  `fill-in {from: opacity 0, scale(.94)}`, `stage-glow {0%,100%: opacity .75, scale(1); 50%: opacity 1, scale(1.08)}`,
  `scan-down {0%: translateY(-100%); 100%: translateY(400%)}`, `grow-y {from: scaleY(0)}`, `grow-x {from: scaleX(0)}`,
  `draw {from: stroke-dashoffset: var(--len)}`, `tile-pulse {0%: box-shadow 0 0 0 0 rgba(0,119,255,.55); 100%: 0 0 0 8px rgba(0,119,255,0)}`;
  анимации к ним (входы 300–500 мс `--ease-out`, `stage-glow 7s ease-in-out infinite`, `scan-down 2.4s linear infinite`).
- [ ] **Step 2: index.css** — `.text-brand` (градиент + `background-clip: text` + `color: transparent`,
  `-webkit-box-decoration-break: clone`), `body` уже `bg-canvas`; правила View Transitions для `vt-rail`, `vt-stage`
  (`mix-blend-mode: normal`, старое уходит как `vt-aside`, новое проявляется), классы `.vt-rail`, `.vt-stage`;
  контейнерный запрос сборки: `.build-grid` три колонки `152px minmax(0,1fr) 288px`, при ширине контейнера
  `build` < 1100 px — две колонки и `.build-log { display: none }`.
- [ ] **Step 3: index.html** — `<style>html, body { background: #F4F3EF; }</style>`, `theme-color` `#F4F3EF`, Onest
  с весами `400;500;600;700;800`, иконка вкладки — плитка с `linearGradient` #0066F5 → #6A4DFF.
- [ ] **Step 4: Button.tsx** — `ButtonVariant` += `"brand"`:
  `"relative isolate bg-brand text-white shadow-brand hover:shadow-brand-hover before:absolute before:inset-0 before:-z-10 before:rounded-[inherit] before:bg-white/0 before:transition-colors before:duration-150 before:content-[''] hover:before:bg-white/[0.12] active:before:bg-black/[0.08]"`;
  `ButtonShape` += `"pill"` (скругление `rounded-full`, поля прежние); `buttonClass` учитывает обе формы.
- [ ] **Step 5: Logo.tsx** — `LogoMark` рисует плитку градиентом (`useId()` для id градиента), полосы белые как раньше.
- [ ] **Step 6: Header.tsx** — фон `bg-canvas`, линия `shadow-[inset_0_-1px_0_rgba(16,24,40,0.07)]`.
- [ ] **Step 7:** `npm run build` без ошибок; на :5181 фон тёплый, логотип с градиентом, ничего не сломано.
- [ ] **Step 8: Commit** — «Визуальная система: тёплый фон, фирменный градиент, тёмная сцена, кнопка brand».

### Task 5: Вертикальная лента миниатюр результата

**Files:**
- Create: `web/src/components/simple/SlideThumb.tsx`, `web/src/components/simple/SlideRail.tsx`
- Modify: `web/src/components/simple/ResultScreen.tsx`, `web/src/components/VariantsSlidePreview.tsx` (класс рамки)
- Delete: `web/src/components/simple/SlideStrip.tsx`

**Interfaces:**
- Produces:
  - `SlideThumb.tsx`: `export function ThumbImg({ url, onBroken }: { url: string; onBroken(url: string): void })`,
    `export function ThumbBadge({ count, sev, fixing, delay }: { count: number; sev: Severity | null; fixing: boolean; delay: number })` — перенос без изменений.
  - `SlideRail.tsx`: `export function SlideRail(props: { variant: Variant; rev: string; total: number; selected: number; aspect: number; issueMap: Map<number, Issue[]>; showRemarks?: boolean; fixingSlide?: number | null; onSelect(n: number): void; className?: string })`.
  - `VariantsSlidePreview` получает необязательный `frameClassName?: string` для рамки слайда.

- [ ] **Step 1: SlideThumb.tsx** — перенести `ThumbImg`, `ThumbBadge`, `BADGE` из `SlideStrip.tsx`.
- [ ] **Step 2: SlideRail.tsx** — белая карточка `rounded-2xl bg-white shadow-card` на всю высоту колонки 152 px;
  внутри прокручиваемый список (`overflow-y-auto`, `[scrollbar-width:none]`, маска-затухание сверху/снизу только когда
  там есть скрытое), плитки шириной 128 px с `aspect-ratio` слайда, номер в углу, `ThumbBadge`, `ThumbImg` или
  заголовок слайда без картинки. Одно кольцо выбора `useIndicator(list, '[aria-current="true"]', key, { outset: 4 })`
  скользит по вертикали. Одна точка табуляции (активная плитка), ↑/↓ листают (с `preventDefault`), фокус следует за
  выбором. Активная плитка прокручивается в видимую часть только внутри ленты (`scrollTo`, не `scrollIntoView`).
- [ ] **Step 3: ResultScreen.tsx** — константы `STAGE_CHROME = 84` (поля 32 + шапка 40 + зазор 12),
  `RAIL_W = 152 + 16`; `capH` вычитает `RAIL_W`; сетка `grid-cols-[152px_minmax(0,1fr)_288px]` (без правой колонки —
  `grid-cols-[152px_minmax(0,1fr)]`); `<SlideRail className="vt-rail" …/>` первой колонкой (у пустого варианта —
  пустая карточка); удалить блок `stripRef`/`SlideStrip`, состояние `box`, `onBox`; затухание ленты в эффекте
  `layoutKey` убрать (лента не меняет ширину); `frameClassName="vt-stage"`; «Скачать PowerPoint» — `variant="brand"`;
  `DeckSkeleton` — та же сетка из трёх колонок (скелет ленты — 6 плиток 128×72).
- [ ] **Step 4:** `npm run build`; на :5181 открыть презентацию: лента слева, клики, ↑/↓, ←/→, режим «Замечания»
  (счётчики на плитках), помощник открыт/закрыт (правая колонка уезжает под помощника и возвращается), полноэкранный
  просмотр, 1280×720 и 1920×1080.
- [ ] **Step 5: Commit** — «Результат: миниатюры слайдов вертикальной лентой слева, слайду — вся высота».

### Task 6: Экран «Создать» — герой и композер

**Files:**
- Create: `web/src/components/simple/Typewriter.tsx`, `web/src/components/simple/Composer.tsx`
- Modify: `web/src/components/simple/CreateScreen.tsx`

**Interfaces:**
- Produces:
  - `export function TypewriterHint({ lines, active, className }: { lines: string[]; active: boolean; className?: string })` —
    `aria-hidden` текст с кареткой; печать 35 мс/знак, пауза 2200 мс, стирание 18 мс/знак, пауза 400 мс; при
    `!active` ничего не рендерит; при `prefers-reduced-motion` — первый пример целиком без каретки.
  - `export const Composer = forwardRef<HTMLDivElement, ComposerProps>` где
    `ComposerProps = { invalid: boolean; shake: boolean; field: ReactNode; hint: ReactNode; toolbar: ReactNode; settings: ReactNode; settingsOpen: boolean; settingsId: string }` —
    карточка `rounded-[28px] bg-white shadow-float`, при `:focus-within` градиентная обводка 1,5 px (слой
    `bg-brand` под карточкой с `opacity` 0 → 1) и мягкое свечение; `invalid` — красное кольцо; `shake` — `animate-shake`.

- [ ] **Step 1: Typewriter.tsx** по контракту (один таймер в `useEffect`, состояние `{ i, len, deleting }`,
  ререндер только самого компонента).
- [ ] **Step 2: Composer.tsx** по контракту; настройки раскрываются внутри карточки под панелью тем же приёмом
  `grid-rows-[0fr] → [1fr]`, что сейчас.
- [ ] **Step 3: CreateScreen.tsx** — вместо двух шагов:
  1. бейдж «● Открытые модели · строго по вашему шаблону» (`rounded-full bg-white px-3 h-8 shadow-card text-footnote`);
  2. `h1.text-hero` «Презентация в стиле» + `<span class="text-brand">вашего шаблона</span>` (на низких окнах 52 px);
  3. подзаголовок 17/26 `text-zinc-500` max-w 640: «Вставьте текст с тезисами и цифрами — агент продумает слайды,
     соберёт их из макетов вашего шаблона и сверит каждое число. Три варианта в PowerPoint за 5 минут.» (в режиме
     автора — «Вставьте текст или просто тему — …»);
  4. `Composer`: иконка `Sparkles`, поле 17/26 (`[field-sizing:content]`, `min-h-[104px]`, `max-h-[40vh]`),
     `TypewriterHint` поверх пустого поля без фокуса (примеры: «Итоги квартала: выручка 1,2 млрд ₽ (+18 %), три
     ключевых проекта и планы на IV квартал», «Запуск продукта: проблема клиентов, решение, рынок 40 млрд ₽ и план на
     год», «Слайд 1. Титул. Слайд 2. Цели на 2027 год. Слайд 3. Бюджет — круговая диаграмма», «Стратегия продаж:
     воронка, конверсия 12 % → 18 %, найм пяти менеджеров»; в режиме автора первым — «История VK — от социальной сети
     до экосистемы»), счётчик «ещё N»; панель: чип шаблона (мини-обложка 32×18, название, `ChevronDown`; клик
     плавно прокручивает к `#templates`), «Файл», «Пример»; справа степпер «− 12 + слайдов» / «по тексту», кнопка
     настроек (`SlidersHorizontal`, `aria-expanded`), `Button variant="brand" shape="pill" size="lg"` «Создать»;
  5. строка состояния под композером (прежняя сетка-наложение `ModelStatus` / проблема / «Текст напишет агент»);
  6. `<section id="templates">` с галереей (Task 7) и `shake` при отсутствии шаблона;
  7. плавающая панель: `sticky bottom-6` внутри формы, видна, когда панель композера вне прокручиваемой области
     (IntersectionObserver с `root` = ближайший `main`), появление `animate-rise`, уход `animate-fade-out`;
     состав: мини-обложка, «Шаблон «…»», «12 слайдов», `brand pill` «Создать презентацию» (`type="submit"`).
  Вся логика формы (черновик, `dictatedSlides`, проверки, `onSubmit`, `composerText`, `keepClearOfBar` — теперь
  относительно плавающей панели) сохраняется.
- [ ] **Step 4:** `npm run build`; на :5181 при 1280×720 кнопка «Создать» видна без прокрутки; печать примеров идёт
  и останавливается при фокусе; «Пример», «Файл», степпер, настройки, ошибки (пустой текст — встряхивается композер),
  плавающая панель появляется при прокрутке к галерее и отправляет форму.
- [ ] **Step 5: Commit** — «Экран создания: герой с градиентом и большой композер с печатающимися примерами».

### Task 7: Галерея шаблонов и предпросмотр

**Files:**
- Create: `web/src/components/simple/TemplatePreview.tsx`
- Modify: `web/src/components/simple/TemplatePicker.tsx`, `web/src/components/simple/CreateScreen.tsx`

**Interfaces:**
- Consumes: `TemplateListItem` (`cover_url`, `n_slides`, `palette`, `font`, `aspect`), `useApp().selectTemplate`, `setDetail("template")`.
- Produces:
  - `export function TemplatePreview({ t, onClose }: { t: TemplateListItem | null; onClose(): void })` — `Modal size="xl"`;
    миниатюры `/api/templates/${id}/files/thumbs/slide-${NNN}.jpg` для 1…`n_slides`, 4 колонки, `loading="lazy"`,
    номер на плитке; палитра и шрифт под заголовком; футер «Подробный разбор» (выбрать + `setDetail("template")`) и
    `brand` «Выбрать шаблон» (выбранный — «Шаблон выбран» с галочкой).
  - `TemplatePicker` — сетка 3 колонки `gap-5`; `TemplateActions` — «Разбор шаблона ›» и «Загрузить свой».

- [ ] **Step 1: TemplatePreview.tsx** по контракту.
- [ ] **Step 2: TemplatePicker.tsx** — карточка: `rounded-2xl bg-white p-2 shadow-card hover:shadow-raise`, обложка
  `aspect-video rounded-xl overflow-hidden` с `group-hover:scale-[1.03]` (600 мс), на обложке справа снизу при
  наведении/фокусе белая pill-кнопка «Слайды» (`Eye`) → предпросмотр; под обложкой название `text-title3`, мета
  «54 слайда · Play», точки палитры (до 5, 12 px, `ring-1 ring-black/10`); выбранный — `shadow-selected` и галочка;
  корзина при наведении (прежний диалог). Плитка «Свой шаблон»: пунктир `border-2 border-dashed border-zinc-300`,
  градиентный круг 48 px с `Upload`, «Загрузить свой шаблон», «.pptx, .potx, .ppt или .odp — или перетащите файл»;
  при перетаскивании — синяя рамка и `bg-accent-50`. Во время разбора — плитка с прогрессом первой. Видно 5 шаблонов
  (выбранный среди них) + плитка; «Показать все шаблоны (N)» / «Свернуть» под сеткой. Каскад появления и FLIP при
  удалении сохраняются.
- [ ] **Step 3: CreateScreen.tsx** — секция `#templates`: `h2.text-title1` «Шаблон оформления», пояснение
  «Слайды собираются из макетов шаблона: его шрифты, цвета и сетка.», справа `TemplateActions`; секция — зона
  перетаскивания (`useTemplateDrop`).
- [ ] **Step 4:** `npm run build`; выбор, предпросмотр (прокрутка 55 слайдов, «Выбрать шаблон», «Подробный разбор»
  открывает шторку), загрузка файла кнопкой и перетаскиванием, удаление с подтверждением, «Показать все».
- [ ] **Step 5: Commit** — «Галерея шаблонов крупными карточками и предпросмотр всех слайдов шаблона».

### Task 8: Сцена сборки

**Files:**
- Create: `web/src/components/build/BuildStage.tsx`, `web/src/components/build/Blueprint.tsx`,
  `web/src/components/build/StageRail.tsx`, `web/src/components/build/AgentLog.tsx`, `web/src/components/build/VariantChips.tsx`
- Modify: `web/src/components/BuildScreen.tsx`

**Interfaces:**
- Consumes: `ActiveJob` (`agent`, `phase`, `progress`, `variants`, `line`, `generation`, `slides`, `items`, `startedAt`,
  `status`), `buildTimeline`, `railSlides`, `sketchOf`, `STAGE_TITLE`, `ROLE`, `logLines`, `clock`.
- Produces:
  - `BuildStage({ title, kicker, line, sketch, phase, progress, queued, elapsed, aspect, running, className })` — тёмная
    сцена: свечения (`animate-stage-glow` только при `running`), точечная сетка, кикер `font-mono uppercase
    tracking-[0.14em] text-accent-300`, таймер справа, заголовок — слова поднимаются (`animate-word-rise`, шаг 40 мс,
    максимум 6), прежний заголовок уходит вверх (`animate-word-out`), размер `clamp(28px, 5.2cqw, 64px)`; строка
    печатается (12 мс/знак, держится ≥ 900 мс); справа `Blueprint`; снизу градиентная полоса со светящимся концом и
    процент (`CountUp`). `aria-live="polite"` на обёртке заголовка.
  - `Blueprint({ sketch, mode })`, `mode: "read" | "sketch" | "check"` — каркас 16:9 по `sketch.kind` с анимацией
    дорисовки (ключ — `slide/kind`), заголовок слайда мелко сверху; `read` — строки текста и бегущая подсветка;
    `check` — галочки поверх каркаса.
  - `StageRail({ slides, images, focus, className })` — `slides: RailSlide[]`, `images: Record<number, string>`;
    плитки: скелет / иконка формы + заголовок (`animate-fill-in` + `animate-tile-pulse` при появлении эскиза) /
    настоящая миниатюра поверх (проявление 400 мс); метки: янтарная точка (замечание), синяя (правка), галочка
    (свёрстан); активная — кольцо; лента следует за `focus`.
  - `AgentLog({ rows, events, className })` — чек-лист этапов (✓ / крутилка / точка / минус + заметка) и поток строк
    `logLines` моноширинным 12/18 (время, роль капителью цветом этапа, «сл. 4», текст), следует за новыми строками,
    пока читатель не прокрутил вверх; `aria-live="off"`.
  - `VariantChips({ names, states, value, onChange, titleOf })` — радиогруппа чипов: название, статус, тонкая полоса.

- [ ] **Step 1: Blueprint.tsx** — 16 видов каркаса (обложка, столбцы, горизонтальные полосы, кольцо, линия,
  таблица, числа, карточки, список, хронология, сравнение, цитата, картинка, повестка, раздел, текст) на белых/синих
  линиях по сцене; анимации `grow-y`/`grow-x`/`draw` со сдвигом 60 мс; при `prefers-reduced-motion` — сразу готовый.
- [ ] **Step 2: BuildStage.tsx** по контракту (контейнер `containerType: size`, соотношение сторон — шаблона).
- [ ] **Step 3: StageRail.tsx**, **AgentLog.tsx**, **VariantChips.tsx** по контрактам.
- [ ] **Step 4: BuildScreen.tsx** — корень как у результата (`h-full`, `max-w-[1600px]`, `containerType:
  inline-size`, `container-name: build`); заголовок «Готовлю презентацию» + мета (как сейчас, `vt-title`); сетка
  `.build-grid`: `StageRail` (`vt-rail`), колонка «сцена + чипы вариантов» (сцена — `vt-stage`, вписана в колонку как
  самый большой прямоугольник с соотношением сторон шаблона), `AgentLog` (`build-log`, `vt-aside`). Данные: `rows`
  как сейчас; выбранный в чипах вариант (по умолчанию первый) задаёт ленту (`railSlides(job.agent, v, count, laid)`,
  `count = variants[v].of ?? job.slides ?? max слайда`), фокус = `line.slide` (если строка о слайде) или последний
  эскиз; эскиз фокуса — в `Blueprint`; `mode` = `read` до первых эскизов, `check` на этапе проверки. Настоящие превью:
  при `progress ≥ 0.86` или этапе `check` и известном `job.generation` — загрузка
  `/api/generations/${gid}/${v}/slides/slide-NNN.jpg` через `new Image()` с повтором раз в 3 с до успеха.
  Механика `useEntrance` сохраняется и раздаёт имена `vt-title`, `vt-rail`, `vt-stage`, `vt-aside` после входа.
- [ ] **Step 5:** `npm run build`; настоящая сборка без модели на :5181 (переключатель «Тексты пишет модель»
  выключен): сцена, лента, журнал, чипы, превью в конце, переход в результат без вспышек.
- [ ] **Step 6: Commit** — «Сборка — тёмная сцена: живой заголовок этапа, эскиз слайда, лента и журнал агента».

### Task 9: Dev-повтор сборки

**Files:**
- Create: `web/src/dev/StageReplay.tsx`
- Modify: `web/src/main.tsx`

**Interfaces:**
- Consumes: `api.generation`, `foldJobEvent`, `BuildScreen`, `Header`, `AppProvider`.
- Produces: в режиме разработки `/?replay=<gid>[&speed=2]` показывает шапку и `BuildScreen` с синтетической задачей.

- [ ] **Step 1: StageReplay.tsx** — загружает сборку; сценарий: `analyze: loaded cached manifest` (0,05),
  `plan: N variants` (0,15); события агента всех вариантов (у первого — все, у остальных — только свои), `seq` по
  порядку, интервалы из `t` с ускорением `speed` (ограничены 60–1200 мс), прогресс 0,15 → 0,6; затем по вариантам
  `v: planned N slides, rendering` и `v: rendered slide i/N` (по 120 мс), `export: pdf, html, slide previews` (0,86),
  `v: audit` (0,9), `v: done in 42.0s` (0,97); всё сворачивается `foldJobEvent`; в конце статус `done`.
- [ ] **Step 2: main.tsx** — `const replay = import.meta.env.DEV ? new URLSearchParams(location.search).get("replay") : null;`
  при `replay` — `import("./dev/StageReplay").then(…)` вместо `App` (без top-level await); прод-сборка этот код
  выбрасывает (проверить `grep -c StageReplay dist/assets/*.js` → 0).
- [ ] **Step 3:** `/?replay=20260929-133413-4c9b28&speed=3` на :5181 — сцена проходит все этапы; скриншоты.
- [ ] **Step 4: Commit** — «Dev-повтор записанной сборки в сцене (только в режиме разработки)».

### Task 10: Визуальная проверка и доводка

- [ ] **Step 1:** Скриншоты всех экранов и состояний на 1280×720, 1440×900, 1920×1080 (создание: пусто/текст/ошибка/
  настройки/плавающая панель/предпросмотр/загрузка; сборка: начало/дизайнер/вёрстка/проверка/конец; результат:
  обычный/замечания/помощник/шторка) в `scratchpad/ui3/`.
- [ ] **Step 2:** Два агента-ревьюера с промптом «ищи проблемы» (наложения, обрезки, неровности, контраст, лишний
  текст, мерцание, сломанные состояния) — отдельно по экрану создания и по сборке/результату.
- [ ] **Step 3:** Исправить найденное, повторить снимки затронутых состояний.
- [ ] **Step 4:** `npm test`, `npm run build`, `prefers-reduced-motion` (эмуляция) — циклов нет, всё читается.
- [ ] **Step 5: Commit** — «Доводка редизайна по визуальной проверке».
