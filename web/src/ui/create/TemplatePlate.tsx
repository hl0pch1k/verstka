// Плита 01 «Шаблон»: справа в заголовке — выбранный шаблон и «Сменить» (шаг свёрнут) или «Готово» (раскрыт); тело
// `#p2-b1` — лента обложек (C-templates), файл над шагом (C-upload) и разбор загруженного файла (C-analyzing).
// Разметка — boards/V2.dc.html, плита 01 и модуль tp. Загрузка живёт в `useTemplateUpload` (AppShell): её начинают
// и плитка ленты, и перетаскивание на плиту, и «Загрузить свой» в разделе «Шаблоны».
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { useApp } from "../../store";
import { humanError } from "../../lib/errors";
import { templateTitle, tplLabel } from "../../lib/plain";
import { cls } from "../kit/cls";
import { ErrorLine } from "../kit/ErrorLine";
import { Spinner } from "../kit/Spinner";
import { Analysis } from "./Analysis";
import { Cover, inkOf, Ribbon } from "./TemplateRibbon";
import { analysisError, analysisFacts, analysisSteps, ANALYSIS_STEPS, orderTemplates, tplMeta, type AnalysisFacts, type StepState } from "./ribbon";
import { FileInput, UploadZone, useFileDrop } from "./UploadZone";
import { ribbonLayout } from "../deck/fit";
import { useDeckFit } from "../deck/useDeckFit";

/** idle — лента; run — файл уходит на сервер и разбирается; settle — разбор закончился, решается итог; done — все
 *  галочки держатся 560 мс; out — разбор гаснет 240 мс; fail — строка ошибки в коробке разбора. */
export type UploadPhase = "idle" | "run" | "settle" | "done" | "out" | "fail";
const BUSY: UploadPhase[] = ["run", "settle", "done", "out"];
/** V2 `tpTick`: после последнего шага галочки держатся 560 мс, затем разбор гаснет за 240 мс. */
const HOLD_MS = 560;
const OUT_MS = 240;

export interface TemplateUpload {
  phase: UploadPhase;
  file: File | null;
  /** Только что загруженный шаблон: первым в ленте и в разделе. */
  fresh: string | null;
  /** Текст неудачи (fail) как пришёл: сырой, для показа не годится — см. `failure`. */
  error: string | null;
  /** Идёт загрузка или разбор (run, settle, done, out): новый файл не принимается. */
  busy: boolean;
  /** Неудача (fail) для показа: причина по-русски и можно ли повторить с тем же файлом (`analysisError`). */
  failure: { text: string; retry: boolean } | null;
  steps: StepState[];
  facts: AnalysisFacts;
  inputRef: RefObject<HTMLInputElement>;
  start(file: File): void;
  /** Окно выбора файла. */
  pick(): void;
  retry(): void;
  /** Закрыть разбор после неудачи — вернуть ленту. */
  dismiss(): void;
}

const ALL_DONE: StepState[] = Array.from({ length: ANALYSIS_STEPS }, () => "done");

export function useTemplateUpload(): TemplateUpload {
  const { uploadTemplate, clearNotice, notices, templateId, activeJob } = useApp();
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [file, setFile] = useState<File | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [facts, setFacts] = useState<AnalysisFacts>({});
  const inputRef = useRef<HTMLInputElement>(null);
  const seq = useRef(0);
  const since = useRef(0);
  const lastSteps = useRef<StepState[]>(analysisSteps("", 0));
  const phaseNow = useRef(phase);
  phaseNow.current = phase;

  const start = useCallback((f: File) => {
    if (BUSY.includes(phaseNow.current)) return;
    const n = ++seq.current;
    since.current = Date.now();
    lastSteps.current = analysisSteps("", 0);
    clearNotice("template");
    setFile(f);
    setError(null);
    setFacts({});
    setPhase("run");
    void uploadTemplate(f, true).then(() => {
      if (seq.current === n) setPhase((p) => (p === "run" ? "settle" : p));
    });
  }, [uploadTemplate, clearNotice]);

  // итог: строка ошибки области «Шаблон» — неудача; иначе шаблон уже выбран (adoptManifest) — он и есть новый
  const notice = notices.template;
  useEffect(() => {
    if (phase !== "settle") return;
    if (notice?.kind === "error") {
      setError(notice.text.replace(/^Не получилось:\s*/, ""));
      setPhase("fail");
    } else {
      setFresh(templateId);
      setPhase("done");
    }
  }, [phase, notice, templateId]);

  useEffect(() => {
    if (phase !== "done" && phase !== "out") return;
    const t = window.setTimeout(() => setPhase(phase === "done" ? "out" : "idle"), phase === "done" ? HOLD_MS : OUT_MS);
    return () => window.clearTimeout(t);
  }, [phase]);

  // строка о ходе («Модель не подключена…») живёт, пока идёт разбор
  useEffect(() => {
    if (phase === "idle" && notice?.kind === "info") clearNotice("template");
  }, [phase, notice, clearNotice]);

  // задача этой загрузки: analyze, начатая после выбора файла
  const job = activeJob && activeJob.kind === "analyze" && activeJob.startedAt >= since.current ? activeJob : null;
  const live = phase === "run" || phase === "settle";
  const msg = live ? job?.message : undefined;
  useEffect(() => {
    if (msg) setFacts((f) => analysisFacts(f, msg));
  }, [msg]);
  let steps = lastSteps.current;
  if (phase === "done" || phase === "out") steps = ALL_DONE;
  else if (live && job) steps = lastSteps.current = analysisSteps(job.message, job.progress);

  // пока файл разбирается, второй не выбирают: окно выбора не открывается, выбранное молча пропало бы (start занят)
  const pick = useCallback(() => {
    if (!BUSY.includes(phaseNow.current)) inputRef.current?.click();
  }, []);
  const retry = useCallback(() => {
    if (file) start(file);
  }, [file, start]);
  const dismiss = useCallback(() => {
    setPhase("idle");
    setError(null);
    clearNotice("template");
  }, [clearNotice]);
  const busy = BUSY.includes(phase);
  const failure = useMemo(() => (phase === "fail" ? analysisError(error, file?.name) : null), [phase, error, file]);
  return { phase, file, fresh, error, busy, failure, steps, facts, inputRef, start, pick, retry, dismiss };
}

/** Строка в свёрнутой шапке, пока файл разбирается. */
function RunningLine({ name }: { name: string }) {
  return (
    <span role="status" title={name || undefined} style={{ display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0, fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap" }}>
      <span style={{ display: "flex", flex: "none", color: "#2563EB" }}><Spinner size={16} /></span>
      <span>Разбираю шаблон…</span>
    </span>
  );
}

/** Короткая красная строка в свёрнутой шапке, когда разбор не удался: целиком помещается и при 1280 px, без
 *  многоточия. Причина — в открытом шаге (коробка разбора), «Сменить» и заголовок его раскрывают. */
export const HEAD_FAIL = "Не удалось разобрать шаблон";
/** Строка области «Шаблон» в шапке, когда причины в тексте не осталось (одни технические слова). */
const HEAD_NOTE = "Не удалось загрузить шаблоны";

/** Что стоит в свёрнутой шапке перед «Сменить»: ход разбора, неудача, выбранный шаблон. */
type HeadKind = "run" | "fail" | "tpl" | "none";

/** Место под одну из этих строк: при смене содержимого оно проявляется (`p2-in`, как всё на доске), а не
 *  подменяется рывком. Решение «проявлять» принимается один раз при появлении: класс не снимается посреди движения. */
function HeadSlot({ fade, children }: { fade: boolean; children: ReactNode }) {
  const [on] = useState(fade);
  return <span className={on ? "p2-in" : undefined} style={{ display: "inline-flex", alignItems: "center", minWidth: 0 }}>{children}</span>;
}

/** Заголовок плиты 01 справа (слот `h1`): выбранный шаблон и «Сменить», на раскрытом шаге — «Готово». Строка ошибки
 *  области «Шаблон», которая пришла не от разбора (список, манифест), стоит перед ними — без технического хвоста
 *  (`humanError`). Пока шаг свёрнут, а файл разбирается, вместо шаблона стоит строка «Разбираю шаблон…»; если разбор
 *  не удался — короткая красная строка (`HEAD_FAIL`; полная причина и «Попробовать ещё раз» — в коробке раскрытого
 *  шага, «Сменить» и заголовок его раскрывают). Каждая из них проявляется, а не появляется сразу. */
export function TemplateHead({ upload }: { upload: TemplateUpload }) {
  const { ui, dispatch, templates, templateId, notices } = useApp();
  const open = ui.screen === "create" && ui.open === "tpl";
  const t = templates.find((x) => x.template_id === templateId);
  const note = upload.phase === "idle" && notices.template?.kind === "error" ? humanError(notices.template.text, HEAD_NOTE) : null;
  const running = upload.phase === "run" || upload.phase === "settle";
  const kind: HeadKind = running ? "run" : upload.failure ? "fail" : t ? "tpl" : "none";
  // что стояло в прошлый раз: если то же, содержимое не новое — плита (p2-in на группе) уже проявляет его целиком
  const was = useRef<HeadKind | null>(null);
  useEffect(() => {
    was.current = kind;
  });
  const fade = was.current !== null && was.current !== kind;
  return (
    <>
      <span style={{ flex: 1, minWidth: 0 }} />
      {note && (
        <span key={note} className="p2-in" style={{ display: "inline-flex", minWidth: 0 }}>
          <ErrorLine text={note} lines={1} style={{ maxWidth: 480 }} />
        </span>
      )}
      {open ? (
        <div key="open" className="p2-in" style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <button type="button" className="p2-ob" onClick={() => dispatch({ type: "open", step: "text" })} style={{ height: 40 }}>Готово</button>
        </div>
      ) : (
        <div key="closed" className="p2-in" style={{ display: "flex", alignItems: "center", gap: 24, minWidth: 0 }}>
          {kind === "run" ? (
            <HeadSlot key="run" fade={fade}><RunningLine name={upload.file?.name ?? ""} /></HeadSlot>
          ) : kind === "fail" ? (
            <HeadSlot key="fail" fade={fade}><ErrorLine text={HEAD_FAIL} lines={1} /></HeadSlot>
          ) : t && (
            <HeadSlot key="tpl" fade={fade}>
              <div style={{ display: "flex", alignItems: "center", gap: 16, minWidth: 0 }}>
                <Cover src={t.cover_url} kind="m" ink={inkOf(t)} label={`Обложка шаблона ${tplLabel(t)}`} />
                <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                  <span style={{ fontSize: 15, fontWeight: 700, lineHeight: "24px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{tplLabel(t)}</span>
                  <span style={{ fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{tplMeta(t)}</span>
                </div>
              </div>
            </HeadSlot>
          )}
          <button type="button" className="p2-ob" onClick={() => dispatch({ type: "open", step: "tpl" })} style={{ flex: "none", height: 40 }}>
            {t ? "Сменить" : "Выбрать шаблон"}
          </button>
        </div>
      )}
    </>
  );
}

/** Тело шага 01 (слот `p1`, `#p2-b1`): лента или разбор и зона «Отпустите файл». */
export function TemplateBody({ upload }: { upload: TemplateUpload }) {
  const { ui, dispatch, templates, notices } = useApp();
  // помощник сужает колоду: лента — четыре обложки в три колонки (ribbonLayout), и тот же разбор
  const { cols } = ribbonLayout(useDeckFit());
  const on = ui.screen === "create" && ui.open === "tpl" && !ui.more;
  const body = useRef<HTMLDivElement>(null);
  const over = useFileDrop(body, on && !upload.busy, upload.start);
  const peek = (id: string) => dispatch({ type: "set", patch: { tplPreview: id, tplDelete: null } });
  const gallery = () => dispatch({ type: "sect", sect: "tpls" });
  const fileName = upload.file?.name ?? "";
  const info = notices.template?.kind === "info" ? notices.template.text : null;
  return (
    <div id="p2-b1" ref={body} className={cls("p2-body p2-g4", on ? "p2-on" : "p2-off")}
      style={{ position: "relative", display: "grid", gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap: 16, margin: "24px 0 0 192px" }}>
      {upload.phase === "idle" ? (
        <Ribbon fresh={upload.fresh} onPeek={peek} onGallery={gallery} onUpload={upload.pick} />
      ) : (
        <Analysis list={orderTemplates(templates, upload.fresh)} cols={cols} name={templateTitle(fileName)} fileName={fileName}
          steps={upload.steps} facts={upload.facts} out={upload.phase === "out"} error={upload.failure?.text ?? null} canRetry={upload.failure?.retry ?? true}
          info={upload.phase === "fail" ? null : info} onPeek={peek} onGallery={gallery}
          onRetry={upload.retry} onOther={upload.pick} onClose={upload.dismiss} />
      )}
      <UploadZone on={over} />
      <FileInput inputRef={upload.inputRef} onFile={upload.start} />
    </div>
  );
}
