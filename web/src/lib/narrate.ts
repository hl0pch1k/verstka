// Pure helpers used by the app store: assistant-side chat texts and small derivations over API payloads.
import type { Generation, TemplateListItem, Variant } from "../types";
import { silentNote as modelSilentNote } from "./modelText";
import { fmtSeconds, plural } from "./utils";

export function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** First meaningful line of a job error (the backend appends a traceback after it). */
export function firstLine(text: string | null | undefined, fallback = "неизвестная ошибка"): string {
  const line = (text ?? "").split("\n").map((l) => l.trim()).find(Boolean);
  return line ? line.replace(/^failed:\s*/i, "") : fallback;
}

export function slideCount(v: Variant | null | undefined): number {
  if (!v) return 1;
  return v.slides.length || v.outline?.slides.length || v.plan?.slides.length || 1;
}

export function newestTemplate(list: TemplateListItem[]): TemplateListItem | null {
  return list.reduce<TemplateListItem | null>((best, t) => (!best || t.analyzed_at > best.analyzed_at ? t : best), null);
}

/** Assistant message after a finished generation: one line per variant with its quality score. */
export function describeGeneration(g: Generation, strategyTitle: (name: string) => string): string {
  if (g.variants.length === 0) return "Не получилось собрать ни одного варианта. Попробуйте ещё раз или измените текст — причина записана в технических деталях.";
  const rows = g.variants.map((v) => {
    const s = v.audit?.summary;
    const fromMeta = g.summary?.[v.strategy];
    const score = s?.score ?? fromMeta?.score ?? null;
    const errors = s?.errors ?? fromMeta?.errors ?? null;
    const warnings = s?.warnings ?? fromMeta?.warnings ?? null;
    const parts = [plural(slideCount(v), "слайд", "слайда", "слайдов")];
    parts.push(score === null ? "без проверки качества" : `оценка ${Math.round(score)}`);
    if (errors !== null) parts.push(errors === 0 ? "без ошибок" : plural(errors, "ошибка", "ошибки", "ошибок"));
    if (warnings) parts.push(plural(warnings, "предупреждение", "предупреждения", "предупреждений"));
    return { strategy: v.strategy, score, line: `• ${strategyTitle(v.strategy)} — ${parts.join(", ")}` };
  });
  const head = `Готово: ${plural(g.variants.length, "вариант", "варианта", "вариантов")}${g.seconds ? ` за ${fmtSeconds(g.seconds)}` : ""}.`;
  const silentNote = modelSilentNote(g);
  if (g.variants.every((v) => v.outline?.planned_by === "skeleton")) {
    // a topic whose text the model did not write: said plainly, no score (gate 4 G4-21)
    const unwritten = g.writer?.status === "failed" || g.writer?.status === "skipped";
    const what = unwritten
      ? "Модель недоступна — текст по теме не написан, поэтому это каркас: титул, повестка и разделы с подсказками в заметках. Соберите ещё раз позже или допишите тезисы и цифры."
      : "В тексте была только тема, поэтому это каркас: титул, повестка и разделы с подсказками в заметках. Допишите тезисы и цифры — Verstka соберёт содержательные слайды.";
    return [head.replace(/^Готово: .*$/, unwritten ? "Текст не написан." : head), silentNote, what].filter(Boolean).join("\n");
  }
  // the best variant is named only when the scores differ; no tutorial tail (the page shows where things are)
  const scored = rows.filter((r) => r.score !== null);
  const differ = new Set(scored.map((r) => Math.round(r.score ?? 0))).size > 1;
  const best = differ ? scored.reduce((a, b) => ((b.score ?? 0) > (a.score ?? 0) ? b : a)) : null;
  const tail = best ? `Лучшая оценка — у варианта «${strategyTitle(best.strategy)}».` : null;
  return [head, ...rows.map((r) => r.line), silentNote, tail].filter(Boolean).join("\n");
}

// «1 число сверено», «3 числа сверены», «70 чисел сверены»: the verb agrees with the count
const agrees = (n: number, one: string, many: string) => (n % 10 === 1 && n % 100 !== 11 ? one : many);

/** The one sentence about the figures checked against the text — the same words on the result card, in the audit tab
 *  and in the plan. ok: «70 чисел сверены с текстом»; warn: «3 числа не найдены в тексте»; `title` (tooltip) splits the
 *  checked ones: «60 взяты из текста, 10 посчитаны из его чисел». null when nothing was checked. */
export function figuresLine(f: { checked: number; derived?: number; unverified?: number } | null | undefined): { text: string; tone: "ok" | "warn"; title?: string } | null {
  if (!f || !f.checked) return null;
  const derived = f.derived ?? 0;
  const unverified = f.unverified ?? 0;
  if (unverified > 0) {
    return { text: `${plural(unverified, "число", "числа", "чисел")} ${agrees(unverified, "не найдено", "не найдены")} в тексте`, tone: "warn" };
  }
  const taken = Math.max(0, f.checked - derived);
  return {
    text: `${plural(f.checked, "число", "числа", "чисел")} ${agrees(f.checked, "сверено", "сверены")} с текстом`,
    tone: "ok",
    title: derived > 0 ? `${taken} ${agrees(taken, "взято", "взяты")} из текста, ${derived} ${agrees(derived, "посчитано", "посчитаны")} из его чисел` : undefined,
  };
}
