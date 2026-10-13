// Лента миниатюр под сценой (R-aside `p2-film` / `p2-th`): все слайды варианта, текущий — в синей обводке. Лента
// прокручивается вбок сама и держит текущий слайд в виду (прокрутка самой ленты, не страницы и не колоды). Смена
// варианта: показанная миниатюра держит прежнюю картинку, пока новая не декодирована, — серых провалов нет. В режиме
// «Замечания» (R-remarks) на миниатюре — число открытых замечаний слайда цвета худшего (`rk-tb`, всплывает), у слайда,
// который исправляет агент, — дуга загрузки (`rf-tsp`); режим выключается — бейджи гаснут вместе с панелью.
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { decodeImage, isDecoded, prefersReducedMotion } from "../../lib/motion";
import { cls } from "../kit/cls";
import { countText, type Tone } from "./remarks";
import { slideSrc } from "./resultView";
import type { Variant } from "../../types";

/** Отметки режима «Замечания» на ленте: бейджи по слайдам, гаснут ли они, какой слайд исправляет агент. */
export interface FilmMarks { badges: Map<number, { count: number; tone: Tone }>; out: boolean; spin: number | null }

export function Film({ film, variant, n, headline, onPick, marks }: {
  /** Сама лента: по ней смена варианта узнаёт, какие миниатюры уже показаны (`loadedThumbs`). */
  film: RefObject<HTMLDivElement>;
  variant: Variant;
  /** Текущий слайд, с 1. */
  n: number;
  headline(n: number): string;
  onPick(n: number): void;
  marks?: FilmMarks | null;
}) {
  const count = variant.slides.length;
  useEffect(() => {
    const box = film.current;
    const th = box?.children[n - 1] as HTMLElement | undefined;
    if (!box || !th) return;
    // обводка (4 px) и тень остаются внутри видимой части
    const pad = 8;
    const left = th.offsetLeft; // от края ленты: она — offsetParent (position: relative)
    const right = left + th.offsetWidth;
    let to: number | null = null;
    if (left - pad < box.scrollLeft) to = left - pad;
    else if (right + pad > box.scrollLeft + box.clientWidth) to = right + pad - box.clientWidth;
    if (to !== null) box.scrollTo({ left: Math.max(0, to), behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }, [film, n, count]);

  return (
    <div ref={film} className="p2-film p2-in" style={{ position: "relative", margin: "8px -4px 0", animationDelay: "280ms" }}>
      {variant.slides.map((_, i) => {
        const h = headline(i + 1);
        const spin = marks?.spin === i + 1;
        const badge = marks && !spin ? marks.badges.get(i + 1) ?? null : null;
        const said = spin ? " · агент исправляет" : badge ? ` · ${countText(badge.count)}${badge.tone === "err" ? ", есть ошибка" : ""}` : "";
        return (
          <Thumb key={i} src={slideSrc(variant, i + 1) ?? ""} alt={`${h ? `Слайд ${i + 1}: ${h}` : `Слайд ${i + 1}`}${said}`} on={i + 1 === n}
            onPick={() => onPick(i + 1)} badge={badge} out={!!marks?.out} spin={spin} />
        );
      })}
    </div>
  );
}

/** Миниатюры показанных картинок, которые уже загружены: их новые картинки декодируются до смены варианта. */
export function loadedThumbs(film: HTMLElement | null): number[] {
  if (!film) return [];
  return [...film.querySelectorAll("img")].flatMap((img, i) => (img.complete && img.naturalWidth > 0 ? [i + 1] : []));
}

function Thumb({ src, alt, on, onPick, badge, out, spin }: {
  src: string;
  alt: string;
  on: boolean;
  onPick(): void;
  badge?: { count: number; tone: Tone } | null;
  out?: boolean;
  spin?: boolean;
}) {
  const img = useRef<HTMLImageElement>(null);
  const [shown, setShown] = useState(src);
  useLayoutEffect(() => {
    if (src === shown) return;
    const el = img.current;
    // не показанная (за краем ленты, ещё не загружена) или декодированная заранее — сразу
    if (!el || !(el.complete && el.naturalWidth > 0) || isDecoded(src)) return setShown(src);
    let off = false;
    const take = () => {
      if (!off) setShown(src);
    };
    decodeImage(src).then(take, take);
    return () => {
      off = true;
    };
  }, [src, shown]);
  return (
    <button type="button" className={cls("p2-th", on && "p2-th-on")} aria-pressed={on} onClick={onPick}>
      <img ref={img} src={shown} alt={alt} loading="lazy" decoding="async"
        style={{ display: "block", width: 112, height: 63, objectFit: "contain", borderRadius: 12, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" }} />
      {badge && <span className={cls("rk-tb p2-pop", `rk-${badge.tone}`, out && "rm-out")} aria-hidden="true" style={{ animationDelay: "240ms" }}>{badge.count}</span>}
      {spin && (
        <span className="rf-tsp p2-pop" aria-hidden="true">
          <svg className="gh-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true">
            <circle cx="12" cy="12" r="8" stroke="rgba(37,99,235,.14)" />
            <path d="M12 4a8 8 0 0 1 8 8" stroke="#2563EB" />
          </svg>
        </span>
      )}
    </button>
  );
}
