// Мелкие общие части вкладок листа «Подробнее» (разметка — boards/V2.dc.html, `#p2-lay-d`): панель вкладки с
// перекрёстным затуханием, раскрываемые разделы (`dq-acc` «Качества», `dpl-col` «Плана» и «Шаблона», `df-coll`
// «Файлов»), картинка с тихой заменой и строка ошибки у места действия. Раскрытое тело появляется ходом `p2-in`,
// закрытое убирается сразу (kit/Collapse, S-motion карта 17).
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { cls } from "../kit/cls";
import { Collapse } from "../kit/Collapse";
import { Icon, type IconName } from "../kit/Icon";
import { Tx } from "../kit/Tx";
import type { SheetTab } from "../deck/geometry";

/** Панель вкладки: стоит под рядом вкладок (top 104) и сменяется перекрёстным затуханием (p2-on / p2-off); невыбранная
 *  (`dd-pw p2-off`) держит замороженную ширину и без переходов внутри (layers.css). */
export function Panel({ tab, on, children, style }: { tab: SheetTab; on: boolean; children: ReactNode; style?: CSSProperties }) {
  return (
    <div className={cls("dd-pw", on ? "p2-on" : "p2-off")} data-tab={tab} style={{ position: "absolute", left: 48, right: 48, top: 104, ...style }}>
      {children}
    </div>
  );
}

/** Раскрываемый раздел «Качества» (`dq-acc`): значок в круге, название, число, стрелка; тело — список `dq-rows`. */
export function Acc({ id, icon, title, n, open, onToggle, children, first, small }: {
  id: string; icon?: IconName; title: string; n: ReactNode; open: boolean; onToggle(): void; children: ReactNode; first?: boolean; small?: boolean;
}) {
  return (
    <div className={first ? undefined : "dq-accb"}>
      <h3 style={{ margin: 0 }}>
        <button type="button" className={cls("dq-acc", open && "dq-acc-on")} aria-expanded={open} aria-controls={id} onClick={onToggle} style={small ? { height: 48 } : undefined}>
          {icon && <span className="dd-ico" aria-hidden="true"><Icon name={icon} size={18} /></span>}
          <span className="dq-acct" style={small ? { fontSize: 14, fontWeight: 700, lineHeight: "20px" } : { fontSize: 15, fontWeight: 700, lineHeight: "24px" }}>{title}</span>
          <span className="dq-cnt dq-cnt0">{n}</span>
          <Icon name="chevron-down" size={18} className="dq-chev" />
        </button>
      </h3>
      <Collapse open={open} id={id} as="ul" className={small ? "dq-rows dq-rows-tight" : "dq-rows"}>{children}</Collapse>
    </div>
  );
}

/** Ряд раздела (`dq-row`): метка слайда, жирное начало и продолжение — стопка (вторая колонка «Качества»). */
export function Row({ tag, b, c }: { tag: string | null; b: string; c: string }) {
  return (
    <li className="dq-row">
      {tag && <span className="dd-tag dd-tag-n">{tag}</span>}
      <Tx tx="q-acc" as="span" f>{b && <b style={{ fontWeight: 700 }}>{b}</b>}{c}</Tx>
    </li>
  );
}

/** Раскрываемая плашка «Плана» и «Шаблона» (`dpl-col` / `dtp-col`): стрелка в круге, название и подпись; справа —
 *  своё действие («Изменить»); тело — под рядом (`dl-body`). В колонке, которую помощник сужает («О плане»), название с
 *  подписью и тело — стопки (`tx`, `bodyTx`, kit/Tx). */
export function Col({ prefix, label, title, hint, open, onToggle, tall, action, children, delay, tx, bodyTx }: {
  prefix: "dpl" | "dtp"; label: string; title: string; hint: ReactNode; open: boolean; onToggle(): void; tall?: boolean; action?: ReactNode; children: ReactNode; delay: number;
  tx?: string; bodyTx?: string;
}) {
  const ctx = <><span className={`${prefix}-ct`}>{title}</span><span className={`${prefix}-ch`}>{hint}</span></>;
  return (
    <section className={cls(`${prefix}-col`, open && "dl-acc-on", tall && "dpl-col-tall", "p2-in")} aria-label={label} style={{ animationDelay: `${delay}ms` }}>
      <button type="button" className={`${prefix}-colbtn`} aria-expanded={open} onClick={onToggle}>
        <span className={`${prefix}-chev`} aria-hidden="true"><Icon name="chevron-down" size={18} className={cls("df-chev", open && "df-chev-up")} /></span>
        {tx ? <Tx tx={tx} as="span" wrap="span" f className={`${prefix}-ctx`}>{ctx}</Tx> : <span className={`${prefix}-ctx`}>{ctx}</span>}
      </button>
      {action}
      <Collapse open={open} className="dl-body">{bodyTx ? <Tx tx={bodyTx} as="div">{children}</Tx> : children}</Collapse>
    </section>
  );
}

/** Картинка слайда в рамке: не загрузилась — рамка остаётся пустой (серой), без значков поверх. */
export function Shot({ src, alt, style, fallback, loading = "lazy" }: { src: string | null | undefined; alt: string; style?: CSSProperties; fallback?: string | null; loading?: "lazy" | "eager" }) {
  const [cur, setCur] = useState(src ?? null);
  const [broken, setBroken] = useState(false);
  useEffect(() => {
    setCur(src ?? null);
    setBroken(false);
  }, [src]);
  if (!cur || broken) return <span role="img" aria-label={alt} style={{ display: "block", background: "#F3F4F1", ...style }} />;
  return (
    <img src={cur} alt={alt} loading={loading} decoding="async" draggable={false} style={{ display: "block", objectFit: "cover", ...style }}
      onError={() => (fallback && cur !== fallback ? setCur(fallback) : setBroken(true))} />
  );
}

/** Пустое место вкладки (данных нет): белая коробка с объяснением по центру. */
export function Empty({ title, text, children }: { title: string; text: string; children?: ReactNode }) {
  return (
    <section className="dd-box p2-pop" style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "40px 24px", textAlign: "center" }}>
      <h3 className="dd-h">{title}</h3>
      <p style={{ maxWidth: 440, margin: "8px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272" }}>{text}</p>
      {children}
    </section>
  );
}
