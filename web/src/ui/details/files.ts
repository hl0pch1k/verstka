// Вкладка «Файлы» без React (boards/D-files, V2 модуль details `dlF`; логика — старые ExportPanel, RunPanel*):
// файлы каждого варианта, паспорт запуска (`run_manifest`: шаблон, когда, версия, кто составил план, какие модели),
// время по этапам, итог проверки, автоисправления и «Для разработчиков» (JSON, навыки и агенты, сравнение запусков).
import { auditCounts } from "../../lib/auditCounts";
import { plannedByText } from "../../lib/plain";
import { fmtSeconds, fmtWhen, plural, shortSha } from "../../lib/utils";
import type { DiffResponse, Generation, RunManifest, SkillsResponse, Variant } from "../../types";
import type { IconName } from "../kit/icons";
import { docTitle, fileBase, scoreOf } from "../result/resultView";
import { appliedRows, type FixRow } from "./fixes";

export interface FileRow {
  key: string; title: string; score: number | null; tip: string; file: string; cur: boolean;
  pptx: string | null; pdf: string | null; html: string | null; base: string; aPpt: string; aPdf: string; aWeb: string;
}

export function fileRows(g: Generation, cur: string, titleOf: (name: string) => string): FileRow[] {
  return g.variants.map((v, i) => {
    const name = titleOf(v.strategy);
    const s = scoreOf(g, v);
    const base = fileBase(docTitle(g, v), name);
    return {
      key: v.strategy, title: `${i + 1} · ${name}`, score: s === null ? null : Math.round(s), tip: s === null ? "" : `Оценка качества ${Math.round(s)} из 100`,
      file: `${base}.pptx`, cur: v.strategy === cur, base,
      pptx: v.files["deck.pptx"] ?? null, pdf: v.files["deck.pdf"] ?? null, html: v.files["deck.html"] ?? null,
      aPpt: `Скачать PowerPoint — ${name}`, aPdf: `Скачать PDF — ${name}`, aWeb: `Веб-версия — ${name}, откроется в новой вкладке`,
    };
  });
}

// ---- паспорт запуска -------------------------------------------------------------------------------------------------

const ROLES: Array<[string, string]> = [["llm", "Тексты и план"], ["vlm", "Проверка по картинке"], ["embed", "Поиск похожего"], ["audit", "Проверка"]];
type Link = { backend?: string; model?: string; label?: string; off?: boolean };
type Provider = RunManifest["providers"][string] & { chain?: Link[]; label?: string };

const tidy = (label: string) => label.replace(/\s*\(([^)]+)\)\s*$/, " · $1");

/** Модель роли словами: та, что ответила (если запуск её знает), иначе первая в цепочке. */
function modelName(p: Provider, answered?: string | null): string {
  if (p.backend === "none" || p.backend === "mock") return "без модели";
  const chain = (p.chain ?? []).filter((l) => !l.off);
  const hit = (answered && chain.find((l) => l.model === answered)) || chain[0];
  if (hit) return tidy(hit.label ?? hit.model ?? "модель");
  if (p.label) return tidy(p.label);
  return [p.model, p.backend === "polza" ? "Polza" : null].filter(Boolean).join(" · ") || "модель";
}

/** Спрашивал ли запуск модель роли: false — переключатель был выключен; null — неизвестно (старые запуски). */
function roleUsed(role: string, m: RunManifest, g: Generation): boolean | null {
  if (role === "vlm") return g.audit_models === undefined ? (g.use_models === false ? false : null) : g.audit_models;
  if (g.use_models === false) return false;
  if (role === "llm" && (g.outline_supplied || m.planner?.supplied) && g.audit_models === false) return false;
  return null;
}

/** Кто составил план, коротко: модели названы своими строками паспорта. */
function plannedBy(v: Variant, g: Generation, titleOf: (name: string) => string): string {
  const pl = v.planner ?? g.planner ?? null;
  const by = pl?.planned_by === "supplied" ? "supplied" : v.outline?.planned_by ?? pl?.planned_by ?? null;
  if (by === "agent") return "агент";
  if (by === "model") return "модель";
  if (by === "rules" && g.use_models === false) return "текст автора дословно";
  return plannedByText(by ?? undefined, titleOf, pl ? { ...pl, model_label: null } : pl);
}

export interface Fact { k: string; v: string; dim: boolean; title?: string }

export function passport(g: Generation, v: Variant, template: string, titleOf: (name: string) => string): { badge: string; facts: Fact[] } {
  const i = g.variants.indexOf(v);
  const badge = `вариант ${i + 1} · ${titleOf(v.strategy)}`;
  const m = v.run_manifest;
  if (!m) return { badge, facts: [] };
  const facts: Fact[] = [
    { k: "Шаблон", v: template, dim: false, title: m.template.file },
    { k: "Собран", v: fmtWhen(m.created_at), dim: false },
    { k: "Версия Verstka", v: m.verstka_version, dim: false, title: [m.git_commit ? `коммит ${m.git_commit}` : null, m.platform].filter(Boolean).join("\n") || undefined },
    { k: "План составил", v: plannedBy(v, g, titleOf), dim: false },
  ];
  for (const [role, label] of ROLES) {
    const p = m.providers[role] as Provider | undefined;
    if (!p) continue;
    const value = roleUsed(role, m, g) === false ? (role === "vlm" ? "выключена" : "без модели") : modelName(p, role === "llm" ? m.planner?.model : null);
    facts.push({ k: label, v: value, dim: value === "выключена" || value === "без модели" });
  }
  // «Взгляд дизайнера» смотрит на слайды моделью зрения и тогда, когда проверка по картинке выключена
  const vlm = m.providers.vlm as Provider | undefined;
  if (v.eyes && v.eyes.looked > 0 && vlm) facts.push({ k: "Взгляд дизайнера", v: modelName(vlm), dim: false });
  return { badge, facts };
}

// ---- время по этапам ---------------------------------------------------------------------------------------------------

const STAGE: Record<string, string> = {
  analyze: "Разбор шаблона", plan: "План (общий для вариантов)", render: "Сборка PowerPoint", audit: "Проверка и правки", eyes: "Взгляд дизайнера",
  pictures: "Изображения", export: "PDF, веб-версия и превью", other: "Прочее",
};
const secs = (v: number) => (v < 0.5 ? "<1 с" : `${Math.round(v)} с`);

/** Этапы варианта: итог варианта не включает общий план — он добавляется; неизмеренный остаток — «Прочее». */
export function stagesOf(m: RunManifest): { total: string; title: string; rows: { name: string; v: string; w: string; tip: string }[] } | null {
  const measured = Object.entries(m.timings_s).filter(([k, v]) => k !== "total" && Number.isFinite(v));
  if (!measured.length) return null;
  const sum = measured.reduce((s, [, v]) => s + v, 0);
  const total = m.timings_s.total ?? sum;
  const all = total + 0.5 < sum ? total + (m.timings_s.plan ?? 0) : Math.max(total, sum);
  const rest = all - sum;
  const list: Array<[string, number]> = rest > 1 ? [...measured, ["other", rest]] : measured;
  return {
    total: `≈ ${fmtSeconds(all)}`, title: `Весь вариант с общим планом: ${Math.round(all)} с`,
    rows: list.map(([k, v]) => {
      const share = all > 0 ? v / all : 0;
      return { name: STAGE[k] ?? k, v: secs(v), w: `${(share * 100).toFixed(1)}%`, tip: `${STAGE[k] ?? k}: ${secs(v)} — ${Math.round(share * 100)} % всего времени` };
    }),
  };
}

// ---- итог проверки -----------------------------------------------------------------------------------------------------

export interface Tile { label: string; v: string; sub: string; cls: string; icon: IconName; span: number }

/** Автоисправления варианта: живой отчёт проверки (после «Исправить замечания» паспорт запуска устарел), иначе паспорт. */
const appliedOf = (v: Variant) => v.audit?.applied_fixes ?? v.run_manifest?.applied_fixes ?? [];

/** Строки «Автоисправлений» (слайд — по id плана). */
export function fixRowsOf(v: Variant): FixRow[] {
  const slideOf = (id: string) => {
    const i = v.outline?.slides.findIndex((s) => s.id === id) ?? -1;
    return i >= 0 ? i + 1 : null;
  };
  return appliedRows(appliedOf(v), slideOf, () => null);
}

/** «Итог проверки»: числа — `auditCounts` живого отчёта (те же, что у карточки результата и вкладки «Качество»);
 *  отчёта нет — сводка паспорта запуска. «По картинке» — замечания модели; выключенная проверка без них — «выключена». */
export function checkTiles(g: Generation, v: Variant): { head: string | null; score: number | null; tiles: Tile[] } {
  const live = auditCounts(v.audit);
  const m = (v.run_manifest?.audit ?? {}) as Record<string, unknown>;
  const n = (k: string) => (typeof m[k] === "number" ? (m[k] as number) : 0);
  const c = live ?? { errors: n("errors"), warnings: n("warnings"), model: n("model_flags"), infos: n("infos") };
  const run = v.audit?.summary.checks_run ?? (Array.isArray(m.checks_run) ? (m.checks_run as string[]) : []);
  const off = v.run_manifest ? roleUsed("vlm", v.run_manifest, g) === false : g.audit_models === false;
  const fixes = fixRowsOf(v).reduce((k, r) => k + r.n, 0);
  const score = scoreOf(g, v);
  return {
    head: run.length ? plural(run.length, "проверка", "проверки", "проверок") : null,
    score: score === null ? null : Math.round(score),
    tiles: [
      { label: "Ошибки", v: String(c.errors), sub: "", cls: c.errors ? "" : "df-t-ok", icon: "check-circle", span: 2 },
      { label: "Предупреждения", v: String(c.warnings), sub: "", cls: c.warnings ? "df-t-warn" : "", icon: "warning", span: 2 },
      { label: "Заметки", v: String(c.infos), sub: "", cls: "", icon: "info", span: 2 },
      off && !c.model ? { label: "По картинке", v: "—", sub: "выключена", cls: "df-t-off", icon: "eye", span: 3 } : { label: "По картинке", v: String(c.model), sub: "", cls: "", icon: "eye", span: 3 },
      { label: "Автоисправления", v: String(fixes), sub: "", cls: "", icon: "wrench", span: 3 },
    ],
  };
}

// ---- для разработчиков -----------------------------------------------------------------------------------------------

export const JSON_FILES: Array<{ name: string; label: string }> = [
  { name: "outline.json", label: "План" }, { name: "layout_plan.json", label: "Раскладка" }, { name: "audit_report.json", label: "Проверка" }, { name: "run_manifest.json", label: "Паспорт запуска" },
];

/** Реестр навыков и агентов сервера рядом с версиями, записанными в этом запуске. */
export function registryRows(data: SkillsResponse, m: RunManifest | null): { name: string; role: string; version: string; match: string }[] {
  const all = [...data.skills.map((s) => ({ name: s.name, role: s.role, version: s.version, sha: s.sha256 })), ...(data.agents ?? []).map((x) => ({ name: x.name, role: "агент", version: x.version, sha: x.sha256 }))];
  return all.map((r) => {
    const used = m?.skills[r.name];
    const match = !m ? "" : !used ? "не участвовал" : used.sha256 === r.sha ? "как в запуске" : used.version !== r.version ? `в запуске v${used.version}` : "текст изменён";
    return { name: r.name, role: r.role, version: `v${r.version}`, match };
  });
}

type Named = { model?: string | null; label?: string; chain?: Array<{ label?: string; model?: string; off?: boolean }> } | null;
const named = (x: Named) => (x ? x.chain?.filter((l) => !l.off).map((l) => l.label ?? l.model).join(" → ") || x.label || x.model || "—" : "без модели");

/** «Сравнить с другим запуском»: что поменялось между запусками. */
export function diffRows(d: DiffResponse, titleOf: (name: string) => string): { label: string; from: string; to: string }[] {
  const rows: { label: string; from: string; to: string }[] = [];
  if (d.diff.strategy) rows.push({ label: "Вариант", from: titleOf(d.diff.strategy.from), to: titleOf(d.diff.strategy.to) });
  if (d.diff.audit_score) rows.push({ label: "Оценка качества", from: d.diff.audit_score.from === null ? "—" : String(Math.round(d.diff.audit_score.from)), to: d.diff.audit_score.to === null ? "—" : String(Math.round(d.diff.audit_score.to)) });
  for (const [role, ch] of Object.entries(d.diff.providers)) rows.push({ label: `Модель · ${role}`, from: named(ch.from as Named), to: named(ch.to as Named) });
  for (const [name, ch] of Object.entries(d.diff.skills)) rows.push({ label: `Навык · ${name}`, from: ch.from ? `v${ch.from.version} · ${shortSha(ch.from.sha256)}` : "не участвовал", to: ch.to ? `v${ch.to.version} · ${shortSha(ch.to.sha256)}` : "не участвовал" });
  return rows;
}
