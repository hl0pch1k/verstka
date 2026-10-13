// Лента шага 01 (C-templates): шесть обложек (четыре, когда помощник сужает колоду) — свои первыми, выбранная всегда
// видна, — плитка «Все шаблоны · ещё N» и плитка «Загрузить свой». Разметка — boards/V2.dc.html, `#p2-b1` (`tpRib`, `tpMoreOn`, плитка `tpUpload`). Здесь же
// обложка шаблона (картинка или схема титульного слайда `tp-wf`) и плитка обложки — их берут разбор, раздел «Шаблоны»,
// «Слайды шаблона» и диалог удаления.
import { useState, type CSSProperties } from "react";
import { useApp } from "../../store";
import { tplLabel } from "../../lib/plain";
import { plural } from "../../lib/utils";
import type { TemplateListItem } from "../../types";
import { cls } from "../kit/cls";
import { Icon, type IconName } from "../kit/Icon";
import { ribbonItems, tplMeta, tplShort } from "./ribbon";

/** Как стоит обложка: плитка ленты (142 px), раздел «Шаблоны» (16:9), миниатюра слайда (16:9, r12), шапка шага
 *  (80×45), диалог удаления (112, 16:9). */
export type CoverKind = "tile" | "r" | "s" | "m" | "d";

const IMG: Record<CoverKind, CSSProperties> = {
  tile: { display: "block", width: "100%", height: 142, objectFit: "cover", borderRadius: 16, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" },
  r: { display: "block", width: "100%", aspectRatio: "16 / 9", objectFit: "cover", borderRadius: 16, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" },
  s: { display: "block", width: "100%", aspectRatio: "16 / 9", objectFit: "cover", borderRadius: 12, background: "#F3F4F1", boxShadow: "0 0 0 1px rgba(11,18,32,.08)" },
  m: { display: "block", width: 80, height: 45, objectFit: "cover", borderRadius: 12, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" },
  d: { display: "block", flex: "none", width: 112, aspectRatio: "16 / 9", objectFit: "cover", borderRadius: 12, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" },
};
const WF: Record<CoverKind, string> = { tile: "tp-wf", r: "tp-wf tp-wf-r", s: "tp-wf tp-wf-s", m: "tp-wf tp-wf-m", d: "tp-wf tp-wf-d" };

/** Цвет палитры как CSS: сервер шлёт «FEFCFF» без решётки. */
export const hexOf = (h: string) => (h.startsWith("#") ? h : `#${h}`);

/** Цвет акцента схемы — первый цвет палитры шаблона. */
export const inkOf = (t: Pick<TemplateListItem, "palette"> | null | undefined) => (t?.palette?.[0] ? hexOf(t.palette[0]) : "#2563EB");

/** Схема титульного слайда, пока у шаблона нет картинки (V2 `tp-wf`): метка, два ряда заголовка, подпись. */
export function Wireframe({ kind, ink, label }: { kind: CoverKind; ink: string; label: string }) {
  return (
    <span className={WF[kind]} role="img" aria-label={label}>
      <span className="tp-b" style={{ left: "8%", top: "24%", width: "10%", height: "4%", background: ink }} />
      <span className="tp-b tp-dk" style={{ left: "8%", top: "36%", width: "56%", height: "9%" }} />
      <span className="tp-b tp-dk" style={{ left: "8%", top: "49%", width: "38%", height: "9%" }} />
      <span className="tp-b" style={{ left: "8%", top: "66%", width: "30%", height: "4%" }} />
    </span>
  );
}

/** Картинка (обложка `cover_url` или миниатюра слайда); нет её или она не загрузилась — схема в цвете шаблона. */
export function Cover({ src, kind, ink, label }: { src?: string | null; kind: CoverKind; ink: string; label: string }) {
  const [bad, setBad] = useState<string | null>(null);
  if (!src || bad === src) return <Wireframe kind={kind} ink={ink} label={label} />;
  return <img src={src} alt={label} loading={kind === "s" ? "lazy" : undefined} decoding="async" style={IMG[kind]} onError={() => setBad(src)} />;
}

/** Выбор шаблона в ленте, разделе и «Слайдах шаблона». Другой шаблон выводит из «Улучшить готовую» (её оформление —
 *  сама презентация; V2 `txImpOn` требует `tpl === txTpl`). */
export function usePickTemplate() {
  const { templateId, selectTemplate, ui, dispatch } = useApp();
  return (id: string) => {
    if (id === templateId) return;
    selectTemplate(id);
    if (ui.improve) dispatch({ type: "set", patch: { improve: false } });
  };
}

/** Плитка обложки: выбор по клику, галочка у выбранной, таблетка «Слайды» при наведении. `kind` — классы доски:
 *  tt (лента) или an (лента во время разбора). */
export function TemplateTile({ t, selected, delay, out, onPick, onPeek, kind = "tt" }: {
  t: TemplateListItem; selected: boolean; delay: number; out?: boolean; onPick(): void; onPeek(): void; kind?: "tt" | "an";
}) {
  const name = tplLabel(t);
  const short = tplShort(t);
  const full = [name, tplMeta(t)].filter(Boolean).join(" · ");
  return (
    <div className={cls("p2-stag p2-in", out && "tp-out")} style={{ animationDelay: `${delay}ms`, transitionDelay: `${delay}ms` }}>
      <div className={`${kind}-tile`}>
        <button type="button" className="p2-card" onClick={onPick} aria-pressed={selected} title={full}>
          <span className={cls("p2-cover", selected && "p2-sel")}>
            <Cover src={t.cover_url} kind="tile" ink={inkOf(t)} label={`Обложка шаблона ${name}`} />
            <span className={cls("p2-chk", !selected && "p2-chk-off")} aria-hidden="true"><Icon name="check" size={14} /></span>
          </span>
          <span className={`${kind}-cap`}>
            <span className={`${kind}-name`}>{name}</span>
            {short && <span className={`${kind}-meta`}>{short}</span>}
          </span>
        </button>
        <button type="button" className={`${kind}-eye`} onClick={onPeek} aria-label={`Слайды шаблона «${name}»`}>
          <Icon name="eye" size={16} />
          <span>Слайды</span>
        </button>
      </div>
    </div>
  );
}

/** Служебная плитка: значок-слои и подпись в две строки (высота 40 у обеих — знаки на одной линии). */
export function ActTile({ icon, note, name, delay, out, onClick, label, title, kind = "tt" }: {
  icon: IconName; note: string[]; name: string; delay: number; out?: boolean; onClick(): void; label?: string; title?: string; kind?: "tt" | "an";
}) {
  return (
    <div className={cls("p2-stag p2-in", out && "tp-out")} style={{ animationDelay: `${delay}ms`, transitionDelay: `${delay}ms` }}>
      <button type="button" className="p2-card" onClick={onClick} aria-label={label} title={title}>
        <span className={`p2-cover ${kind}-act`}>
          <span className="p2-lic" aria-hidden="true"><span className="p2-lic-b" /><span className="p2-lic-f"><Icon name={icon} size={22} /></span></span>
          <span className={`${kind}-note`}>{note.map((s) => <span key={s}>{s}</span>)}</span>
        </span>
        <span className={`${kind}-cap`}>
          <span className={`${kind}-name`}>{name}</span>
        </span>
      </button>
    </div>
  );
}

/** «ещё 2 шаблона». */
export const moreText = (n: number) => `ещё ${plural(n, "шаблон", "шаблона", "шаблонов")}`;

export function Ribbon({ covers, fresh, onPeek, onGallery, onUpload }: {
  /** Сколько обложек: в широкой колоде шесть, в суженной помощником — четыре (с «Все шаблоны» и «Загрузить свой» — те же
   *  два ряда; fit.ts `ribbonLayout`). */
  covers: number;
  /** Только что загруженный шаблон — первым. */
  fresh: string | null;
  onPeek(id: string): void;
  onGallery(): void;
  onUpload(): void;
}) {
  const { templates, templateId } = useApp();
  const pick = usePickTemplate();
  const { shown, rest } = ribbonItems(templates, templateId, covers, fresh);
  const hidden = templates.filter((x) => !shown.includes(x));
  return (
    <>
      {shown.map((t, i) => (
        <TemplateTile key={t.template_id} t={t} selected={t.template_id === templateId} delay={i * 40}
          onPick={() => pick(t.template_id)} onPeek={() => onPeek(t.template_id)} />
      ))}
      {rest > 0 && (
        <ActTile icon="grid" note={[moreText(rest)]} name="Все шаблоны" delay={240} onClick={onGallery}
          label={`Все шаблоны, ${moreText(rest)}`} title={hidden.map(tplLabel).join(", ")} />
      )}
      <ActTile icon="upload" note={[".pptx, .potx, .ppt или .odp", "до 200 МБ"]} name="Загрузить свой" delay={280} onClick={onUpload} />
    </>
  );
}
