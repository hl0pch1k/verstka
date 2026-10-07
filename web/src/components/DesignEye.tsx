// «Взгляд дизайнера» (Verstka 3.0), in the quality tab: the vision model looked at every finished slide like an art
// director; the slides it laid out again show side by side as they were and as they are, with what the model saw and
// why it chose the new layout; the slides that kept their layout say why; the minor polish is folded.
import { Eye } from "lucide-react";
import { designEyeLine, problemsText } from "../lib/designEye";
import type { DesignEye, DesignEyeSlide } from "../types";
import { SlideTag } from "./AuditIssues";
import { Collapsible } from "./ui/Collapsible";

function cap(t: string): string {
  return t ? t[0].toUpperCase() + t.slice(1) : t;
}

function Shot({ src, label, slide }: { src: string; label: string; slide: number }) {
  return (
    <figure className="min-w-0">
      <img src={src} alt={`Слайд ${slide}: ${label.toLowerCase()}`} loading="lazy" className="block h-auto w-full rounded-lg bg-zinc-100 ring-1 ring-zinc-200" />
      <figcaption className="mt-1.5 text-caption font-medium text-zinc-500">{label}</figcaption>
    </figure>
  );
}

export function DesignEyeSection({ eye, onShow }: { eye: DesignEye | null | undefined; onShow(slide: number): void }) {
  if (!eye || eye.skipped || eye.looked <= 0) return null;
  const fixed = eye.slides.filter((s) => s.status === "fixed");
  const kept = eye.slides.filter((s) => s.status === "kept");
  const seen = eye.slides.filter((s) => s.status === "seen");
  return (
    <section className="rounded-2xl bg-white p-6 shadow-card" aria-labelledby="design-eye-title">
      <div className="flex items-center gap-2">
        <Eye className="h-5 w-5 shrink-0 text-accent-600" aria-hidden />
        <h3 id="design-eye-title" className="text-title3 font-semibold text-zinc-900">Взгляд дизайнера</h3>
        <span className="min-w-0 flex-1 truncate text-footnote text-zinc-500">{designEyeLine(eye)}</span>
      </div>
      <p className="mt-2 max-w-[720px] text-footnote text-zinc-600 [text-wrap:pretty]">
        Модель с компьютерным зрением посмотрела на каждый готовый слайд, как арт-директор перед отправкой клиенту. Слайд с серьёзной проблемой собран заново; новая вёрстка осталась, только если автоматическая проверка не нашла на ней больше замечаний, а модель выбрала её дважды — когда новая стояла первой и когда второй.
      </p>

      {fixed.map((s) => (
        <div key={s.outline_id} className="mt-5 border-t border-zinc-100 pt-5">
          <div className="flex items-start gap-3 text-footnote">
            <SlideTag slide={s.slide} onShow={onShow} />
            <span className="min-w-0 flex-1 text-zinc-900">
              {cap(problemsText(s, true))} <span className="text-zinc-500">— собрал заново</span>
            </span>
          </div>
          {s.before && s.after ? (
            <div className="mt-3 grid grid-cols-2 gap-3">
              <Shot src={s.before} label="Было" slide={s.slide} />
              <Shot src={s.after} label="Стало" slide={s.slide} />
            </div>
          ) : (
            s.redone && <p className="mt-2 text-footnote text-zinc-500">Слайд с тех пор переделан в чате — картинки «было / стало» к нему больше не относятся.</p>
          )}
          {s.reason && <p className="mt-2 text-footnote text-zinc-700 [text-wrap:pretty]">Почему новая: {s.reason.replace(/\.$/, "")}.</p>}
        </div>
      ))}

      {kept.length > 0 && (
        <ul className="mt-5 space-y-3 border-t border-zinc-100 pt-5">
          {kept.map((s) => (
            <li key={s.outline_id} className="flex items-start gap-3 text-footnote">
              <SlideTag slide={s.slide} onShow={onShow} />
              <span className="min-w-0 flex-1 text-zinc-900">
                {cap(problemsText(s, true))}
                <span className="text-zinc-500"> — пробовал другую вёрстку, оставил прежнюю{s.reason ? `: ${s.reason.replace(/\.$/, "")}` : ""}.</span>
              </span>
            </li>
          ))}
        </ul>
      )}

      {seen.length > 0 && (
        <div className="mt-5">
          <Collapsible variant="plain" title="Мелкие замечания модели" hint={String(seen.length)} keepMounted={false}>
            <ul className="space-y-3">
              {seen.map((s) => (
                <li key={s.outline_id} className="flex items-start gap-3 text-footnote">
                  <SlideTag slide={s.slide} onShow={onShow} />
                  <span className="min-w-0 flex-1 text-zinc-700">{cap(problemsText(s, false))}</span>
                </li>
              ))}
            </ul>
          </Collapsible>
        </div>
      )}
    </section>
  );
}

/** Beside the slide on the result screen: the shown slide was laid out again by the review — the two pictures small,
 *  side by side, and what the model saw in one line; the card opens the quality tab, where the pair is large. */
export function DesignEyeCard({ item, onOpen, className }: { item: DesignEyeSlide; onOpen(): void; className?: string }) {
  const seen = problemsText(item, true);
  return (
    <button type="button" onClick={onOpen} title={`Увидел: ${seen}. Собрал слайд заново`} className={["tap-soft group block w-full shrink-0 cursor-pointer rounded-2xl bg-white px-4 py-3 text-left shadow-card hover:bg-zinc-50 active:bg-zinc-100", className].filter(Boolean).join(" ")}>
      <span className="flex items-center gap-2">
        <Eye className="h-4 w-4 shrink-0 text-accent-600" aria-hidden />
        <span className="text-body font-semibold text-zinc-900">Взгляд дизайнера</span>
        <span className="ml-auto text-caption text-zinc-500">пересобрал</span>
      </span>
      {item.before && item.after && (
        <span className="mt-2 flex items-center gap-1.5" aria-hidden>
          <img src={item.before} alt="" loading="lazy" className="block h-[44px] min-w-0 flex-1 rounded-md object-cover opacity-75 ring-1 ring-zinc-200" />
          <span className="shrink-0 text-caption text-zinc-400">→</span>
          <img src={item.after} alt="" loading="lazy" className="block h-[44px] min-w-0 flex-1 rounded-md object-cover ring-1 ring-accent-200" />
        </span>
      )}
      <span className="mt-1 block truncate text-footnote text-zinc-700">{seen.charAt(0).toUpperCase() + seen.slice(1)}</span>
    </button>
  );
}
