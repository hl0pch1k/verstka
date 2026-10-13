// Сцена `ra-stage` (R-aside): превью текущего слайда варианта. Каждое превью — свой слой со своим <img> (stageLayers):
// новое ложится сверху невидимым и ждёт, пока его картинка загрузится и декодируется, затем проявляется 240 мс (`ra-xf`)
// и, проявившись, снимает слои под собой. Медленная картинка не оставляет серую рамку — до её готовности виден прежний
// слайд; быстрое листание не обрывает проявляющийся слой — это тот же элемент, он доигрывает своё затухание.
// Пропорции — шаблона (по умолчанию 16:9); высота сцены не больше, чем у 16:9 шириной 720, — рабочая область держит
// свою высоту. Поверх слоёв — то, что приходит детьми: зоны изображений (R-picture), разметка замечаний (R-remarks) и
// эскиз исправления (R-fixing); слои под ними живут своей жизнью.
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { isDecoded, prefersReducedMotion } from "../../lib/motion";
import { cls } from "../kit/cls";
import { pushShot, shotDone, shotReady, type Shot } from "./stageLayers";

export function Stage({ src, alt, aspect, children }: { src: string | null; alt: string; aspect: number; children?: ReactNode }) {
  const ar = aspect > 0 ? aspect : 16 / 9;
  return (
    <div className="p2-in" style={{ display: "flex", justifyContent: "center", marginTop: 16, animationDelay: "240ms" }}>
      {/* выше 16:9 (например, 4:3) — уже: высота сцены та же, что у 16:9 шириной 720; помощник сужает колоду — сцена не
          выше свободного места (helper.css: `--ra-ar` — пропорции шаблона) */}
      <div className="ra-stage" style={{ aspectRatio: String(ar), "--ra-ar": ar.toFixed(4) } as CSSProperties}>
        <Shots src={src} alt={alt} />
        {children}
      </div>
    </div>
  );
}

/** Стопка превью сцены (stageLayers): новое ложится сверху невидимым, проявляется, когда декодировано, и снимает слои
 *  под собой. Её же показывает просмотр на весь экран. Рамка — у того, кто её ставит (`position: relative`). */
export function Shots({ src, alt }: { src: string | null; alt: string }) {
  const seq = useRef(0);
  const [layers, setLayers] = useState<Shot[]>(() => pushShot([], src, alt, ++seq.current));
  useEffect(() => {
    const id = ++seq.current;
    setLayers((ls) => pushShot(ls, src, alt, id));
  }, [src, alt]);
  const ready = useCallback((id: number, instant: boolean) => setLayers((ls) => shotReady(ls, id, instant, prefersReducedMotion())), []);
  const done = useCallback((id: number) => setLayers((ls) => shotDone(ls, id)), []);
  const top = layers.length - 1;
  return <>{layers.map((l, i) => <ShotImg key={l.id} shot={l} top={i === top} onReady={ready} onDone={done} />)}</>;
}

/** Слой сцены. Пока картинка не готова — невидим (`ra-wait`); готова — проявляется (`ra-xf`); проявился — просто стоит.
 *  Подпись — только у верхнего слоя, нижние скрыты от чтения с экрана. */
function ShotImg({ shot, top, onReady, onDone }: {
  shot: Shot;
  top: boolean;
  onReady(id: number, instant: boolean): void;
  onDone(id: number): void;
}) {
  const ref = useRef<HTMLImageElement>(null);
  const { id, src, ready } = shot;
  useLayoutEffect(() => {
    const img = ref.current;
    if (ready || !img) return;
    // декодирована заранее (сосед, тот же слайд другого варианта) — встаёт в этом же кадре
    if (img.complete && img.naturalWidth > 0 && isDecoded(src)) return onReady(id, true);
    let off = false;
    // decode() ждёт загрузки; неудача (битая картинка) тоже показывается — сцена не застревает на прежнем слайде
    const go = () => {
      if (!off) onReady(id, false);
    };
    img.decode().then(go, go);
    return () => {
      off = true;
    };
  }, [id, src, ready, onReady]);
  return (
    <img ref={ref} className={cls("ra-shot", !shot.ready && "ra-wait", shot.ready && !shot.done && "ra-xf")} src={src}
      alt={top ? shot.alt : ""} aria-hidden={top ? undefined : true}
      onAnimationEnd={(e) => {
        if (e.target === e.currentTarget && e.animationName === "ra-xf") onDone(id);
      }} />
  );
}
