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
import { clock, fixedRows, fixSteps, fixSummary, fixToRevert, lastEditIs, slideSketch } from "./fix";
import { firstRemarkSlide, slideBadges, slideRemarks, stageMarks, type Frame, type OkPin, type Pin } from "./marks";
import type { PanelLine, PanelRow, PanelView, RemarksPanelProps } from "./RemarksPanel";
import { busyWhy } from "./slideJob";
import type { SlideJob } from "./useSlideJob";

export interface RemarksMode {
  /** Панель в DOM (режим включён или гаснет): зон изображений на сцене нет. */
  mounted: boolean;
  /** Панель стоит на месте колонки (колонка под ней скрыта). */
  shown: boolean;
  /** Почему переключатель сейчас не нажимается (агент исправляет слайд); null — нажимается. */
  off: string | null;
  toggle(): void;
  /** Разметка сцены (StageMarks); null — режим выключен. */
  stage: { k: string; frames: Frame[]; pins: Pin[]; oks: OkPin[]; out: boolean; delay: number; onPick(id: string): void } | null;
  /** Эскиз исправления поверх сцены (FixSketch); null — его нет. */
  sketch: { phase: FxPhase; kind: SketchKind; formula: boolean } | null;
  film: FilmMarks | null;
  panel: RemarksPanelProps | null;
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
  const slideKey = `${v.strategy}:${n}`;
  const [wishAt, setWishAt] = useState({ k: "", t: "" });
  const wish = wishAt.k === slideKey ? wishAt.t : "";
  const badges = useMemo(() => slideBadges(v), [v]);
  const off = fixWork ? `Агент исправляет слайд ${fixWork.slide}` : null;

  const toggle = () => {
    if (off) return;
    if (ui.remarks) return dispatch({ type: "set", patch: { remarks: false } });
    setSince(Date.now());
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

  if (!rm.mounted) return { mounted: false, shown: false, off, toggle, stage: null, sketch: null, film: null, panel: null };

  const line: PanelLine | null = fixRun && fixRun.phase === "done" && !fixing
    ? fixRun.error ? { tone: "error", text: fixRun.error }
      : fixRun.fix && !fixRun.fix.applied ? { tone: "info", text: `Слайд остался прежним: ${lower((fixRun.fix.why ?? "замечания остались").replace(/\.\s*$/, ""))}` } : null
    : null;
  const steps = fixRun ? fixSteps(job.live.events, fixRun.phase === "done") : null;
  const summary = fixDone ? fixSummary(fixRun!.fix!) : null;
  // «Вернуть как было» без итога на странице (перезагрузка): последнее изменение варианта — исправление этого слайда
  const back = here?.kind === "fix" ? here : null;
  const revert = (view === "rem" || view === "none") && fixToRevert(v, n)
    ? { onRevert: () => job.revert(v.strategy, n), busy: back?.undo === "work", error: back?.undo === "error" ? back.undoError : null }
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
    film: { badges, out: !rm.shown, spin: fixWork && fixWork.strategy === v.strategy ? fixWork.slide : null },
    panel: {
      shown: rm.shown, since, n, view, rows, sel, onSel: (i) => setSelAt({ k: viewKey, i }),
      wish, onWish: (t) => setWishAt({ k: slideKey, t }), onFix, fixBusy, fixOff: busyWhy(run), revert,
      line: view === "rem" ? line : null,
      elsewhere: badges.size > 0,
      progress: view === "fix" && fixRun && steps ? {
        clock: clock((fixRun.endedAt ?? now) - fixRun.startedAt), value: fixRun.phase === "work" ? job.live.progress : 1,
        steps: steps.steps, preview: steps.preview, wish: fixRun.wish,
      } : null,
      done: summary && fixRun ? {
        summary, onShow: () => summary.show !== null && setSelectedSlide(summary.show), onUndo: job.undo,
        canUndo: lastEditIs(v, fixRun.fix!.version, "fix"), undoBusy: fixRun.undo === "work", undoError: fixRun.undoError,
      } : null,
    },
  };
}
