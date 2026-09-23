// Design tokens of the analysed template: palette, typography and the slide grid.
import { useState } from "react";
import { Palette, Ruler, Star, Type } from "lucide-react";
import { cn, fmtPct, isLightHex, plural } from "../lib/utils";
import { useApp } from "../store";
import type { ColorToken, TemplateManifest } from "../types";
import { Badge, type BadgeTone } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";
import { Progress } from "./ui/Progress";

export const hexOf = (hex: string) => (hex.startsWith("#") ? hex : `#${hex}`).toUpperCase();
const num = (v: number, digits = 1) => v.toLocaleString("ru-RU", { maximumFractionDigits: digits });
const pct = (v: number) => `${num(v * 100)}%`;

export function roleLabel(role: string): string {
  const [base, sub] = role.split(".");
  if (base === "background") return sub === "dark" ? "фон тёмный" : sub === "light" ? "фон светлый" : "фон";
  if (base === "surface") return "поверхность";
  if (base === "text") return sub === "secondary" ? "текст вторичный" : sub === "inverse" ? "текст инверсный" : "текст основной";
  if (base === "accent") return sub ? `акцент ${sub}` : "акцент";
  if (base === "neutral") return sub ? `нейтральный ${sub}` : "нейтральный";
  return role;
}

const roleTone = (role: string): BadgeTone => (role.startsWith("accent") ? "accent" : role.startsWith("text") ? "info" : "neutral");
const SEMANTIC: Record<string, { label: string; tone: BadgeTone }> = {
  negative: { label: "негатив", tone: "error" },
  positive: { label: "позитив", tone: "success" },
  warning: { label: "внимание", tone: "warn" },
};
const CONTEXT_RU: Record<string, string> = { text: "текст", fill: "заливка", background: "фон", line: "линия" };
const FILL_RU: Record<string, string> = { solid: "сплошной", gradient: "градиент", image: "изображение", picture: "изображение", pattern: "узор" };

function Swatch({ color, share }: { color: ColorToken; share: number }) {
  const { toast } = useApp();
  const hex = hexOf(color.hex);
  const roles = color.roles.length ? color.roles : color.role ? [color.role] : [];
  const semantic = color.semantic ? SEMANTIC[color.semantic] ?? { label: color.semantic, tone: "neutral" as BadgeTone } : null;
  const contexts = Object.entries(color.contexts).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${CONTEXT_RU[k] ?? k} ${n}`).join(" · ");
  const copy = () => {
    void navigator.clipboard?.writeText(hex).then(() => toast("success", `Цвет ${hex} скопирован`), () => undefined);
  };
  return (
    <div className="overflow-hidden rounded-2xl bg-zinc-50 shadow-inner-line">
      <button
        type="button"
        onClick={copy}
        title="Скопировать HEX"
        className={cn("flex h-20 w-full cursor-pointer items-end justify-between px-3 pb-2.5 text-left focus:outline-none", isLightHex(hex) ? "text-zinc-900" : "text-white")}
        style={{ backgroundColor: hex }}
      >
        <span className="font-mono text-xs font-semibold tracking-wide">{hex}</span>
        {color.is_brand && (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium opacity-90">
            <Star className="h-3 w-3 fill-current" aria-hidden /> бренд
          </span>
        )}
      </button>
      <div className="space-y-1.5 px-2.5 py-2">
        <div className="flex min-h-[18px] flex-wrap gap-1">
          {roles.map((r) => <Badge key={r} size="sm" tone={roleTone(r)}>{roleLabel(r)}</Badge>)}
          {semantic && <Badge size="sm" tone={semantic.tone}>{semantic.label}</Badge>}
          {roles.length === 0 && !semantic && <span className="text-[11px] text-zinc-400">без роли</span>}
        </div>
        <div className="flex items-center gap-2">
          <Progress value={share} size="xs" tone="neutral" />
          <span className="w-9 shrink-0 text-right text-[11px] tabular-nums text-zinc-600">{share < 0.01 ? "<1%" : fmtPct(share)}</span>
        </div>
        <p className="truncate text-[11px] leading-4 text-zinc-500" title={contexts}>{contexts || "нет вхождений"}</p>
      </div>
    </div>
  );
}

const PALETTE_LIMIT = 12;

export function PaletteCard({ manifest }: { manifest: TemplateManifest }) {
  const [all, setAll] = useState(false);
  const colors = manifest.tokens.colors;
  const total = colors.reduce((s, c) => s + c.weight, 0) || 1;
  const shown = all ? colors : colors.slice(0, PALETTE_LIMIT);
  const backgrounds = manifest.tokens.backgrounds ?? [];
  return (
    <Card>
      <CardHeader actions={colors.length > PALETTE_LIMIT && <Button size="sm" variant="ghost" onClick={() => setAll(!all)}>{all ? "Свернуть" : `Показать все ${colors.length}`}</Button>}>
        <CardTitle icon={Palette} hint={`${plural(colors.length, "цвет", "цвета", "цветов")} · доля — вес цвета в шаблоне с учётом площади`}>Палитра</CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        {colors.length === 0 ? (
          <p className="text-[13px] text-zinc-500">В шаблоне не нашлось устойчивых цветов.</p>
        ) : (
          <div className="grid grid-cols-4 gap-3 min-[1400px]:grid-cols-6">
            {shown.map((c) => <Swatch key={c.hex} color={c} share={c.weight / total} />)}
          </div>
        )}
        {backgrounds.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-zinc-100 pt-3">
            <span className="text-xs font-medium text-zinc-500">Фоны слайдов</span>
            {backgrounds.map((b, i) => (
              <span key={i} className="inline-flex h-7 items-center gap-1.5 rounded-full bg-zinc-100 pl-1.5 pr-3 text-xs font-medium text-zinc-700">
                <span className="h-3.5 w-3.5 rounded-full border border-zinc-300" style={{ background: b.hex ? hexOf(b.hex) : "repeating-linear-gradient(45deg,#e4e4e7 0 3px,#fff 3px 6px)" }} />
                {b.family === "dark" ? "тёмный" : "светлый"} · {FILL_RU[b.fill_kind] ?? b.fill_kind}
                <span className="text-zinc-400">{plural(b.slides.length, "слайд", "слайда", "слайдов")}</span>
              </span>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

const SCALE_RU: Record<string, { label: string; sample: string }> = {
  display: { label: "Дисплей", sample: "Заголовок доклада" },
  h1: { label: "Заголовок слайда", sample: "Главная мысль слайда" },
  h2: { label: "Подзаголовок", sample: "Подзаголовок или ключевой тезис" },
  h3: { label: "Заголовок блока", sample: "Заголовок карточки или блока" },
  body: { label: "Основной текст", sample: "Основной текст: факты, пояснения и выводы" },
  small: { label: "Мелкий текст", sample: "Подписи, сноски и источники данных" },
  caption: { label: "Подпись", sample: "Подпись к диаграмме или изображению" },
};

export function TypographyCard({ manifest }: { manifest: TemplateManifest }) {
  const typo = manifest.tokens.typography;
  const primary = typo.families[0]?.family;
  const stack = (family?: string) => (family ? `"${family}", Inter, system-ui, sans-serif` : undefined);
  const maxPt = Math.max(1, ...typo.scale.map((s) => s.size_pt));
  const inScale = new Set(typo.scale.map((s) => s.size_pt));
  return (
    <Card>
      <CardHeader>
        <CardTitle icon={Type} hint={`выравнивание влево ${fmtPct(typo.left_align_share)} · интерлиньяж ×${num(typo.line_spacing, 2)}`}>Типографика</CardTitle>
      </CardHeader>
      <CardBody className="space-y-5">
        {typo.families.length === 0 ? (
          <p className="text-[13px] text-zinc-500">Гарнитуры не определены.</p>
        ) : (
          <div className="grid grid-cols-3 gap-4">
            {typo.families.slice(0, 6).map((f, i) => (
              <div key={f.family} className="min-w-0">
                <div className="mb-1.5 flex items-baseline justify-between gap-2">
                  <span className="truncate text-[15px] font-medium text-zinc-900" style={{ fontFamily: stack(f.family) }}>{f.family}</span>
                  <span className="shrink-0 text-xs font-medium tabular-nums text-zinc-700">{fmtPct(f.weight, f.weight < 0.1 ? 1 : 0)}</span>
                </div>
                <Progress value={f.weight} tone={i === 0 ? "accent" : "neutral"} />
                <p className="mt-1.5 truncate text-[11px] text-zinc-500">
                  {manifest.embedded_fonts.includes(f.family) ? "встроен в файл · " : ""}полужирный {fmtPct(f.bold_share)}
                </p>
              </div>
            ))}
          </div>
        )}
        {typo.scale.length > 0 && (
          <div className="divide-y divide-zinc-200/70 rounded-2xl bg-zinc-50">
            {typo.scale.map((s) => {
              const meta = SCALE_RU[s.role] ?? { label: s.role, sample: "Пример текста в этом кегле" };
              return (
                <div key={s.role} className="flex items-center gap-4 px-3.5 py-2.5">
                  <div className="w-36 shrink-0">
                    <div className="flex items-center gap-1.5">
                      <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] font-medium text-zinc-700">{s.role}</span>
                      <span className="text-[13px] font-semibold tabular-nums text-zinc-900">{num(s.size_pt)} pt</span>
                    </div>
                    <p className="mt-0.5 truncate text-[11px] text-zinc-500">{meta.label} · {s.count.toLocaleString("ru-RU")}×</p>
                  </div>
                  <p
                    className="min-w-0 flex-1 truncate leading-tight text-zinc-900"
                    style={{ fontFamily: stack(primary), fontSize: Math.max(10, Math.round((s.size_pt / maxPt) * 34)), fontWeight: s.weight_bold_share > 0.5 ? 700 : 400 }}
                  >
                    {meta.sample}
                  </p>
                </div>
              );
            })}
          </div>
        )}
        {typo.sizes_used.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs font-medium text-zinc-500">Кегли в шаблоне</span>
            {typo.sizes_used.map((s) => (
              <span key={s} className={cn("rounded px-1.5 py-0.5 font-mono text-[11px] tabular-nums", inScale.has(s) ? "bg-accent-50 font-semibold text-accent-700" : "bg-zinc-100 text-zinc-600")}>{num(s)}</span>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

const RATIOS: Array<[string, number]> = [["16:9", 16 / 9], ["4:3", 4 / 3], ["16:10", 1.6], ["3:2", 1.5], ["1:1", 1]];

export function slideFormat(size: { w: number; h: number }): string {
  if (!size.w || !size.h) return "—";
  const r = size.w / size.h;
  const named = RATIOS.find(([, v]) => Math.abs(v - r) < 0.02)?.[0] ?? `${num(r, 2)}:1`;
  return `${named} · ${num(size.w / 360000)} × ${num(size.h / 360000)} см`;
}

export function SpacingCard({ manifest }: { manifest: TemplateManifest }) {
  const spacing = manifest.tokens.spacing;
  const { w, h } = manifest.slide_size;
  if (!spacing) return null;
  const sa = spacing.safe_area;
  const facts: Array<[string, string]> = [
    ["Формат слайда", slideFormat(manifest.slide_size)],
    ["Безопасная область", `${pct(sa.w)} × ${pct(sa.h)} слайда`],
    ["Поля", `слева ${pct(sa.x)} · сверху ${pct(sa.y)} · справа ${pct(Math.max(0, 1 - sa.x - sa.w))} · снизу ${pct(Math.max(0, 1 - sa.y - sa.h))}`],
    ["Направляющие колонок", spacing.columns.length ? spacing.columns.map(pct).join(" · ") : "не выражены"],
    ["Межколонник", spacing.gutter === null || spacing.gutter === undefined ? "не определён" : `${pct(spacing.gutter)} ширины`],
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle icon={Ruler} hint="поля и направляющие, общие для слайдов шаблона">Сетка и поля</CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        <div className="relative w-full overflow-hidden rounded-xl bg-zinc-100 shadow-inner-line" style={{ aspectRatio: w && h ? `${w} / ${h}` : "16 / 9" }}>
          <div className="absolute rounded-sm border border-dashed border-accent bg-accent/5" style={{ left: `${sa.x * 100}%`, top: `${sa.y * 100}%`, width: `${sa.w * 100}%`, height: `${sa.h * 100}%` }} />
          {spacing.columns.map((c) => <div key={c} className="absolute inset-y-0 w-px bg-pink-500/70" style={{ left: `${c * 100}%` }} />)}
          <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-[11px] font-medium text-accent-700">безопасная область</span>
        </div>
        <dl className="space-y-2">
          {facts.map(([k, v]) => (
            <div key={k}>
              <dt className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">{k}</dt>
              <dd className="text-[13px] leading-5 text-zinc-800">{v}</dd>
            </div>
          ))}
        </dl>
      </CardBody>
    </Card>
  );
}
