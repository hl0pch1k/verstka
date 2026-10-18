// «Брендбук» в заголовке шага 01 (boards/V2.dc.html версии 105, модуль ds, `.bb-fg`): тихая кнопка рядом с шаблоном →
// меню как «Из файла» (выровнено по правому краю кнопки) → разбор в теле шага (BrandAnalysis) → карточка с палитрой
// (BrandCard), она открывает слой «Брендбук». Пока разбор идёт — строка «Разбираю брендбук…». Каждое из трёх
// проявляется (p2-in), меню — 240 мс, гаснет 160 мс. Figma: пункт меню раскрывает в том же меню поле ссылки.
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { useApp } from "../../store";
import { cls } from "../kit/cls";
import { BRAND_ACCEPT, BRAND_ITEMS, BRAND_SAMPLE, brandMeta, brandName, brandPalette, brandTight, figmaUrlOk, type BrandPick } from "./dataRules";
import { useDeckWrap } from "../deck/useDeckFit";
import { DsIcon, DsSpin, type DsIconName } from "./dsKit";

const ITEM_ICON: Record<BrandPick, DsIconName> = { pdf: "file", json: "json", dir: "folder", zip: "folder", figma: "frame" };
/** Пример брендбука — GET /api/examples/brandbook-vk-cloud (манифест: файл брендбука ссылкой). */
export const BRAND_EXAMPLE = "brandbook-vk-cloud";

/** Плитка палитры 80 × 45 (карточка брендбука) — шесть цветов полосами. */
export function PaletteTile({ hexes, className }: { hexes: string[]; className?: string }) {
  return (
    <span className={cls("bb-tile", className)} aria-hidden="true">
      {hexes.map((h, i) => <span key={`${h}-${i}`} style={{ background: h }} />)}
    </span>
  );
}

/** Карточка брендбука — пара карточке шаблона: плитка палитры и две строки; клик — слой «Брендбук». */
export function BrandCard() {
  const { data, dispatch, ui } = useApp();
  const tight = brandTight(useDeckWrap());
  const b = data.brand;
  // подпись в тесной колоде сжимается до нуля от своей ширины (--ctw — замер): ход идёт той же кривой до конца. Мерятся
  // строки (их scrollWidth — ширина текста), а не сама подпись: под помощником она сжата до нуля, и замер дал бы 0 —
  // подпись не вернулась бы после него. Ноль не записывается; замер — и после хода помощника
  const ct = useRef<HTMLSpanElement>(null);
  const label = b.spec ? `${brandName(b.spec, b.file)}|${brandMeta(b.spec)}` : "";
  useLayoutEffect(() => {
    const el = ct.current;
    if (!el) return;
    let alive = true;
    const measure = () => {
      if (!alive) return;
      const w = Math.ceil(Math.max(0, ...Array.from(el.children, (c) => c.scrollWidth)));
      if (w > 0) el.style.setProperty("--ctw", `${w}px`);
    };
    measure();
    void document.fonts?.ready.then(measure);
    return () => {
      alive = false;
    };
  }, [label, tight, ui.helper]);
  if (!b.spec) return null;
  return (
    <button type="button" className={cls("bb-chip p2-in", tight && "bb-chip-t")} onClick={() => dispatch({ type: "set", patch: { brandLayer: true } })}
      aria-haspopup="dialog" aria-controls="bb-lay" title={`Брендбук ${brandName(b.spec, b.file)} · ${brandMeta(b.spec)} — палитра, шрифты, правила, расхождения с шаблоном`}>
      <PaletteTile hexes={brandPalette(b.spec)} />
      <span ref={ct} className="bb-ct">
        <span className="bb-cn">Брендбук {brandName(b.spec, b.file)}</span>
        <span className="bb-cm">{brandMeta(b.spec)}</span>
      </span>
    </button>
  );
}

/** Кнопка, строка хода или карточка — и меню. `menu` — открыто ли меню (одно на оба вида заголовка шага: раскрытый и
 *  свёрнутый); `off` — почему выбрать брендбук сейчас нельзя (разбирается свой шаблон). */
export function BrandHead({ menu, setMenu, off }: { menu: boolean; setMenu(on: boolean): void; off: string | null }) {
  const { data, dispatch } = useApp();
  const b = data.brand;
  const busy = b.phase === "run" || b.phase === "done" || b.phase === "out";
  const has = b.phase === "on" && !!b.spec;
  const btn = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [figma, setFigma] = useState(false);
  const [link, setLink] = useState("");
  const [linkBad, setLinkBad] = useState(false);
  useEffect(() => {
    if (!menu) {
      setFigma(false);
      setLinkBad(false);
    }
  }, [menu]);
  // щелчок мимо меню (по ленте под ним) — меню закрывается
  useEffect(() => {
    if (!menu) return;
    const down = (e: PointerEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setMenu(false);
    };
    document.addEventListener("pointerdown", down, true);
    return () => document.removeEventListener("pointerdown", down, true);
  }, [menu, setMenu]);
  // открылось — фокус на первый пункт (как «Из файла»)
  useEffect(() => {
    if (!menu) return;
    const r = requestAnimationFrame(() => box.current?.querySelector<HTMLElement>("#bb-menu .tx-mi, #bb-menu input")?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(r);
  }, [menu, figma]);

  const toggle = () => {
    if (off) return;
    // меню у кнопки шага 01: шаг раскрывается (плита 02 уезжает вниз), меню — над лентой
    if (!menu) dispatch({ type: "open", step: "tpl" });
    setMenu(!menu);
  };
  const pick = (k: BrandPick) => {
    if (k === "figma") return setFigma(true);
    // папка целиком: своё окно выбора (webkitdirectory) — файлы уходят с путями в папке (API: `files`)
    if (k === "dir") {
      setMenu(false);
      folder.current?.click();
      return;
    }
    const el = input.current;
    if (!el) return;
    el.accept = BRAND_ACCEPT[k];
    setMenu(false);
    el.click();
  };
  const sample = () => {
    setMenu(false);
    btn.current?.focus({ preventScroll: true });
    void data.loadExample(BRAND_EXAMPLE, "brand");
  };
  const sendLink = () => {
    if (!figmaUrlOk(link)) return setLinkBad(true);
    setMenu(false);
    data.startBrand({ figmaUrl: link });
    setLink("");
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      if (figma) return setFigma(false);
      setMenu(false);
      btn.current?.focus({ preventScroll: true });
      return;
    }
    if (figma || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
    e.preventDefault();
    const list = Array.from(box.current?.querySelectorAll<HTMLButtonElement>("#bb-menu .tx-mi") ?? []);
    const i = list.indexOf(document.activeElement as HTMLButtonElement);
    list[(i + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length]?.focus({ preventScroll: true });
  };

  return (
    <div ref={box} className="bb-fg">
      {!busy && !has && (
        <button ref={btn} type="button" className="p2-gb bb-btn" data-hpm="" onClick={toggle} aria-haspopup="menu" aria-expanded={menu} aria-controls="bb-menu"
          aria-disabled={off ? true : undefined} title={off ?? "Брендбук или дизайн-система: PDF, токены, папка, Figma"}
          style={off ? { opacity: 0.32, cursor: "default" } : undefined}>
          {/* открыт помощник — кнопка круглая (create.css `.hp-nar .bb-btn`): подпись гаснет, книжка встаёт в середину круга */}
          <span className="bb-bi" data-hpm=""><DsIcon name="book" size={18} /></span>
          <span className="hp-wo">Брендбук</span>
        </button>
      )}
      {busy && (
        <span className="bb-busy p2-in" role="status" title={b.file}><DsSpin /><span>Разбираю брендбук…</span></span>
      )}
      {has && <BrandCard />}
      {/* поле ссылки Figma — не пункт меню: пока оно открыто, плита — группа с формой, а не меню */}
      <div id="bb-menu" role={figma ? "group" : "menu"} aria-label={figma ? "Ссылка на файл Figma" : "Выберите брендбук"} aria-hidden={!menu || undefined}
        className={cls("tx-menu bb-menu", menu && "tx-menu-on")} onKeyDown={onKey}>
        {!figma ? (
          <>
            <p className="tx-mcap">Брендбук или дизайн-система</p>
            {BRAND_ITEMS.map((it) => (
              <button key={it.key} type="button" role="menuitem" className="tx-mi" tabIndex={menu ? 0 : -1} onClick={() => pick(it.key)}>
                <span className="tx-mic" aria-hidden="true"><DsIcon name={ITEM_ICON[it.key]} size={16} /></span>
                <span className="tx-mt"><span className="tx-mn">{it.name}</span><span className="tx-mm">{it.meta}</span></span>
              </button>
            ))}
            <span className="tx-mdiv" role="separator" />
            <button type="button" role="menuitem" className="tx-mi" tabIndex={menu ? 0 : -1} onClick={sample} disabled={data.exampleBusy}>
              <span className="tx-mic" aria-hidden="true">{data.exampleBusy ? <DsSpin /> : <DsIcon name="book" size={16} />}</span>
              <span className="tx-mt"><span className="tx-mn">{BRAND_SAMPLE.name}</span><span className="tx-mm">{BRAND_SAMPLE.meta}</span></span>
            </button>
          </>
        ) : (
          <form className="bb-fig p2-in" onSubmit={(e) => { e.preventDefault(); sendLink(); }}>
            <label className="tx-mcap" htmlFor="bb-figma">Ссылка на файл Figma</label>
            <input id="bb-figma" className={cls("bb-figin", linkBad && "bb-figbad")} type="url" inputMode="url" placeholder="https://www.figma.com/design/…"
              value={link} onChange={(e) => { setLink(e.target.value); setLinkBad(false); }} aria-invalid={linkBad || undefined} aria-describedby="bb-fighint" />
            <p id="bb-fighint" className={cls("bb-fighint", linkBad && "bb-figbadt")} aria-live="polite">{linkBad ? "Это не ссылка на файл Figma" : "Стили и переменные файла — по ключу сервера"}</p>
            <div className="bb-figrow">
              <button type="button" className="p2-gb" onClick={() => setFigma(false)}>Назад</button>
              <button type="submit" className="p2-ob" style={{ height: 40 }} disabled={!link.trim()}>Разобрать</button>
            </div>
          </form>
        )}
      </div>
      <input ref={input} type="file" hidden tabIndex={-1} aria-hidden="true"
        onChange={(e) => {
          const f = e.currentTarget.files?.[0];
          e.currentTarget.value = "";
          if (f) data.startBrand(f);
        }} />
      <input ref={folder} type="file" hidden tabIndex={-1} aria-hidden="true" multiple
        {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
        onChange={(e) => {
          const fs = Array.from(e.currentTarget.files ?? []);
          e.currentTarget.value = "";
          if (fs.length) data.startBrand(fs);
        }} />
    </div>
  );
}
