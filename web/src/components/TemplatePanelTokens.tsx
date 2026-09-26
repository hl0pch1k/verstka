// The design tokens of the template in plain words: the palette ribbon of the overview (a click copies a colour) and
// the folded «Шрифты и поля» for a designer — the size scale and the safe area.
import { useState, type KeyboardEvent } from "react";
import { fontStack } from "../lib/fonts";
import { cn } from "../lib/utils";
import { useApp } from "../store";
import type { ColorToken, TemplateManifest } from "../types";
import { Collapsible } from "./ui/Collapsible";

export const hexOf = (hex: string) => (hex.startsWith("#") ? hex : `#${hex}`).toUpperCase();
const num = (v: number, digits = 1) => v.toLocaleString("ru-RU", { maximumFractionDigits: digits });
const pct = (v: number) => `${num(v * 100, 0)} %`;

export function roleLabel(role: string): string {
  const [base, sub] = role.split(".");
  if (base === "background") return sub === "dark" ? "тёмный фон" : sub === "light" ? "светлый фон" : "фон";
  if (base === "surface") return "подложка";
  if (base === "text") return sub === "secondary" ? "второстепенный текст" : sub === "inverse" ? "текст на тёмном" : "основной текст";
  if (base === "accent") return "акцент";
  if (base === "neutral") return "нейтральный";
  return role;
}

const SEMANTIC: Record<string, string> = { negative: "для негатива", positive: "для позитива", warning: "для предупреждений" };

/** «фирменный», «основной текст», «акцент»… — what a colour does in the template. */
export function colorRole(color: ColorToken): string {
  if (color.is_brand) return "фирменный";
  if (color.semantic) return SEMANTIC[color.semantic] ?? color.semantic;
  const roles = color.roles.length ? color.roles : color.role ? [color.role] : [];
  return roles[0] ? roleLabel(roles[0]) : "дополнительный";
}

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hexOf(hex).slice(i, i + 2), 16));
const near = (a: string, b: string) => Math.hypot(...rgb(a).map((v, i) => v - rgb(b)[i])) < 12;

/** The palette by share of area without near-twins (#FAFCFF beside #FEFFFF is one white: its share joins the first). */
function distinct(colors: ColorToken[]): ColorToken[] {
  const kept: ColorToken[] = [];
  for (const c of colors) {
    const twin = kept.find((k) => near(k.hex, c.hex));
    if (twin) twin.weight += c.weight;
    else kept.push({ ...c });
  }
  return kept;
}

/** The palette by share of area, one ribbon without hex labels; each swatch names its colour and role on hover. A
 *  hairline parts neighbours (two whites never read as a gap), and the ribbon is one Tab stop: ←/→/Home/End move. */
export function PaletteRibbon({ manifest, className }: { manifest: TemplateManifest; className?: string }) {
  const { toast } = useApp();
  const colors = distinct(manifest.tokens.colors.slice(0, 12)).slice(0, 10);
  const [focusIdx, setFocusIdx] = useState(0);
  const total = colors.reduce((s, c) => s + c.weight, 0) || 1;
  if (colors.length === 0) return null;
  const at = Math.min(focusIdx, colors.length - 1);
  const copy = (hex: string) => void navigator.clipboard?.writeText(hex).then(() => toast("success", `Цвет ${hex} скопирован`), () => undefined);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const n = colors.length;
    const next = { ArrowRight: (at + 1) % n, ArrowLeft: (at - 1 + n) % n, Home: 0, End: n - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    e.stopPropagation();
    setFocusIdx(next);
    e.currentTarget.querySelectorAll<HTMLButtonElement>("button")[next]?.focus();
  };
  return (
    <div
      // the frame is drawn over the swatches (a white swatch keeps its edge on the grey tile)
      className={cn(
        "relative flex overflow-hidden rounded-lg [&>button+button]:shadow-[inset_1px_0_0_rgba(0,16,61,0.12)]",
        "after:pointer-events-none after:absolute after:inset-0 after:rounded-lg after:shadow-inner-line after:content-['']",
        className,
      )}
      role="group"
      aria-label="Палитра шаблона"
      onKeyDown={onKey}
    >
      {colors.map((c, i) => {
        const hex = hexOf(c.hex);
        const label = `${hex} · ${colorRole(c)} · нажмите, чтобы скопировать`;
        return (
          <button
            key={c.hex}
            type="button"
            tabIndex={i === at ? 0 : -1}
            onClick={() => copy(hex)}
            onFocus={() => setFocusIdx(i)}
            title={label}
            aria-label={label}
            className="h-full min-w-4 cursor-pointer transition-[filter] duration-150 hover:brightness-95 focus-visible:outline-offset-[-2px]"
            // square-root widths: a background that covers 90% of the area still leaves the accents readable
            style={{ background: hex, flexGrow: Math.max(Math.sqrt(c.weight / total), 0.1) }}
          />
        );
      })}
    </div>
  );
}

const SCALE_RU: Record<string, { label: string; sample: string }> = {
  display: { label: "Обложка", sample: "Заголовок доклада" },
  h1: { label: "Заголовок", sample: "Главная мысль слайда" },
  h2: { label: "Подзаголовок", sample: "Подзаголовок или тезис" },
  h3: { label: "Заголовок блока", sample: "Заголовок карточки" },
  body: { label: "Текст", sample: "Факты, пояснения и выводы" },
  small: { label: "Мелкий текст", sample: "Подписи и источники данных" },
  caption: { label: "Подпись", sample: "Подпись к диаграмме" },
};

const RATIOS: Array<[string, number]> = [["16:9", 16 / 9], ["4:3", 4 / 3], ["16:10", 1.6], ["3:2", 1.5], ["1:1", 1]];

export function slideFormat(size: { w: number; h: number }): string {
  if (!size.w || !size.h) return "—";
  const r = size.w / size.h;
  const named = RATIOS.find(([, v]) => Math.abs(v - r) < 0.02)?.[0] ?? `${num(r, 2)}:1`;
  return `${named} · ${num(size.w / 360000)} × ${num(size.h / 360000)} см`;
}

const SUB = "mb-2 text-footnote font-semibold text-zinc-700";

/** «Шрифты и поля» (folded): the size scale in the template's font and the safe area the slides keep to. */
export function FontsAndMargins({ manifest }: { manifest: TemplateManifest }) {
  const typo = manifest.tokens.typography;
  const primary = typo.families[0]?.family;
  const maxPt = Math.max(1, ...typo.scale.map((s) => s.size_pt));
  const spacing = manifest.tokens.spacing;
  const { w, h } = manifest.slide_size;
  if (typo.scale.length === 0 && !spacing) return null;
  const sa = spacing?.safe_area;
  return (
    <Collapsible title="Шрифты и поля" hint="для дизайнера">
      <div className="grid grid-cols-[minmax(0,1fr)_240px] gap-6">
        {typo.scale.length > 0 && (
          <section className="min-w-0">
            <h4 className={SUB}>Размеры шрифтов</h4>
            <ul className="divide-y divide-zinc-100">
              {typo.scale.map((s) => {
                const meta = SCALE_RU[s.role] ?? { label: s.role, sample: "Пример текста" };
                return (
                  <li key={s.role} className="flex items-center gap-4 py-2">
                    <span className="w-32 shrink-0">
                      <span className="block text-footnote text-zinc-900">{meta.label}</span>
                      <span className="block text-caption tabular-nums text-zinc-500">{num(s.size_pt)} пт</span>
                    </span>
                    <span
                      className="min-w-0 flex-1 truncate leading-tight text-zinc-900"
                      title={meta.sample}
                      style={{ fontFamily: fontStack(primary), fontSize: Math.max(11, Math.round((s.size_pt / maxPt) * 28)), fontWeight: s.weight_bold_share > 0.5 ? 700 : 400 }}
                    >
                      {meta.sample}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
        {sa && (
          <section className={cn(typo.scale.length === 0 && "col-span-2 max-w-[240px]")}>
            <h4 className={SUB}>Поля</h4>
            <div className="relative w-full overflow-hidden rounded-lg bg-zinc-100 shadow-inner-line" style={{ aspectRatio: w && h ? `${w} / ${h}` : "16 / 9" }}>
              <div className="absolute border border-dashed border-accent bg-accent/[0.06]" style={{ left: `${sa.x * 100}%`, top: `${sa.y * 100}%`, width: `${sa.w * 100}%`, height: `${sa.h * 100}%` }} />
            </div>
            <p className="mt-2 grid grid-cols-2 gap-x-4 text-caption tabular-nums text-zinc-500">
              <span>слева {pct(sa.x)}</span>
              <span>справа {pct(Math.max(0, 1 - sa.x - sa.w))}</span>
              <span>сверху {pct(sa.y)}</span>
              <span>снизу {pct(Math.max(0, 1 - sa.y - sa.h))}</span>
            </p>
          </section>
        )}
      </div>
    </Collapsible>
  );
}
