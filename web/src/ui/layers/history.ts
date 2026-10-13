// «Мои презентации» (G-history, V2 `#p2-lay-h`): чистая логика раздела — группы по дням, обложка, оценка, состояние
// карточки и что делает клик по ней (V2 `openDoc`). Данные — список `GET /api/generations` (мета без текста целиком:
// сервер режет `brief` до 400 знаков).
import type { GenerationMeta } from "../../types";
import { templateTitle } from "../../lib/plain";
import { plural } from "../../lib/utils";
import type { Screen } from "../deck/geometry";

/** Лесенка карточек (V2 `200 + hk * 40`): дальше девятой задержка не растёт — открытие не ждёт хвост списка, и длинный
 *  список (в разделе все презентации) входит так же быстро, как короткий. */
const STAG0 = 200;
const STAG = 40;
const STAG_MAX = 8;
/** Даты в пределах недели — свои группы, всё старше — «Раньше» (G-history: «Сегодня», «Вчера», «24 сент.», «Раньше»). */
const WEEK = 7;

export type DeckState = "run" | "fail" | "done";

export function deckState(g: GenerationMeta): DeckState {
  if (g.status === "running" || g.status === "queued") return "run";
  if (g.status === "failed") return "fail";
  return "done";
}

/** Лучшая оценка среди вариантов (сводка списка). Каркас темы без текста оценки не имеет: «100» читалось бы как успех. */
export function bestScore(g: GenerationMeta): number | null {
  if (g.writer && g.writer.status !== "written" && g.planner?.planned_by === "skeleton") return null;
  const scores = Object.values(g.summary ?? {})
    .map((s) => s.score)
    .filter((s): s is number => typeof s === "number" && Number.isFinite(s));
  return scores.length ? Math.max(...scores) : null;
}

/** Вариант обложки: с лучшей оценкой (равные — по порядку вариантов); без оценок — первый; вариант без слайдов
 *  (`n_slides: 0`) обложкой не бывает. */
export function coverStrategy(g: GenerationMeta): string | null {
  const built = g.strategies.filter((s) => g.summary?.[s]?.n_slides !== 0);
  let best: string | null = null;
  let top = -Infinity;
  for (const s of built) {
    const score = g.summary?.[s]?.score;
    if (typeof score === "number" && Number.isFinite(score) && score > top) {
      top = score;
      best = s;
    }
  }
  return best ?? built[0] ?? null;
}

/** Обложка готовой презентации — первый слайд лучшего варианта. Ревизия из сводки (оценка, слайды, замечания):
 *  исправленный слайд не остаётся в кэше браузера прежним. */
export function coverSrc(g: GenerationMeta): string | null {
  if (deckState(g) !== "done") return null;
  const s = coverStrategy(g);
  if (!s) return null;
  const url = `/api/generations/${encodeURIComponent(g.id)}/${encodeURIComponent(s)}/slides/slide-001.jpg`;
  const sum = g.summary?.[s];
  if (!sum) return url;
  const part = (v: number | null | undefined) => (typeof v === "number" && Number.isFinite(v) ? String(v) : "-");
  const score = typeof sum.score === "number" && Number.isFinite(sum.score) ? Math.round(sum.score * 10) : null;
  return `${url}?v=${[part(score), part(sum.n_slides), part(sum.errors), part(sum.warnings)].join(".")}`;
}

/** «12 слайдов» или «8–10 слайдов» — сколько собрано (варианты могут различаться), иначе — сколько просили. */
export function slidesText(g: GenerationMeta): string | null {
  const built = Object.values(g.summary ?? {})
    .map((s) => s.n_slides)
    .filter((n): n is number => typeof n === "number" && n > 0);
  if (built.length === 0) return g.slides ? plural(g.slides, "слайд", "слайда", "слайдов") : null;
  const lo = Math.min(...built);
  const hi = Math.max(...built);
  return lo === hi ? plural(hi, "слайд", "слайда", "слайдов") : `${lo}–${plural(hi, "слайд", "слайда", "слайдов")}`;
}

/** Название: своё; у старых и неудачных — первая строка текста без разметки; иначе — имя шаблона. */
export function deckTitle(g: GenerationMeta): string {
  const own = g.title?.trim();
  if (own) return own;
  const line = g.brief?.split("\n").map((l) => l.replace(/^#+\s*/, "").replace(/\*\*/g, "").trim()).find(Boolean);
  return line ? line.slice(0, 120) : templateTitle(g.template_file, g.template_id);
}

const toDate = (ts: number) => new Date(ts * 1000);
const dayStart = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
/** «24 сент.»; другого года — «24 сент. 2025». */
const dateText = (d: Date, now: Date) =>
  d.toLocaleDateString("ru-RU", d.getFullYear() === now.getFullYear() ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" })
    .replace(/\s*г\.$/, "");

/** День карточки: «Сегодня», «Вчера», дата в пределах недели, старше — общая группа «Раньше» (`early`). */
export function dayBucket(ts: number | undefined, now: Date): { key: string; label: string; early: boolean } {
  if (typeof ts !== "number" || !Number.isFinite(ts)) return { key: "early", label: "Раньше", early: true };
  const d = toDate(ts);
  const diff = Math.max(0, Math.round((dayStart(now) - dayStart(d)) / 86_400_000));
  if (diff >= WEEK) return { key: "early", label: "Раньше", early: true };
  return { key: String(diff), label: diff === 0 ? "Сегодня" : diff === 1 ? "Вчера" : dateText(d, now), early: false };
}

export interface HistItem {
  id: string;
  title: string;
  /** «17:38 · VK Tech · 12 слайдов»; в «Раньше» вместо времени — дата. */
  meta: string;
  state: DeckState;
  /** Лучшая оценка, целая (только у готовой). */
  score: number | null;
  cover: string | null;
  /** Открыта сейчас — только обводка обложки (значка выделения нет). */
  current: boolean;
  aria: string;
  /** Задержка лесенки `p2-ls`, мс. */
  delay: number;
}
export interface HistGroup { key: string; day: string; count: string; items: HistItem[] }

const decks = (n: number) => plural(n, "презентация", "презентации", "презентаций");

/** Раздел целиком: все презентации, новые первыми, группы по дням с числом, подпись «7 презентаций» — их настоящее
 *  число. `label` — имя шаблона для людей, `current` — открытая сейчас. */
export function historyView(list: GenerationMeta[], opts: { now: Date; label(g: GenerationMeta): string; current: string | null }): { groups: HistGroup[]; total: string } {
  const sorted = [...list].sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0));
  const groups: HistGroup[] = [];
  sorted.forEach((g, k) => {
    const day = dayBucket(g.created_at, opts.now);
    const state = deckState(g);
    const score = state === "done" ? bestScore(g) : null;
    const when = typeof g.created_at === "number"
      ? day.early ? dateText(toDate(g.created_at), opts.now) : toDate(g.created_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
      : null;
    const title = deckTitle(g);
    const meta = [when, opts.label(g), slidesText(g)].filter(Boolean).join(" · ");
    const current = g.id === opts.current;
    const said = state === "run" ? "собирается" : state === "fail" ? "не удалось собрать" : score !== null ? `оценка ${Math.round(score)} из 100` : null;
    const item: HistItem = {
      id: g.id, title, meta, state, score: score === null ? null : Math.round(score), cover: coverSrc(g), current,
      aria: [title, meta, said, current ? "открыта сейчас" : null].filter(Boolean).join(", "),
      delay: STAG0 + Math.min(k, STAG_MAX) * STAG,
    };
    const last = groups[groups.length - 1];
    if (last && last.key === day.key) last.items.push(item);
    else groups.push({ key: day.key, day: day.label, count: "", items: [item] });
  });
  for (const gr of groups) gr.count = decks(gr.items.length);
  return { groups, total: decks(sorted.length) };
}

/** Что делает клик по карточке (V2 `openDoc`):
 *  - готовая → результат: загрузить (если открыта другая), из «Создать» плита результата поднимается снизу одним
 *    движением с плитами 02/03 (`rise`);
 *  - идущая → экран сборки с её задачей;
 *  - неудачная → «Создать» с той же темой и шаблоном (с результата плита уходит вниз — это делает сам переход);
 *  - неудачная сборка, которую держит страница (`buildId` — её законченная сборка, кончилась, пока человек был в
 *    другом месте) → её экран «Сборка» с причиной, «Вернуться к тексту» и «Собрать ещё раз» (`ended`);
 *  - она уже на экране → только закрыть раздел;
 *  - открытая, но несвежая (`stale`: изменение сохранено, а перечитать её не вышло) → перечитать (`load`), а не
 *    оставить прежнюю. */
export type OpenPlan =
  | { kind: "result"; load: boolean; rise: boolean }
  | { kind: "build" }
  | { kind: "ended" }
  | { kind: "create" }
  | { kind: "stay" };

export function openPlan(g: GenerationMeta, at: { screen: Screen; openId: string | null; buildId: string | null; stale?: string | null }): OpenPlan {
  const state = deckState(g);
  if (state === "run") return at.screen === "build" && at.buildId === g.id ? { kind: "stay" } : { kind: "build" };
  if (state === "fail" && at.buildId === g.id) return at.screen === "build" ? { kind: "stay" } : { kind: "ended" };
  if (state === "fail") return { kind: "create" };
  const stale = at.openId === g.id && at.stale === g.id;
  if (at.screen === "result" && at.openId === g.id && !stale) return { kind: "stay" };
  return { kind: "result", load: at.openId !== g.id || stale, rise: at.screen === "create" };
}
