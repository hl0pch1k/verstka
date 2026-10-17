// «На весь экран» (boards/R-lightbox, V2 `#rt-lay-lb`): тёмная плита поднимается на всю колоду (translateY 0) и уезжает
// вниз непрозрачной, с кадром. Шапка «3 / 12 · заголовок» и ✕, кадр с текущим слайдом результата (проявляется из
// scale .98, rt-lsp 200 мс), стрелки по краям (на первом и последнем слайде их нет) и подсказка клавиш. Листание — тот же
// текущий слайд, что у результата (`selectedSlide`): закрыли — результат стоит на последнем показанном. Превью — та же
// стопка, что у сцены (Shots): новый слайд проявляется, когда его картинка декодирована. Клавиши ←/→, Home/End и Esc —
// свои, пока поверх просмотра ничего не открыто; клавиши результата в это время молчат (ResultPlate `layered`).
import { useCallback, useEffect, useRef, type CSSProperties, type MouseEvent } from "react";
import { useApp } from "../../store";
import type { Variant } from "../../types";
import { Icon } from "../kit/Icon";
import { cls } from "../kit/cls";
import { slideHeadline, slideSrc, slidesOf } from "../result/resultView";
import { Shots } from "../result/Stage";
import { useStack } from "../shell/tier";
import { Layer, lsDelay } from "./Layer";
import { lbFrameWidth, lbKey, lbView } from "./lightboxView";

/** Поля, меню и прочее, что держит клавиши себе: просмотр их не листает. */
const OWN_KEYS = "input, textarea, select, [contenteditable='true'], [role='menu'], [role='slider']";

export function Lightbox() {
  const { ui, dispatch, generation, activeVariant, selectedSlide, setSelectedSlide, templates } = useApp();
  const g = ui.screen === "result" ? generation : null;
  const v = g?.variants.length ? (activeVariant && g.variants.includes(activeVariant) ? activeVariant : g.variants[0]) : null;
  const total = slidesOf(v);
  const open = ui.lightbox && !!v && total > 0;
  const n = Math.min(Math.max(1, selectedSlide), Math.max(1, total));
  const tpl = g ? templates.find((t) => t.template_id === g.template_id) : undefined;
  const aspect = tpl?.aspect && tpl.aspect > 0 ? tpl.aspect : 16 / 9;

  const close = useCallback(() => dispatch({ type: "set", patch: { lightbox: false } }), [dispatch]);
  // показывать нечего (другая презентация, слайдов нет) — флаг снимается, иначе просмотр вернулся бы сам
  useEffect(() => {
    if (ui.lightbox && !open) close();
  }, [ui.lightbox, open, close]);

  // показанный слайд держится, пока плита уезжает
  const last = useRef<{ v: Variant; n: number; total: number; aspect: number } | null>(null);
  if (open && v) last.current = { v, n, total, aspect };
  const view = last.current;

  // клавиши просмотра — пока поверх него не открыт раздел или диалог
  const keys = open && !ui.sect && !ui.tplPreview && !ui.tplDelete;
  useEffect(() => {
    if (!keys) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      const t = e.target as HTMLElement | null;
      if (t && typeof t.closest === "function" && t.closest(OWN_KEYS)) return;
      const k = lbKey(e.key, n, total);
      if (k === null) return;
      e.preventDefault();
      if (k === "close") close();
      else if (k !== n) setSelectedSlide(k);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [keys, n, total, close, setSelectedSlide]);

  // слой монтируется при открытии: сначала внизу (закрытым), со следующего кадра въезжает; после закрытия уезжает 520 мс
  // и размонтируется (Layer, kit/usePresence)
  return (
    <Layer id="rt-lay-lb" open={open} top={0} z={5} label="Просмотр на весь экран" role="dialog" tone="dark" onClose={close}
      plateStyle={{ display: "flex", flexDirection: "column" }}>
      {view && <Frame view={view} live={open} onClose={close} onPage={setSelectedSlide} />}
    </Layer>
  );
}

function Frame({ view, live, onClose, onPage }: {
  view: { v: Variant; n: number; total: number; aspect: number };
  /** Просмотр открыт (уезжающий не листается). */
  live: boolean;
  onClose(): void;
  onPage(n: number): void;
}) {
  const lb = lbView(view.n, view.total, slideHeadline(view.v, view.n));
  const src = slideSrc(view.v, view.n);
  // колода стопкой (окно уже 1280): кадр вписывается в место по ширине и высоте — пропорция шаблона для CSS (layers.css)
  const fit = useStack() ? ({ "--lb-ar": String(view.aspect) } as CSSProperties) : null;
  // стрелка, дошедшая до края, прячется — фокус с неё уходит на плиту просмотра, а не в никуда
  const page = (k: number) => (e: MouseEvent<HTMLButtonElement>) => {
    if (!live) return;
    if (k <= 1 || k >= view.total) e.currentTarget.closest<HTMLElement>("section")?.focus({ preventScroll: true });
    onPage(k);
  };
  return (
    <>
      <div className="p2-ls lb-hd" style={{ ...lsDelay(120), display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, height: 40, flex: "none" }}>
        <h2 aria-live="polite" style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0, margin: 0, whiteSpace: "nowrap" }}>
          <span style={{ flex: "none", fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: "28px", letterSpacing: "-0.02em", color: "#FFFFFF" }}>
            {lb.count}
          </span>
          {lb.title && (
            <span className="lb-t" style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", fontSize: 15, fontWeight: 600, lineHeight: "24px", color: "rgba(255,255,255,.64)" }}>
              · {lb.title}
            </span>
          )}
        </h2>
        <button type="button" className="p2-rb" onClick={onClose} aria-label="Закрыть" title="Закрыть (Esc)">
          <Icon name="x" size={18} />
        </button>
      </div>

      <div className="lb-stage" style={{ position: "relative", flex: 1, minHeight: 0, display: "flex", alignItems: "center", justifyContent: "center", marginTop: 16 }}>
        <button type="button" className={cls("p2-rb lb-arrow", !lb.prev && "lb-hide")} onClick={page(view.n - 1)} aria-label="Предыдущий слайд (←)"
          title="Предыдущий слайд (←)" style={{ left: 0 }}>
          <Icon name="chevron-left" size={20} />
        </button>
        <div className="lb-frame rt-lsp"
          style={{ ...lsDelay(200), position: "relative", flex: "none", width: lbFrameWidth(view.aspect), aspectRatio: String(view.aspect), borderRadius: 24, overflow: "hidden", background: "rgba(255,255,255,.06)", boxShadow: "0 0 0 1px rgba(255,255,255,.1)", ...fit }}>
          <Shots src={src} alt={lb.title ? `Слайд ${view.n}: ${lb.title}` : `Слайд ${view.n}`} />
        </div>
        <button type="button" className={cls("p2-rb lb-arrow", !lb.next && "lb-hide")} onClick={page(view.n + 1)} aria-label="Следующий слайд (→)"
          title="Следующий слайд (→)" style={{ right: 0 }}>
          <Icon name="chevron-right" size={20} />
        </button>
      </div>

      <p className="p2-ls lb-keys" style={{ ...lsDelay(280), display: "flex", alignItems: "center", justifyContent: "center", gap: 8, height: 24, margin: "16px 0 0", flex: "none", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "rgba(255,255,255,.48)" }}>
        <kbd className="lb-k" aria-label="Стрелка влево">←</kbd>
        <kbd className="lb-k" aria-label="Стрелка вправо">→</kbd>
        <span>листать</span>
        <span aria-hidden="true" style={{ margin: "0 4px" }}>·</span>
        <kbd className="lb-k">Esc</kbd>
        <span>закрыть</span>
      </p>
    </>
  );
}
