// Вкладка «Качество» листа «Подробнее» (boards/D-quality, V2 `#dd-panel-quality`, модуль details `dlQ`): сводка с
// кольцом оценки и исправлением отмеченных, чипы, замечания по слайдам с флажками и «Показать», «Взгляд дизайнера»,
// мелкие заметки, исправленное автоматически и «Что проверяется». Данные и тексты — quality.ts, числа сводки —
// auditCounts (те же, что у карточки результата и «Файлов»), исправление — useQualityFix (состояние в хранилище:
// переживает закрытие листа). Смена чипа, итог исправления и «Вернуть как было» заново проявляют список лесенкой (p2-in).
import { useEffect, useMemo, useState } from "react";
import { api } from "../../../api";
import { auditCounts } from "../../../lib/auditCounts";
import { variantRev } from "../../../lib/rev";
import { plural } from "../../../lib/utils";
import { useApp } from "../../../store";
import type { CheckSpec, Generation, Variant } from "../../../types";
import { Arc } from "../../kit/Arc";
import { cls } from "../../kit/cls";
import { ErrorLine } from "../../kit/ErrorLine";
import { Icon } from "../../kit/Icon";
import { scoreOf } from "../../result/resultView";
import { appliedRows } from "../fixes";
import { Acc, Empty, Row, Shot } from "../parts";
import {
  checkRows, chipsOf, emptyOf, eyeView, fixableIds, fixingLabel, fixLabel, isFixable, minorRows, qualityGroups, qualitySummary, slideTag, splitIssues, type QFilter,
} from "../quality";
import { useQualityFix } from "../useQualityFix";
import { EyeBox } from "./QualityEye";

// Реестр проверок (GET /api/checks) один на страницу: его просят, когда лист открылся впервые; не ответил — раздел
// говорит только число проверок, а следующий лист попросит снова.
let checksCache: CheckSpec[] | null = null;
function useChecks(): CheckSpec[] | "failed" | null {
  const [list, setList] = useState<CheckSpec[] | "failed" | null>(checksCache);
  useEffect(() => {
    if (list) return;
    let off = false;
    api.checks().then((c) => {
      checksCache = c;
      if (!off) setList(c);
    }, () => !off && setList("failed"));
    return () => {
      off = true;
    };
  }, [list]);
  return list;
}

export function QualityTab({ g, v }: { g: Generation; v: Variant }) {
  const { selectedSlide, setSelectedSlide, dispatch } = useApp();
  const audit = v.audit;
  const { main, minor } = useMemo(() => splitIssues(audit?.issues ?? []), [audit]);
  const [filter, setFilter] = useState<QFilter>("all");
  const [k, setK] = useState(0);
  const [unmarked, setUnmarked] = useState<Set<string>>(() => new Set());
  // другой вариант — свои замечания: снятые флажки прежнего не переносятся
  const [marksOf, setMarksOf] = useState(v.strategy);
  if (marksOf !== v.strategy) {
    setMarksOf(v.strategy);
    setUnmarked(new Set());
  }
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const fix = useQualityFix(g.id, v);
  const checks = useChecks();
  const toggle = (key: string) => setOpen((o) => ({ ...o, [key]: !o[key] }));
  const pick = (f: QFilter) => {
    if (f === filter) return;
    setFilter(f);
    setK((x) => x + 1);
  };

  if (!audit) {
    return (
      <div id="dd-panel-quality" className="dd-scroll p2-fade" role="tabpanel" aria-labelledby="dd-tab-quality" tabIndex={0}>
        <Empty title="Проверки нет" text="Для этого варианта отчёт проверки не сохранился — соберите презентацию заново." />
      </div>
    );
  }

  const score = scoreOf(g, v) ?? audit.summary.score;
  const sum = qualitySummary(score, auditCounts(audit)!);
  const groups = qualityGroups(v, main, filter, selectedSlide, unmarked, fix.busy);
  const marked = fixableIds(main, unmarked);
  const fixableAll = audit.issues.filter(isFixable).map((i) => i.id);
  // над вариантом идёт работа (своя — и после закрытия листа, или чужая задача): кнопки и флажки выключены
  const busy = fix.locked;
  const allOn = !fix.undo && fixableAll.length > 0;
  const ctaOn = main.some(isFixable);
  const outline = v.outline?.slides ?? [];
  const slideOf = (id: string) => {
    const i = outline.findIndex((s) => s.id === id);
    return i >= 0 ? i + 1 : null;
  };
  const fixed = appliedRows(audit.applied_fixes, slideOf, () => null);
  const minors = minorRows(minor);
  const checkList = Array.isArray(checks) ? checkRows(checks, audit.summary.checks_run) : [];
  const eye = eyeView(v.eyes, v);
  const empty = emptyOf(filter, main.length);
  const show = (n: number) => {
    setSelectedSlide(n);
    dispatch({ type: "sheet", tab: null });
  };
  const mark = (id: string) => setUnmarked((s) => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  return (
    <div id="dd-panel-quality" className="dd-scroll p2-fade" role="tabpanel" aria-labelledby="dd-tab-quality" tabIndex={0}>
      <section className="dd-box p2-in" aria-label="Сводка проверки" style={{ display: "flex", alignItems: "center", gap: 24, animationDelay: "240ms" }}>
        <div className="dq-ring" role="img" aria-label={`Оценка качества ${sum.score} из 100`}>
          <svg width="88" height="88" viewBox="0 0 88 88" aria-hidden="true">
            <circle cx="44" cy="44" r="40" fill="none" stroke="#F3F4F1" strokeWidth="8" />
            <circle cx="44" cy="44" r="40" fill="none" stroke="#2563EB" strokeWidth="8" strokeLinecap="round" strokeDasharray={sum.dash} />
          </svg>
          <span className="dq-ring-v" aria-hidden="true">
            <span style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 700, fontSize: 28, lineHeight: "32px", letterSpacing: "-0.04em", color: "#0B1220" }}>{sum.score}</span>
            <span style={{ fontSize: 12, fontWeight: 600, lineHeight: "16px", color: "#5A6272" }}>из 100</span>
          </span>
        </div>
        <div style={{ position: "relative", flex: 1, minWidth: 0 }}>
          <h3 className="dd-h">{sum.head}</h3>
          {/* в одну строку, как на доске; рядом с итогом исправления места меньше — счётчики переносятся, а не наезжают */}
          <p style={{ display: "flex", flexWrap: "wrap", alignItems: "center", columnGap: 8, margin: "4px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#0B1220", whiteSpace: "nowrap" }}>
            <span style={sum.hasErr ? { fontWeight: 700, color: "#DC2626" } : undefined}>{sum.nErr}</span>
            <span aria-hidden="true" style={{ color: "#5A6272" }}>·</span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontWeight: 700, color: "#B45309" }}><Icon name="warning" size={16} />{sum.nWarn}</span>
            <span aria-hidden="true" style={{ color: "#5A6272" }}>·</span>
            <span>{sum.nModel}</span>
          </p>
          {/* строка неудачи — под счётчиками, не сдвигая их (сводка выровнена по центру) */}
          {fix.error && (
            <div className="p2-in" style={{ position: "absolute", left: 0, right: 0, top: "100%", marginTop: 2 }}>
              <ErrorLine text={fix.error} lines={1} style={{ maxWidth: "100%" }} />
            </div>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, flex: "none" }}>
          {fix.undo && (
            <>
              <p className="dlq-st p2-in" role="status"><Icon name="check-circle" size={20} />{fix.status}</p>
              <button type="button" className="p2-ob dlq-ob p2-in" onClick={fix.revert} disabled={busy} aria-busy={fix.working === "undo" || undefined} style={{ animationDelay: "40ms" }}>
                {fix.working === "undo" ? <Arc size={18} /> : <Icon name="undo" size={18} />}
                <span>Вернуть как было</span>
              </button>
            </>
          )}
          {allOn && (
            <button type="button" className="p2-ob dlq-ob" disabled={busy} onClick={() => fix.start("all", fixableAll)}>Исправить всё автоматически</button>
          )}
          {ctaOn && (
            <button type="button" className="p2-cta dq-cta" disabled={busy || marked.length === 0} onClick={() => fix.start(marked, marked)}>
              <Icon name="wand" size={20} />
              <span>{fix.working === "fix" ? fixingLabel(fix.busy === "all" ? fixableAll.length : (fix.busy ?? []).length) : fixLabel(marked.length)}</span>
            </button>
          )}
        </div>
      </section>

      <div className="dd-g" style={{ marginTop: 24 }}>
        <div style={{ minWidth: 0 }}>
          <div className="p2-in" role="radiogroup" aria-label="Какие замечания показать" style={{ display: "flex", alignItems: "center", gap: 8, height: 40, animationDelay: "280ms" }}>
            {chipsOf(main, filter).map((ch) => (
              <button key={ch.key} type="button" role="radio" aria-checked={ch.on} className={cls("p2-pill dq-chip", ch.on && "dq-chip-on")} onClick={() => pick(ch.key)}>
                <span>{ch.label}</span><span className={cls("dq-cnt", ch.n === 0 && "dq-cnt0")}>{ch.n}</span>
              </button>
            ))}
          </div>
          <div key={`${filter}|${v.strategy}|${variantRev(v)}|${k}`}>
            {groups.map((gr, gi) => (
              <section key={gr.slide} className={cls("dd-box p2-in", gr.current && "dq-grp-on")} aria-label={gr.aria} aria-current={gr.current || undefined} style={{ marginTop: 16, animationDelay: `${gi * 40}ms` }}>
                <div style={{ display: "flex", alignItems: "center", gap: 16, height: 48 }}>
                  <span style={{ display: "block", width: 80, height: 45, flex: "none" }}>
                    {gr.slide ? <Shot src={gr.img} alt="" style={{ width: 80, height: 45, borderRadius: 12, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" }} />
                      : <span aria-hidden="true" style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 80, height: 45, borderRadius: 12, background: "#F3F4F1", color: "#2563EB" }}><Icon name="layers" size={20} /></span>}
                  </span>
                  <h3 style={{ minWidth: 0, margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 14, fontWeight: 600, lineHeight: "24px", letterSpacing: "-0.02em", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {gr.label}<span style={{ fontFamily: "'Manrope',system-ui,sans-serif", fontSize: 15, fontWeight: 500, letterSpacing: 0, color: "#5A6272" }}>{gr.sub}</span>
                  </h3>
                  <span style={{ marginLeft: "auto", flex: "none", fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "#5A6272" }}>{gr.count}</span>
                  {gr.slide > 0 && (
                    <button type="button" className="p2-gb" onClick={() => show(gr.slide)} aria-label={`Показать слайд ${gr.slide}`} style={{ flex: "none", marginRight: -16 }}>
                      Показать<Icon name="arrow-right" size={16} />
                    </button>
                  )}
                </div>
                <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
                  {gr.items.map((it) => (
                    <li key={it.id} className={cls("dq-iss dlq-iss", it.busy && "dlq-busy")}>
                      <div style={{ width: 24 }}>
                        {it.fixable ? (
                          <button type="button" role="checkbox" aria-checked={it.checked} aria-label="Отметить для исправления" className={cls("dq-cb", it.checked && "dq-cb-on")} disabled={busy} onClick={() => mark(it.id)}>
                            <span className="dq-cbx"><Icon name="check" size={12} /></span>
                          </button>
                        ) : <span className="dq-dot" aria-hidden="true" style={{ color: it.color }} />}
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <span className={cls("dd-tag", it.cls)}><Icon name={it.icon} size={14} />{it.label}</span>
                        <p style={{ margin: "8px 0 0", fontSize: 15, fontWeight: 600, lineHeight: "24px", color: "#0B1220" }}>{it.msg}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
            {groups.length === 0 && (
              <section className="dd-box p2-pop" style={{ display: "flex", flexDirection: "column", alignItems: "center", marginTop: 16, padding: "40px 24px", textAlign: "center" }}>
                <span aria-hidden="true" style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 48, height: 48, borderRadius: 999, background: "#E9F1FF", color: "#2563EB" }}><Icon name="check" size={20} /></span>
                <h3 className="dd-h" style={{ marginTop: 16 }}>{empty.title}</h3>
                <p style={{ maxWidth: 440, margin: "8px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272" }}>{empty.text}</p>
                {empty.showAll && <button type="button" className="p2-ob" onClick={() => pick("all")} style={{ marginTop: 24 }}>Показать все замечания</button>}
              </section>
            )}
          </div>
        </div>

        <div style={{ minWidth: 0 }}>
          {eye && <EyeBox eye={eye} open={!!open.eye} onToggle={() => toggle("eye")} />}
          {(minors.length > 0 || fixed.length > 0 || audit.summary.checks_run.length > 0) && (
            <section className="dd-box p2-in" aria-label="Подробности проверки" style={{ marginTop: eye ? 24 : 0, padding: "0 24px", animationDelay: "360ms" }}>
              {minors.length > 0 && (
                <Acc id="dq-acc-notes" icon="note" title="Мелкие заметки" n={minors.length} open={!!open.notes} onToggle={() => toggle("notes")} first>
                  {minors.map((r, i) => <Row key={i} {...r} />)}
                </Acc>
              )}
              {fixed.length > 0 && (
                <Acc id="dq-acc-fixed" icon="wand" title="Исправлено автоматически" n={fixed.reduce((x, r) => x + r.n, 0)} open={!!open.fixed} onToggle={() => toggle("fixed")} first={minors.length === 0}>
                  {fixed.map((r, i) => <Row key={i} tag={slideTag(r.slide)} b={r.title} c={`${r.extra ? `: ${r.extra}` : ""}${r.n > 1 ? ` ×${r.n}` : ""}`} />)}
                </Acc>
              )}
              {audit.summary.checks_run.length > 0 && (
                <Acc id="dq-acc-checks" icon="list-check" title="Что проверяется" n={audit.summary.checks_run.length} open={!!open.checks} onToggle={() => toggle("checks")} first={minors.length === 0 && fixed.length === 0}>
                  {checkList.length ? checkList.map((r) => <Row key={r.b} {...r} />)
                    : <Row tag={null} b="" c={`${plural(audit.summary.checks_run.length, "проверка", "проверки", "проверок")}${checks === "failed" ? " — список проверок не загрузился" : checks === null ? " — список загружается" : ""}`} />}
                </Acc>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
