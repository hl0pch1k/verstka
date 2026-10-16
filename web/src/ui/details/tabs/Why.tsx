// Вкладка «Почему так» листа «Подробнее» (boards/D-why, V2 `#dd-panel-why`, модуль details `dlW`): липкая навигация
// по слайдам — одна с результатом (`selectedSlide`), «Почему такая форма», «Как собран слайд», «Другие подходящие
// макеты» и строка «Проверка слайда» (ведёт в «Качество»). Новый слайд, вариант или версия — колонки проявляются
// заново лесенкой (p2-in); стрелки ←/→ листают, пока вкладка на экране. Нет довода у слайда — объяснение сервера.
// Помощник сужает колоду (V2 версии 100): первая колонка 526 → 416, вторая — остальное; текст — стопки (kit/Tx: w-why,
// w-dd, w-form, w-crit — первая колонка; w-sim, w-ok, подписи образца и макетов — вторая).
// Слайд с данными (вторая ступень, V2 v105 `dlWD`): в тех же колонках — «Данные», «Задача», «Варианты визуализации» с
// мини-графиками и «Пересобрать слайд так», «Заголовок-вывод» (DataWhy); в навигации — форма выбранного варианта.
// Слайд без данных — как было.
import { useEffect, useState } from "react";
import { api, ApiError } from "../../../api";
import { errText } from "../../../lib/narrate";
import { variantRev } from "../../../lib/rev";
import { useApp } from "../../../store";
import type { Generation, Variant } from "../../../types";
import { cls } from "../../kit/cls";
import { ErrorLine } from "../../kit/ErrorLine";
import { Icon } from "../../kit/Icon";
import { Spinner } from "../../kit/Spinner";
import { Tx } from "../../kit/Tx";
import { liveWork, variantLiveJob } from "../../result/slideJob";
import { ownsKeys, slideForKey } from "../../result/resultView";
import { useStale } from "../../shell/StaleLine";
import { dataWhyCap } from "../../../lib/dataWhy";
import { miniColors } from "../../../lib/miniChart";
import { Shot } from "../parts";
import { SEV } from "../quality";
import { headerLayerOpen } from "../sheetView";
import { useRebuild } from "../useRebuild";
import type { DeckManifest } from "../useDeckManifest";
import { explainError, explainPlan, explainWhy, whyView, type SampleSource } from "../why";
import { DataWhy } from "./DataWhy";

const asked = new Map<string, string | null>();

/** Объяснение сервера для слайда без довода дизайнера (один раз на слайд и версию варианта). Шаблона презентации больше
 *  нет (`gone`) — сервер объяснить не сможет: не спрашиваем, так и говорим. */
function useExplain(gid: string, strategy: string, n: number, rev: string, need: boolean, gone: boolean): { text: string | null; busy: boolean; error: string | null } {
  const key = `${gid}/${strategy}/${n}/${rev}`;
  const [st, setSt] = useState<{ key: string; text: string | null; busy: boolean; error: string | null }>({ key: "", text: null, busy: false, error: null });
  useEffect(() => {
    // спрошенное раньше берётся и тогда, когда шаблона уже нет (иначе вкладка ждала бы ответа вечно)
    const plan = explainPlan(need, asked.has(key), gone);
    if (plan === "cached") return void setSt({ key, text: asked.get(key) ?? null, busy: false, error: null });
    if (plan !== "ask") return;
    let off = false;
    setSt({ key, text: null, busy: true, error: null });
    api.explain(gid, strategy, n).then(
      (r) => {
        const t = explainWhy(r.text);
        asked.set(key, t);
        if (!off) setSt({ key, text: t, busy: false, error: null });
      },
      (e) => !off && setSt({ key, text: null, busy: false, error: explainError(e instanceof ApiError ? e.status : -1, errText(e)) }),
    );
    return () => {
      off = true;
    };
  }, [key, need, gone, gid, strategy, n]);
  if (explainPlan(need, asked.has(key), gone) === "gone") return { text: null, busy: false, error: explainError(404, "") };
  return st.key === key ? st : { text: null, busy: need, error: null };
}

/** Разбор шаблона листа → что с образцами «Как собран слайд». */
const SOURCE: Record<DeckManifest["state"], SampleSource> = { ready: "ready", loading: "loading", gone: "missing", offline: "failed", error: "failed" };

const FRAME = { width: "100%", aspectRatio: "16 / 9", borderRadius: 12, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" } as const;
const SMALL = { margin: 0, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#0B1220" } as const;
const DD = { margin: 0, minWidth: 0 } as const;

/** «Вывод» и «Сноска» слайда (`dl`: только `dt` и `dd`). Определение — стопка из двух копий (kit/Tx, `w-dd`) внутри `dd`. */
export function WhyTerms({ dl }: { dl: { t: string; d: string }[] }) {
  return (
    <dl style={{ display: "grid", gridTemplateColumns: "72px minmax(0, 1fr)", gap: "8px 12px", margin: "16px 0 0", paddingTop: 16, borderTop: "1px solid rgba(11,18,32,.08)" }}>
      {dl.map((x) => [
        <dt key={`${x.t}t`} className="dw-sub">{x.t}</dt>,
        <dd key={`${x.t}d`} style={DD}><Tx tx="w-dd" style={SMALL}>{x.d}</Tx></dd>,
      ])}
    </dl>
  );
}

/** Пересобрать слайд нельзя: шаблона презентации больше нет. */
const TEMPLATE_GONE_REBUILD = "Шаблона этой презентации больше нет в библиотеке — пересобрать слайд нельзя";

export function WhyTab({ g, v, deck, active }: { g: Generation; v: Variant; deck: DeckManifest; active: boolean }) {
  const { selectedSlide, setSelectedSlide, setActiveStrategy, strategyTitle, dispatch, ui, liveJobs } = useApp();
  const w = whyView(g, v, Math.min(Math.max(1, selectedSlide), Math.max(1, v.slides.length || v.outline?.slides.length || 1)), deck.manifest, strategyTitle, SOURCE[deck.state]);
  const n = w.n;
  const rev = variantRev(v);
  // слайд с данными: профиль, задача, варианты визуализации — свои колонки (объяснение сервера не нужно)
  const slide = v.outline?.slides[n - 1] ?? null;
  const data = slide?.data ?? null;
  const ex = useExplain(g.id, v.strategy, n, rev, w.ask && !data, deck.state === "gone");
  const why = w.why ?? ex.text;
  const rebuild = useRebuild(g.id, v.strategy);
  const refresh = useStale(g.id);
  const other = rebuild.taken ? variantLiveJob(liveJobs, g.id, v.strategy, rebuild.run?.jobId ?? null) : null;
  const lock = deck.state === "gone" ? { off: true, why: TEMPLATE_GONE_REBUILD }
    : rebuild.taken ? { off: true, why: other ? liveWork(other).why : null } : { off: false, why: null };
  const cap = data ? dataWhyCap(w, data) : w.cap;

  // ←/→ листают слайды, пока вкладка на экране и поверх листа ничего не открыто (слой «Слайд N шаблона», раздел шапки,
  // просмотр или удаление шаблона)
  const covered = ui.pattern !== null || headerLayerOpen(ui);
  useEffect(() => {
    if (!active || covered || w.total < 2) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || ownsKeys(e.target)) return;
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const to = slideForKey(e.key, n, w.total);
      if (to === null) return;
      e.preventDefault();
      if (to !== n) setSelectedSlide(to);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, covered, n, w.total, setSelectedSlide]);

  return (
    <div id="dd-panel-why" className="dd-scroll p2-fade dw-fade" role="tabpanel" aria-labelledby="dd-tab-why" tabIndex={0}>
      <div className="dw-navw">
        <nav className="dd-box p2-in" aria-label="Слайды презентации" style={{ display: "flex", alignItems: "center", gap: 16, height: 72, padding: "12px 16px", animationDelay: "240ms" }}>
          <button type="button" className="p2-rbl" aria-label="Предыдущий слайд" title="Предыдущий слайд (←)" disabled={n <= 1} onClick={() => setSelectedSlide(n - 1)}><Icon name="chevron-left" size={18} /></button>
          <div key={`${n}|${v.strategy}`} className="p2-in" style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: 1, minWidth: 0, textAlign: "center" }}>
            <span className="dd-cap">{cap}</span>
            <h3 className="dd-h" title={w.title} style={{ maxWidth: "100%", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{w.title}</h3>
          </div>
          <button type="button" className="p2-rbl" aria-label="Следующий слайд" title="Следующий слайд (→)" disabled={n >= w.total} onClick={() => setSelectedSlide(n + 1)}><Icon name="chevron-right" size={18} /></button>
        </nav>
      </div>

      <div key={`${n}|${v.strategy}|${rev}`} className="dd-g dw-g">
        {data && slide ? (
          <DataWhy v={v} n={n} slide={slide} d={data} colors={miniColors(deck.manifest)} rebuild={rebuild} lock={lock} refresh={refresh} />
        ) : <>
        <section className="dd-box p2-in" aria-labelledby="dw-h-form" style={{ display: "flex", flexDirection: "column", minWidth: 0, animationDelay: "0ms" }}>
          <h3 id="dw-h-form" className="dd-h">Почему такая форма</h3>
          {w.src && <p style={{ display: "flex", alignItems: "center", gap: 8, margin: "4px 0 0", fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "#5A6272" }}><Icon name="file-text" size={16} />{w.src}</p>}
          {why ? <Tx tx="w-why" className={cls(!w.why && "p2-in")} style={{ margin: "16px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#0B1220" }}>{why}</Tx>
            : ex.busy ? <p style={{ display: "flex", alignItems: "center", gap: 8, margin: "16px 0 0", fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#5A6272" }}><Spinner size={16} />Собираю объяснение…</p>
              : ex.error ? <ErrorLine text={ex.error} style={{ marginTop: 16 }} />
                : <Tx tx="w-why" style={{ margin: "16px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272" }}>Дизайнер не оставил объяснения для этого слайда.</Tx>}
          {w.dl.length > 0 && <WhyTerms dl={w.dl} />}
          {w.forms.length > 0 && (
            <>
              <h4 className="dw-sub" style={{ marginTop: 24 }}>Другие формы</h4>
              <ul style={{ margin: "8px 0 0", padding: 0, listStyle: "none" }}>
                {w.forms.map((f, i) => (
                  <li key={i} className="dw-row">
                    <Tx tx="w-form" f style={SMALL}>{f.name && <b style={{ fontWeight: 700 }}>{f.name}</b>}{f.name && f.text ? " — " : ""}{f.text}</Tx>
                    {(f.variant || f.onScreen) && (
                      <span style={{ flex: "none" }}>
                        {f.variant && (
                          <button type="button" className="p2-ob" title="Переключиться на этот вариант" aria-label={`Переключиться на вариант ${f.variant.name}`} onClick={() => setActiveStrategy(f.variant!.key)} style={{ height: 40, padding: "0 16px", fontSize: 14 }}>
                            <span>{f.variant.name}</span>{f.variant.score !== null && <span className="p2-rsc">{f.variant.score}</span>}
                          </button>
                        )}
                        {f.onScreen && <span className="dd-tag dd-tag-b p2-in">{f.onScreen}</span>}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
          {w.crit.length > 0 && (
            <div style={{ marginTop: "auto", paddingTop: 24 }}>
              <h4 className="dw-sub">Критик и правка</h4>
              <ol style={{ display: "flex", flexDirection: "column", gap: 12, margin: "12px 0 0", padding: 16, borderRadius: 16, background: "#F3F4F1", listStyle: "none" }}>
                {w.crit.map((c, i) => (
                  <li key={i} className="dw-cr">
                    <span className="dd-tag" style={{ background: "#FFFFFF", color: c.who === "Критик" ? "#0B1220" : "#2563EB" }}>{c.who}</span>
                    <Tx tx="w-crit" as="span">{c.arrow && <><b style={{ fontWeight: 700, color: "#2563EB" }}>→</b> </>}{c.text}</Tx>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </section>

        <div style={{ minWidth: 0 }}>
          <section className="dd-box p2-in" aria-labelledby="dw-h-build" style={{ animationDelay: "40ms" }}>
            <h3 id="dw-h-build" className="dd-h">Как собран слайд</h3>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 40px minmax(0, 1fr)", alignItems: "center", rowGap: 8, marginTop: 16 }}>
              {w.sample ? <Shot src={w.sample.src} alt={w.sample.label} style={FRAME} />
                : <span className="dw-wf" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 16, textAlign: "center" }}>
                  <Tx tx="w-cap" as="span" wrap="span" f style={{ fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "#5A6272" }}>{w.frame}</Tx>
                </span>}
              <span aria-hidden="true" style={{ display: "flex", alignItems: "center", justifyContent: "center", color: "#2563EB" }}><Icon name="arrow-right" size={20} /></span>
              <Shot src={w.own.src} alt={w.own.alt} style={FRAME} />
              <Tx tx="w-cap" as="span" className="dd-cap">{w.sampleCap}</Tx>
              <span />
              <span className="dd-cap" style={{ color: "#0B1220" }}>Ваш слайд</span>
            </div>
            {w.sim && (
              <div style={{ marginTop: 24, paddingTop: 16, borderTop: "1px solid rgba(11,18,32,.08)" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, height: 28 }}>
                  <span id="dw-sim" style={{ fontSize: 14, fontWeight: 700, lineHeight: "20px", color: "#0B1220" }}>Сходство с образцом</span>
                  <span style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: "28px", letterSpacing: "-0.02em", color: "#2563EB" }}>{w.sim.pct}%</span>
                </div>
                <div role="meter" aria-labelledby="dw-sim" aria-valuemin={0} aria-valuemax={100} aria-valuenow={w.sim.pct} aria-valuetext={`${w.sim.pct}%`} style={{ position: "relative", height: 4, marginTop: 8, borderRadius: 999, background: "#F3F4F1", overflow: "hidden" }}>
                  <span style={{ position: "absolute", inset: 0, borderRadius: 999, background: "#2563EB", transformOrigin: "left center", transform: `scaleX(${w.sim.pct / 100})` }} />
                </div>
                <Tx tx="w-sim" style={{ margin: "8px 0 0", fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>{w.sim.note}</Tx>
              </div>
            )}
            {w.reasons.length > 0 && (
              <ul style={{ display: "flex", flexDirection: "column", gap: 12, margin: "16px 0 0", padding: "16px 0 0", borderTop: "1px solid rgba(11,18,32,.08)", listStyle: "none" }}>
                {w.reasons.map((r) => (
                  <li key={r.text} className="dw-ok">
                    <span style={{ display: "flex", flex: "none", color: r.good ? "#2563EB" : "#B45309" }}><Icon name={r.good ? "check-circle" : "warning"} size={20} /></span>
                    <Tx tx="w-ok" as="span" f>{r.text}</Tx>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {w.alts.length > 0 && (
            <section className="dd-box p2-in" aria-labelledby="dw-h-alt" style={{ marginTop: 24, animationDelay: "80ms" }}>
              <h3 id="dw-h-alt" className="dd-h">Другие подходящие макеты</h3>
              <ul style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16, margin: "16px 0 0", padding: 0, listStyle: "none" }}>
                {w.alts.map((a) => (
                  <li key={a.key}>
                    <Shot src={a.src} alt={a.label} style={FRAME} />
                    <Tx tx="w-alt" style={{ margin: "8px 0 0", fontSize: 13, fontWeight: 700, lineHeight: "20px", color: "#0B1220" }}>{a.cap}</Tx>
                    <Tx tx="w-alt" className="dd-cap" style={{ margin: 0 }}>{a.sim}</Tx>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
        </>}

        {w.check && (
          <button type="button" className="dw-chk p2-in" onClick={() => dispatch({ type: "sheet", tab: "quality" })} aria-label={`Проверка слайда: ${w.check.text} — открыть вкладку «Качество»`} style={{ gridColumn: "1 / -1", animationDelay: "120ms" }}>
            <span className="dd-ico" aria-hidden="true"><Icon name="list-check" size={18} /></span>
            <span style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 14, fontWeight: 600, lineHeight: "24px", letterSpacing: "-0.02em" }}>
              Проверка слайда <span style={{ fontFamily: "'Manrope',system-ui,sans-serif", fontSize: 15, fontWeight: 500, letterSpacing: 0, color: "#5A6272" }}>· {w.check.text}</span>
            </span>
            {w.check.tone && <span className={cls("dd-tag", SEV[w.check.tone].cls)}><Icon name={SEV[w.check.tone].icon} size={14} />{SEV[w.check.tone].label}</span>}
            <span style={{ display: "flex", marginLeft: "auto", flex: "none", color: "#5A6272" }}><Icon name="chevron-right" size={18} /></span>
          </button>
        )}
      </div>
    </div>
  );
}
