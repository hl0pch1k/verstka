// Режим «Замечания» на экране результата (R-remarks, R-fixing, R-fixed; V2 `rmToggle`): переключатель в шапке, панель
// на месте колонки, разметка на сцене, бейджи ленты, исправление слайда с эскизом и «Вернуть как было». Чистая логика —
// marks.ts и fix.ts, шаги работы — useSlideJob, эскиз — useFixStage; здесь они сведены в то, что рисуют WorkHead,
// Stage (StageMarks, FixSketch), Film и RemarksPanel.
import { useMemo, useState } from "react";
import type { SketchKind } from "../../lib/stage";
import { useApp } from "../../store";
import type { Variant } from "../../types";
import { usePresence } from "../kit/usePresence";
import type { FilmMarks } from "./Film";
import { useFixStage, type FxPhase } from "./FixSketch";
import { clock, fixedRows, fixSteps, fixSummary, fixToRevert, lastEditIs, slideSketch, undoneIn } from "./fix";
import { firstRemarkSlide, slideBadges, slideRemarks, stageMarks, type Frame, type OkPin, type Pin } from "./marks";
import type { PanelLine, PanelRow, PanelView, RemarksPanelProps } from "./RemarksPanel";
import { busyWhy, staleOf } from "./slideJob";
import type { SlideJob } from "./useSlideJob";

export interface RemarksMode {
  /** Панель в DOM (режим включён или гаснет): зон изображений на сцене нет. */
  mounted: boolean;
  /** Панель стоит на месте колонки (колонка под ней скрыта). */
  shown: boolean;
  /** Почему переключатель сейчас не нажимается (агент исправляет слайд этого варианта, над вариантом идёт другая
   *  задача); null — нажимается. */
  off: string | null;
  toggle(): void;
  /** Разметка сцены (StageMarks); null — режим выключен. */
  stage: { k: string; frames: Frame[]; pins: Pin[]; oks: OkPin[]; out: boolean; delay: number; onPick(id: string): void } | null;
  /** Эскиз исправления поверх сцены (FixSketch); null — его нет. */
  sketch: { phase: FxPhase; kind: SketchKind; formula: boolean } | null;
  film: FilmMarks | null;
  /** Панель замечаний; `helper` (ширина колонки) подставляет плита результата. */
  panel: Omit<RemarksPanelProps, "helper"> | null;
}

const lower = (t: string) => t.charAt(0).toLowerCase() + t.slice(1);

export function useRemarksMode({ v, n, src, job, now, titleOf }: {
  v: Variant;
  /** Текущий слайд, с 1. */
  n: number;
  /** Превью текущего слайда: в него разворачивается эскиз исправления. */
  src: string | null;
  job: SlideJob;
  /** Секундная стрелка часов хода. */
  now: number;
  titleOf(checkId: string): string | null | undefined;
}): RemarksMode {
  const { ui, dispatch, setSelectedSlide } = useApp();
  const rm = usePresence(ui.remarks, 520);
  // когда панель появилась: содержимое, вошедшее вместе с ней, не ведёт лесенку отдельно (V2 `rmD`, `rmRide`)
  const [since, setSince] = useState(0);
  const run = job.run;
  const here = !!run && run.strategy === v.strategy && run.slide === n ? run : null;
  const open = useMemo(() => slideRemarks(v, n, titleOf), [v, n, titleOf]);
  const fixRun = here?.kind === "fix" ? here : null;
  // вид исправления (карточка хода, разметка гаснет, переключатель выключен) — только когда сервер принял задачу:
  // отказ при запуске не мигает; до ответа занята только кнопка
  const fixWork = run?.kind === "fix" && run.phase === "work" && run.jobId ? run : null;
  const fixBusy = !!fixRun && fixRun.phase === "work" && !fixRun.jobId;
  const fx = useFixStage(fixRun?.jobId && rm.mounted ? fixRun.seq : null, fixRun?.phase === "done", src);
  const fixing = !!fixRun && ((fixRun.phase === "work" && !!fixRun.jobId) || fx !== null);
  // исправление (или его возврат) сохранено, а презентация на экране не перечиталась: строка с «Обновить» на месте итога
  const stale = staleOf(fixRun, !!job.refresh);
  // итог держится, пока исправление не вернули как было — здесь или в другом месте (лист «Подробнее», помощник); пока
  // исправленный слайд не перечитан, итога нет (на экране прежний слайд)
  const fixDone = !!fixRun && !fixing && fixRun.phase === "done" && !!fixRun.fix?.applied && !undoneIn(v, fixRun.fix.version) && stale !== "change";
  const view: PanelView = fixing ? "fix" : fixDone ? "done" : open.length ? "rem" : "none";
  const rows: PanelRow[] = useMemo(
    () => (view === "fix" ? fixRun!.requested : view === "done" ? fixedRows(fixRun!.requested, fixRun!.fix!, open) : open),
    [view, fixRun, open],
  );
  const viewKey = `${v.strategy}:${n}:${view}`;
  const [selAt, setSelAt] = useState<{ k: string; i: number } | null>(null);
  const sel = selAt?.k === viewKey ? selAt.i : view === "rem" || view === "fix" ? 0 : -1;
  const marks = useMemo(() => stageMarks(rows, sel), [rows, sel]);
  const slideKey = `${v.strategy}:${n}`;
  const [wishAt, setWishAt] = useState({ k: "", t: "" });
  const wish = wishAt.k === slideKey ? wishAt.t : "";
  const badges = useMemo(() => slideBadges(v), [v]);
  // над вариантом идёт задача над всем вариантом, которую этот экран не запускал («Исправить всё», возврат из
  // «Агента»): переключатель и «Исправить слайд» выключены с её причиной. Работа над слайдом (своя или подхваченная —
  // начатая до возвращения сюда, помощником) режим не выключает: пока агент исправляет слайд, режим не закрывается, а
  // включить его можно — он открывается на этом слайде с карточкой хода
  const other = job.elsewhere;
  const off = fixWork && ui.remarks ? `Агент исправляет слайд ${fixWork.slide}` : other?.why ?? null;

  const toggle = () => {
    if (off) return;
    if (ui.remarks) return dispatch({ type: "set", patch: { remarks: false } });
    setSince(Date.now());
    // агент исправляет слайд — к нему (карточка хода); на открытом слайде замечаний нет (и нет итога исправления) — к
    // первому слайду с ними
    if (fixWork && fixWork.slide !== n) setSelectedSlide(fixWork.slide);
    else if (!fixWork && !open.length && !fixDone) {
      const to = firstRemarkSlide(v, n);
      if (to !== null && to !== n) setSelectedSlide(to);
    }
    dispatch({ type: "set", patch: { remarks: true } });
  };
  const onFix = () => {
    if (job.busy || other || !open.length) return;
    void job.start("fix", n, { wishes: wish.trim() || null, issue_ids: open.map((r) => r.id) }, open).then((ok) => {
      if (ok) setWishAt({ k: "", t: "" });
    });
  };

  if (!rm.mounted) return { mounted: false, shown: false, off, toggle, stage: null, sketch: null, film: null, panel: null };

  const line: PanelLine | null = fixRun && fixRun.phase === "done" && !fixing
    ? stale === "change" && job.refresh ? { tone: "error", text: job.refresh.text, refresh: job.refresh }
      : fixRun.error ? { tone: "error", text: fixRun.error }
      : fixRun.note ? { tone: "info", text: fixRun.note }
      : fixRun.fix && !fixRun.fix.applied ? { tone: "info", text: `Слайд остался прежним: ${lower((fixRun.fix.why ?? "замечания остались").replace(/\.\s*$/, ""))}` } : null
    : null;
  const steps = fixRun ? fixSteps(job.live.events, fixRun.phase === "done") : null;
  const summary = fixDone ? fixSummary(fixRun!.fix!) : null;
  // «Вернуть как было» без итога на странице (перезагрузка): последнее изменение варианта — исправление этого слайда
  const back = here?.kind === "fix" ? here : null;
  const backStale = staleOf(back, !!job.refresh) === "undo" ? job.refresh : null;
  const revert = (view === "rem" || view === "none") && fixToRevert(v, n)
    ? { onRevert: () => job.revert(v.strategy, n), busy: back?.undo === "work", error: back?.undo === "error" ? back.undoError : null, refresh: backStale }
    : null;

  return {
    mounted: true,
    shown: rm.shown,
    off,
    toggle,
    stage: {
      k: viewKey, ...marks, out: !rm.shown || fixing, delay: Date.now() - since < 300 ? 200 : 0,
      onPick: (id) => setSelAt({ k: viewKey, i: rows.findIndex((r) => r.id === id) }),
    },
    sketch: fx ? { phase: fx, ...slideSketch(v, n, job.live.events) } : null,
    film: { badges, out: !rm.shown, spin: job.spin },
    panel: {
      shown: rm.shown, since, n, view, rows, sel, onSel: (i) => setSelAt({ k: viewKey, i }),
      wish, onWish: (t) => setWishAt({ k: slideKey, t }), onFix, fixBusy, fixOff: busyWhy(run) ?? other?.why ?? null, revert,
      line: view === "rem" ? line : null,
      elsewhere: badges.size > 0,
      progress: view === "fix" && fixRun && steps ? {
        clock: clock((fixRun.endedAt ?? now) - fixRun.startedAt), value: fixRun.phase === "work" ? job.live.progress : 1,
        steps: steps.steps, preview: steps.preview, wish: fixRun.wish,
      } : null,
      done: summary && fixRun ? {
        summary, onShow: () => summary.show !== null && setSelectedSlide(summary.show), onUndo: job.undo,
        // вернули, а экран ещё прежний: вместо «Вернуть как было» — строка с «Обновить»
        canUndo: lastEditIs(v, fixRun.fix!.version, "fix") && stale !== "undo", undoBusy: fixRun.undo === "work", undoError: fixRun.undoError,
        refresh: stale === "undo" ? job.refresh : null,
      } : null,
    },
  };
}
