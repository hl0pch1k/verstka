// The design tokens of the template in plain words: colours with their roles, fonts and sizes, the slide grid.
import { useState } from "react";
import { fontStack } from "../lib/fonts";
import { cn, isLightHex, plural } from "../lib/utils";
import { useApp } from "../store";
import type { ColorToken, TemplateManifest } from "../types";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";

export const hexOf = (hex: string) => (hex.startsWith("#") ? hex : `#${hex}`).toUpperCase();
const num = (v: number, digits = 1) => v.toLocaleString("ru-RU", { maximumFractionDigits: digits });
const pct = (v: number) => `${num(v * 100, 0)}%`;

export function roleLabel(role: string): string {
  const [base, sub] = role.split(".");
  if (base === "background") return sub === "dark" ? "тёмный фон" : sub === "light" ? "светлый фон" : "фон";
  if (base === "surface") return "подложка";
  if (base === "text") return sub === "secondary" ? "второстепенный текст" : sub === "inverse" ? "текст на тёмном" : "основной текст";
  if (base === "accent") return sub ? `акцент ${sub}` : "акцент";
  if (base === "neutral") return "нейтральный";
  return role;
}

const SEMANTIC: Record<string, string> = { negative: "для негатива", positive: "для позитива", warning: "для предупреждений" };

function Swatch({ color, share }: { color: ColorToken; share: number }) {
  const { toast } = useApp();
  const hex = hexOf(color.hex);
  const roles = color.roles.length ? color.roles : color.role ? [color.role] : [];
  const role = color.semantic ? SEMANTIC[color.semantic] ?? color.semantic : roles[0] ? roleLabel(roles[0]) : null;
  const copy = () => void navigator.clipboard?.writeText(hex).then(() => toast("success", `Цвет ${hex} скопирован`), () => undefined);
  return (
    <button type="button" onClick={copy} title="Скопировать цвет" className="group min-w-0 cursor-pointer text-left focus:outline-none">
      <span
        className={cn("flex h-16 items-end rounded-xl px-2.5 pb-2 font-mono text-[11px] font-semibold shadow-inner-line transition-transform duration-200 group-hover:-translate-y-0.5 group-focus-visible:shadow-[0_0_0_2px_#0077FF]", isLightHex(hex) ? "text-zinc-900/70" : "text-white/90")}
        style={{ backgroundColor: hex }}
      >
        {hex}
      </span>
      <span className="mt-1.5 flex items-baseline justify-between gap-2 px-0.5 text-xs">
        <span className="truncate text-zinc-700">{color.is_brand ? "фирменный" : role ?? "дополнительный"}</span>
        <span className="shrink-0 tabular-nums text-zinc-400">{share < 0.01 ? "<1%" : pct(share)}</span>
      </span>
    </button>
  );
}

const PALETTE_LIMIT = 12;

export function PaletteCard({ manifest }: { manifest: TemplateManifest }) {
  const [all, setAll] = useState(false);
  const colors = manifest.tokens.colors;
  const total = colors.reduce((s, c) => s + c.weight, 0) || 1;
  const shown = all ? colors : colors.slice(0, PALETTE_LIMIT);
  if (colors.length === 0) return null;
  const bg = manifest.tokens.backgrounds ?? [];
  const light = bg.filter((b) => b.family !== "dark").reduce((n, b) => n + b.slides.length, 0);
  const dark = bg.filter((b) => b.family === "dark").reduce((n, b) => n + b.slides.length, 0);
  return (
    <Card>
      <CardHeader actions={colors.length > PALETTE_LIMIT && <button type="button" onClick={() => setAll(!all)} className="cursor-pointer text-[13px] font-semibold text-accent-700 hover:underline">{all ? "Свернуть" : `Все ${colors.length}`}</button>}>
        <CardTitle hint={`По доле площади в шаблоне${bg.length ? ` · фоны: светлых слайдов ${light}, тёмных ${dark}` : ""} · нажмите, чтобы скопировать`}>Цвета</CardTitle>
      </CardHeader>
      <CardBody>
        <div className="grid grid-cols-6 gap-x-3 gap-y-4">{shown.map((c) => <Swatch key={c.hex} color={c} share={c.weight / total} />)}</div>
      </CardBody>
    </Card>
  );
}

const SCALE_RU: Record<string, { label: string; sample: string }> = {
  display: { label: "Дисплей", sample: "Заголовок доклада" },
  h1: { label: "Заголовок слайда", sample: "Главная мысль слайда" },
  h2: { label: "Подзаголовок", sample: "Подзаголовок или тезис" },
  h3: { label: "Заголовок блока", sample: "Заголовок карточки" },
  body: { label: "Основной текст", sample: "Факты, пояснения и выводы" },
  small: { label: "Мелкий текст", sample: "Подписи и источники данных" },
  caption: { label: "Подпись", sample: "Подпись к диаграмме" },
};

export function TypographyCard({ manifest }: { manifest: TemplateManifest }) {
  const typo = manifest.tokens.typography;
  const primary = typo.families[0]?.family;
  const maxPt = Math.max(1, ...typo.scale.map((s) => s.size_pt));
  if (typo.families.length === 0 && typo.scale.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle hint="Шрифты по доле текста и размеры, которых придерживается шаблон">Шрифты и размеры</CardTitle>
      </CardHeader>
      <CardBody className="space-y-5">
        <div className="flex flex-wrap gap-2">
          {typo.families.slice(0, 4).map((f) => (
            <span key={f.family} className="flex items-baseline gap-2 rounded-xl bg-zinc-100 px-3.5 py-2">
              <span className="text-[15px] font-semibold text-zinc-900" style={{ fontFamily: fontStack(f.family) }}>{f.family}</span>
              <span className="text-xs tabular-nums text-zinc-500">{pct(f.weight)}</span>
              {manifest.embedded_fonts.includes(f.family) && <span className="text-xs text-zinc-400">встроен</span>}
            </span>
          ))}
        </div>
        {typo.scale.length > 0 && (
          <ul className="divide-y divide-zinc-100">
            {typo.scale.map((s) => {
              const meta = SCALE_RU[s.role] ?? { label: s.role, sample: "Пример текста" };
              return (
                <li key={s.role} className="flex items-center gap-4 py-2.5">
                  <span className="w-40 shrink-0">
                    <span className="block text-[13px] font-medium text-zinc-900">{meta.label}</span>
                    <span className="block text-xs tabular-nums text-zinc-500">{num(s.size_pt)} пт</span>
                  </span>
                  <span className="min-w-0 flex-1 truncate leading-tight text-zinc-900" style={{ fontFamily: fontStack(primary), fontSize: Math.max(11, Math.round((s.size_pt / maxPt) * 32)), fontWeight: s.weight_bold_share > 0.5 ? 700 : 400 }}>
                    {meta.sample}
                  </span>
                </li>
              );
            })}
          </ul>
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
  return (
    <Card>
      <CardHeader>
        <CardTitle hint="Поля, внутри которых Verstka размещает содержание, и направляющие колонок">Сетка и поля</CardTitle>
      </CardHeader>
      <CardBody className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-center gap-6">
        <div className="relative w-full overflow-hidden rounded-xl bg-zinc-100 shadow-inner-line" style={{ aspectRatio: w && h ? `${w} / ${h}` : "16 / 9" }}>
          <div className="absolute rounded-md border border-dashed border-accent bg-accent/[0.06]" style={{ left: `${sa.x * 100}%`, top: `${sa.y * 100}%`, width: `${sa.w * 100}%`, height: `${sa.h * 100}%` }} />
          {spacing.columns.map((c) => <div key={c} className="absolute inset-y-0 w-px bg-accent/40" style={{ left: `${c * 100}%` }} />)}
        </div>
        <dl className="space-y-3 text-[13px]">
          <div><dt className="text-xs text-zinc-500">Формат</dt><dd className="font-medium text-zinc-900">{slideFormat(manifest.slide_size)}</dd></div>
          <div><dt className="text-xs text-zinc-500">Поля</dt><dd className="font-medium text-zinc-900">слева {pct(sa.x)}, сверху {pct(sa.y)}, справа {pct(Math.max(0, 1 - sa.x - sa.w))}, снизу {pct(Math.max(0, 1 - sa.y - sa.h))}</dd></div>
          <div><dt className="text-xs text-zinc-500">Колонки</dt><dd className="font-medium text-zinc-900">{spacing.columns.length ? plural(spacing.columns.length, "направляющая", "направляющие", "направляющих") : "не выражены"}</dd></div>
        </dl>
      </CardBody>
    </Card>
  );
}
