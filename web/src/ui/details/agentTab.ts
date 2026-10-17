// Вкладка «Агент» без React (boards/D-agent, V2 модуль details `dlA`): полная лента работы агента над вариантом по
// ролям — что каждая роль сделала (итог жирным), её строки с номером слайда (ведёт в «Почему так»), исправления
// критика стрелкой — и «Ваши правки» (журнал правок варианта: отменённые помечены, «Вернуть как было» — пока есть что
// вернуть). Лента — lib/agent `buildTimeline` по `variant.agent.events`, правки — `variant.edits`.
import { buildTimeline, eventParts, formsSummary, slideGroups, type PhaseKey } from "../../lib/agent";
import { eyesSkipEvent } from "../../lib/designEye";
import { plainTerms } from "../../lib/plain";
import { plural } from "../../lib/utils";
import type { Generation, Variant, VariantEdit } from "../../types";
import type { IconName } from "../kit/icons";
import { slidesOf } from "../result/resultView";
import { appliedRows } from "./fixes";

const ICON: Record<PhaseKey, IconName> = {
  writer: "pen", analyst: "search", architect: "plan", designer: "layout", critic: "chat-check", revise: "refresh", layout: "layers", check: "list-check", eyes: "eye",
};

export interface AgentLine { key: string; n: number | null; mark: "ok" | "warn" | null; a: string; arrow: boolean; tag: string | null }
export interface AgentRole { key: PhaseKey; name: string; hint: string; icon: IconName; skip: boolean; sum: string | null; lines: AgentLine[]; last: boolean; delay: string }

const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** «4 слайда · 1 диаграмма, 1 формула» — над лентой. */
export function agentCap(v: Variant): string {
  const n = slidesOf(v);
  return [n ? plural(n, "слайд", "слайда", "слайдов") : null, formsSummary(v.outline)].filter(Boolean).join(" · ");
}

/** «Сверил цифры…» и «… (проверьте)» шага вёрстки: числа, сверенные с текстом. */
const figureMark = (text: string): AgentLine["mark"] => (/\(проверьте\)/i.test(text) ? "warn" : /^сверил цифры/i.test(text) ? "ok" : null);

/** Что написал автор: «Текст на 12 слайдов по статье «Интеграл» в Википедии». */
function writerSum(g: Generation): string | null {
  const w = g.writer;
  if (!w || w.status !== "written") return null;
  const n = w.slides ? ` на ${plural(w.slides, "слайд", "слайда", "слайдов")}` : "";
  if (w.basis === "kb") return `Текст${n} по базе знаний «${w.kb?.name ?? "База знаний"}»`;
  const src = w.source ? ` по статье «${w.source.title}»${/wikipedia\.org/i.test(w.source.url) ? " в Википедии" : ""}` : " по теме";
  return `Текст${n}${src}`;
}

export function agentRoles(g: Generation, v: Variant, titleOf: (name: string) => string): AgentRole[] {
  const a = v.audit?.summary;
  const n = slidesOf(v);
  const fixes = appliedRows(v.audit?.applied_fixes ?? [], () => null, () => null).reduce((k, r) => k + r.n, 0);
  // «Взгляд дизайнера», пропущенный сервером без строки в ленте (сборки до того, как он стал её говорить), — по записи
  // варианта: «пропущен» и причина по-русски
  const skipped = eyesSkipEvent(v);
  const rows = buildTimeline({
    events: skipped ? [...(v.agent?.events ?? []), skipped] : v.agent?.events ?? [],
    phase: "check",
    running: false,
    notes: {
      writer: writerSum(g),
      layout: n ? `${plural(n, "слайд", "слайда", "слайдов")} по макетам и стилю шаблона` : null,
      check: a ? `оценка ${Math.round(a.score)}${a.errors ? `, ${plural(a.errors, "ошибка", "ошибки", "ошибок")}` : ", без ошибок"}${fixes ? `, исправлено автоматически: ${fixes}` : ""}` : null,
    },
  });
  return rows.map((r, ri) => {
    const skip = r.status === "skipped";
    const lines: AgentLine[] = [];
    slideGroups(r.events).forEach((grp, gi) => {
      grp.events.forEach((e, j) => {
        const { text, fix } = eventParts(e);
        const tag = e.variants?.length ? e.variants.map(titleOf).join(", ") : null;
        lines.push({ key: `${r.key}-${gi}-${j}`, n: j === 0 ? grp.slide : null, mark: grp.slide === null ? figureMark(text) : null, a: text, arrow: false, tag });
        if (fix) lines.push({ key: `${r.key}-${gi}-${j}f`, n: null, mark: null, a: fix, arrow: true, tag: null });
      });
    });
    const note = r.note?.trim() || null;
    return {
      key: r.key, name: r.title, hint: r.hint, icon: skip ? "dash" : ICON[r.key], skip,
      // у пропущенного шага метка «пропущен» уже стоит — итог говорит только почему
      sum: note && skip ? cap(note.replace(/^пропущен[:.]?\s*/i, "")) : note,
      lines, last: ri === rows.length - 1, delay: `${280 + ri * 40}ms`,
    };
  });
}

/** Ход агента у старых сборок без ленты: строки журнала («Аналитик: …»). */
export function legacyLines(log: string[]): AgentLine[] {
  return log.map((line, i) => ({ key: `log-${i}`, n: null, mark: null, a: plainTerms(line), arrow: false, tag: null }));
}

// ---- ваши правки ------------------------------------------------------------------------------------------------------

/** `quoted` — строка — слова человека (в «кавычках»); пересборка слайда кнопкой и «Правка» без текста — подпись. */
export interface EditRow { key: string; q: string; a: string; off: boolean; quoted: boolean }

const isUndo = (e: VariantEdit) => e.kind === "undo" || e.undo_of != null;

/** Ответ правки: свой ответ сервера; у «Исправить замечания» без ответа — сколько исправлено и оценка до → после. */
function answer(e: VariantEdit): string {
  if (e.reply?.trim()) return e.reply.trim();
  const parts = [e.fixed?.length ? `Исправлено ${plural(e.fixed.length, "замечание", "замечания", "замечаний")}` : null,
    e.score_before != null && e.score_after != null ? `оценка ${Math.round(e.score_before)} → ${Math.round(e.score_after)}` : null];
  return parts.filter(Boolean).join(" · ");
}

/** Заголовок строки журнала: «Пересобрать слайд так» — «Пересборка слайда 4 — полосы» (а не «Правка»), иначе — что
 *  просили в чате. */
export function editTitle(e: Pick<VariantEdit, "kind" | "request" | "slides">): string {
  const req = e.request?.trim() ?? "";
  if (e.kind === "rebuild") {
    const n = e.slides?.length ? ` ${e.slides.join(", ")}` : "";
    const how = /так:\s*(.+)$/i.exec(req)?.[1]?.trim();
    return `Пересборка слайда${n}${how ? ` — ${how}` : ""}`;
  }
  return req || "Правка";
}

/** Журнал правок, как его держит сервер: каждая правка хранит версию, «верни как было» снимает самую новую ещё
 *  хранимую (свой `undo_of`). Отменённые правки помечены; вернуть есть что, пока хоть одна версия хранится. */
export function editRows(edits: VariantEdit[]): { rows: EditRow[]; active: number; canUndo: boolean; hint: string } {
  const kept: number[] = []; // индексы правок, чья версия ещё хранится
  const off = new Set<number>();
  edits.forEach((e, i) => {
    if (isUndo(e)) {
      let at = -1;
      for (let k = kept.length - 1; k >= 0; k--) if (e.undo_of == null || edits[kept[k]].version === e.undo_of) { at = k; break; }
      if (at >= 0) off.add(kept.splice(at, 1)[0]);
    } else if (e.version != null) kept.push(i);
  });
  const rows = edits.map((e, i) => ({ e, i })).filter(({ e }) => !isUndo(e)).map(({ e, i }) => ({ key: `${i}`, q: editTitle(e), a: answer(e), off: off.has(i), quoted: e.kind !== "rebuild" && !!e.request?.trim() }));
  const active = rows.filter((r) => !r.off).length;
  const hint = active ? "Что вы меняли в чате после сборки. «Вернуть как было» отменит последнюю правку."
    : rows.length ? "Все правки отменены — слайды такие, как после сборки."
      : "После сборки слайды не меняли. Правки из помощника и исправления замечаний появятся здесь.";
  return { rows, active, canUndo: kept.length > 0, hint };
}
