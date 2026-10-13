// Сцена `ra-stage` (R-aside): превью текущего слайда варианта. Смена слайда или варианта — перекрёстное затухание:
// новое превью сперва декодируется (медленное ждём не дольше 800 мс), встаёт поверх прежнего и проявляется 240 мс
// (`ra-xf`), прежнее под ним снимается, когда новое проявилось. Пропорции — шаблона (по умолчанию 16:9); высота сцены
// не больше, чем у 16:9 шириной 720, — рабочая область держит свою высоту.
import { useEffect, useState } from "react";
import { decodeImage } from "../../lib/motion";
import { cls } from "../kit/cls";

/** Сколько ждать декодирования нового превью, прежде чем показать его как есть. */
const DECODE_WAIT = 800;
/** Прежнее превью снимается, когда новое проявилось (ra-xf 240 мс). */
const UNDER_MS = 280;

interface Shot { src: string | null; alt: string }

export function Stage({ src, alt, aspect }: { src: string | null; alt: string; aspect: number }) {
  const [st, setSt] = useState<{ top: Shot; under: Shot | null; k: number }>({ top: { src, alt }, under: null, k: 0 });
  useEffect(() => {
    if (src === st.top.src) {
      if (alt !== st.top.alt) setSt((s) => ({ ...s, top: { ...s.top, alt } }));
      return;
    }
    let done = false;
    const swap = () => {
      if (done) return;
      done = true;
      setSt((s) => (s.top.src === src ? s : { top: { src, alt }, under: s.top.src ? s.top : null, k: s.k + 1 }));
    };
    if (!src) {
      swap();
      return;
    }
    const t = window.setTimeout(swap, DECODE_WAIT);
    decodeImage(src).then(swap, swap);
    return () => {
      done = true;
      window.clearTimeout(t);
    };
    // the shown shot is read from the render that changed `src`: a newer change cancels the older one's swap
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, alt]);
  useEffect(() => {
    if (!st.under) return;
    const t = window.setTimeout(() => setSt((s) => ({ ...s, under: null })), UNDER_MS);
    return () => window.clearTimeout(t);
  }, [st.k, st.under]);

  const ar = aspect > 0 ? aspect : 16 / 9;
  return (
    <div className="p2-in" style={{ display: "flex", justifyContent: "center", marginTop: 16, animationDelay: "240ms" }}>
      {/* выше 16:9 (например, 4:3) — уже: высота сцены та же, что у 16:9 шириной 720 */}
      <div className="ra-stage" style={{ aspectRatio: String(ar), maxWidth: ar < 16 / 9 - 0.01 ? `${Math.round(405 * ar)}px` : undefined }}>
        {st.under?.src && <img className="ra-shot" src={st.under.src} alt="" aria-hidden="true" />}
        {st.top.src && <img key={st.k} className={cls("ra-shot", st.k > 0 && "ra-xf")} src={st.top.src} alt={st.top.alt} />}
      </div>
    </div>
  );
}
