// Слой колоды — общий для всех слоёв «Слоёв» (разделы «Шаблоны» и «Мои презентации», «Слайды шаблона», лист
// «Подробнее», «Текст презентации», просмотр на весь экран). Разметка — boards/V2.dc.html (`#p2-lay-t`, `#tp-lay-p`,
// `#rt-lay-text`): место `.p2-slot.p2-lay` выезжает снизу (translateY 880 → top) за 520 мс и уезжает обратно
// непрозрачным, со своим содержимым — оно держится смонтированным, пока идёт уход (usePresence), и размонтируется, когда
// слой уехал. Лесенка внутри — элементы с классом `p2-ls` и задержкой `--d` (style={{ "--d": "160ms" }}): проявляются
// после въезда; на следующем открытии слой монтируется заново — закрытым, и лесенка идёт с начала.
// Помощник сужает колоду — содержимое слоя (открытого и уходящего) перестраивается вместе с ней каждый кадр (сетки с тем
// же числом дорожек, стопки многострочного текста — kit/Tx; V2 версии 100). Закрытого слоя в DOM нет: у V2 закрытые слои
// стояли в DOM, и ход помощника их не трогал (ширина колоды в покое и `--lgone` через 520 мс после ухода), а здесь в тот
// же момент слой размонтируется — отдельной заморозки закрытых слоёв нет. Заморожены только невыбранные вкладки листа
// «Подробнее» (layers.css, `dd-pw p2-off`).
import { useEffect, useRef, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { cls } from "../kit/cls";
import type { Presence } from "../kit/presence";
import { usePresence } from "../kit/usePresence";

/** Сколько слой едет (и сколько держится его содержимое после закрытия). */
export const LAYER_MS = 520;
/** Где ждёт закрытый слой: под нижним краем колоды. */
const OFF_Y = 880;

/** Плита слоя: голубая (разделы, «Слайды шаблона», «Текст») или тёмная (просмотр на весь экран). */
const TONE: Record<"light" | "dark", CSSProperties> = {
  light: { background: "#E9F1FF", color: "#0B1220", boxShadow: "0 -24px 48px -24px rgba(11,18,32,.4)" },
  dark: { background: "#0B1220", color: "#FFFFFF" },
};

export interface LayerProps {
  open: boolean;
  /** translateY открытого слоя, px (разделы — 120, «Подробнее» и «Текст» — 160, весь экран — 0). */
  top: number;
  /** z-index места: разделы 6/7, «Слайды шаблона» 6/8 (уходящий вместе с контекстом — под новым разделом). */
  z: number;
  /** Высота места, px: 812 (вся колода) или 692 (раздел под полосой 120). */
  height?: number;
  /** Имя области для чтения с экрана (aria-label плиты). */
  label: string;
  children: ReactNode;
  /** Esc внутри слоя закрывает его. */
  onClose?(): void;
  id?: string;
  /** region — раздел, dialog — слой поверх работы (aria-modal). */
  role?: "region" | "dialog";
  tone?: "light" | "dark";
  /** Своя плита у содержимого (лист «Подробнее»): слой даёт только место; фокус при открытии — в первый элемент
   *  содержимого, если у него есть tabIndex. */
  bare?: boolean;
  /** Дополнение к стилю плиты (например, flex-колонка). */
  plateStyle?: CSSProperties;
  /** Присутствие слоя, уже заведённое снаружи (`useLayerPresence`: по нему считается содержимое, пока слой на экране) —
   *  своё слой тогда не заводит. */
  presence?: Presence;
}

export function Layer(props: LayerProps) {
  return props.presence ? <LayerSlot {...props} p={props.presence} /> : <OwnLayer {...props} />;
}

/** Слой со своим присутствием (уход держит содержимое LAYER_MS). */
function OwnLayer(props: LayerProps) {
  return <LayerSlot {...props} p={usePresence(props.open, LAYER_MS)} />;
}

function LayerSlot({ open, top, z, height = 812, label, children, onClose, id, role = "region", tone = "light", bare, plateStyle, p }: LayerProps & { p: Presence }) {
  const plate = useRef<HTMLElement>(null);
  const slot = useRef<HTMLDivElement>(null);
  // фокус — в слой, когда он открылся; при закрытии — туда, откуда его открыли (если фокус был в слое)
  useEffect(() => {
    if (!p.shown) return;
    const back = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const el = slot.current;
    // своя плита у содержимого (bare): фокус — в неё, если она его принимает (tabIndex)
    const own = el?.firstElementChild instanceof HTMLElement && el.firstElementChild.hasAttribute("tabindex") ? el.firstElementChild : null;
    if (el && !el.contains(document.activeElement)) (plate.current ?? own ?? el).focus({ preventScroll: true });
    return () => {
      const now = document.activeElement;
      if (back && back.isConnected && (!now || now === document.body || el?.contains(now))) back.focus({ preventScroll: true });
    };
  }, [p.shown]);
  if (!p.mounted) return null;
  // закрытие — в том же кадре, что и сам переход (колода едет в этом же рендере); открытие — со следующего кадра
  const on = open && p.shown;
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Escape" || !onClose || !on || e.defaultPrevented) return;
    e.preventDefault();
    e.stopPropagation();
    onClose();
  };
  return (
    <div ref={slot} id={id} className={cls("p2-slot p2-lay", !on && "p2-lay-off")} onKeyDown={onKey} aria-hidden={on ? undefined : true}
      style={{ position: "absolute", left: 0, right: 0, top: 0, height, zIndex: z, transform: `translateY(${on ? top : OFF_Y}px)` }}>
      {bare ? children : (
        <section ref={plate} className={cls("p2-plate", tone === "dark" && "p2-dark")} role={role} aria-modal={role === "dialog" ? true : undefined}
          aria-label={label} tabIndex={-1}
          style={{ position: "relative", height: "100%", padding: "40px 48px", borderRadius: 40, outline: "none", ...TONE[tone], ...plateStyle }}>
          {children}
        </section>
      )}
    </div>
  );
}

/** Задержка лесенки `p2-ls` (CSS-переменная `--d`). */
export const lsDelay = (ms: number) => ({ "--d": `${ms}ms` }) as CSSProperties;

/** Присутствие слоя (смонтирован, пока открыт и пока доигрывает уход) — для того, что считается только на экране;
 *  отдаётся слою (`<Layer presence>`). */
export function useLayerPresence(open: boolean): Presence {
  return usePresence(open, LAYER_MS);
}
