// Лист «Подробнее» (boards/D-quality … D-files, V2 `#p2-lay-d`): голубой лист поднимается над результатом до 160 px
// (слой колоды, 520 мс; над ним видна полоса «04 …» плиты результата — BackStrip). Шапка: шесть вкладок `dd-tabs`,
// меню варианта (как `df-menu`) и ✕; шапка и вкладки проявляются лесенкой (p2-ls 120/200 мс). Вкладки сменяются
// перекрёстным затуханием (p2-on 360 мс через 120 / p2-off 240 мс) и все стоят, пока лист открыт: их раскрытия и выбор
// переживают переключение. Закрытый лист уезжает вниз непрозрачным со своей вкладкой (`sheetLast`); слой «Слайд N
// шаблона» и меню варианта сбрасываются, когда лист уехал. Esc закрывает меню, слой шаблона или лист — что сверху.
// Помощник сужает колоду — лист идёт за ней каждый кадр (V2 версии 100, details.css): дорожки колонок вкладок с тем же
// числом дорожек, многострочный текст — стопки из двух копий (kit/Tx), только-широкое сжимается и гаснет на месте.
// Невыбранные вкладки и закрытый лист ход помощника не трогают (layers.css, `--lgone`). При окне около 1280 (тесная
// колода, sheetMorph.ts) V2 не помещается — свои дорожки (`dd-tight`).
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useApp } from "../../store";
import type { Generation, Variant } from "../../types";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { Menu } from "../kit/Menu";
import { Layer, LAYER_MS, lsDelay, useLayerPresence } from "../layers/Layer";
import { TxNarrow } from "../kit/Tx";
import { useNarrow } from "../create/useNarrow";
import { useDeckWrap } from "../deck/useDeckFit";
import { SheetCtx, sheetMorph } from "./sheetMorph";
import { Panel } from "./parts";
import { PatternLayer } from "./PatternLayer";
import { headerLayerOpen, menuItems, SHEET_TABS, tabStep } from "./sheetView";
import { AgentTab } from "./tabs/Agent";
import { FilesTab } from "./tabs/Files";
import { PlanTab } from "./tabs/Plan";
import { QualityTab } from "./tabs/Quality";
import { TemplateTab } from "./tabs/Template";
import { WhyTab } from "./tabs/Why";
import { useDeckManifest } from "./useDeckManifest";
import { scoreOf, docTitle } from "../result/resultView";

/** Сброс слоя шаблона и меню — после того как лист уехал (V2: 560 мс). */
const RESET_MS = LAYER_MS + 40;
/** Лист доехал (520 мс) и самая долгая лесенка вкладок доиграла («Файлы» — 480 + 360). */
const SETTLE_MS = 900;

export function DetailsSheet() {
  const { ui, dispatch, generation, activeVariant, setActiveStrategy, strategyTitle } = useApp();
  const ready = ui.screen === "result" && !!generation && generation.variants.length > 0;
  const open = ready && !!ui.sheet;
  // показанная презентация держится, пока лист уезжает
  const last = useRef<{ g: Generation; v: Variant } | null>(null);
  if (open && generation) last.current = { g: generation, v: activeVariant && generation.variants.includes(activeVariant) ? activeVariant : generation.variants[0] };
  const keep = last.current;
  const tab = ui.sheetLast;
  // разбор шаблона не загрузился — лист открыли снова или сменили вкладку: просим ещё раз (закрытие не просит)
  const [attempt, setAttempt] = useState(0);
  const [seen, setSeen] = useState("");
  const at = open ? tab : "";
  if (at !== seen) {
    setSeen(at);
    if (at) setAttempt((a) => a + 1);
  }
  const deck = useDeckManifest(keep?.g.template_id ?? null, attempt);
  const [menu, setMenu] = useState(false);
  const presence = useLayerPresence(open);
  // лист доехал и вкладки доиграли свою лесенку (p2-in идёт и в невидимых) — невыбранные вкладки больше не рисуются
  // (`dd-settled`, layers.css: content-visibility); раньше — их лесенка проиграла бы заново при первом показе
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    if (!open) return void setSettled(false);
    const t = window.setTimeout(() => setSettled(true), SETTLE_MS);
    return () => window.clearTimeout(t);
  }, [open]);
  const narrow = useNarrow();
  const morph = sheetMorph(useDeckWrap());

  const pattern = ui.pattern;
  useEffect(() => {
    if (open) return;
    const t = window.setTimeout(() => {
      setMenu(false);
      if (pattern !== null) dispatch({ type: "pattern", n: null });
    }, RESET_MS);
    return () => window.clearTimeout(t);
  }, [open, pattern, dispatch]);

  const close = () => dispatch({ type: "sheet", tab: null });
  // фокус потерялся (на странице ничего не выбрано) — Esc закрывает лист, если поверх него ничего нет: ни меню, ни слоя
  // шаблона, ни раздела шапки, ни просмотра или удаления шаблона (Esc — их)
  const covered = menu || pattern !== null || headerLayerOpen(ui);
  useEffect(() => {
    if (!open || covered) return;
    const onEsc = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || (document.activeElement && document.activeElement !== document.body)) return;
      e.preventDefault();
      dispatch({ type: "sheet", tab: null });
    };
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [open, covered, dispatch]);
  const onTabKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const to = tabStep(tab, e.key);
    if (!to) return;
    e.preventDefault();
    dispatch({ type: "sheet", tab: to });
    e.currentTarget.querySelector<HTMLButtonElement>(`#dd-tab-${to}`)?.focus();
  };

  const g = keep?.g;
  const v = keep?.v;
  const score = g && v ? scoreOf(g, v) : null;
  return (
    <Layer id="p2-lay-d" presence={presence} open={open} top={160} z={5} bare label="Подробнее" onClose={close}>
      {g && v && (
        <TxNarrow.Provider value={narrow}>
        <SheetCtx.Provider value={morph}>
        <section className={cls("dd-sheet", morph.tight && "dd-tight", settled && "dd-settled")} style={{ outline: "none" }} role="region" aria-label={`Подробнее о презентации «${docTitle(g, v)}»`} tabIndex={-1}>
          <div className="dd-fx">
          <div className="dd-top p2-ls" style={lsDelay(120)}>
            <div className="dd-tabs" role="tablist" aria-label="Разделы подробностей" onKeyDown={onTabKey}>
              {SHEET_TABS.map((t) => (
                <button key={t.key} type="button" role="tab" id={`dd-tab-${t.key}`} className={cls("p2-rseg", t.key === tab && "p2-rseg-on")}
                  aria-selected={t.key === tab} aria-controls={`dd-panel-${t.key}`} tabIndex={t.key === tab ? 0 : -1} onClick={() => dispatch({ type: "sheet", tab: t.key })}>
                  {t.label}
                </button>
              ))}
            </div>
            <span style={{ flex: 1, minWidth: 0 }} />
            <div style={{ position: "relative", flex: "none" }}>
              <button type="button" aria-haspopup="menu" aria-expanded={menu} aria-label={`Вариант оформления: ${strategyTitle(v.strategy)}${score === null ? "" : `, оценка ${Math.round(score)}`}`}
                onClick={() => setMenu(!menu)} className="p2-ob dd-var" style={{ height: 40, padding: "0 16px 0 24px" }}>
                <span className="dd-var-n">{strategyTitle(v.strategy)}</span>
                {score !== null && <span className="p2-rsc" title={`Оценка качества ${Math.round(score)} из 100`}>{Math.round(score)}</span>}
                <Icon name="chevron-down" size={18} className={cls("df-chev", menu && "df-chev-up")} />
              </button>
              {menu && (
                <Menu label="Вариант оформления" value={v.strategy} onClose={() => setMenu(false)}
                  items={menuItems(g, strategyTitle).map((x) => ({ key: x.key, n: x.n, name: x.name, score: x.score ?? undefined }))}
                  onPick={(k) => {
                    setActiveStrategy(k);
                    setMenu(false);
                  }} />
              )}
            </div>
            <button type="button" className="p2-rbl" aria-label="Закрыть" title="Закрыть (Esc)" onClick={close} style={{ flex: "none", background: "#FFFFFF" }}><Icon name="x" size={18} /></button>
          </div>

          <div className="p2-ls" style={{ ...lsDelay(200), position: "absolute", inset: 0, pointerEvents: "none" }}>
            <div style={{ pointerEvents: "auto" }}>
              <Panel tab="quality" on={tab === "quality"}><QualityTab g={g} v={v} deck={deck} /></Panel>
              <Panel tab="why" on={tab === "why"}><WhyTab g={g} v={v} deck={deck} active={open && tab === "why"} /></Panel>
              <Panel tab="agent" on={tab === "agent"}><AgentTab g={g} v={v} /></Panel>
              <Panel tab="plan" on={tab === "plan"} style={{ height: 508, display: "flex", flexDirection: "column" }}><PlanTab g={g} v={v} active={open && tab === "plan"} /></Panel>
              <Panel tab="template" on={tab === "template"} style={{ height: 508, display: "flex", flexDirection: "column" }}><TemplateTab deck={deck} /></Panel>
              <Panel tab="files" on={tab === "files"} style={{ height: 508, display: "flex", flexDirection: "column" }}><FilesTab g={g} v={v} deck={deck} /></Panel>
            </div>
          </div>
          </div>
          <PatternLayer deck={deck} />
        </section>
        </SheetCtx.Provider>
        </TxNarrow.Provider>
      )}
    </Layer>
  );
}
