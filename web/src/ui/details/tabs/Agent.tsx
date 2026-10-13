// Вкладка «Агент» листа «Подробнее» (boards/D-agent, V2 `#dd-panel-agent`, модуль details `dlA`): полная лента работы
// агента над вариантом по ролям — номер слайда открывает «Почему так» на этом слайде, исправление критика — стрелкой;
// справа — «Ваши правки» с «Вернуть как было» («верни как было» → задача `edit`, презентация перечитывается).
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../../api";
import { humanError } from "../../../lib/errors";
import { useApp } from "../../../store";
import type { Generation, Job, Variant } from "../../../types";
import { Arc } from "../../kit/Arc";
import { cls } from "../../kit/cls";
import { ErrorLine } from "../../kit/ErrorLine";
import { Icon } from "../../kit/Icon";
import { agentCap, agentRoles, editRows, legacyLines } from "../agentTab";

/** «Вернуть как было» последней правки варианта; ход — дуга в кнопке, неудача — строка под шапкой. */
function useUndoEdit(gid: string, strategy: string) {
  const { runJob, reloadIfOpen } = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const set = (b: boolean, e: string | null) => {
    if (!alive.current) return;
    setBusy(b);
    setError(e);
  };
  const undo = async () => {
    if (busy) return;
    set(true, null);
    const fail = (t: string | null | undefined) => set(false, humanError(t, "Вернуть не получилось. Попробуйте ещё раз."));
    let jobId: string;
    try {
      jobId = (await api.editVariant(gid, strategy, { message: "верни как было" })).job_id;
    } catch (e) {
      return fail(e instanceof ApiError || e instanceof Error ? e.message : String(e));
    }
    runJob(jobId, "Возвращаю как было", {
      kind: "edit", area: "result", quiet: true,
      onDone: async (job: Job) => {
        const r = job.result as { changed?: boolean; reply?: string } | null;
        if (r && r.changed === false) return fail(r.reply);
        await reloadIfOpen(gid);
        set(false, null);
      },
      onFailed: (job: Job) => fail(job.error ?? job.message),
    });
  };
  return { busy, error, undo };
}

export function AgentTab({ g, v }: { g: Generation; v: Variant }) {
  const { setSelectedSlide, dispatch, strategyTitle } = useApp();
  const roles = agentRoles(g, v, strategyTitle);
  const hasEvents = (v.agent?.events?.length ?? 0) > 0;
  const legacy = hasEvents ? [] : legacyLines(v.agent?.log ?? []);
  const ed = editRows(v.edits ?? []);
  const un = useUndoEdit(g.id, v.strategy);
  const why = (n: number) => {
    setSelectedSlide(n);
    dispatch({ type: "sheet", tab: "why" });
  };

  return (
    <div id="dd-panel-agent" className="dd-scroll p2-fade" role="tabpanel" aria-labelledby="dd-tab-agent" tabIndex={0}>
      <div className="dd-g">
        <section key={v.strategy} className="dd-box p2-in" aria-labelledby="da-h-log" style={{ animationDelay: "240ms" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, height: 40 }}>
            <h3 id="da-h-log" className="dd-h">Как работал агент</h3>
            <span className="dd-cap" style={{ whiteSpace: "nowrap" }}>{agentCap(v)}</span>
          </div>
          {hasEvents ? (
            <ol className="da-tl">
              {roles.map((r) => (
                <li key={r.key} className={cls("da-role p2-in", r.skip && "da-skip", r.last && "da-last")} style={{ animationDelay: r.delay }}>
                  <span className="da-dot" aria-hidden="true"><Icon name={r.icon} size={16} /></span>
                  <div style={{ minWidth: 0 }}>
                    <div className="da-head">
                      <span className="da-name">{r.name}</span>
                      <span className="da-hint">{r.hint}</span>
                      {r.skip && <span className="dd-tag dd-tag-n">пропущен</span>}
                    </div>
                    {r.sum && <p className="da-sum">{r.sum}</p>}
                    {r.lines.length > 0 && (
                      <ul className="da-lns">
                        {r.lines.map((l) => (
                          <li key={l.key} className={cls("da-ln", l.arrow && "da-ln-arr")}>
                            <span className="da-c1">
                              {l.n !== null && (
                                <button type="button" className="da-sl" title={`Почему слайд ${l.n} такой`} aria-label={`Слайд ${l.n} — почему он такой`} onClick={() => why(l.n!)}>{l.n}</button>
                              )}
                              {l.mark && <span style={{ display: "flex", color: l.mark === "ok" ? "#2563EB" : "#B45309" }}><Icon name={l.mark === "ok" ? "check-circle" : "warning"} size={20} /></span>}
                            </span>
                            <span className="da-tx">
                              {l.arrow && <span className="da-arr" aria-hidden="true">→</span>}
                              {l.arrow ? <b style={{ fontWeight: 700 }}>{l.a}</b> : l.a}
                              {l.tag && <span className="dd-tag dd-tag-n" style={{ marginLeft: 8 }}>{l.tag}</span>}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          ) : legacy.length ? (
            <ul className="da-lns" style={{ marginTop: 24 }}>
              {legacy.map((l) => <li key={l.key} className="da-ln"><span className="da-c1" /><span className="da-tx">{l.a}</span></li>)}
            </ul>
          ) : (
            <p style={{ margin: "16px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272" }}>Журнал агента для этой сборки не записан.</p>
          )}
        </section>

        <section className="dd-box p2-in" aria-labelledby="da-h-ed" style={{ position: "sticky", top: 0, animationDelay: "280ms" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, height: 40 }}>
            <h3 id="da-h-ed" className="dd-h">Ваши правки</h3>
            <span className="da-cnt">{ed.active}</span>
            <button type="button" className="p2-ob dla-ob" onClick={() => void un.undo()} disabled={!ed.canUndo || un.busy} aria-busy={un.busy || undefined} style={{ height: 40, marginLeft: "auto" }}>
              {un.busy ? <Arc size={18} /> : <Icon name="undo" size={18} />}
              <span>Вернуть как было</span>
            </button>
          </div>
          {un.error ? <ErrorLine text={un.error} style={{ marginTop: 8 }} />
            : <p style={{ margin: "8px 0 0", fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>{ed.hint}</p>}
          {ed.rows.length > 0 && (
            <ol style={{ margin: "16px 0 0", padding: 0, listStyle: "none" }}>
              {ed.rows.map((e) => (
                <li key={e.key} className={cls("da-ed dla-ed", e.off && "dla-off")}>
                  <p style={{ margin: 0, fontSize: 15, fontWeight: 600, lineHeight: "24px", color: "#0B1220" }}>
                    «{e.q}»{e.off && <span className="dd-tag dd-tag-n p2-in" style={{ marginLeft: 8 }}>отменена</span>}
                  </p>
                  {e.a && <p style={{ margin: "4px 0 0", fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>{e.a}</p>}
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}
