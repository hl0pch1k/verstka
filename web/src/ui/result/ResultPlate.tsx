// Плита 04 «Результат» (слот `p4` колоды; boards/R-aside — утверждённая «Правая колонка целиком», V2 плита 04): над
// рабочей областью — таблетка уведомления, слева — шапка «Слайд N из M», сцена и лента миниатюр, справа — колонка с
// названием, оценкой, вариантами, скачиванием, карточками и ссылками. Содержимое стоит, пока открыт результат, и
// уезжает вниз вместе с плитой (`ui.down`); у каждой презентации — своё (ключ — id), и входит оно лесенкой p2-in
// (160/200/240/280 мс). Данные — resultView; режим «Замечания» (задача 9), слой текста и просмотр на весь экран
// (задача 10) и лист «Подробнее» (задача 11, `useOpenSheet`) подключаются сюда своими задачами.
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
import { Aside, type AsideData } from "./Aside";
import { Film, loadedThumbs } from "./Film";
import { NotePill, NoteRow } from "./NotePill";
import {
  agentLines, deckPreset, docLine, docTitle, eyesCard, fileBase, latestWithModel, noteView, qualityCard, recheckIn, remarkCount, retryLeft,
  retryTick, retryWaitTitle, rewriteText, scoreOf, slideForKey, slideHeadline, slideSrc, slidesOf, switchShots, variantSegs, whyText,
} from "./resultView";
import { Stage } from "./Stage";
import { useOpenSheet } from "./useOpenSheet";
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

  // Задачи 9 и 10 заменят эти обработчики: режим «Замечания», «На весь экран», слой «Текст презентации»
  const onToggleRemarks = () => {};
  const onOpenLightbox = () => {};
  const onShowText = () => {};

  // клавиши ←/→ листают слайды, Home/End — к первому и последнему, пока поверх результата ничего не открыто
  const layered = !!(ui.sheet || ui.textLayer || ui.lightbox || ui.sect || ui.tplPreview || ui.tplDelete);
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
        <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
          <WorkHead n={n} total={total} title={h} remarks={remarkCount(v)} onPrev={() => setSelectedSlide(n - 1)} onNext={() => setSelectedSlide(n + 1)}
            onToggleRemarks={onToggleRemarks} onOpenLightbox={onOpenLightbox} />
          <Stage src={src} alt={h ? `Слайд ${n}: ${h}` : `Слайд ${n}`} aspect={aspect} />
          <Film film={film} variant={v} n={n} headline={headline} onPick={setSelectedSlide} />
        </div>
        <Aside d={aside} onVariant={pickVariant} onEditText={() => editDeck(g.brief ?? null)} open={openSheet} />
      </div>
    </>
  );
}
