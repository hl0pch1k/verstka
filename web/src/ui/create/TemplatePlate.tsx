// Плита 01 «Шаблон»: справа в заголовке — выбранный шаблон и «Сменить» (шаг свёрнут) или «Готово» (раскрыт); тело
// `#p2-b1` — лента обложек (C-templates), файл над шагом (C-upload) и разбор загруженного файла (C-analyzing).
// Разметка — boards/V2.dc.html, плита 01 и модуль tp. Загрузка живёт в `useTemplateUpload` (AppShell): её начинают
// и плитка ленты, и перетаскивание на плиту, и «Загрузить свой» в разделе «Шаблоны».
import { useCallback, useEffect, useRef, useState, type CSSProperties, type RefObject } from "react";
import { useApp } from "../../store";
import { templateTitle, tplLabel } from "../../lib/plain";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { Analysis } from "./Analysis";
import { Cover, inkOf, Ribbon } from "./TemplateRibbon";
import { analysisFacts, analysisSteps, ANALYSIS_STEPS, orderTemplates, tplMeta, type AnalysisFacts, type StepState } from "./ribbon";
import { FileInput, UploadZone, useFileDrop } from "./UploadZone";

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
  /** Текст неудачи (fail). */
  error: string | null;
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

  const pick = useCallback(() => inputRef.current?.click(), []);
  const retry = useCallback(() => {
    if (file) start(file);
  }, [file, start]);
  const dismiss = useCallback(() => {
    setPhase("idle");
    setError(null);
    clearNotice("template");
  }, [clearNotice]);
  return { phase, file, fresh, error, steps, facts, inputRef, start, pick, retry, dismiss };
}

const NOTE: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0, maxWidth: 480, fontSize: 14, fontWeight: 600, lineHeight: "20px",
  color: "#DC2626", whiteSpace: "nowrap",
};

/** Заголовок плиты 01 справа (слот `h1`): выбранный шаблон и «Сменить», на раскрытом шаге — «Готово». Строка ошибки
 *  области «Шаблон», которая пришла не от разбора (список, манифест), стоит перед ними. */
export function TemplateHead({ upload }: { upload: TemplateUpload }) {
  const { ui, dispatch, templates, templateId, notices } = useApp();
  const open = ui.screen === "create" && ui.open === "tpl";
  const t = templates.find((x) => x.template_id === templateId);
  const note = upload.phase === "idle" && notices.template?.kind === "error" ? notices.template.text : null;
  return (
    <>
      <span style={{ flex: 1, minWidth: 0 }} />
      {note && (
        <span role="alert" style={NOTE} title={note}>
          <Icon name="alert" size={16} />
          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{note}</span>
        </span>
      )}
      {open ? (
        <div key="open" className="p2-in" style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <button type="button" className="p2-ob" onClick={() => dispatch({ type: "open", step: "text" })} style={{ height: 40 }}>Готово</button>
        </div>
      ) : (
        <div key="closed" className="p2-in" style={{ display: "flex", alignItems: "center", gap: 24 }}>
          {t && (
            <div style={{ display: "flex", alignItems: "center", gap: 16, minWidth: 0 }}>
              <Cover src={t.cover_url} kind="m" ink={inkOf(t)} label={`Обложка шаблона ${tplLabel(t)}`} />
              <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                <span style={{ fontSize: 15, fontWeight: 700, lineHeight: "24px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{tplLabel(t)}</span>
                <span style={{ fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap" }}>{tplMeta(t)}</span>
              </div>
            </div>
          )}
          <button type="button" className="p2-ob" onClick={() => dispatch({ type: "open", step: "tpl" })} style={{ height: 40 }}>
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
  const on = ui.screen === "create" && ui.open === "tpl" && !ui.more;
  const body = useRef<HTMLDivElement>(null);
  const busy = BUSY.includes(upload.phase);
  const over = useFileDrop(body, on && !busy, upload.start);
  const peek = (id: string) => dispatch({ type: "set", patch: { tplPreview: id, tplDelete: null } });
  const gallery = () => dispatch({ type: "sect", sect: "tpls" });
  const fileName = upload.file?.name ?? "";
  const info = notices.template?.kind === "info" ? notices.template.text : null;
  return (
    <div id="p2-b1" ref={body} className={cls("p2-body p2-g4", on ? "p2-on" : "p2-off")}
      style={{ position: "relative", display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 16, margin: "24px 0 0 192px" }}>
      {upload.phase === "idle" ? (
        <Ribbon fresh={upload.fresh} onPeek={peek} onGallery={gallery} onUpload={upload.pick} />
      ) : (
        <Analysis list={orderTemplates(templates, upload.fresh)} name={templateTitle(fileName)} fileName={fileName}
          steps={upload.steps} facts={upload.facts} out={upload.phase === "out"} error={upload.phase === "fail" ? upload.error : null}
          info={upload.phase === "fail" ? null : info} onPeek={peek} onGallery={gallery}
          onRetry={upload.retry} onOther={upload.pick} onClose={upload.dismiss} />
      )}
      <UploadZone on={over} />
      <FileInput inputRef={upload.inputRef} onFile={upload.start} />
    </div>
  );
}
