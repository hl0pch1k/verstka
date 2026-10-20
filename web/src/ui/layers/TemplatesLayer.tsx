// Раздел «Шаблоны» (C-gallery): голубой слой поднимается до 120 px — над ним видна полоса колоды, она закрывает раздел
// (Scrim в AppShell). Сетка четыре колонки: «Загрузить свой», затем все шаблоны — свои первыми. Клик по обложке выбирает
// шаблон, таблетка «Слайды» открывает «Слайды шаблона». Разметка — boards/V2.dc.html, `#p2-lay-t` (`tpGal`, `tpGalUp`).
// Помощник сужает колоду — сетка идёт за ней каждый кадр (четыре колонки и в узкой, как V2 версии 100).
import { useEffect, useState } from "react";
import { useApp } from "../../store";
import { tplLabel } from "../../lib/plain";
import { plural } from "../../lib/utils";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { Cover, inkOf, usePickTemplate } from "../create/TemplateRibbon";
import { orderTemplates, tplMeta } from "../create/ribbon";
import { Caption } from "./HistoryLayer";
import { Layer, lsDelay } from "./Layer";
import { useWarm } from "./warm";
import { deckPick } from "./tplPick";
import { deckTemplate } from "../result/resultView";
import { startFailure } from "../create/params";
import { BUILD_RUNNING } from "../create/ParamsPlate";
import { ErrorLine } from "../kit/ErrorLine";

export function TemplatesLayer({ fresh, onUpload, busy }: {
  /** Только что загруженный шаблон — первым, как в ленте. */
  fresh: string | null;
  /** «Загрузить свой»: раздел уезжает, раскрывается шаг 01 и над ним — выбор файла. */
  onUpload(): void;
  /** Файл уже разбирается (или читается презентация «Улучшить готовую»): «Загрузить свой» не нажимается — почему; null — нажимается. */
  busy: string | null;
}) {
  const { ui, dispatch, templates, templateId, templateLabel, generation, retryBuild, building, notices } = useApp();
  const pick = usePickTemplate();
  const open = ui.sect === "tpls";
  const list = orderTemplates(templates, fresh);
  // над результатом: выбор — для следующей сборки, открытая презентация остаётся на своём шаблоне (полоса 01 — о ней);
  // строка под заголовком говорит это, «Пересобрать на нём» собирает эту же презентацию на выбранном
  const deck = ui.screen === "result" ? generation : null;
  const chosenTpl = templates.find((t) => t.template_id === templateId);
  const here = deck ? deckPick({
    deckTpl: deckTemplate(deck), deckName: templateLabel(deckTemplate(deck), deck.template_file),
    chosen: templateId, chosenName: chosenTpl ? tplLabel(chosenTpl) : null, improved: !!deck.improved_from,
  }) : null;
  const [askAt, setAskAt] = useState<number | null>(null);
  const [asking, setAsking] = useState(false);
  const target = here?.rebuild ?? null;
  // раздел закрылся или выбран другой шаблон: прежний отказ сервера больше не о нём
  useEffect(() => setAskAt(null), [open, target]);
  const refused = startFailure(notices.build, askAt);
  const rebuildOff = building ? BUILD_RUNNING : null;
  const rebuild = () => {
    if (!deck || !target || rebuildOff || asking) return;
    setAskAt(Date.now());
    setAsking(true);
    // принятая сборка уводит на «Сборку» (переход закрывает раздел); отказ — строкой под заголовком
    void retryBuild(deck, target).finally(() => setAsking(false));
  };
  const sub = here ? here.line : `${plural(list.length, "шаблон", "шаблона", "шаблонов")}. Выберите оформление или загрузите своё.`;
  // прогрет наведением на пункт шапки — смонтирован закрытым, подъём в кадре нажатия
  const warm = useWarm("tpls");
  const close = () => dispatch({ type: "sect", sect: null });
  // помощник сужает колоду: те же четыре колонки сужаются вместе с ней (V2 версии 100), подписи — в строку с многоточием
  return (
    <Layer id="p2-lay-t" open={open} warm={warm} top={120} z={open ? 7 : 6} height={692} label="Шаблоны" onClose={close}>
      <div className="ly-hd" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, height: 64 }}>
        <div className="ly-hc" style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
          <h2 id="ga-ttl" className="ly-ttl" style={{ margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 32, lineHeight: "40px", letterSpacing: "-0.03em", color: "#0B1220", whiteSpace: "nowrap" }}>Шаблоны</h2>
          {refused ? <ErrorLine text={refused} lines={1} style={{ height: 24, fontSize: 15, lineHeight: "24px" }} /> : (
            <p className="ly-sub" title={here ? sub : undefined}
              style={{ margin: 0, fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {sub}
            </p>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, flex: "none" }}>
          {target && (
            <button type="button" className="p2-ob ga-rb" data-hpm="" onClick={rebuild} aria-disabled={rebuildOff || asking ? true : undefined} aria-busy={asking || undefined}
              title={rebuildOff ?? `Собрать эту презентацию заново на шаблоне «${chosenTpl ? tplLabel(chosenTpl) : "шаблон"}»: тот же текст, параметры и данные`}>
              <Icon name="refresh" size={18} />
              <span>Пересобрать на нём</span>
            </button>
          )}
          <button type="button" className="p2-rbl ga-rbw" data-hpm="" onClick={close} aria-label="Закрыть"><Icon name="x" size={18} /></button>
        </div>
      </div>

      <div className="ga-box">
        <div className="ga-scroll p2-fade">
          <div className="ga-grid">
            <div className="p2-ls" style={lsDelay(160)}>
              <button type="button" className="p2-card" onClick={busy ? undefined : onUpload} aria-disabled={busy ? true : undefined}
                title={busy ?? undefined}>
                {/* помощник сужает сетку: обложка — сдвигом и масштабом, подпись — сдвигом (helperMotion) */}
                <span className="p2-cover ga-act" data-hpz="" style={{ height: "auto", aspectRatio: "16 / 9" }}>
                  <span className="p2-lic" aria-hidden="true"><span className="p2-lic-b" /><span className="p2-lic-f"><Icon name="upload" size={22} /></span></span>
                </span>
                <Caption className="ga-cap">
                  <span className="ga-name">Загрузить свой</span>
                  <span className="ga-meta">.pptx, .potx, .ppt или .odp</span>
                </Caption>
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
                      <span className={cls("p2-cover", sel && "p2-sel")} data-hpz="" style={{ height: "auto", aspectRatio: "16 / 9" }}>
                        <Cover src={t.cover_url} kind="r" ink={inkOf(t)} label={`Обложка шаблона ${name}`} />
                        <span className={cls("p2-chk", !sel && "p2-chk-off")} aria-hidden="true"><Icon name="check" size={14} /></span>
                      </span>
                      <Caption className="ga-cap">
                        <span className="ga-name">{name}</span>
                        <span className="ga-meta">{meta}</span>
                      </Caption>
                    </button>
                    <button type="button" className="ga-eye" data-hpm="" onClick={() => dispatch({ type: "set", patch: { tplPreview: t.template_id, tplDelete: null } })}
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
