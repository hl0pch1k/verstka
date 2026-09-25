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
    parts.push(score === null ? "без проверки качества" : `качество ${Math.round(score)}/100`);
    if (errors !== null) parts.push(errors === 0 ? "без ошибок" : plural(errors, "ошибка", "ошибки", "ошибок"));
    if (warnings) parts.push(plural(warnings, "предупреждение", "предупреждения", "предупреждений"));
    return { strategy: v.strategy, score, line: `• ${strategyTitle(v.strategy)} — ${parts.join(", ")}` };
  });
  const head = `Готово: ${plural(g.variants.length, "вариант", "варианта", "вариантов")}${g.seconds ? ` за ${fmtSeconds(g.seconds)}` : ""}.`;
  const silentNote = modelSilentNote(g);
  if (g.variants.every((v) => v.outline?.planned_by === "skeleton")) {
    return [head, silentNote, "В тексте была только тема, поэтому это каркас: титул, повестка и разделы с подсказками в заметках. Допишите тезисы и цифры — Verstka соберёт содержательные слайды."].filter(Boolean).join("\n");
  }
  const scored = rows.filter((r) => r.score !== null);
  const best = scored.length > 1 ? scored.reduce((a, b) => ((b.score ?? 0) > (a.score ?? 0) ? b : a)) : null;
  const tail = best
    ? `Лучшая оценка качества — у варианта «${strategyTitle(best.strategy)}». Переключайте варианты над слайдом, замечания — в «Проверке качества».`
    : "Переключайте варианты над слайдом, замечания — в «Проверке качества».";
  return [head, ...rows.map((r) => r.line), silentNote, tail].filter(Boolean).join("\n");
}
