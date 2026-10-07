// «Изображение» beside a slide that has one or keeps a place for one: what the picture shows (the author's words, the
// person's wish), which model made it — «Заменить» with an optional description of the wanted picture, «Убрать» to
// leave the place for one's own photo, the job's progress and «Вернуть как было». A free place says why it waits.
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Check, ImageOff, ImagePlus, Loader2, RotateCcw, WandSparkles } from "lucide-react";
import { about, stage } from "../../lib/pictures";
import { cn } from "../../lib/utils";
import type { SlidePicture } from "../../types";
import { Button } from "../ui/Button";
import type { PictureAction, PictureRun } from "./usePictureChange";

interface Props {
  pic: SlidePicture;
  /** The run on this slide (null when none or another slide's). */
  run: PictureRun | null;
  progress: number;
  message: string;
  /** Another job of the deck is running: the actions wait. */
  busy: boolean;
  /** A text-to-image model has a key. */
  configured: boolean;
  onStart(action: PictureAction, wish: string): Promise<boolean>;
  onUndo(): void;
  onDismiss(): void;
  className?: string;
}

const AREA =
  "scroll-thin block h-[72px] max-h-[96px] w-full resize-none rounded-xl bg-zinc-100 px-3 py-2 text-footnote leading-6 text-zinc-900 outline-none transition-[background-color,box-shadow] duration-150 placeholder:text-zinc-500 focus:bg-white focus:shadow-selected";

export function PictureCard({ pic, run, progress, message, busy, configured, onStart, onUndo, onDismiss, className }: Props) {
  const [open, setOpen] = useState(false);
  const [wish, setWish] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  const working = !!run && (run.phase === "submitting" || run.phase === "running" || run.phase === "undoing");
  // a new slide (or a run that ended) closes the form; the wish stays until a picture is made with it
  useEffect(() => setOpen(false), [pic.id]);
  useEffect(() => {
    if (run?.phase === "done" && run.result?.applied) setWish("");
  }, [run?.phase, run?.result]);
  useEffect(() => {
    if (open) requestAnimationFrame(() => area.current?.focus({ preventScroll: true }));
  }, [open]);

  const generated = pic.status === "generated";
  const own = !!pic.own && !generated;
  const start = async (action: PictureAction) => {
    if (await onStart(action, action === "remove" ? "" : wish)) setOpen(false);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void start("generate");
    } else if (e.key === "Escape") setOpen(false);
  };
  const what = about(pic);
  // «Улучшить готовую»: the original deck's own picture back on its place — nothing was drawn
  const original = generated && pic.model === "original";
  const title = generated ? "Изображение" : own ? "Место под ваше фото" : "Место под изображение";
  const sub = original
    ? null
    : generated
    ? [pic.model_label || pic.model, typeof pic.palette_match === "number" ? `в палитре шаблона ${Math.round(pic.palette_match * 100)}%` : null].filter(Boolean).join(" · ")
    : own
      ? "Вставьте фото в PowerPoint: щёлкните по месту → «Рисунок»"
      : pic.why ? pic.why.charAt(0).toUpperCase() + pic.why.slice(1) : null;
  const blockedTitle = busy && !working ? "Агент занят — дождитесь конца" : !configured ? "Модель изображений не подключена" : undefined;
  const canGenerate = configured && !busy && !working;

  return (
    <section aria-label={title} className={cn("shrink-0 rounded-2xl bg-white p-4 shadow-card", className)}>
      <div className="flex items-center gap-2">
        <h3 className="text-title3 font-semibold text-zinc-900">{title}</h3>
        {generated && !working && <span className="ml-auto rounded-full bg-zinc-100 px-2 py-0.5 text-caption text-zinc-600">{original ? "из исходной презентации" : "сгенерировано"}</span>}
      </div>
      {what && (
        <p className="mt-2 line-clamp-2 text-footnote text-zinc-700 [text-wrap:pretty]" title={what}>
          {pic.wish ? `По вашему описанию: ${what}` : what}
        </p>
      )}
      {sub && <p className="mt-1 truncate text-caption text-zinc-500" title={sub}>{sub}</p>}

      {/* the run on this slide: its progress, then its outcome */}
      {run && working && (
        <div className="mt-3 animate-fade" role="status" aria-live="polite">
          <div className="flex items-center gap-2 text-footnote text-zinc-700">
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-accent" aria-hidden />
            <span className="truncate">{run.phase === "undoing" ? "Возвращаю как было…" : run.action === "remove" ? "Убираю изображение…" : `${stage(message)}…`}</span>
          </div>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-zinc-100">
            <div className="h-full rounded-full bg-accent transition-[width] duration-300 ease-out" style={{ width: `${Math.max(6, Math.round(progress * 100))}%` }} />
          </div>
        </div>
      )}
      {run && run.phase === "done" && run.result?.applied && (
        <div className="mt-3 animate-fade">
          <p className="flex items-start gap-2 text-footnote text-zinc-700">
            <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
            <span>{run.action === "remove" ? "Изображение убрано — место оставлено под ваше фото" : "Новое изображение на слайде"}</span>
          </p>
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="ghost" icon={RotateCcw} disabled={!run.synced || busy} onClick={onUndo}>
              Вернуть как было
            </Button>
            <Button size="sm" variant="ghost" onClick={onDismiss}>
              Готово
            </Button>
          </div>
        </div>
      )}
      {run && run.phase === "undone" && <p className="mt-3 animate-fade text-footnote text-zinc-700">Вернул как было.</p>}
      {run && run.phase === "failed" && (
        <p className="mt-3 animate-fade text-footnote text-red-700" role="alert">
          Не получилось: {run.error ?? "сервер не смог поменять изображение"}.
        </p>
      )}

      {/* the actions: closed — one line of buttons; open — the wish and «Сгенерировать» */}
      {!working && !(run && run.phase === "done" && run.result?.applied) && (
        open ? (
          <div className="mt-3 flex animate-fade flex-col gap-2">
            <textarea
              ref={area}
              rows={2}
              maxLength={500}
              value={wish}
              onChange={(e) => setWish(e.target.value)}
              onKeyDown={onKey}
              aria-label="Какое изображение нужно"
              placeholder={generated ? "Какое нужно? Например: вид сверху, больше зелени" : "Что показать? Можно оставить пустым"}
              className={AREA}
            />
            <div className="flex gap-2">
              <span className="block flex-1" title={blockedTitle}>
                <Button size="sm" variant="primary" block icon={WandSparkles} disabled={!canGenerate} onClick={() => void start("generate")}>
                  Сгенерировать
                </Button>
              </span>
              <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
                Отмена
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-3 flex flex-wrap gap-2">
            <span className="block" title={blockedTitle}>
              <Button size="sm" variant={generated ? "secondary" : "primary"} icon={ImagePlus} disabled={!canGenerate} onClick={() => setOpen(true)}>
                {generated ? "Заменить" : own ? "Сгенерировать всё равно" : "Сгенерировать"}
              </Button>
            </span>
            {generated && (
              <span className="block" title={busy ? "Агент занят — дождитесь конца" : undefined}>
                <Button size="sm" variant="ghost" icon={ImageOff} disabled={busy} onClick={() => void start("remove")}>
                  Убрать
                </Button>
              </span>
            )}
          </div>
        )
      )}
      {!configured && !generated && !own && <p className="mt-2 text-caption text-zinc-500">Модель изображений не подключена — место оставлено под ваше фото.</p>}
    </section>
  );
}
