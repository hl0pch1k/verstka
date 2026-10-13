// «Изображение на слайде» (R-picture, V2 модуль `rt`): на сцене — невидимая зона над каждой картинкой (или местом под
// неё), при наведении проступает рамка, клик выбирает картинку: рамка встаёт (`rt-fr-on`), колонка сменяется своей же
// колонкой, прокрученной к карточке «Изображение» (проявление 360 мс, карточка поднимается p2-stag). В карточке — что
// на картинке и какая модель её сделала; «Заменить» раскрывает поле пожелания и «Сгенерировать», «Убрать» оставляет
// место под своё фото, «Вернуть» отменяет последнюю замену. Ход и неудача — строкой в карточке (503 — модели
// изображений нет).
import { Fragment, useEffect, useRef } from "react";
import { stage } from "../../lib/pictures";
import type { BboxFrac, SlidePicture } from "../../types";
import { Arc } from "../kit/Arc";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { cls } from "../kit/cls";
import type { PictureView } from "./picture";

const pct = (n: number) => `${+(n * 100).toFixed(2)}%`;
const place = (b: BboxFrac) => ({ left: pct(b.x), top: pct(b.y), width: pct(b.w), height: pct(b.h) });

/** Зоны картинок на сцене и их рамки. `sel` — выбранная картинка, `frame` — её рамка видна (форма открыта). */
export function PictureSpots({ pics, sel, frame, onPick }: {
  pics: Array<SlidePicture & { bbox: BboxFrac }>;
  sel: string | null;
  frame: boolean;
  onPick(id: string): void;
}) {
  return (
    <>
      {pics.map((p) => {
        const on = p.id === sel;
        const what = p.status === "generated" ? "Изображение на слайде" : "Место под изображение";
        return (
          <Fragment key={p.id}>
            <button type="button" className="rt-hit" style={place(p.bbox)} onClick={() => onPick(p.id)} aria-pressed={on} aria-controls="rt-pcol"
              aria-label={what} title={p.status === "generated" ? "Изображение на слайде — заменить или убрать" : "Место под изображение — сгенерировать"} />
            <span className={cls("rp-frame rt-fr", on && frame && "rt-fr-on")} aria-hidden="true" style={place(p.bbox)} />
          </Fragment>
        );
      })}
    </>
  );
}

export interface PictureRunView {
  /** Задача над этой картинкой идёт (или «Вернуть»). */
  work: "change" | "undo" | null;
  action: "generate" | "remove" | null;
  progress: number;
  message: string;
  clock: string;
  /** Изменение применено: «Вернуть» (и строка «Новое изображение на слайде» после замены; убранное говорит о себе
   *  само — строкой «почему место пустует»). */
  done: "generate" | "remove" | null;
  canUndo: boolean;
  error: string | null;
}

export function PictureCard({ view, form, formDelay, wish, onWish, onToggleForm, onCancel, onGenerate, onRemove, onUndo, run, off }: {
  view: PictureView;
  form: boolean;
  /** Задержка появления формы: 320 мс вместе с колонкой, 40 мс по «Заменить». */
  formDelay: number;
  wish: string;
  onWish(text: string): void;
  onToggleForm(): void;
  onCancel(): void;
  onGenerate(): void;
  onRemove(): void;
  onUndo(): void;
  run: PictureRunView;
  /** Почему действия сейчас не начнутся (идёт другая работа над вариантом); null — начнутся. */
  off: string | null;
}) {
  const area = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (form) requestAnimationFrame(() => area.current?.focus({ preventScroll: true }));
  }, [form]);
  const working = run.work !== null;
  const blocked = off ?? undefined;
  return (
    <section className="p2-stag" aria-labelledby="rp-pt" style={{ padding: 24, borderRadius: 24, background: "#F3F4F1", transitionDelay: "280ms" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, height: 24 }}>
        <h3 id="rp-pt" style={{ margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 14, fontWeight: 600, lineHeight: "24px", letterSpacing: "-0.02em", color: "#0B1220" }}>
          {view.title}
        </h3>
        {view.tag && <span className="rp-tag">{view.tag}</span>}
      </div>
      {view.about && (
        <p title={view.about} style={{ display: "-webkit-box", margin: "8px 0 0", fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#0B1220", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
          {view.about}
        </p>
      )}
      {(view.model || view.why) && (
        <p style={{ margin: "4px 0 0", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>{view.model ?? view.why}</p>
      )}

      {working ? (
        <div className="p2-in" role="status" aria-live="polite" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, height: 24 }}>
            <Arc />
            <span style={{ flex: 1, minWidth: 0, fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {run.work === "undo" ? "Возвращаю как было…" : run.action === "remove" ? "Убираю изображение…" : `${stage(run.message)}…`}
            </span>
            <span style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "#5A6272", fontVariantNumeric: "tabular-nums" }}>
              <span className="p2-sr">Прошло </span>{run.clock}
            </span>
          </div>
          <div role="progressbar" aria-label="Ход замены изображения" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(run.progress * 100)}
            style={{ position: "relative", height: 4, marginTop: 8, borderRadius: 999, background: "rgba(11,18,32,.08)", overflow: "hidden" }}>
            <span className="p2-bar" style={{ position: "absolute", inset: 0, borderRadius: 999, background: "#2563EB", transformOrigin: "left center", transform: `scaleX(${run.progress.toFixed(4)})` }} />
          </div>
        </div>
      ) : (
        <>
          {run.done === "generate" && (
            <p className="p2-in" role="status" style={{ display: "flex", alignItems: "center", gap: 8, margin: "16px 0 0", fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#0B1220" }}>
              <span style={{ display: "flex", flex: "none", color: "#2563EB" }}><Icon name="check-circle" size={16} /></span>
              <span>Новое изображение на слайде</span>
            </p>
          )}
          {run.error && <ErrorLine text={run.error} lines={2} style={{ marginTop: 16 }} />}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16 }}>
            <button type="button" className={cls("p2-ob", form && "rp-on")} onClick={onToggleForm} aria-expanded={form} aria-controls="rp-form" style={{ height: 40 }}>
              {view.action}
            </button>
            {view.canRemove && (
              <button type="button" className="p2-ob" onClick={onRemove} disabled={!!off} title={blocked} style={{ height: 40 }}>
                <Icon name="image-off" size={18} />
                <span>Убрать</span>
              </button>
            )}
            {/* последнюю замену или «Убрать» можно отменить, пока после неё вариант не менялся */}
            {run.done && run.canUndo && (
              <button type="button" className="p2-gb p2-in" onClick={onUndo} disabled={!!off} title={blocked ?? "Вернуть изображение, каким оно было"}>
                <Icon name="undo" size={18} />
                <span>Вернуть</span>
              </button>
            )}
          </div>
          {form && (
            <div id="rp-form" className="p2-in" style={{ marginTop: 16, animationDelay: `${formDelay}ms` }}>
              <label className="p2-field" style={{ display: "block", padding: "16px 24px", borderRadius: 24, background: "#FFFFFF" }}>
                <span className="p2-sr">Ваши правки к изображению</span>
                <textarea ref={area} className="p2-ta" rows={2} maxLength={500} value={wish} onChange={(e) => onWish(e.target.value)}
                  placeholder={view.generated ? "Ваши правки, например: вид сверху, больше зелени" : "Что показать? Можно оставить пустым"}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault();
                      if (!off) onGenerate();
                    } else if (e.key === "Escape") onCancel();
                  }}
                  style={{ display: "block", width: "100%", height: 48, margin: 0, padding: 0, border: 0, resize: "none", background: "transparent", fontFamily: "inherit", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#0B1220" }} />
              </label>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16 }}>
                <button type="button" className="p2-ob" onClick={onGenerate} disabled={!!off} title={blocked}>
                  <Icon name="wand" size={18} />
                  <span>Сгенерировать</span>
                </button>
                <button type="button" className="p2-gb" onClick={onCancel}>Отмена</button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
