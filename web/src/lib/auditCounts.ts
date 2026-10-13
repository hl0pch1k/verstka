// Сколько в отчёте проверки ошибок, предупреждений, замечаний модели и мелких заметок — одни числа для карточки
// «Качество» результата, вкладки «Качество» листа «Подробнее» и «Итога проверки» во вкладке «Файлы». Считается по самим
// замечаниям (`audit.issues`), а не по сводке сервера: там замечание модели посчитано дважды — и замечанием модели, и
// предупреждением (или заметкой) по своей важности, и числа разных мест не сходились.
import type { AuditReport, Issue } from "../types";

/** Тон замечания: ошибка — всегда ошибка (и у модели); остальные замечания модели — «замечание модели»; правила —
 *  предупреждение или мелкая заметка. Каждое замечание — ровно один тон. */
export type IssueTone = "err" | "warn" | "model" | "info";
export const issueTone = (i: Issue): IssueTone => (i.severity === "error" ? "err" : i.kind === "model" ? "model" : i.severity === "warn" ? "warn" : "info");

export interface AuditCounts {
  errors: number;
  /** Предупреждения правил (без замечаний модели). */
  warnings: number;
  /** Замечания модели (кроме ошибок). */
  model: number;
  /** Мелкие заметки правил (без замечаний модели). */
  infos: number;
}

/** Числа отчёта; отчёта нет (не загружен, не сохранился) — null: тогда место берёт мету генерации. */
export function auditCounts(audit: Pick<AuditReport, "issues"> | null | undefined): AuditCounts | null {
  if (!audit) return null;
  const c: AuditCounts = { errors: 0, warnings: 0, model: 0, infos: 0 };
  for (const i of audit.issues) {
    const t = issueTone(i);
    if (t === "err") c.errors += 1;
    else if (t === "warn") c.warnings += 1;
    else if (t === "model") c.model += 1;
    else c.infos += 1;
  }
  return c;
}
