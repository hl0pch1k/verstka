// «Как думает агент» (boards/B-start, B-sketch, B-failed, V2 `bdQueue`/`bdRoles`): девять ролей агента. Пока сборка в
// очереди — лента очереди (номер, роль, подсказка); с первым шагом она гаснет, и встаёт рабочая лента: готовые роли —
// синяя галочка, работающая — кольцо со своей иконкой и «сейчас», впереди — номер и подсказка, с ошибкой — красное
// кольцо и «!», не запускавшиеся — тире. Под ролью — её последние мысли. Лента сама сдвигается (520 мс), чтобы
// работающая роль и следующая были видны над нижним краем.
// Помощник сужает колонку 416 → 320 (V2 версии 100; в тесной колоде — 288): многострочный текст (мысли, подсказки
// очереди, причина ошибки) — стопки из двух копий (hp-tx, create.css): широкая гаснет, узкая проявляется на месте, ни
// одна не переносится заново посреди хода. Ширины копий — постоянные, в px (build.css `--bd-tw`, `--bd-tn`): строка,
// пришедшая посреди хода, свёрстана на ширину своей раскладки сразу, а не на живую ширину колонки. Высоты ролей
// меняются вместе со сдвигом ленты одной кривой: сдвиг считается для обеих раскладок сразу (по высотам копий; замер —
// только когда меняются строки ленты, не каждый кадр и не каждую секунду часов), высота стопки ленты на ходу идёт от
// широкой к узкой линейно (build.css, `--hw`, `--hdd`) — роли движутся в одну сторону, нижняя видимая стоит у края.
// Сборка с файлами данных (V2 v105): на месте аналитика — «Аналитик данных» со значком графика (buildView `DATA_ROLE`).
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { PhaseKey } from "../../lib/agent";
import { cls } from "../kit/cls";
import { Icon, type IconName } from "../kit/Icon";
import type { BuildView, RoleLine, RoleStatus, RoleView } from "./buildView";
import { rollOf } from "./columns";

const ROLE_ICON: Record<PhaseKey, IconName> = {
  writer: "pen", analyst: "search", architect: "outline", designer: "layout", critic: "chat-check",
  revise: "refresh", layout: "layers", check: "list-check", eyes: "eye",
};
const ROLE_CLS: Record<RoleStatus, string> = {
  queue: "p2-role-pend", now: "p2-role-act", done: "p2-role-done", error: "bf-role-err", skip: "bf-role-skip",
};
const STATUS_WORD: Partial<Record<RoleStatus, string>> = { done: "готово", now: "сейчас", error: "ошибка" };
/** Нижний отступ ленты (V2: 652 − 64 − 24 = 564 px видно над краем).
 *  Сайт: окно 564 — в обеих раскладках. V2 v100 в узкой берёт 500 (`hpNar ? 500 : 564`) — остаток раскладки, где узкая
 *  колонка агента стояла под фазой («окно ленты ниже на 64»); в v100 колонка агента — во всю высоту плиты в обеих
 *  раскладках (замер V2: aside 652, лента 588 и закрытой, и открытой), и с 500 открытие помощника каждый раз уводило бы
 *  ленту на 64 px дальше, чем нужно (такт 16: сдвиг −120 вместо −56), — работающая роль и следующая вставали бы на 64 px
 *  выше нижнего края, хотя ни одна строка не перенеслась. */
const PAD_BOTTOM = 24;
/** Зазор между ролями ленты. */
const GAP = 12;
/** Закрытие помощника: ход сетки 340 мс (открытие — 520, как сдвиг ленты по новым строкам). */
const CLOSE_MS = 340;
const LINE: CSSProperties = { margin: 0, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "rgba(255,255,255,.72)" };
/** Лента очереди и рабочая лента — одно место. */
const LOG: CSSProperties = { position: "absolute", inset: 0, display: "flex", flexDirection: "column", gap: GAP, margin: 0, padding: "16px 0 24px", listStyle: "none", overflow: "auto" };
/** Строка хода рядом с «Как думает агент». */
const STEP: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "rgba(255,255,255,.64)", whiteSpace: "nowrap" };

/** Стопка из двух копий (hp-tx): широкая и узкая в одной клетке; активная — по раскладке (`narrow`), вторая — aria-hidden.
 *  Отступ сверху — у стопки, не у копий: высота стопки — высота копий. */
function Tx({ tx, narrow, className, style, title, top = 0, children }: {
  tx: string; narrow: boolean; className?: string; style?: CSSProperties; title?: string; top?: number; children: ReactNode;
}) {
  return (
    <div className="hp-tx" data-tx={tx} style={top ? { marginTop: top } : undefined}>
      <p className={cls("hp-txw", className)} style={style} title={narrow ? undefined : title} aria-hidden={narrow || undefined}>{children}</p>
      <p className={cls("hp-txn", className)} style={style} title={narrow ? title : undefined} aria-hidden={!narrow || undefined}>{children}</p>
    </div>
  );
}

/** «Слайд 4: нет обозначений → подписи a, b, f(x)» (критик, взгляд дизайнера) или «Слайд 3 — карточки (4)»; не длиннее
 *  двух строк (обрезка — у внутренней строки копии), целиком — в подсказке. */
function Line({ role, line, narrow }: { role: PhaseKey; line: RoleLine; narrow: boolean }) {
  const colon = role === "critic" || role === "eyes";
  const full = `${line.slide != null ? `Слайд ${line.slide}${colon ? ": " : " — "}` : ""}${line.text}${line.fix ? ` → ${line.fix}` : ""}`;
  return (
    <Tx tx="b-line" narrow={narrow} className="p2-in" style={LINE} title={full} top={4}>
      <span className="bd-line">
        {line.slide != null && <b style={{ fontWeight: 700, color: "#FFFFFF" }}>Слайд {line.slide}{colon ? ":" : ""}</b>}
        {line.slide != null ? (colon ? " " : " — ") : null}
        {line.text}
        {line.fix && <><span className="p2-arrow">→</span><b style={{ fontWeight: 700, color: "#FFFFFF" }}>{line.fix}</b></>}
      </span>
    </Tx>
  );
}

function Dot({ r }: { r: RoleView }) {
  return (
    <span className="p2-dot" aria-hidden="true">
      {r.status === "done" && <Icon key="done" name="check" size={14} className="p2-pop" />}
      {r.status === "now" && <Icon key="now" name={r.data ? "chart" : ROLE_ICON[r.key]} size={16} className="p2-pop" />}
      {r.status === "queue" && <span className="bk-n">{r.n}</span>}
      {r.status === "error" && <Icon key="err" name="alert-mark" size={16} className="p2-pop" />}
      {r.status === "skip" && <Icon key="skip" name="minus" size={14} className="p2-pop" />}
    </span>
  );
}

/** Высоты ролей ленты в широкой и узкой раскладке — по высотам копий её стопок (их ширины постоянны, так что посреди
 *  хода получается то же, что в покое), отступ первой роли и сколько ленты видно над нижним краем. Заодно ставит стопкам
 *  `--hw` (высота в широкой) и `--hdd` (на сколько выше в узкой): по ним их высота на ходу (build.css). Сначала все
 *  замеры, потом записи — без лишних раскладок. */
interface LogHeights { wide: number[]; narrow: number[]; top: number; view: number }
function measure(el: HTMLElement): LogHeights {
  const items = [...el.children] as HTMLElement[];
  const rows = items.map((li) => {
    const stacks = [...li.querySelectorAll<HTMLElement>(".hp-tx")].map((st) => {
      const [cw, cn] = [...st.children] as HTMLElement[];
      const w = cw.offsetHeight;
      return { st, w, n: Math.max(w, cn.scrollHeight), live: st.offsetHeight };
    });
    return { h: li.offsetHeight, stacks };
  });
  const top = items[0]?.offsetTop ?? 0;
  const view = el.clientHeight - PAD_BOTTOM;
  for (const r of rows) for (const s of r.stacks) {
    s.st.style.setProperty("--hw", `${s.w}px`);
    s.st.style.setProperty("--hdd", `${s.n - s.w}px`);
  }
  const sum = (r: (typeof rows)[number], k: "w" | "n") => r.h + r.stacks.reduce((a, s) => a + s[k] - s.live, 0);
  return { wide: rows.map((r) => sum(r, "w")), narrow: rows.map((r) => sum(r, "n")), top, view };
}

const same = (a: LogHeights | null, b: LogHeights) =>
  !!a && a.top === b.top && a.view === b.view && a.wide.join() === b.wide.join() && a.narrow.join() === b.narrow.join();

/** Что меняет высоты ролей ленты: строки (их тексты), ошибка, статусы ролей. Часы и ход помощника — нет. */
const logShape = (view: BuildView) =>
  view.roles.map((r) => `${r.key}:${r.status}:${r.lines.map((l) => `${l.key}/${l.slide ?? ""}/${l.text}/${l.fix ?? ""}`).join("\u0001")}`).join("|")
  + `|${view.failed?.text ?? ""}`;

export function Roles({ view, narrow, widths }: {
  view: BuildView; narrow: boolean;
  /** Ширины текста ролей в широкой и узкой раскладке (columns.ts `textWide`, `textNarrow`): по ним — замер. */
  widths: string;
}) {
  const queued = view.phase === "queued";
  const last = view.roles.length - 1;

  // сдвиг ленты: работающая роль (или с ошибкой) и следующая — над нижним краем. Работающей нет (последнюю роль сервер
  // пропустил, а сборка ещё сохраняет файлы) — на виду последняя пройденная, лента не уезжает к началу. Считается для
  // обеих раскладок; помощник меняет раскладку — сдвиг едет вместе с высотами ролей (открытие 520 мс, закрытие 340)
  const list = useRef<HTMLOListElement>(null);
  const [hs, setHs] = useState<LogHeights | null>(null);
  const at = view.roles.findIndex((r) => r.status === "now" || r.status === "error");
  const reached = view.roles.map((r) => r.status !== "queue").lastIndexOf(true);
  const focus = at >= 0 ? at : view.phase === "done" ? last : reached;
  // замер — только когда меняются строки ленты (и ширины текста — с окном) и когда догрузились шрифты: не каждую
  // перерисовку (часы идущей сборки — раз в секунду) и не посреди хода помощника
  const shape = logShape(view);
  useLayoutEffect(() => {
    const el = list.current;
    if (!el) return void setHs(null);
    let alive = true;
    const run = () => {
      if (!alive || !list.current) return;
      const next = measure(list.current);
      setHs((cur) => (same(cur, next) ? cur : next));
    };
    run();
    void document.fonts?.ready.then(run);
    return () => {
      alive = false;
    };
  }, [shape, widths, queued]);
  const roll = useMemo(() => {
    if (!hs || focus < 0) return { wide: 0, narrow: 0 };
    return { wide: rollOf(hs.wide, GAP, hs.top, focus + 1, hs.view), narrow: rollOf(hs.narrow, GAP, hs.top, focus + 1, hs.view) };
  }, [hs, focus]);
  // помощник закрывается: сдвиг — за 340 мс, как сетка и высоты стопок (следующие сдвиги — снова 520)
  const was = useRef(narrow);
  const closing = was.current && !narrow;
  useEffect(() => {
    was.current = narrow;
  });
  const shift = narrow ? roll.narrow : roll.wide;

  return (
    <aside aria-label="Как думает агент" style={{ display: "flex", flexDirection: "column", minWidth: 0, height: 652 }}>
      <div className="hq-bdh" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, height: 64 }}>
        <h2 className="hq-bdt" style={{ margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: "28px", letterSpacing: "-0.02em", color: "#FFFFFF", whiteSpace: "nowrap" }}>
          Как думает агент
        </h2>
        {queued ? (
          <span style={STEP}>
            <Icon name="clock" size={16} /><span>в очереди</span>
          </span>
        ) : view.failed ? (
          <span key="failed" className="p2-in" style={{ ...STEP, color: "#F87171" }}>
            <Icon name="alert" size={16} /><span>{view.step}</span>
          </span>
        ) : (
          <span key="running" className="p2-in" style={{ ...STEP, display: undefined }}>{view.step}</span>
        )}
      </div>
      <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
        {/* очередь (B-start): гаснет, когда начинается работа */}
        <ol className={cls("bs-log p2-fade", queued ? "p2-on" : "p2-off")} style={LOG}>
          {view.roles.map((r, i) => (
            <li key={r.key} className={cls("p2-role p2-in p2-role-pend", i === last && "p2-role-last")} style={{ animationDelay: `${160 + i * 40}ms` }}>
              <span className="p2-dot" aria-hidden="true"><span className="bs-n">{r.n}</span></span>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, height: 28 }}>
                  <span className="p2-rname">{r.title}</span>
                  <span className="p2-sr">шаг {r.n}, впереди</span>
                </div>
                <Tx tx="b-hint" narrow={narrow} className="bs-hint">{r.hint}</Tx>
              </div>
            </li>
          ))}
        </ol>
        {!queued && (
          <ol ref={list} className={cls("bk-log p2-fade", shift > 0 && "bd-roll")} style={LOG}>
            {view.roles.map((r, i) => (
              <li key={r.key} className={cls("p2-role p2-in bd-li", ROLE_CLS[r.status], i === last && "p2-role-last")}
                style={{ animationDelay: `${160 + i * 40}ms`, transform: `translateY(${-shift}px)`, ...(closing && { transitionDuration: `${CLOSE_MS}ms` }) }}>
                <Dot r={r} />
                <div style={{ minWidth: 0 }}>
                  <div className="bk-rrow">
                    <span className="p2-rname">{r.title}</span>
                    {STATUS_WORD[r.status] && <span className="p2-rst">{STATUS_WORD[r.status]}</span>}
                    <span className="bk-note bf-note" title={r.status === "queue" || (r.status === "now" && !r.lines.length) ? r.hint : r.note || undefined}>{r.note}</span>
                    {r.status === "queue" && <span className="p2-sr">шаг {r.n}, впереди</span>}
                  </div>
                  {r.lines.map((l) => <Line key={l.key} role={r.key} line={l} narrow={narrow} />)}
                  {r.status === "error" && view.failed && (
                    <Tx tx="b-err" narrow={narrow} className="bf-err p2-in" style={{ margin: 0 }} top={4}>
                      <Icon name="alert" size={16} /><span>{view.failed.text}</span>
                    </Tx>
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
