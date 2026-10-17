// «Для разработчиков» вкладки «Файлы» (boards/D-files, V2 `#df-dev`): JSON-файлы запуска и три раскрываемые строки —
// реестр навыков и агентов сервера рядом с версиями этого запуска (`api.skills`), журнал агента и сравнение с другим
// запуском (`api.diff`). Раскрытое появляется ходом p2-in, свёрнутое убирается сразу.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../../../api";
import { humanError } from "../../../lib/errors";
import { errText } from "../../../lib/narrate";
import { plainTerms } from "../../../lib/plain";
import { fmtWhen, plural } from "../../../lib/utils";
import { useApp } from "../../../store";
import type { DiffResponse, Generation, SkillsResponse, Variant } from "../../../types";
import { cls } from "../../kit/cls";
import { Collapse } from "../../kit/Collapse";
import { ErrorLine } from "../../kit/ErrorLine";
import { Icon } from "../../kit/Icon";
import { Spinner } from "../../kit/Spinner";
import { diffRows, JSON_FILES, registryRows } from "../files";

const TEXT = { fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#0B1220" } as const;
const SELECT = {
  height: 40, minWidth: 0, padding: "0 16px", border: 0, borderRadius: 999, background: "#FFFFFF", boxShadow: "inset 0 0 0 1px rgba(11,18,32,.14)",
  fontFamily: "inherit", fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#0B1220", cursor: "pointer",
} as const;

function DevRow({ t, h, open, onToggle, children }: { t: string; h: string; open: boolean; onToggle(): void; children: ReactNode }) {
  return (
    <li className="df-fx">
      <button type="button" className="df-dr" aria-expanded={open} onClick={onToggle}
        style={{ display: "flex", alignItems: "center", gap: 16, width: "100%", height: 48, padding: 0, border: 0, background: "none", textAlign: "left", cursor: "pointer" }}>
        <span style={{ fontSize: 14, fontWeight: 700, lineHeight: "20px", color: "#0B1220" }}>{t}</span>
        <span className="df-drh" style={{ marginLeft: "auto", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>{h}</span>
        <Icon name="chevron-down" size={18} className={cls("df-chev", open && "df-chev-up")} />
      </button>
      <Collapse open={open}><div style={{ paddingBottom: 16 }}>{children}</div></Collapse>
    </li>
  );
}

let skillsCache: SkillsResponse | null = null;

function Registry({ v }: { v: Variant }) {
  const [data, setData] = useState(skillsCache);
  const [err, setErr] = useState<string | null>(null);
  const [round, setRound] = useState(0);
  useEffect(() => {
    if (data) return;
    let off = false;
    setErr(null);
    api.skills().then((d) => {
      skillsCache = d;
      if (!off) setData(d);
    }, (e) => !off && setErr(humanError(`Список навыков не загрузился: ${errText(e)}`, "Список навыков не загрузился")));
    return () => {
      off = true;
    };
  }, [data, round]);
  if (err) return <div style={{ display: "flex", alignItems: "center", gap: 8 }}><ErrorLine text={err} lines={1} /><button type="button" className="p2-gb" onClick={() => setRound((r) => r + 1)}>Повторить</button></div>;
  if (!data) return <p style={{ display: "flex", alignItems: "center", gap: 8, margin: 0, ...TEXT, color: "#5A6272" }}><Spinner size={16} />Загружаю реестр…</p>;
  return (
    <div className="dpl-tbl p2-in">
      <span className="dpl-tr dpl-thd" style={{ gridTemplateColumns: "minmax(0,1fr) 120px 96px 160px" }}><span>Название</span><span>Роль</span><span>Версия</span><span>К этому запуску</span></span>
      {registryRows(data, v.run_manifest).map((r) => (
        <span key={r.name} className="dpl-tr" style={{ gridTemplateColumns: "minmax(0,1fr) 120px 96px 160px" }}>
          <span style={{ fontWeight: 700 }}>{r.name}</span><span>{r.role}</span><span>{r.version}</span>
          <span style={{ color: r.match === "как в запуске" ? "#2563EB" : r.match === "не участвовал" ? "#5A6272" : "#B45309" }}>{r.match}</span>
        </span>
      ))}
    </div>
  );
}

function Compare({ g, v }: { g: Generation; v: Variant }) {
  const { generations, strategyTitle, templateLabel } = useApp();
  const done = generations.filter((x) => x.status !== "running" && x.status !== "failed");
  const [gid, setGid] = useState("");
  const other = done.find((x) => x.id === gid) ?? null;
  const [s, setS] = useState("");
  const [res, setRes] = useState<DiffResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const strat = other && other.strategies.includes(s) ? s : other?.strategies[0] ?? "";
  // номер запроса: ответ о прежнем выборе (другой запуск, вариант этой презентации или ушедший с экрана раздел) не
  // ложится поверх нового
  const seq = useRef(0);
  const ask = `${g.id}|${v.strategy}|${gid}|${strat}`;
  useEffect(() => {
    seq.current += 1;
    setBusy(false);
    setRes(null);
    setErr(null);
  }, [ask]);
  useEffect(() => () => {
    seq.current += 1;
  }, []);
  const run = async () => {
    if (!gid || !strat || busy) return;
    const my = ++seq.current;
    setBusy(true);
    setErr(null);
    try {
      const d = await api.diff(g.id, v.strategy, gid, strat);
      if (my === seq.current) setRes(d);
    } catch (e) {
      if (my === seq.current) setErr(humanError(`Не удалось сравнить: ${errText(e)}`, "Не удалось сравнить"));
    } finally {
      if (my === seq.current) setBusy(false);
    }
  };
  const rows = res ? diffRows(res, strategyTitle) : null;
  return (
    <div>
      <div className="df-cmp" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <select aria-label="Другой запуск" value={gid} onChange={(e) => setGid(e.target.value)} style={{ ...SELECT, flex: 1 }}>
          <option value="">Выберите запуск…</option>
          {done.map((x) => <option key={x.id} value={x.id}>{fmtWhen(x.created_at)} · {x.title || templateLabel(x.template_id, x.template_file)}{x.id === g.id ? " · этот" : ""}</option>)}
        </select>
        <select aria-label="Вариант другого запуска" value={strat} disabled={!other} onChange={(e) => setS(e.target.value)} style={{ ...SELECT, width: 176 }}>
          {!other && <option value="">Вариант…</option>}
          {(other?.strategies ?? []).map((x) => <option key={x} value={x}>{strategyTitle(x)}</option>)}
        </select>
        <button type="button" className="p2-ob" disabled={!gid || !strat || busy} aria-busy={busy || undefined} onClick={() => void run()} style={{ height: 40, padding: "0 16px" }}>
          {busy && <Spinner size={16} />}<span>Сравнить</span>
        </button>
      </div>
      {err && <ErrorLine text={err} style={{ marginTop: 8 }} />}
      {rows && (
        rows.length ? (
          <div className="dpl-tbl p2-in" style={{ marginTop: 12 }}>
            <span className="dpl-tr dpl-thd" style={{ gridTemplateColumns: "180px minmax(0,1fr) minmax(0,1fr)" }}><span>Что изменилось</span><span>Этот запуск</span><span>Другой запуск</span></span>
            {rows.map((r) => <span key={r.label} className="dpl-tr" style={{ gridTemplateColumns: "180px minmax(0,1fr) minmax(0,1fr)" }}><span style={{ fontWeight: 700 }}>{r.label}</span><span>{r.from}</span><span>{r.to}</span></span>)}
          </div>
        ) : <p className="p2-in" style={{ margin: "12px 0 0", ...TEXT, color: "#2563EB", fontWeight: 700 }}>Отличий нет</p>
      )}
    </div>
  );
}

export function FilesDev({ g, v }: { g: Generation; v: Variant }) {
  const [row, setRow] = useState<"skills" | "log" | "diff" | null>(null);
  const flip = (k: "skills" | "log" | "diff") => setRow((r) => (r === k ? null : k));
  const log = v.agent?.log ?? [];
  return (
    <div id="df-dev" className="p2-in" style={{ padding: "0 24px 24px" }}>
      <p className="df-fk">Данные запуска в JSON</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
        {JSON_FILES.map((f) => (
          <a key={f.name} className="p2-ob" href={api.fileUrl(g.id, v.strategy, f.name)} target="_blank" rel="noopener noreferrer" title={f.name} style={{ height: 40, padding: "0 16px" }}>{f.label}</a>
        ))}
      </div>
      <ul style={{ margin: "16px 0 0", padding: 0, listStyle: "none" }}>
        <DevRow t="Навыки и агенты" h="название, роль, версия, что ушло в запуск" open={row === "skills"} onToggle={() => flip("skills")}><Registry v={v} /></DevRow>
        <DevRow t="Журнал агента" h={log.length ? plural(log.length, "запись", "записи", "записей") : "не записан"} open={row === "log"} onToggle={() => flip("log")}>
          {log.length ? (
            <ol style={{ display: "flex", flexDirection: "column", gap: 4, margin: 0, padding: 0, listStyle: "none" }}>
              {log.map((l, i) => <li key={i} style={{ display: "grid", gridTemplateColumns: "32px minmax(0,1fr)", ...TEXT }}><span style={{ color: "#5A6272", fontVariantNumeric: "tabular-nums" }}>{i + 1}.</span><span>{plainTerms(l)}</span></li>)}
            </ol>
          ) : <p style={{ margin: 0, ...TEXT, color: "#5A6272" }}>Журнал агента для этой сборки не записан.</p>}
        </DevRow>
        <DevRow t="Сравнить с другим запуском" h="выберите запуск и вариант" open={row === "diff"} onToggle={() => flip("diff")}><Compare g={g} v={v} /></DevRow>
      </ul>
    </div>
  );
}
