// Данные тестов режима «Замечания» (marks, fix, picture, slideJob): замечания — как у сохранённой генерации «Интеграл:
// от площади к физике» (workspace/runs/20261008-171650-b28994), сокращённо. Только для тестов: приложение это не
// импортирует.
import type { AgentEvent, AuditReport, Issue, Variant, VariantEdit } from "../../types";

export const issue = (patch: Partial<Issue>): Issue => ({
  id: "i", slide: 3, check_id: "x", severity: "warn", kind: "deterministic", message: "", bboxes: [], element_ids: [], suggestion: null,
  autofix: null, details: {}, outline_id: null, ...patch,
});
export const audit = (issues: Issue[]): AuditReport => ({
  deck: "d", template_id: "t", strategy: "structured", per_slide: {}, iterations: 1, applied_fixes: [], seconds: 1, issues,
  summary: { errors: 0, warnings: 0, infos: 0, model_flags: 0, score: 84, checks_run: [] },
});
export const variant = (issues: Issue[], patch: Partial<Variant> = {}): Variant => ({
  strategy: "structured", outline: null, plan: null, audit: audit(issues), run_manifest: null, slides: [], files: {}, ...patch,
});
export const edit = (patch: Partial<VariantEdit>): VariantEdit => ({
  at: 1, request: "", reply: "", kind: "fix", slides: [3], score_before: null, score_after: null, version: 2, undo_of: null, ...patch,
});

const TITLES: Record<string, string> = {
  margin_violation: "Контент заходит в поля у краёв", design_review: "Взгляд дизайнера (VLM)", content_missing: "Часть запланированного контента пропала со слайда",
  contrast_low: "Контраст текста к фону ниже 4.5:1", grid_alignment: "Блоки не выровнены по направляющим макета",
};
export const titleOf = (id: string) => TITLES[id] ?? null;

export const CONTRAST = issue({ id: "contrast_low-3-1", check_id: "contrast_low", severity: "error", message: "Подпись под формулой (#9CA3AF на #FFFFFF, 3.1:1)",
  bboxes: [{ x: 0.0521, y: 0.5741, w: 0.4125, h: 0.0667 }], element_ids: ["12"] });
export const DENSE = issue({ id: "fill_ratio-3-2", check_id: "fill_ratio", message: "абзац под формулой — 4 строки", bboxes: [{ x: 0.0208, y: 0.6815, w: 0.7708, h: 0.1889 }] });
// взгляд дизайнера присылает свои замечания с важностью «предупреждение» (verstka/audit/eyes.py) — тон у них серый
export const MODEL = issue({ id: "design_review-3-0", check_id: "design_review", severity: "warn", kind: "model", message: "Нет примера", suggestion: "покажите, как найти первообразную" });
export const GRID = issue({ id: "grid-3-9", check_id: "grid_alignment", severity: "info", message: "сетка" });

export const ev = (step: string, message: string): AgentEvent => ({ step, message, slide: 3, variant: "structured" });
