// Раздел «Шаблоны» (C-gallery): голубой слой поднимается до 120 px — над ним видна полоса колоды, она закрывает раздел
// (Scrim в AppShell). Сетка четыре колонки: «Загрузить свой», затем все шаблоны — свои первыми. Клик по обложке выбирает
// шаблон, таблетка «Слайды» открывает «Слайды шаблона». Разметка — boards/V2.dc.html, `#p2-lay-t` (`tpGal`, `tpGalUp`).
import { useApp } from "../../store";
import { tplLabel } from "../../lib/plain";
import { plural } from "../../lib/utils";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { Cover, inkOf, usePickTemplate } from "../create/TemplateRibbon";
import { orderTemplates, tplMeta, UPLOAD_BUSY_TITLE } from "../create/ribbon";
import { Layer, lsDelay } from "./Layer";

export function TemplatesLayer({ fresh, onUpload, busy }: {
  /** Только что загруженный шаблон — первым, как в ленте. */
  fresh: string | null;
  /** «Загрузить свой»: раздел уезжает, раскрывается шаг 01 и над ним — выбор файла. */
  onUpload(): void;
  /** Файл уже разбирается: «Загрузить свой» не нажимается. */
  busy: boolean;
}) {
  const { ui, dispatch, templates, templateId } = useApp();
  const pick = usePickTemplate();
  const open = ui.sect === "tpls";
  const list = orderTemplates(templates, fresh);
  const close = () => dispatch({ type: "sect", sect: null });
  return (
    <Layer id="p2-lay-t" open={open} top={120} z={open ? 7 : 6} height={692} label="Шаблоны" onClose={close}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, height: 64 }}>
        <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
          <h2 id="ga-ttl" style={{ margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 32, lineHeight: "40px", letterSpacing: "-0.03em", color: "#0B1220", whiteSpace: "nowrap" }}>Шаблоны</h2>
          <p style={{ margin: 0, fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272", whiteSpace: "nowrap" }}>
            {plural(list.length, "шаблон", "шаблона", "шаблонов")}. Выберите оформление или загрузите своё.
          </p>
        </div>
        <button type="button" className="p2-rbl ga-rbw" onClick={close} aria-label="Закрыть"><Icon name="x" size={18} /></button>
      </div>

      <div className="ga-box">
        <div className="ga-scroll p2-fade">
          <div className="ga-grid">
            <div className="p2-ls" style={lsDelay(160)}>
              <button type="button" className="p2-card" onClick={busy ? undefined : onUpload} aria-disabled={busy || undefined}
                title={busy ? UPLOAD_BUSY_TITLE : undefined}>
                <span className="p2-cover ga-act" style={{ height: "auto", aspectRatio: "16 / 9" }}>
                  <span className="p2-lic" aria-hidden="true"><span className="p2-lic-b" /><span className="p2-lic-f"><Icon name="upload" size={22} /></span></span>
                </span>
                <span className="ga-cap">
                  <span className="ga-name">Загрузить свой</span>
                  <span className="ga-meta">.pptx, .potx, .ppt или .odp</span>
                </span>
              </button>
            </div>

            {list.map((t, i) => {
              const sel = t.template_id === templateId;
              const name = tplLabel(t);
              const meta = tplMeta(t);
              return (
                <div key={t.template_id} className="p2-ls" style={lsDelay(200 + i * 40)}>
                  <div className="ga-tile">
                    <button type="button" className="p2-card" onClick={() => pick(t.template_id)} aria-pressed={sel} title={[name, meta].filter(Boolean).join(" · ")}>
                      <span className={cls("p2-cover", sel && "p2-sel")} style={{ height: "auto", aspectRatio: "16 / 9" }}>
                        <Cover src={t.cover_url} kind="r" ink={inkOf(t)} label={`Обложка шаблона ${name}`} />
                        <span className={cls("p2-chk", !sel && "p2-chk-off")} aria-hidden="true"><Icon name="check" size={14} /></span>
                      </span>
                      <span className="ga-cap">
                        <span className="ga-name">{name}</span>
                        <span className="ga-meta">{meta}</span>
                      </span>
                    </button>
                    <button type="button" className="ga-eye" onClick={() => dispatch({ type: "set", patch: { tplPreview: t.template_id, tplDelete: null } })}
                      aria-label={`Слайды шаблона «${name}»`}>
                      <Icon name="eye" size={16} />
                      <span>Слайды</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </Layer>
  );
}
