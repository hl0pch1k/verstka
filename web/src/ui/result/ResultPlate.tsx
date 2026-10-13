// Плита 04 «Результат» (слот `p4` колоды; boards/R-aside — утверждённая «Правая колонка целиком», V2 плита 04): над
// рабочей областью — таблетка уведомления, слева — шапка «Слайд N из M», сцена и лента миниатюр, справа — колонка с
// названием, оценкой, вариантами, скачиванием, карточками и ссылками. Содержимое стоит, пока открыт результат, и
// уезжает вниз вместе с плитой (`ui.down`); у каждой презентации — своё (ключ — id), и входит оно лесенкой p2-in
// (160/200/240/280 мс). Данные — resultView; режим «Замечания» (задача 9), слой текста и просмотр на весь экран
// (задача 10) и лист «Подробнее» (задача 11) подключаются сюда своими задачами.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { humanError } from "../../lib/errors";
import { decodeImage } from "../../lib/motion";
import { failReason } from "../../lib/narrate";
import { variantHint } from "../../lib/plain";
import { variantRev, withRev } from "../../lib/rev";
import { fmtWhen } from "../../lib/utils";
import { useApp } from "../../store";
import type { Generation } from "../../types";
import { startFailure } from "../create/params";
import { BUILD_RUNNING } from "../create/ParamsPlate";
import type { SheetTab } from "../deck/geometry";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { Aside, type AsideData } from "./Aside";
import { Film } from "./Film";
import { NotePill, NoteRow } from "./NotePill";
import {
  agentLines, deckPreset, docLine, docTitle, eyesCard, fileBase, latestWithModel, noteView, qualityCard, remarkCount, retryWaitTitle,
  rewriteText, scoreOf, slideHeadline, slidesOf, variantSegs, whyText,
} from "./resultView";
import { Stage } from "./Stage";
import { WorkHead } from "./WorkHead";

/** Плита результата уходит вниз 520 мс; `down` снимается, когда она ушла за край (V2 `go('create')`: 560 мс). */
const DOWN_MS = 560;

/** Лист «Подробнее» на вкладке `tab` (лист рисует задача 11). */
export function useOpenSheet(): (tab: SheetTab) => void {
  const { dispatch } = useApp();
  return useCallback((tab: SheetTab) => dispatch({ type: "sheet", tab }), [dispatch]);
}

/** Клавиши ←/→ листают слайды, пока фокус не в поле и не в элементе со своими стрелками. */
const ownsArrows = (el: EventTarget | null) => {
  const t = el as HTMLElement | null;
  if (!t || typeof t.closest !== "function") return false;
  return t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable
    || !!t.closest('[role="tablist"], [role="dialog"], [role="radiogroup"], [role="menu"], [role="slider"]');
};

export function ResultPlate() {
  const { ui, dispatch, generation, notices } = useApp();
  const on = ui.screen === "result" || ui.down;
  // «Изменить текст», «Дописать текст»: плита уходит вниз непрозрачной вместе со своей презентацией, как с логотипа
  // (`go` сбрасывает `down`, поэтому он ставится после)
  const downTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(downTimer.current), []);
  const goDown = useCallback(() => {
    dispatch({ type: "set", patch: { down: true } });
    window.clearTimeout(downTimer.current);
    downTimer.current = window.setTimeout(() => dispatch({ type: "set", patch: { down: false } }), DOWN_MS);
  }, [dispatch]);
  if (!on) return null;
  if (!generation) {
    // презентация не открылась: строка неудачи на месте уведомления; пока грузится — плита пустая
    const err = notices.result?.kind === "error" ? humanError(notices.result.text) : null;
    return err ? <NoteRow><ErrorLine text={err} lines={1} /></NoteRow> : null;
  }
  if (!generation.variants.length) return <NoDeck key={generation.id} g={generation} goDown={goDown} />;
  return <ResultBody key={generation.id} g={generation} goDown={goDown} />;
}

/** Презентация без вариантов (сборка не удалась): причина и путь к тексту. */
function NoDeck({ g, goDown }: { g: Generation; goDown(): void }) {
  const { editText, dispatch } = useApp();
  const back = () => {
    if (g.brief) editText(g.brief, deckPreset(g));
    else dispatch({ type: "go", screen: "create" });
    goDown();
  };
  return (
    <NoteRow>
      <ErrorLine text={`Не получилось собрать презентацию. ${failReason(g.error)}`} lines={1} />
      <button type="button" className="p2-ob" onClick={back} style={{ flex: "none", height: 40, padding: "0 16px" }}>
        <Icon name="arrow-left" size={18} />
        <span>Вернуться к тексту</span>
      </button>
    </NoteRow>
  );
}

function ResultBody({ g, goDown }: { g: Generation; goDown(): void }) {
  const {
    activeVariant, setActiveStrategy, selectedSlide, setSelectedSlide, strategyTitle, strategies, templateLabel, templates, ui, dispatch,
    editText, retryBuild, building, health, modelStatus, refreshModelStatus, generations, notices,
  } = useApp();
  const openSheet = useOpenSheet();
  const v = activeVariant && g.variants.includes(activeVariant) ? activeVariant : g.variants[0];
  const total = slidesOf(v);
  const n = Math.min(Math.max(1, selectedSlide), Math.max(1, total));
  const rev = variantRev(v);
  const raw = v.slides[n - 1] ?? null;
  const src = raw ? withRev(raw, rev) : null;
  const headline = useCallback((k: number) => slideHeadline(v, k), [v]);
  const title = docTitle(g, v);
  const tpl = templates.find((t) => t.template_id === g.template_id);
  const aspect = tpl?.aspect && tpl.aspect > 0 ? tpl.aspect : 16 / 9;

  // новая презентация открывается со свёрнутой таблеткой (по умолчанию — таблетка)
  const noteOpen = useRef(ui.note);
  useEffect(() => {
    if (noteOpen.current) dispatch({ type: "set", patch: { note: false } });
  }, [dispatch]);

  // уведомление: «Собрать ещё раз» и его совет следуют живому состоянию модели (lib/modelText)
  const latest = useMemo(() => latestWithModel(generations, g), [generations, g]);
  const note = noteView(g, v, total, { status: modelStatus, latest, retryIn: modelStatus?.retry_in ?? 0 });
  const modelFailed = !!g.use_models && g.planner?.by_model === false;
  useEffect(() => {
    if (modelFailed) void refreshModelStatus();
  }, [modelFailed, g.id, refreshModelStatus]);

  // «Изменить текст», «Дописать текст»: «Создать» с текстом и параметрами этой презентации; плита уходит вниз
  const editDeck = (text: string | null) => {
    if (text) editText(text, deckPreset(g));
    else dispatch({ type: "go", screen: "create" });
    goDown();
  };
  // «Собрать ещё раз»: тот же запрос этой презентации; ответ сервера — экран «Сборка» или строка отказа в ряду уведомления
  const [retryAt, setRetryAt] = useState<number | null>(null);
  const refused = startFailure(notices.build, retryAt);
  const starting = retryAt !== null && !refused;
  const rebuildOff = building ? BUILD_RUNNING : note && note.retryWait > 0 ? retryWaitTitle(modelStatus?.retry_state) : null;
  const rebuild = () => {
    if (rebuildOff || starting) return;
    // без текста или без модели повтор дал бы то же самое — к тексту
    if (!g.brief || !health?.models_configured) return editDeck(g.brief ?? null);
    setRetryAt(Date.now());
    void retryBuild(g);
  };
  const resultErr = notices.result?.kind === "error" ? humanError(notices.result.text) : null;
  const errText = refused ?? resultErr;
  const line = errText ? <ErrorLine text={errText} lines={1} style={note ? { marginLeft: 16, flex: "0 1 auto" } : undefined} /> : null;

  // Задачи 9 и 10 заменят эти обработчики: режим «Замечания», «На весь экран», слой «Текст презентации»
  const onToggleRemarks = () => {};
  const onOpenLightbox = () => {};
  const onShowText = () => {};

  // клавиши ←/→ листают слайды, пока поверх результата ничего не открыто
  const layered = !!(ui.sheet || ui.textLayer || ui.lightbox || ui.sect || ui.tplPreview || ui.tplDelete);
  useEffect(() => {
    if (ui.screen !== "result" || layered || total < 2) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || ownsArrows(e.target)) return;
      const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      e.preventDefault();
      setSelectedSlide(n + step);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ui.screen, layered, total, n, setSelectedSlide]);
  // соседние слайды декодируются заранее: ← и → показывают их сразу
  useEffect(() => {
    for (const k of [n + 1, n - 1]) {
      const u = v.slides[k - 1];
      if (u) void decodeImage(withRev(u, rev)).catch(() => {});
    }
  }, [n, v, rev]);

  const agent = useMemo(() => agentLines(v), [v]);
  const score = scoreOf(g, v);
  const name = strategyTitle(v.strategy);
  const aside: AsideData = {
    title,
    line: docLine(templateLabel(g.template_id, g.template_file), total, fmtWhen(g.created_at)),
    score: score === null ? null : Math.round(score),
    variants: variantSegs(g, strategyTitle).map((s) => {
      const hint = variantHint(s.key, strategies.find((x) => x.name === s.key)?.description);
      return { ...s, title: s.score !== null ? `${hint} · оценка качества ${s.score} из 100` : hint };
    }),
    variant: v.strategy,
    pptx: v.files["deck.pptx"] ?? null,
    pdf: v.files["deck.pdf"] ?? null,
    fileBase: fileBase(title, name),
    pptxTitle: `Вариант ${g.variants.indexOf(v) + 1} · ${name}`,
    cards: { quality: qualityCard(g, v), agent, why: whyText(v, n), eyes: eyesCard(v, n), slide: n, variant: v.strategy },
  };
  const h = headline(n);

  return (
    <>
      {note ? (
        <NotePill note={note} open={ui.note} line={line} actions={{
          onToggle: () => dispatch({ type: "set", patch: { note: !ui.note } }),
          onClose: () => dispatch({ type: "set", patch: { note: false } }),
          onShowText,
          onRebuild: rebuild,
          onRewrite: () => editDeck(rewriteText(g) || null),
          rebuildOff,
        }} />
      ) : (
        <NoteRow>{line}</NoteRow>
      )}
      <div className="p2-two" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 416px", gap: 48, height: 548, marginTop: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
          <WorkHead n={n} total={total} title={h} remarks={remarkCount(v)} onPrev={() => setSelectedSlide(n - 1)} onNext={() => setSelectedSlide(n + 1)}
            onToggleRemarks={onToggleRemarks} onOpenLightbox={onOpenLightbox} />
          <Stage src={src} alt={h ? `Слайд ${n}: ${h}` : `Слайд ${n}`} aspect={aspect} />
          <Film slides={v.slides} rev={rev} n={n} headline={headline} onPick={setSelectedSlide} />
        </div>
        <Aside d={aside} onVariant={setActiveStrategy} onEditText={() => editDeck(g.brief ?? null)} open={openSheet} />
      </div>
    </>
  );
}
