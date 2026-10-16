// Плита 04 «Результат» (слот `p4` колоды; boards/R-aside — утверждённая «Правая колонка целиком», V2 плита 04): над
// рабочей областью — таблетка уведомления (сказать нечего — ряда нет, рабочая область выше и сцена шире, как на R-remarks:
// resultView `workGeo`), слева — шапка «Слайд N из M», сцена и лента миниатюр, справа — колонка с
// названием, оценкой, вариантами, скачиванием, карточками и ссылками. Содержимое стоит, пока открыт результат, и
// уезжает вниз вместе с плитой (`ui.down`); у каждой презентации — своё (ключ — id), и входит оно лесенкой p2-in
// (160/200/240/280 мс). Данные — resultView. Режим «Замечания» (R-remarks/R-fixing/R-fixed: разметка на сцене, бейджи
// ленты, панель на месте колонки, исправление слайда с эскизом и «Вернуть как было») — useRemarksMode; изображение на
// слайде (R-picture: зона на сцене, колонка с карточкой «Изображение») — usePictureSelect; работа над слайдом —
// useSlideJob. «Показать текст» и «На весь экран» открывают слои колоды (ui/layers TextLayer, Lightbox); пока открыт
// слой текста, над ним видна полоса «04 Результат» этой плиты (R-text), клик по ней закрывает слой. Карточки и ссылки
// колонки открывают лист «Подробнее» (`useOpenSheet`, ui/details); пока он открыт, над ним видна полоса «04 …» (BackStrip).
// Помощник сужает колоду — результат переходит в компактный вид (CompactResult, helper.css): шапка с действиями-иконками
// вместо уведомления (его действия — за значком «i»), узкая колонка вместо полной; в режиме «Замечания» и с выбранным
// изображением колонка шире — смена ширины перекрёстным затуханием (useSwap), а не ходом сетки. Карточка «Изображение»
// одна: в колонке того вида, что на месте (при смене вида — в компактную встаёт через 120 мс, из полной уходит ещё через
// 120 мс, когда та погасла). Панель замечаний меняет ширину колонки (416 ↔ 320) вместе с помощником перекрёстным
// затуханием своего содержимого (RemarksPanel).
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { humanError } from "../../lib/errors";
import { decodeImage, isDecoded } from "../../lib/motion";
import { variantHint } from "../../lib/plain";
import { fmtWhen } from "../../lib/utils";
import { useApp } from "../../store";
import type { Generation, ModelsStatus } from "../../types";
import { useHeld } from "../create/ImproveNote";
import { startFailure } from "../create/params";
import { BUILD_RUNNING } from "../create/ParamsPlate";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { cls } from "../kit/cls";
import { usePresence } from "../kit/usePresence";
import { SWAP_OUT, useSwap } from "../kit/useSwap";
import { useDeckFit } from "../deck/useDeckFit";
import { BackStrip } from "../details/BackStrip";
import { useGoHome } from "../shell/useGoHome";
import { textStripMeta, writtenText } from "../layers/writerText";
import { Aside, type AsideData } from "./Aside";
import { compactChecks, headTight } from "./compact";
import { CompactResult, type CompactData } from "./CompactResult";
import { Film, loadedThumbs } from "./Film";
import { FixSketch } from "./FixSketch";
import { NotePill, NoteRow, type NoteActions } from "./NotePill";
import { PictureCard, PictureSpots } from "./PictureCard";
import { RemarksPanel } from "./RemarksPanel";
import {
  agentLines, deckBrand, deckPreset, deckTemplate, docLine, docTitle, eyesCard, fileBase, whyFile, latestWithModel, noDeckText, noteView, ownsKeys, qualityCard, recheckIn, remarkCount,
  retryLeft, retryTick, retryWaitTitle, rewriteText, scoreOf, slideForKey, slideHeadline, slideSrc, slidesOf, switchShots, variantSegs, whyText,
  WORK_GEO, workGeo,
} from "./resultView";
import { Stage } from "./Stage";
import { StageMarks } from "./StageMarks";
import { slideRemarks, type Tone } from "./marks";
import { slideEditKind } from "./fix";
import { useCheckTitles } from "./useCheckTitles";
import { useOpenSheet } from "./useOpenSheet";
import { usePictureSelect } from "./usePictureSelect";
import { useRemarksMode } from "./useRemarksMode";
import { useSlideJob, type SlideRun } from "./useSlideJob";
import { compactRow, failInRow, placeShown, staleInRow, type ResultAt, type SlideFail } from "./slideJob";
import { StaleLine } from "../shell/StaleLine";
import { WorkHead } from "./WorkHead";

/** Сколько смена варианта ждёт декодирования его картинок, прежде чем смениться как есть. */
const SWITCH_WAIT = 800;
const NO_BADGES = new Map<number, { count: number; tone: Tone }>();

/** Секунд до конца паузы модели: пересчёт раз в 15 с и ровно к концу паузы — «Собрать ещё раз»
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

export function ResultPlate() {
  const { ui, generation, notices } = useApp();
  // с результата на «Создать» (логотип, «Изменить текст», «Дописать текст», помощник) плита уходит вниз непрозрачной
  // вместе со своей презентацией: `go` ставит `down`
  const on = ui.screen === "result" || ui.down;
  if (!on) return null;
  if (!generation) {
    // презентация не открылась: строка неудачи на месте уведомления; пока грузится — плита пустая
    const err = notices.result?.kind === "error" ? humanError(notices.result.text) : null;
    return err ? <NoteRow><ErrorLine text={err} lines={1} /></NoteRow> : null;
  }
  if (!generation.variants.length) return <NoDeck key={generation.id} g={generation} />;
  return <ResultBody key={generation.id} g={generation} />;
}

/** Презентация без вариантов (сборка не удалась): причина и путь к тексту. */
function NoDeck({ g }: { g: Generation }) {
  const { editText, dispatch } = useApp();
  const back = () => {
    if (g.brief) editText(g.brief, deckPreset(g));
    else dispatch({ type: "go", screen: "create" });
  };
  return (
    <NoteRow>
      <ErrorLine text={noDeckText(g.error)} lines={1} />
      <button type="button" className="p2-ob" onClick={back} style={{ flex: "none", height: 40, padding: "0 16px" }}>
        <Icon name="arrow-left" size={18} />
        <span>Вернуться к тексту</span>
      </button>
    </NoteRow>
  );
}

function ResultBody({ g }: { g: Generation }) {
  const {
    activeVariant, setActiveStrategy, selectedSlide, setSelectedSlide, strategyTitle, strategies, templateLabel, templates, ui, dispatch,
    editText, retryBuild, building, health, modelStatus, refreshModelStatus, generations, notices, slideFail, feedRefresh,
  } = useApp();
  const openSheet = useOpenSheet();
  const goHome = useGoHome();
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

  // «На весь экран» и «Показать текст» — слои колоды (Lightbox, TextLayer); текста нет — кнопка приглушена (V2 rt-nb-off)
  const onOpenLightbox = () => dispatch({ type: "set", patch: { lightbox: true } });
  const hasText = !!writtenText(g.writer);
  const onShowText = () => {
    if (hasText) dispatch({ type: "set", patch: { textLayer: true } });
  };
  const closeText = () => dispatch({ type: "set", patch: { textLayer: false } });

  // ── работа над слайдом: исправление, изображение, «Вернуть как было» (одна задача на вариант за раз)
  const titleOf = useCheckTitles();
  // подхваченная работа над слайдом (начатая до возвращения сюда, помощником): замечания слайда — ряды карточки хода;
  // что вернёт «Вернуть как было» — род последнего изменения слайда; видит ли человек её место — для строки неудачи
  const look = useRef<(r: SlideRun) => boolean>(() => false);
  const job = useSlideJob(g.id, v.strategy, {
    remarksOf: (k) => slideRemarks(v, k, titleOf),
    undoKind: (k) => slideEditKind(v, k),
    looking: (r) => look.current(r),
  });
  const now = useTick(job.busy);
  // другой слайд или вариант: строка неудачи или «слайд остался прежним» уходит вместе со слайдом (итог применённой
  // работы остаётся — у него «Вернуть»)
  const clearJob = job.clear;
  useEffect(() => clearJob(), [v.strategy, n, clearJob]);
  // после снятия строк этого кадра — неудача, до места которой дошли, отмечается увиденной (а не снимается сразу)
  const seeJob = job.see;
  useEffect(() => seeJob());
  const rm = useRemarksMode({ v, n, src, job, now, titleOf });
  // поверх результата открыт слой или лист: клавиши (←/→, Home/End, Esc) — его
  const layered = !!(ui.sheet || ui.textLayer || ui.lightbox || ui.sect || ui.tplPreview || ui.tplDelete);
  const pic = usePictureSelect({ v, n, job, now, blocked: ui.remarks || rm.mounted, remarks: ui.remarks, layered });
  // где человек: место работы над слайдом — панель замечаний или карточка «Изображение» на её слайде, ничего поверх
  const at: ResultAt = { result: ui.screen === "result", layered, strategy: v.strategy, slide: n, remarks: ui.remarks, picture: !!pic.column?.shown };
  look.current = (r) => placeShown(r, at);

  // строка ряда уведомления (одна): неудача запуска или открытия; неудача работы над слайдом, чьё место человек не видел
  // (`slideFail`, с «Показать» — к месту, где строка встанет у работы; пока место на экране, строки здесь нет — одна
  // строка на неудачу); запасная строка «не обновилась» с «Обновить», когда презентация несвежая, а её не говорит ни
  // одна работа экрана. Смена строки — перекрёстным затуханием
  const fail = failInRow(slideFail, g.id, at);
  const staleRow = !errText && !fail && job.refresh && staleInRow(true, job.staleRuns, at) ? job.refresh : null;
  const showFail = (f: SlideFail) => {
    if (f.strategy !== v.strategy) setActiveStrategy(f.strategy);
    setSelectedSlide(f.slide);
    dispatch({ type: "set", patch: { remarks: f.kind === "fix" } });
    // изображение: его карточка — когда вариант сменился и режим «Замечания» погас (usePictureSelect ждёт)
    if (f.kind === "picture") pic.reveal(f.strategy, f.slide);
  };
  const lineStyle = note ? { marginLeft: 16, flex: "0 1 auto" } : undefined;
  const lineKey = errText ? `e:${errText}` : fail ? `f:${fail.jobId}` : staleRow ? "s" : "";
  const lineNow = errText ? <ErrorLine text={errText} lines={1} />
    : fail ? (
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <ErrorLine text={fail.text} lines={1} />
        <button type="button" className="p2-gb" onClick={() => showFail(fail)} title={fail.kind === "fix" ? `Слайд ${fail.slide} в режиме «Замечания»` : `Слайд ${fail.slide}`}
          style={{ flex: "none", height: 32, margin: "-6px -12px -6px 0", padding: "0 12px", fontSize: 14, lineHeight: "20px" }}>
          Показать
        </button>
      </div>
    )
    : staleRow ? <StaleLine r={staleRow} lines={1} /> : null;
  // уходящая строка гаснет со своим содержимым: последнее содержимое каждой строки, пока она на экране
  const lines = useRef(new Map<string, ReactNode>());
  if (lineKey) lines.current.set(lineKey, lineNow);
  const lineSwap = useSwap(lineKey, ui.screen === "result");
  const lineShown = lineSwap.shown === lineKey ? lineNow : lines.current.get(lineSwap.shown) ?? null;
  for (const k of [...lines.current.keys()]) if (k !== lineKey && k !== lineSwap.shown) lines.current.delete(k);
  // уходящая строка в ряду уведомления гаснет, а не пропадает; раскладка рабочей области — по строке, которая есть сейчас
  const line = lineKey || lineSwap.shown ? <span className={lineSwap.cls} style={{ display: "flex", minWidth: 0, ...lineStyle }}>{lineShown}</span> : null;
  // компактный вид (помощник открыт): та же строка с тем же действием; «не обновилась» — только если лента помощника не
  // говорит этого живой строкой
  const row = compactRow({ err: errText, fail, stale: staleRow?.text ?? null, feedSays: g.id in feedRefresh });
  const compactErr: CompactData["error"] = row && {
    text: row.text,
    title: row.title,
    act: row.act === "show" && fail ? { label: "Показать", title: fail.kind === "fix" ? `Слайд ${fail.slide} в режиме «Замечания»` : `Слайд ${fail.slide}`, onClick: () => showFail(fail) }
      : row.act === "refresh" && staleRow ? { label: "Обновить", title: "Перечитать презентацию", busy: staleRow.busy, icon: "refresh", onClick: staleRow.onRefresh }
      : null,
  };
  // работа над слайдом (своя, подхваченная, чужая над вариантом) — дуга на миниатюре её слайда и без режима «Замечания»
  const spinOnly = job.spin;
  const filmMarks = useMemo(() => rm.film ?? (spinOnly !== null ? { badges: NO_BADGES, out: false, spin: spinOnly } : null), [rm.film, spinOnly]);
  // клавиши ←/→ листают слайды, Home/End — к первому и последнему, пока поверх результата ничего не открыто
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
    line: docLine(templateLabel(deckTemplate(g), g.template_file), total, fmtWhen(g.created_at), deckBrand(g)),
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
    cards: { quality: qualityCard(g, v), agent, why: whyText(v, n), whyFile: whyFile(v, n), eyes: eyesCard(v, n), slide: n, variant: v.strategy },
  };
  const h = headline(n);
  // компактный вид (помощник открыт): те же данные, итоги проверки — узкой колонкой; колонка шире, пока на её месте
  // панель замечаний или карточка «Изображение»
  const compact: CompactData = {
    title, line: aside.line, error: compactErr, score: aside.score, variants: aside.variants, variant: v.strategy, pptx: aside.pptx, pdf: aside.pdf,
    fileBase: aside.fileBase, pptxTitle: aside.pptxTitle, checks: compactChecks(g, v, note), hasText,
  };
  const wide = rm.shown || !!pic.column?.shown;
  // колонка компактного вида 184 ↔ 320: слайд и колонка гаснут, сетка подменяется невидимой, новое проявляется (без хода
  // ширины); при закрытом помощнике ширина колонки не меняется — сразу
  const swap = useSwap(wide, ui.helper);
  // карточка «Изображение» — одна, в колонке того вида, что сейчас на месте. В компактную она встаёт через 120 мс (та ещё
  // невидима), из полной уходит ещё через 120 мс: к тому времени колонка погасла (240 мс) — уйди карточка раньше, всё
  // остальное содержимое колонки (внизу, `column-reverse`) подскочило бы на её высоту на 16-процентной видимости
  const compactCard = useSwap(ui.helper).shown;
  const fullCard = usePresence(!compactCard, SWAP_OUT).mounted;
  // шапка рабочей области в тесной колоде рядом с колонкой 320 — без подписи «Замечания» (helper.css `.ra-whx`): смена —
  // перекрёстным затуханием шапки, пока результат на экране; в подмене сетки (`swap`, слайд уже невидим) — сразу
  const head = useSwap(headTight(useDeckFit(), swap.shown) ? "tight" : "wide", ui.screen === "result" && swap.phase === null);
  const noteActions: NoteActions = {
    onToggle: () => dispatch({ type: "set", patch: { note: !ui.note } }),
    onClose: () => dispatch({ type: "set", patch: { note: false } }),
    onShowText,
    textOff: hasText ? null : "Для этой презентации текст недоступен",
    onRebuild: rebuild,
    onRewrite: () => editDeck(rewriteText(g) || null),
    rebuildOff,
    rebuildBusy: asking,
  };
  // раскладка рабочей области (resultView `workGeo`): есть уведомление или строка неудачи — ряд 48 над ней и p2-two 548
  // (R-aside); нет — p2-two 612 с самого верха и сцена до 832 (R-remarks, R-fixing, R-fixed, R-text, R-picture).
  // Уведомление появилось или ушло на той же презентации — рабочая область вместе с рядом гаснет, раскладка подменяется
  // невидимой и проявляется (useSwap на обёртке `.ra-work`), без хода высоты и ширины; уходящий ряд гаснет со своим
  // содержимым (`useHeld`)
  const geo = useSwap(workGeo(note, lineKey || null), ui.screen === "result");
  const g2 = WORK_GEO[geo.shown];
  const noteRow = note ? <NotePill note={note} open={ui.note} line={line} actions={noteActions} /> : line ? <NoteRow>{line}</NoteRow> : null;
  const heldRow = useHeld(noteRow);

  return (
    <>
      {/* полоса результата под слоем «Текст презентации» (R-text): кликабельна — «Вернуться к результату». Полоса гаснет
          вместе со слоем: фокус с неё снимается, и слой возвращает его туда, откуда его открыли */}
      <div className={ui.textLayer ? "p2-on" : "p2-off"}>
        <button type="button" className="rt-strip" onClick={(e) => { e.currentTarget.blur(); closeText(); }} aria-label="Вернуться к результату">
          <span style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 700, fontSize: 13, lineHeight: "20px", color: "#5A6272" }}>04</span>
          <span className="rt-strip-t" style={{ fontSize: 14, fontWeight: 700, lineHeight: "20px", color: "#0B1220" }}>Результат</span>
          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>
            {textStripMeta(name, score, n, total)}
          </span>
        </button>
      </div>
      {/* полоса «04 …» под листом «Подробнее»: клик закрывает лист */}
      <BackStrip g={g} v={v} />
      <CompactResult d={compact} live={ui.helper} wide={wide} snap={{ wide: swap.shown, now: swap.phase === "in" }} note={note} noteActions={noteActions}
        onVariant={pickVariant} onEditText={() => editDeck(g.brief ?? null)} onShowText={onShowText} onDetails={openSheet} onNew={goHome}
        card={pic.column ? { shown: pic.column.shown, node: compactCard ? <PictureCard {...pic.column.card} idp="hp-p" /> : null } : null} />
      <div className={cls("ra-work", geo.cls)}>
        {geo.shown === "note" && (noteRow ?? heldRow)}
        <div className={cls("p2-two ra-two", geo.shown === "top" && "ra-top", swap.shown && "hp-wide", swap.cls)}
          style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 416px", gap: 48, height: g2.height, marginTop: g2.marginTop }}>
          <div style={{ display: "flex", flexDirection: "column", minWidth: 0, gridArea: "1 / 1" }}>
            <div className={cls("ra-whx", head.cls)} data-fit={head.shown}>
              <WorkHead n={n} total={total} title={h} remarks={remarkCount(v)} remarksOn={ui.remarks} remarksOff={rm.off}
                onPrev={() => setSelectedSlide(n - 1)} onNext={() => setSelectedSlide(n + 1)} onToggleRemarks={rm.toggle} onOpenLightbox={onOpenLightbox} />
            </div>
            <Stage src={src} alt={h ? `Слайд ${n}: ${h}` : `Слайд ${n}`} aspect={aspect}>
              {pic.spots && <PictureSpots {...pic.spots} />}
              {rm.stage && <StageMarks {...rm.stage} />}
              {rm.sketch && <FixSketch {...rm.sketch} />}
            </Stage>
            <Film film={film} variant={v} n={n} headline={headline} onPick={setSelectedSlide} marks={filmMarks} />
          </div>
          <Aside d={aside} onVariant={pickVariant} onEditText={() => editDeck(g.brief ?? null)} open={openSheet} className="ra-main"
            hidden={rm.shown || !!pic.column?.shown} style={{ height: g2.height }} />
          {pic.column && (
            <Aside d={aside} onVariant={pickVariant} onEditText={() => editDeck(g.brief ?? null)} open={openSheet} id="rt-pcol" enter={false} bottom
              className={cls("rt-pcw", pic.column.shown ? "p2-on" : "p2-off")} style={{ position: "relative", zIndex: 1, height: g2.height }}
              extra={fullCard ? <PictureCard {...pic.column.card} /> : undefined} />
          )}
          {rm.panel && <RemarksPanel {...rm.panel} helper={ui.helper} />}
        </div>
      </div>
    </>
  );
}
