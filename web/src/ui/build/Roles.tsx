// «Как думает агент» (boards/B-start, B-sketch, B-failed, V2 `bdQueue`/`bdRoles`): девять ролей агента. Пока сборка в
// очереди — лента очереди (номер, роль, подсказка); с первым шагом она гаснет, и встаёт рабочая лента: готовые роли —
// синяя галочка, работающая — кольцо со своей иконкой и «сейчас», впереди — номер и подсказка, с ошибкой — красное
// кольцо и «!», не запускавшиеся — тире. Под ролью — её последние мысли. Лента сама сдвигается (520 мс), чтобы
// работающая роль и следующая были видны над нижним краем.
import { useLayoutEffect, useRef, useState } from "react";
import type { PhaseKey } from "../../lib/agent";
import { cls } from "../kit/cls";
import { Icon, type IconName } from "../kit/Icon";
import type { BuildView, RoleLine, RoleStatus, RoleView } from "./buildView";

const ROLE_ICON: Record<PhaseKey, IconName> = {
  writer: "pen", analyst: "search", architect: "outline", designer: "layout", critic: "chat-check",
  revise: "refresh", layout: "layers", check: "list-check", eyes: "eye",
};
const ROLE_CLS: Record<RoleStatus, string> = {
  queue: "p2-role-pend", now: "p2-role-act", done: "p2-role-done", error: "bf-role-err", skip: "bf-role-skip",
};
const STATUS_WORD: Partial<Record<RoleStatus, string>> = { done: "готово", now: "сейчас", error: "ошибка" };
/** Нижний отступ ленты (V2: 652 − 64 − 24 = 564 px видно над краем). */
const PAD_BOTTOM = 24;

/** «Слайд 4: нет обозначений → подписи a, b, f(x)» (критик, взгляд дизайнера) или «Слайд 3 — карточки (4)». */
function Line({ role, line }: { role: PhaseKey; line: RoleLine }) {
  const colon = role === "critic" || role === "eyes";
  const full = `${line.slide != null ? `Слайд ${line.slide}${colon ? ": " : " — "}` : ""}${line.text}${line.fix ? ` → ${line.fix}` : ""}`;
  return (
    <p className="p2-in bd-line" title={full} style={{ margin: "4px 0 0", fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "rgba(255,255,255,.72)" }}>
      {line.slide != null && <b style={{ fontWeight: 700, color: "#FFFFFF" }}>Слайд {line.slide}{colon ? ":" : ""}</b>}
      {line.slide != null ? (colon ? " " : " — ") : null}
      {line.text}
      {line.fix && <><span className="p2-arrow">→</span><b style={{ fontWeight: 700, color: "#FFFFFF" }}>{line.fix}</b></>}
    </p>
  );
}

function Dot({ r }: { r: RoleView }) {
  return (
    <span className="p2-dot" aria-hidden="true">
      {r.status === "done" && <Icon key="done" name="check" size={14} className="p2-pop" />}
      {r.status === "now" && <Icon key="now" name={ROLE_ICON[r.key]} size={16} className="p2-pop" />}
      {r.status === "queue" && <span className="bk-n">{r.n}</span>}
      {r.status === "error" && <Icon key="err" name="alert-mark" size={16} className="p2-pop" />}
      {r.status === "skip" && <Icon key="skip" name="minus" size={14} className="p2-pop" />}
    </span>
  );
}

export function Roles({ view }: { view: BuildView }) {
  const queued = view.phase === "queued";
  const last = view.roles.length - 1;

  // сдвиг ленты: работающая роль (или с ошибкой) и следующая — над нижним краем
  const list = useRef<HTMLOListElement>(null);
  const [roll, setRoll] = useState(0);
  const at = view.roles.findIndex((r) => r.status === "now" || r.status === "error");
  const focus = at >= 0 ? at : view.phase === "done" ? last : -1;
  useLayoutEffect(() => {
    const el = list.current;
    if (!el || focus < 0) return void setRoll(0);
    const target = el.children[Math.min(last, focus + 1)] as HTMLElement | undefined;
    if (!target) return;
    const end = target.offsetTop + target.offsetHeight;
    const next = Math.max(0, Math.round(end - (el.clientHeight - PAD_BOTTOM)));
    setRoll((cur) => (cur === next ? cur : next));
  });

  return (
    <aside aria-label="Как думает агент" style={{ display: "flex", flexDirection: "column", minWidth: 0, height: 652 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, height: 64 }}>
        <h2 style={{ margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: "28px", letterSpacing: "-0.02em", color: "#FFFFFF", whiteSpace: "nowrap" }}>
          Как думает агент
        </h2>
        {queued ? (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "rgba(255,255,255,.64)", whiteSpace: "nowrap" }}>
            <Icon name="clock" size={16} /><span>в очереди</span>
          </span>
        ) : view.failed ? (
          <span key="failed" className="p2-in" style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "#F87171", whiteSpace: "nowrap" }}>
            <Icon name="alert" size={16} /><span>{view.step}</span>
          </span>
        ) : (
          <span key="running" className="p2-in" style={{ fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "rgba(255,255,255,.64)", whiteSpace: "nowrap" }}>{view.step}</span>
        )}
      </div>
      <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
        {/* очередь (B-start): гаснет, когда начинается работа */}
        <ol className={cls("bs-log p2-fade", queued ? "p2-on" : "p2-off")}
          style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", gap: 12, margin: 0, padding: "16px 0 24px", listStyle: "none", overflow: "auto" }}>
          {view.roles.map((r, i) => (
            <li key={r.key} className={cls("p2-role p2-in p2-role-pend", i === last && "p2-role-last")} style={{ animationDelay: `${160 + i * 40}ms` }}>
              <span className="p2-dot" aria-hidden="true"><span className="bs-n">{r.n}</span></span>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, height: 28 }}>
                  <span className="p2-rname">{r.title}</span>
                  <span className="p2-sr">шаг {r.n}, впереди</span>
                </div>
                <p className="bs-hint">{r.hint}</p>
              </div>
            </li>
          ))}
        </ol>
        {!queued && (
          <ol ref={list} className={cls("bk-log p2-fade", roll > 0 && "bd-roll")}
            style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", gap: 12, margin: 0, padding: "16px 0 24px", listStyle: "none", overflow: "auto" }}>
            {view.roles.map((r, i) => (
              <li key={r.key} className={cls("p2-role p2-in bd-li", ROLE_CLS[r.status], i === last && "p2-role-last")}
                style={{ animationDelay: `${160 + i * 40}ms`, transform: `translateY(${-roll}px)` }}>
                <Dot r={r} />
                <div style={{ minWidth: 0 }}>
                  <div className="bk-rrow">
                    <span className="p2-rname">{r.title}</span>
                    {STATUS_WORD[r.status] && <span className="p2-rst">{STATUS_WORD[r.status]}</span>}
                    <span className="bk-note bf-note" title={r.status === "queue" || (r.status === "now" && !r.lines.length) ? r.hint : r.note || undefined}>{r.note}</span>
                    {r.status === "queue" && <span className="p2-sr">шаг {r.n}, впереди</span>}
                  </div>
                  {r.lines.map((l) => <Line key={l.key} role={r.key} line={l} />)}
                  {r.status === "error" && view.failed && (
                    <p className="bf-err p2-in"><Icon name="alert" size={16} /><span>{view.failed.text}</span></p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </aside>
  );
}
