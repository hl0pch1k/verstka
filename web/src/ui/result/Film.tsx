// Лента миниатюр под сценой (R-aside `p2-film` / `p2-th`): все слайды варианта, текущий — в синей обводке. Лента
// прокручивается вбок сама и держит текущий слайд в виду (прокрутка самой ленты, не страницы и не колоды).
import { useEffect, useRef } from "react";
import { prefersReducedMotion } from "../../lib/motion";
import { withRev } from "../../lib/rev";
import { cls } from "../kit/cls";

export function Film({ slides, rev, n, headline, onPick }: {
  slides: string[];
  rev: string;
  /** Текущий слайд, с 1. */
  n: number;
  headline(n: number): string;
  onPick(n: number): void;
}) {
  const film = useRef<HTMLDivElement>(null);
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
  }, [n, slides.length]);

  return (
    <div ref={film} className="p2-film p2-in" style={{ position: "relative", margin: "8px -4px 0", animationDelay: "280ms" }}>
      {slides.map((url, i) => {
        const on = i + 1 === n;
        const h = headline(i + 1);
        return (
          <button key={i} type="button" className={cls("p2-th", on && "p2-th-on")} aria-pressed={on} onClick={() => onPick(i + 1)}>
            <img src={withRev(url, rev)} alt={h ? `Слайд ${i + 1}: ${h}` : `Слайд ${i + 1}`} loading="lazy" decoding="async"
              style={{ display: "block", width: 112, height: 63, aspectRatio: "16 / 9", objectFit: "cover", borderRadius: 12, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" }} />
          </button>
        );
      })}
    </div>
  );
}
