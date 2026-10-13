// Плита 04 «Результат» (слот `p4` колоды; boards/R-aside — утверждённая «Правая колонка целиком», V2 плита 04): над
// рабочей областью — таблетка уведомления, слева — шапка «Слайд N из M», сцена и лента миниатюр, справа — колонка с
// названием, оценкой, вариантами, скачиванием, карточками и ссылками. Содержимое стоит, пока открыт результат, и
// уезжает вниз вместе с плитой (`ui.down`); у каждой презентации — своё (ключ — id), и входит оно лесенкой p2-in
// (160/200/240/280 мс). Данные — resultView. Режим «Замечания» (R-remarks/R-fixing/R-fixed: разметка на сцене, бейджи
// ленты, панель на месте колонки, исправление слайда с эскизом и «Вернуть как было») и изображение на слайде
// (R-picture: зона на сцене, колонка с карточкой «Изображение») — remarks.ts, useSlideJob и их компоненты; слой текста
// и просмотр на весь экран (задача 10) и лист «Подробнее» (задача 11, `useOpenSheet`) подключаются своими задачами.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { humanError } from "../../lib/errors";
import { decodeImage, isDecoded } from "../../lib/motion";
import { failReason } from "../../lib/narrate";
import { variantHint } from "../../lib/plain";
import { fmtWhen } from "../../lib/utils";
import { useApp } from "../../store";
import type { Generation, ModelsStatus } from "../../types";
import { startFailure } from "../create/params";
import { BUILD_RUNNING } from "../create/ParamsPlate";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { cls } from "../kit/cls";
import { usePresence } from "../kit/usePresence";
import { Aside, type AsideData } from "./Aside";
import { Film, loadedThumbs } from "./Film";
import { FixSketch, useFixStage } from "./FixSketch";
import { NotePill, NoteRow } from "./NotePill";
import { PictureCard, PictureSpots, type PictureRunView } from "./PictureCard";
import {
  clock, firstRemarkSlide, fixedRows, fixSteps, fixSummary, lastEditIs, pictureView, slideBadges, slidePictures, slideRemarks, slideSketch,
  stageMarks,
} from "./remarks";
import { RemarksPanel, type PanelLine, type PanelRow, type PanelView } from "./RemarksPanel";
import {
  agentLines, deckPreset, docLine, docTitle, eyesCard, fileBase, latestWithModel, noteView, qualityCard, recheckIn, remarkCount, retryLeft,
  retryTick, retryWaitTitle, rewriteText, scoreOf, slideForKey, slideHeadline, slideSrc, slidesOf, switchShots, variantSegs, whyText,
} from "./resultView";
import { Stage } from "./Stage";
import { StageMarks } from "./StageMarks";
import { useCheckTitles } from "./useCheckTitles";
import { useOpenSheet } from "./useOpenSheet";
import { useSlideJob } from "./useSlideJob";
import { WorkHead } from "./WorkHead";

/** Плита результата уходит вниз 520 мс; `down` снимается, когда она ушла за край (V2 `go('create')`: 560 мс). */
const DOWN_MS = 560;
/** Сколько смена варианта ждёт декодирования его картинок, прежде чем смениться как есть. */
const SWITCH_WAIT = 800;

/** Секунд до конца паузы модели (старый `useRetryIn`): пересчёт раз в 15 с и ровно к концу паузы — «Собрать ещё раз»
 *  оживает вовремя. Таймер снимается вместе с экраном и с новым состоянием модели. */
function useRetryIn(st: ModelsStatus | null): number {
  const got = useMemo(() => ({ at: Date.now(), s: st?.retry_in ?? 0 }), [st]);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const ms = retryTick(got.s, got.at, Date.now());
    if (ms === null) return;
    const t = window.setTimeout(() => setNow(Date.now()), ms);
    return () => window.clearTimeout(t);
  }, [got, now]);
  return retryLeft(got.s, got.at, now);
}

/** Секундная стрелка часов хода, пока идёт работа. */
function useTick(on: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    setNow(Date.now());
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [on]);
  return now;
}

/** Клавиши ←/→, Home/End листают слайды, пока фокус не в поле и не в элементе со своими клавишами. */
const ownsKeys = (el: EventTarget | null) => {
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
  const src = v.slides[n - 1] ? slideSrc(v, n) : null;
  const headline = useCallback((k: number) => slideHeadline(v, k), [v]);
  const title = docTitle(g, v);
  const tpl = templates.find((t) => t.template_id === g.template_id);
  const aspect = tpl?.aspect && tpl.aspect > 0 ? tpl.aspect : 16 / 9;

  // новая презентация открывается со свёрнутой таблеткой (по умолчанию — таблетка)
  const noteOpen = useRef(ui.note);
  useEffect(() => {
    if (noteOpen.current) dispatch({ type: "set", patch: { note: false } });
  }, [dispatch]);

  // уведомление: «Собрать ещё раз» и его совет следуют живому состоянию модели (lib/modelText); пауза модели
  // отсчитывается, и кнопка оживает, когда она кончилась
  const latest = useMemo(() => latestWithModel(generations, g), [generations, g]);
  const retryIn = useRetryIn(modelStatus);
  const note = noteView(g, v, total, { status: modelStatus, latest, retryIn });
  const modelFailed = !!g.use_models && g.planner?.by_model === false;
  useEffect(() => {
    if (modelFailed) void refreshModelStatus();
  }, [modelFailed, g.id, refreshModelStatus]);
  // пока модель на паузе, её состояние перепрашивается через 2 с после конца паузы — и снова, пока пауза длится
  const recheck = recheckIn(modelStatus);
  const [round, setRound] = useState(0);
  useEffect(() => {
    if (!modelFailed || !recheck) return;
    let off = false;
    const t = window.setTimeout(() => {
      void refreshModelStatus().finally(() => {
        if (!off) setRound((r) => r + 1);
      });
    }, recheck * 1000);
    return () => {
      off = true;
      window.clearTimeout(t);
    };
  }, [modelFailed, recheck, round, refreshModelStatus]);

  // «Изменить текст», «Дописать текст»: «Создать» с текстом и параметрами этой презентации; плита уходит вниз
  const editDeck = (text: string | null) => {
    if (text) editText(text, deckPreset(g));
    else dispatch({ type: "go", screen: "create" });
    goDown();
  };
  // «Собрать ещё раз»: тот же запрос этой презентации; ответ сервера — экран «Сборка» или строка отказа в ряду уведомления.
  // Между кликом и ответом кнопка занята (дуга загрузки, aria-busy), второй клик сборку не повторяет
  const [retryAt, setRetryAt] = useState<number | null>(null);
  const [asking, setAsking] = useState(false);
  const refused = startFailure(notices.build, retryAt);
  const rebuildOff = building ? BUILD_RUNNING : note && note.retryWait > 0 ? retryWaitTitle(modelStatus?.retry_state) : null;
  const rebuild = () => {
    if (rebuildOff || asking) return;
    // без текста или без модели повтор дал бы то же самое — к тексту
    if (!g.brief || !health?.models_configured) return editDeck(g.brief ?? null);
    setRetryAt(Date.now());
    setAsking(true);
    // обещание решается отказом сразу, а принятая сборка уводит на «Сборку» (экран результата уходит вместе с кнопкой)
    void retryBuild(g).finally(() => setAsking(false));
  };
  const resultErr = notices.result?.kind === "error" ? humanError(notices.result.text) : null;
  const errText = refused ?? resultErr;
  const line = errText ? <ErrorLine text={errText} lines={1} style={note ? { marginLeft: 16, flex: "0 1 auto" } : undefined} /> : null;

  // Задача 10 заменит эти обработчики: «На весь экран», слой «Текст презентации»
  const onOpenLightbox = () => {};
  const onShowText = () => {};

  // ── работа над слайдом: исправление, изображение, «Вернуть как было» (одна задача на вариант за раз)
  const titleOf = useCheckTitles();
  const job = useSlideJob(g.id, v.strategy);
  const run = job.run;
  const here = !!run && run.strategy === v.strategy && run.slide === n;
  const fixWork = run?.kind === "fix" && run.phase === "work" ? run : null;
  const now = useTick(job.busy);
  const busyWhy = !job.busy || !run ? null
    : run.undo === "work" ? "Возвращаю как было — дождитесь конца"
      : run.kind === "fix" ? `Агент сейчас исправляет слайд ${run.slide}` : `Агент меняет изображение на слайде ${run.slide}`;

  // ── режим «Замечания» (V2 `rmToggle`): панель на месте колонки, разметка на сцене, бейджи ленты
  const rm = usePresence(ui.remarks, 520);
  const rmSince = useRef(0);
  const open = useMemo(() => slideRemarks(v, n, titleOf), [v, n, titleOf]);
  const fixRun = here && run?.kind === "fix" ? run : null;
  const fx = useFixStage(fixRun && fixRun.jobId && rm.mounted ? fixRun.seq : null, fixRun?.phase === "done", src);
  const fixing = !!fixRun && (fixRun.phase === "work" || fx !== null);
  const fixDone = !!fixRun && !fixing && fixRun.phase === "done" && !!fixRun.fix?.applied;
  const view: PanelView = fixing ? "fix" : fixDone ? "done" : open.length ? "rem" : "none";
  const rows: PanelRow[] = useMemo(
    () => (view === "fix" ? fixRun!.requested : view === "done" ? fixedRows(fixRun!.requested, fixRun!.fix!, open) : open),
    [view, fixRun, open],
  );
  const viewKey = `${v.strategy}:${n}:${view}`;
  const [selAt, setSelAt] = useState<{ k: string; i: number } | null>(null);
  const sel = selAt?.k === viewKey ? selAt.i : view === "rem" || view === "fix" ? 0 : -1;
  const marks = useMemo(() => stageMarks(rows, sel), [rows, sel]);
  const [wishAt, setWishAt] = useState({ k: "", t: "" });
  const slideKey = `${v.strategy}:${n}`;
  const wish = wishAt.k === slideKey ? wishAt.t : "";
  const remarksOff = fixWork ? `Агент исправляет слайд ${fixWork.slide}` : null;
  const onToggleRemarks = () => {
    if (remarksOff) return;
    if (ui.remarks) return dispatch({ type: "set", patch: { remarks: false } });
    rmSince.current = Date.now();
    setPicSel(null); // панель встаёт на место колонки — и колонки «Изображение»
    // на открытом слайде замечаний нет (и нет итога исправления) — к первому слайду с ними
    if (!open.length && !fixDone) {
      const to = firstRemarkSlide(v, n);
      if (to !== null && to !== n) setSelectedSlide(to);
    }
    dispatch({ type: "set", patch: { remarks: true } });
  };
  const onFix = () => {
    if (job.busy || !open.length) return;
    void job.start("fix", n, { wishes: wish.trim() || null, issue_ids: open.map((r) => r.id) }, open).then((ok) => {
      if (ok) setWishAt({ k: "", t: "" });
    });
  };
  const lower = (t: string) => t.charAt(0).toLowerCase() + t.slice(1);
  const panelLine: PanelLine | null = fixRun && fixRun.phase === "done" && !fixing
    ? fixRun.error ? { tone: "error", text: fixRun.error }
      : fixRun.fix && !fixRun.fix.applied ? { tone: "info", text: `Слайд остался прежним: ${lower((fixRun.fix.why ?? "замечания остались").replace(/\.\s*$/, ""))}` } : null
    : null;
  const steps = fixRun ? fixSteps(job.live.events, fixRun.phase === "done") : null;
  const summary = fixDone ? fixSummary(fixRun!.fix!) : null;
  const badges = useMemo(() => slideBadges(v), [v]);

  // ── изображение на слайде (V2 `rtTogglePic`): клик по картинке — рамка и колонка с карточкой «Изображение»
  const pics = useMemo(() => slidePictures(v, n), [v, n]);
  const [picSel, setPicSel] = useState<{ k: string; id: string; form: boolean; d: number } | null>(null);
  // другой слайд или вариант — выбор картинки снимается (V2 `rtStale`), возврат на слайд колонку не открывает; строка
  // неудачи или «слайд остался прежним» уходит вместе со слайдом (итог применённой работы остаётся — у него «Вернуть»)
  const clearJob = job.clear;
  const settledWithout = !!run && run.phase === "done" && !run.fix?.applied && !run.picture?.applied;
  useEffect(() => {
    setPicSel(null);
    if (settledWithout) clearJob();
  }, [slideKey]); // только смена слайда: строка, пришедшая на этом слайде, остаётся
  const picked = picSel && picSel.k === slideKey ? pics.find((p) => p.id === picSel.id) ?? pics[0] ?? null : null;
  const picOn = !!picked && !rm.mounted;
  const pcol = usePresence(picOn, 280);
  const lastPic = useRef(picked);
  if (picked) lastPic.current = picked;
  const shownPic = picked ?? lastPic.current;
  const [picWish, setPicWish] = useState("");
  const onPickPic = (id: string) => {
    if (picSel && picSel.k === slideKey && picked?.id === id && picSel.form) return setPicSel(null);
    setPicSel({ k: slideKey, id, form: true, d: picOn ? 40 : 320 });
  };
  const picRun = here && run?.kind === "picture" ? run : null;
  const picRunView: PictureRunView = {
    work: picRun?.phase === "work" ? "change" : picRun?.undo === "work" ? "undo" : null,
    action: picRun?.action ?? null,
    progress: picRun?.phase === "work" ? job.live.progress : 0,
    message: job.live.message,
    clock: picRun ? clock((picRun.phase === "work" ? now : picRun.endedAt ?? now) - picRun.startedAt) : "0:00",
    done: picRun?.phase === "done" && picRun.picture?.applied && picRun.undo !== "work" ? picRun.action : null,
    canUndo: !!picRun?.picture?.applied && lastEditIs(v, picRun.picture.version, "picture"),
    error: picRun ? picRun.undoError ?? picRun.error : null,
  };
  const picStart = (action: "generate" | "remove") => {
    if (job.busy) return;
    void job.start("picture", n, action === "remove" ? { action } : { action, wish: picWish.trim() || null }).then((ok) => {
      if (!ok) return;
      setPicWish("");
      setPicSel((x) => (x ? { ...x, form: false } : x));
    });
  };
  // клавиши ←/→ листают слайды, Home/End — к первому и последнему, пока поверх результата ничего не открыто
  const layered = !!(ui.sheet || ui.textLayer || ui.lightbox || ui.sect || ui.tplPreview || ui.tplDelete);
  // Esc снимает выбор картинки (колонка «Изображение» уходит), пока поверх ничего не открыто
  useEffect(() => {
    if (!picOn || layered) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || ownsKeys(e.target)) return;
      setPicSel(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [picOn, layered]);
  useEffect(() => {
    if (ui.screen !== "result" || layered || total < 2) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || ownsKeys(e.target)) return;
      const to = slideForKey(e.key, n, total);
      if (to === null) return;
      e.preventDefault();
      if (to !== n) setSelectedSlide(to);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ui.screen, layered, total, n, setSelectedSlide]);
  // заранее декодируются соседние слайды (← и → показывают их сразу) и этот же слайд в каждом варианте (смена варианта
  // не ждёт картинку)
  useEffect(() => {
    const urls = [n + 1, n - 1].filter((k) => k >= 1 && k <= v.slides.length).map((k) => slideSrc(v, k));
    for (const x of g.variants) urls.push(slideSrc(x, n));
    for (const u of urls) if (u) void decodeImage(u).catch(() => {});
  }, [n, v, g]);

  // смена варианта: сперва декодируются его слайд и картинки показанных миниатюр (не дольше SWITCH_WAIT), потом вариант
  // меняется весь сразу — сцена, лента, оценка и сегмент вместе, без серых провалов. Новый выбор отменяет прежний
  const film = useRef<HTMLDivElement>(null);
  const pick = useRef({ seq: 0, timer: 0 });
  useEffect(() => () => {
    pick.current.seq++;
    window.clearTimeout(pick.current.timer);
  }, []);
  const pickVariant = (key: string) => {
    const p = pick.current;
    const seq = ++p.seq;
    window.clearTimeout(p.timer);
    const target = g.variants.find((x) => x.strategy === key);
    const urls = target && target !== v ? switchShots(target, n, loadedThumbs(film.current)) : [];
    if (urls.every(isDecoded)) return setActiveStrategy(key);
    const go = () => {
      if (seq !== p.seq) return;
      p.seq++;
      window.clearTimeout(p.timer);
      setActiveStrategy(key);
    };
    p.timer = window.setTimeout(go, SWITCH_WAIT);
    void Promise.all(urls.map((u) => decodeImage(u).catch(() => {}))).then(go);
  };

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
          rebuildBusy: asking,
        }} />
      ) : (
        <NoteRow>{line}</NoteRow>
      )}
      <div className="p2-two" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 416px", gap: 48, height: 548, marginTop: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", minWidth: 0, gridArea: "1 / 1" }}>
          <WorkHead n={n} total={total} title={h} remarks={remarkCount(v)} remarksOn={ui.remarks} remarksOff={remarksOff}
            onPrev={() => setSelectedSlide(n - 1)} onNext={() => setSelectedSlide(n + 1)} onToggleRemarks={onToggleRemarks} onOpenLightbox={onOpenLightbox} />
          <Stage src={src} alt={h ? `Слайд ${n}: ${h}` : `Слайд ${n}`} aspect={aspect}>
            {pics.length > 0 && !rm.mounted && <PictureSpots pics={pics} sel={picked?.id ?? null} frame={!!picked && !!picSel?.form} onPick={onPickPic} />}
            {rm.mounted && (
              <StageMarks k={viewKey} frames={marks.frames} pins={marks.pins} oks={marks.oks} out={!rm.shown || fixing}
                delay={Date.now() - rmSince.current < 300 ? 200 : 0} onPick={(id) => setSelAt({ k: viewKey, i: rows.findIndex((r) => r.id === id) })} />
            )}
            {fx && <FixSketch phase={fx} {...slideSketch(v, n, job.live.events)} />}
          </Stage>
          <Film film={film} variant={v} n={n} headline={headline} onPick={setSelectedSlide}
            marks={rm.mounted ? { badges, out: !rm.shown, spin: fixWork && fixWork.strategy === v.strategy ? fixWork.slide : null } : null} />
        </div>
        <Aside d={aside} onVariant={pickVariant} onEditText={() => editDeck(g.brief ?? null)} open={openSheet} className="ra-main" hidden={rm.shown || pcol.shown} />
        {pcol.mounted && shownPic && (
          <Aside d={aside} onVariant={pickVariant} onEditText={() => editDeck(g.brief ?? null)} open={openSheet} id="rt-pcol" enter={false} bottom
            className={cls("rt-pcw", pcol.shown ? "p2-on" : "p2-off")} style={{ position: "relative", zIndex: 1 }}
            extra={
              <PictureCard view={pictureView(shownPic)} form={!!picSel?.form && picOn} formDelay={picSel?.d ?? 320} wish={picWish} onWish={setPicWish}
                onToggleForm={() => setPicSel((x) => (x ? { ...x, form: !x.form, d: 40 } : x))}
                onCancel={() => {
                  setPicSel((x) => (x ? { ...x, form: false } : x));
                  setPicWish("");
                }}
                onGenerate={() => picStart("generate")} onRemove={() => picStart("remove")} onUndo={job.undo} run={picRunView}
                off={job.busy && !picRunView.work ? busyWhy : null} />
            } />
        )}
        {rm.mounted && (
          <RemarksPanel shown={rm.shown} since={rmSince.current} n={n} view={view} rows={rows} sel={sel} onSel={(i) => setSelAt({ k: viewKey, i })}
            wish={wish} onWish={(t) => setWishAt({ k: slideKey, t })} onFix={onFix} fixOff={job.busy ? busyWhy : null} line={view === "rem" ? panelLine : null}
            elsewhere={badges.size > 0}
            progress={view === "fix" && fixRun && steps ? {
              clock: clock((fixRun.endedAt ?? now) - fixRun.startedAt), value: fixRun.phase === "work" ? job.live.progress : 1,
              steps: steps.steps, preview: steps.preview, wish: fixRun.wish,
            } : null}
            done={summary && fixRun ? {
              summary, onShow: () => summary.show !== null && setSelectedSlide(summary.show), onUndo: job.undo,
              canUndo: lastEditIs(v, fixRun.fix!.version, "fix"), undoBusy: fixRun.undo === "work", undoError: fixRun.undoError,
            } : null} />
        )}
      </div>
    </>
  );
}
