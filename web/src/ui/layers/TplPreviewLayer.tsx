// «Слайды шаблона» (C-tplpreview): слой над лентой шага 01 или над разделом «Шаблоны» — название с карандашом, точки
// палитры, «54 слайда, шрифт Play», миниатюры всех слайдов лесенкой, внизу «Удалить», «Подробный разбор» и «Выбрать
// шаблон». Разметка — boards/V2.dc.html, `#tp-lay-p`. Слой живёт, пока жив его контекст (раскрытый шаг 01 или открытый
// раздел): ушёл контекст — слой уезжает вниз вместе со всем, под новым разделом (z 6), и сам не возвращается.
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useApp } from "../../store";
import { humanError } from "../../lib/errors";
import { errText } from "../../lib/narrate";
import { templateTitle, tplLabel } from "../../lib/plain";
import { plural } from "../../lib/utils";
import type { TemplateListItem } from "../../types";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { Cover, hexOf, inkOf, usePickTemplate } from "../create/TemplateRibbon";
import { useRise } from "../result/useGoDown";
import { Layer, lsDelay } from "./Layer";
import { Scrim } from "./Scrim";

const thumb = (id: string, n: number) => `/api/templates/${encodeURIComponent(id)}/files/thumbs/slide-${String(n).padStart(3, "0")}.jpg`;
/** V2 `tpPvSlides`: задержка лесенки 160 + 40·i, не дольше восьмой миниатюры. */
const slideDelay = (i: number) => 160 + Math.min(i, 7) * 40;

/** Презентация на этом шаблоне, у которой можно открыть вкладку «Шаблон»: открытая, иначе самая новая готовая. */
function deckOf(id: string, open: { id: string; template_id?: string | null } | null, list: { id: string; template_id: string; status?: string; created_at?: number }[]): string | null {
  if (open?.template_id === id) return open.id;
  const ready = list.filter((g) => g.template_id === id && g.status !== "failed" && g.status !== "running");
  ready.sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0));
  return ready[0]?.id ?? null;
}

export function TplPreviewLayer() {
  const { ui, dispatch, templates, templateId, renameTemplate, generation, generations, loadGeneration } = useApp();
  const pick = usePickTemplate();
  const rise = useRise();
  const id = ui.tplPreview;

  // откуда открыт: из раздела «Шаблоны» или из ленты шага 01 (V2 `tpPvFrom`)
  const [from, setFrom] = useState<"gal" | "step">("step");
  const [dead, setDead] = useState(false);
  const [seen, setSeen] = useState<string | null>(null);
  if (id !== seen) {
    setSeen(id);
    if (id) {
      setFrom(ui.sect === "tpls" ? "gal" : "step");
      setDead(false);
    }
  }
  const ctx = from === "gal" ? ui.sect === "tpls" : ui.screen === "create" && ui.open === "tpl" && !ui.more && !ui.sect;
  // контекст ушёл (логотип, другой раздел, другой экран) — слой закрывается и уходит под новый раздел
  useEffect(() => {
    if (id && !ctx) {
      setDead(true);
      dispatch({ type: "set", patch: { tplPreview: null, tplDelete: null } });
    }
  }, [id, ctx, dispatch]);
  const open = !!id && ctx;

  // последний показанный шаблон держится, пока слой уезжает (и если его только что удалили)
  const found = id ? templates.find((t) => t.template_id === id) : undefined;
  const last = useRef<TemplateListItem | null>(null);
  if (found) last.current = found;
  else if (id && last.current?.template_id !== id) last.current = null;
  const t = last.current;

  // переименование: карандаш → поле с именем, ✓ или Enter — сохранить, Esc — отменить
  const [edit, setEdit] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setEdit(false);
    setErr(null);
  }, [id]);

  const close = () => {
    setDead(false);
    dispatch({ type: "set", patch: { tplPreview: null, tplDelete: null } });
  };

  const name = t ? tplLabel(t) : "";
  const fileName = t?.source_file ?? "";
  const n = t?.n_slides ?? 0;
  const count = n ? plural(n, "слайд", "слайда", "слайдов") : "";
  const meta = [count, t?.font ? `шрифт ${t.font}` : null].filter(Boolean).join(", ");
  const chosen = !!t && t.template_id === templateId;
  const deck = t ? deckOf(t.template_id, generation, generations) : null;

  const save = async () => {
    if (!t || saving) return;
    const v = draft.trim().slice(0, 80);
    // пустое имя или имя файла — шаблон снова зовётся по файлу
    const title = !v || v === templateTitle(t.source_file, t.template_id) ? "" : v;
    if (title === (t.title?.trim() ?? "")) return setEdit(false);
    setSaving(true);
    setErr(null);
    try {
      await renameTemplate(t.template_id, title);
      setEdit(false);
    } catch (e) {
      setErr(humanError(`Не удалось переименовать: ${errText(e)}`, "Не удалось переименовать шаблон"));
    } finally {
      setSaving(false);
    }
  };
  const onNameKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void save();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation(); // Esc закрывает только поле, не слой
      setEdit(false);
      setErr(null);
    }
  };

  // «Подробный разбор»: результат этой презентации и лист «Подробнее» на вкладке «Шаблон»
  const details = () => {
    if (!deck) return;
    const fromCreate = ui.screen === "create";
    if (generation?.id !== deck) void loadGeneration(deck);
    dispatch({ type: "go", screen: "result" });
    // из «Создать» плита результата поднимается снизу одним движением с плитами (V2 `openDoc`)
    if (fromCreate) rise();
    dispatch({ type: "sheet", tab: "template" });
  };

  const single = templates.length <= 1;
  return (
    <>
      <Scrim open={open} onClose={close} label="Закрыть «Слайды шаблона»" z={8} />
      <Layer id="tp-lay-p" open={open} top={120} z={open || !dead ? 8 : 6} label={`Слайды шаблона «${name}»`} role="dialog" onClose={close}>
        {t && (
          <>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, height: 64 }}>
              <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                {!edit ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 16, height: 40, minWidth: 0 }}>
                    <h2 title={t.title ? `Файл: ${fileName}` : undefined}
                      style={{ margin: 0, minWidth: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 32, lineHeight: "40px", letterSpacing: "-0.03em", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {name}
                    </h2>
                    <button type="button" className="p2-rbl pv-rbw pv-edit" onClick={() => { setDraft(name); setErr(null); setEdit(true); }} aria-label="Переименовать шаблон" title="Переименовать">
                      <Icon name="pen" size={16} />
                    </button>
                  </div>
                ) : (
                  <div className="p2-in" style={{ display: "flex", alignItems: "center", gap: 8, height: 40 }}>
                    <label style={{ display: "flex", alignItems: "center" }}>
                      <span className="p2-sr">Название шаблона</span>
                      <input type="text" className="p2-inp pv-name" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onNameKey}
                        placeholder={fileName} maxLength={80} aria-label="Название шаблона" autoFocus disabled={saving} />
                    </label>
                    <button type="button" className="p2-rbl pv-rbw" onClick={() => void save()} aria-label="Сохранить название" disabled={saving}>
                      <Icon name="check" size={18} />
                    </button>
                  </div>
                )}
                <div style={{ display: "flex", alignItems: "center", gap: 16, height: 24 }}>
                  {err ? (
                    <ErrorLine text={err} lines={1} />
                  ) : (
                    <>
                      {!!t.palette?.length && (
                        <span role="img" aria-label="Палитра шаблона" style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          {t.palette.slice(0, 6).map(hexOf).map((hex, i) => <span key={`${hex}-${i}`} className="pv-dot" title={hex} style={{ background: hex }} />)}
                        </span>
                      )}
                      <span style={{ fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272", whiteSpace: "nowrap" }}>{meta}</span>
                    </>
                  )}
                </div>
              </div>
              <button type="button" className="p2-rbl pv-rbw" onClick={close} aria-label="Закрыть"><Icon name="x" size={18} /></button>
            </div>

            <div className="pv-box">
              <div className="pv-scroll p2-fade">
                <ol className="pv-grid" aria-label="Слайды шаблона">
                  {Array.from({ length: n }, (_, i) => (
                    <li key={i} className="p2-ls" style={lsDelay(slideDelay(i))}>
                      <Cover src={thumb(t.template_id, i + 1)} kind="s" ink={inkOf(t)} label={`Слайд ${i + 1} шаблона`} />
                      <span className="pv-n">{i + 1}</span>
                    </li>
                  ))}
                </ol>
              </div>
              <div className="pv-foot">
                <button type="button" className="p2-gb pv-del" onClick={() => dispatch({ type: "set", patch: { tplDelete: t.template_id } })}
                  disabled={single} title={single ? "Последний шаблон удалить нельзя" : undefined} style={single ? { opacity: 0.32, cursor: "default" } : undefined}>
                  <Icon name="trash" size={18} />
                  <span>Удалить</span>
                </button>
                <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                  {deck && (
                    <button type="button" className="p2-ob" onClick={details}>
                      <Icon name="search" size={18} />
                      <span>Подробный разбор</span>
                    </button>
                  )}
                  <button type="button" className="p2-cta pv-cta" onClick={() => pick(t.template_id)} aria-pressed={chosen}>
                    {chosen ? (
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}><Icon name="check" size={18} /><span>Шаблон выбран</span></span>
                    ) : (
                      <span>Выбрать шаблон</span>
                    )}
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </Layer>
    </>
  );
}
