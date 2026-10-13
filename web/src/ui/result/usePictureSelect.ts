// Изображение на слайде (R-picture, V2 `rtTogglePic`): клик по картинке на сцене — рамка и колонка «Изображение» с
// карточкой поверх обычной колонки. Повторный клик, Esc, другой слайд или вариант и режим «Замечания» снимают выбор
// (V2 `rtStale`: возврат на слайд колонку не открывает); картинки, которую выбрали, больше нет на слайде — колонка
// закрывается, чужая не подставляется. Закрываемая колонка уезжает со своей карточкой. Чистая логика — picture.ts,
// задачи «Заменить» / «Убрать» / «Вернуть» — useSlideJob.
import { useEffect, useMemo, useState, type ComponentProps } from "react";
import type { BboxFrac, SlidePicture, Variant } from "../../types";
import { usePresence } from "../kit/usePresence";
import { clock, lastEditIs, undoneIn } from "./fix";
import { pickedPicture, pictureView, slidePictures } from "./picture";
import type { PictureCard, PictureRunView } from "./PictureCard";
import { ownsKeys } from "./resultView";
import { busyWhy, staleOf } from "./slideJob";
import type { SlideJob } from "./useSlideJob";

type Pic = SlidePicture & { bbox: BboxFrac };

export interface PictureSelect {
  /** Зоны картинок на сцене (PictureSpots); null — их нет (картинок нет или включён режим «Замечания»). */
  spots: { pics: Pic[]; sel: string | null; frame: boolean; onPick(id: string): void } | null;
  /** Колонка «Изображение» в DOM: стоит (`shown`) или уезжает, с карточкой. */
  column: { shown: boolean; card: ComponentProps<typeof PictureCard> } | null;
}

export function usePictureSelect({ v, n, job, now, blocked, layered }: {
  v: Variant;
  n: number;
  job: SlideJob;
  now: number;
  /** Режим «Замечания» включён или его панель ещё в DOM: картинки не выбираются. */
  blocked: boolean;
  /** Поверх результата открыт слой или лист: Esc — его. */
  layered: boolean;
}): PictureSelect {
  const pics = useMemo(() => slidePictures(v, n), [v, n]);
  const slideKey = `${v.strategy}:${n}`;
  const [sel, setSel] = useState<{ k: string; id: string; form: boolean; d: number } | null>(null);
  const picked = blocked ? null : pickedPicture(sel, slideKey, pics);
  // выбор снимается: другой слайд или вариант, режим «Замечания», выбранной картинки больше нет на слайде
  const stale = !!sel && (blocked || sel.k !== slideKey || !picked);
  useEffect(() => {
    if (stale) setSel(null);
  }, [stale]);
  const on = !!picked;
  const pcol = usePresence(on, 280);
  // закрываемая колонка уезжает со своей карточкой: последняя выбранная картинка
  const [last, setLast] = useState<Pic | null>(null);
  useEffect(() => {
    if (picked) setLast(picked);
  }, [picked]);
  const shown = picked ?? last;
  const [wish, setWish] = useState("");

  // Esc снимает выбор (колонка уходит), пока поверх ничего не открыто
  useEffect(() => {
    if (!on || layered) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || ownsKeys(e.target)) return;
      setSel(null);
      // одно Esc закрывает одно: помощник (он слушает Esc тоже, но позже — здесь фаза перехвата) это нажатие уже не видит
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [on, layered]);

  const onPick = (id: string) => {
    if (sel && picked?.id === id && sel.form) return setSel(null);
    setSel({ k: slideKey, id, form: true, d: on ? 40 : 320 });
  };
  const run = job.run;
  const picRun = run?.kind === "picture" && run.strategy === v.strategy && run.slide === n ? run : null;
  // замена (или её возврат) сохранена, а презентация на экране не перечиталась: строка с «Обновить» вместо итога
  const unread = staleOf(picRun, !!job.refresh);
  const runView: PictureRunView = {
    work: picRun?.phase === "work" ? "change" : picRun?.undo === "work" ? "undo" : null,
    action: picRun?.action ?? null,
    progress: picRun?.phase === "work" ? job.live.progress : 0,
    message: job.live.message,
    clock: picRun ? clock((picRun.phase === "work" ? now : picRun.endedAt ?? now) - picRun.startedAt) : "0:00",
    // изображение вернули как было в другом месте (лист «Подробнее», помощник) — итога больше нет
    done: picRun?.phase === "done" && picRun.picture?.applied && picRun.undo !== "work" && !undoneIn(v, picRun.picture.version) && !unread ? picRun.action : null,
    canUndo: !!picRun?.picture?.applied && lastEditIs(v, picRun.picture.version, "picture") && !unread,
    error: unread ? null : picRun ? picRun.undoError ?? picRun.error : null,
    refresh: unread ? job.refresh : null,
  };
  const start = (action: "generate" | "remove") => {
    if (job.busy || job.elsewhere) return;
    void job.start("picture", n, action === "remove" ? { action } : { action, wish: wish.trim() || null }).then((ok) => {
      if (!ok) return;
      setWish("");
      setSel((x) => (x ? { ...x, form: false } : x));
    });
  };

  return {
    spots: pics.length > 0 && !blocked ? { pics, sel: picked?.id ?? null, frame: !!picked && !!sel?.form, onPick } : null,
    column: pcol.mounted && shown ? {
      shown: pcol.shown,
      card: {
        view: pictureView(shown), form: !!sel?.form && on, formDelay: sel?.d ?? 320, wish, onWish: setWish,
        onToggleForm: () => setSel((x) => (x ? { ...x, form: !x.form, d: 40 } : x)),
        onCancel: () => {
          setSel((x) => (x ? { ...x, form: false } : x));
          setWish("");
        },
        onGenerate: () => start("generate"), onRemove: () => start("remove"), onUndo: job.undo, run: runView,
        // своя работа на другом слайде или задача над вариантом, которую этот экран не запускал (помощник, лист
        // «Подробнее», исправление, начатое до возвращения сюда)
        off: (job.busy && !runView.work ? busyWhy(run) : null) ?? (!runView.work ? job.elsewhere?.why ?? null : null),
      },
    } : null,
  };
}
