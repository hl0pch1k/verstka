// Вкладка «Агент» листа «Подробнее» (boards/D-agent, V2 `#dd-panel-agent`, модуль details `dlA`): полная лента работы
// агента над вариантом по ролям — номер слайда открывает «Почему так» на этом слайде, исправление критика — стрелкой;
// справа — «Ваши правки» с «Вернуть как было» (общее хранилища `revertVariant`: «верни как было» → задача `edit`,
// презентация перечитывается; ход и неудача — в хранилище, они переживают закрытие листа).
// Помощник сужает колоду (V2 версии 100): «Ваши правки» 526 → 340, у «Вернуть как было» остаётся значок, подсказка роли
// сокращается многоточием, текст — стопки (kit/Tx: a-sum, a-tx, a-hint2, a-q, a-a).
import { useApp } from "../../../store";
import type { Generation, Variant } from "../../../types";
import { Arc } from "../../kit/Arc";
import { cls } from "../../kit/cls";
import { ErrorLine } from "../../kit/ErrorLine";
import { Icon } from "../../kit/Icon";
import { Tx } from "../../kit/Tx";
import { StaleLine, useStale } from "../../shell/StaleLine";
import { undoOffOf } from "../../result/slideJob";
import { agentCap, agentRoles, editRows, legacyLines } from "../agentTab";
import { undoView, workKey } from "../variantWork";

/** «Вернуть как было» последней правки варианта; ход — дуга в кнопке, неудача — строка под шапкой. Презентация
 *  несвежая (изменение сохранено здесь или в другом месте, а перечитать не вышло) — строка с «Обновить», а кнопка
 *  выключена: список правок на экране прежний, возврат отменил бы правку, которой здесь не видно. Кнопка выключена и
 *  пока над вариантом идёт любая работа (сервер держит одну задачу на вариант). */
function useUndoEdit(gid: string, strategy: string) {
  const { work, busyVariants, revertVariant } = useApp();
  const key = workKey(gid, strategy);
  const refresh = useStale(gid);
  const view = undoView(work, key, busyVariants.includes(key), !!refresh);
  return { ...view, refresh, off: undoOffOf(!!refresh), undo: () => void revertVariant(gid, strategy, { by: "agent" }) };
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
            <h3 id="da-h-log" className="dd-h" style={{ flex: "none", whiteSpace: "nowrap" }}>Как работал агент</h3>
            {/* сайт: в тесной колоде с помощником подпись сокращается многоточием, заголовок не переносится */}
            <span className="dd-cap" title={agentCap(v)} style={{ minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{agentCap(v)}</span>
          </div>
          {hasEvents ? (
            <ol className="da-tl">
              {roles.map((r) => (
                <li key={r.key} className={cls("da-role p2-in", r.skip && "da-skip", r.last && "da-last")} style={{ animationDelay: r.delay }}>
                  <span className="da-dot" aria-hidden="true"><Icon name={r.icon} size={16} /></span>
                  <div style={{ minWidth: 0 }}>
                    {/* подсказка роли — стопка: в широкой переносится, в узкой — в строку с многоточием (V2); имя роли — вне
                        стопки, оно в обеих раскладках одно */}
                    <div className="da-head">
                      <span className="da-name">{r.name}</span>
                      <Tx tx="a-head" as="span" wrap="span" f className="da-hint">
                        <span className="da-hintt">{r.hint}</span>{r.skip && <span className="dd-tag dd-tag-n">пропущен</span>}
                      </Tx>
                    </div>
                    {r.sum && <Tx tx="a-sum" className="da-sum">{r.sum}</Tx>}
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
                            <Tx tx="a-tx" as="span" className="da-tx">
                              {l.arrow && <span className="da-arr" aria-hidden="true">→</span>}
                              {l.arrow ? <b style={{ fontWeight: 700 }}>{l.a}</b> : l.a}
                              {l.tag && <span className="dd-tag dd-tag-n" style={{ marginLeft: 8 }}>{l.tag}</span>}
                            </Tx>
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
              {legacy.map((l) => <li key={l.key} className="da-ln"><span className="da-c1" /><Tx tx="a-tx" as="span" className="da-tx">{l.a}</Tx></li>)}
            </ul>
          ) : (
            <p style={{ margin: "16px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272" }}>Журнал агента для этой сборки не записан.</p>
          )}
        </section>

        <section className="dd-box p2-in" aria-labelledby="da-h-ed" style={{ position: "sticky", top: 0, animationDelay: "280ms" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, height: 40 }}>
            <h3 id="da-h-ed" className="dd-h">Ваши правки</h3>
            <span className="da-cnt">{ed.active}</span>
            <button type="button" className="p2-ob dla-ob" onClick={un.undo} disabled={!ed.canUndo || un.busy || !!un.off} aria-busy={un.arc || undefined}
              title={un.off ?? "Вернуть как было"} style={{ height: 40, marginLeft: "auto" }}>
              {un.arc ? <Arc size={18} /> : <Icon name="undo" size={18} />}
              <span className="hq-obt">Вернуть как было</span>
            </button>
          </div>
          {un.refresh ? <StaleLine r={un.refresh} lines={0} style={{ marginTop: 8 }} />
            : un.error ? <ErrorLine text={un.error} style={{ marginTop: 8 }} />
            : <Tx tx="a-hint2" style={{ margin: "8px 0 0", fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>{ed.hint}</Tx>}
          {ed.rows.length > 0 && (
            <ol style={{ margin: "16px 0 0", padding: 0, listStyle: "none" }}>
              {ed.rows.map((e) => (
                <li key={e.key} className={cls("da-ed dla-ed", e.off && "dla-off")}>
                  <Tx tx="a-q" style={{ margin: 0, fontSize: 15, fontWeight: 600, lineHeight: "24px", color: "#0B1220" }}>
                    «{e.q}»{e.off && <span className="dd-tag dd-tag-n p2-in" style={{ marginLeft: 8 }}>отменена</span>}
                  </Tx>
                  {e.a && <Tx tx="a-a" style={{ margin: "4px 0 0", fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>{e.a}</Tx>}
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}
