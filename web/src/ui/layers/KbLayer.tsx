// Слой «База знаний» (направление I финальной доводки): голубой слой поднимается из-под колоды, как «Брендбук». Слева —
// документы базы карточками (название, формат, сколько страниц и фрагментов, ✕ — убрать), справа — как добавить: файлы,
// папку или архив .zip, ссылку на публичную страницу; что агент сделает с базой. Документы можно отпустить на слой.
// Внизу «Новая база» и «Готово». Открывается из «Из файла» → «База знаний» и с карточки базы в заголовке шага 02.
import { useEffect, useRef, useState } from "react";
import { useApp } from "../../store";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { Spinner } from "../kit/Spinner";
import { DsIcon, type DsIconName } from "../create/dsKit";
import { useFilesDrop } from "../create/DataPanel";
import { useWriting } from "../create/TextPlate";
import { docMeta, kbHead, kbHint, KB_ACCEPT } from "../create/kbRules";
import { Layer, lsDelay, useLayerPresence } from "./Layer";
import { Scrim } from "./Scrim";
import type { KbDoc } from "../../types";

const docIcon = (d: KbDoc): DsIconName => (d.source === "link" ? "frame" : d.kind === "pdf" || d.kind === "docx" ? "file" : "txt");

export function KbLayer() {
  const { ui, dispatch, kb } = useApp();
  const { writer } = useWriting();
  const ctx = ui.screen === "create" && !ui.sect;
  useEffect(() => {
    if (ui.kbLayer && !ctx) dispatch({ type: "set", patch: { kbLayer: false } });
  }, [ui.kbLayer, ctx, dispatch]);
  const open = ui.kbLayer && ctx;
  const p = useLayerPresence(open);
  const close = () => dispatch({ type: "set", patch: { kbLayer: false } });
  const files = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const [link, setLink] = useState("");
  const docs = kb.kb?.docs ?? [];
  const drop = useFilesDrop(body, open && !kb.busy, (fs) => void kb.addFiles(fs));
  // у папки — атрибут без имени в типах React
  useEffect(() => {
    folder.current?.setAttribute("webkitdirectory", "");
  }, [p.mounted]);
  const addLink = async () => {
    if (await kb.addLink(link)) setLink("");
  };
  const status = kb.busy ?? kb.error ?? kb.done;
  return (
    <>
      <Scrim open={open} onClose={close} label="Закрыть «База знаний»" z={8} />
      <Layer id="kb-lay" presence={p} open={open} top={120} z={8} label="База знаний" role="dialog" onClose={close}>
        {p.mounted && (
          <>
            <div className="ly-hd" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, height: 64 }}>
              <div className="ly-hc" style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                <h2 className="ly-ttl" style={{ margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 32, lineHeight: "40px", letterSpacing: "-0.03em", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  База знаний
                </h2>
                <span className="ly-sub kb-sub">{kbHead(kb.kb)}</span>
              </div>
              <button type="button" className="p2-rbl pv-rbw" onClick={close} aria-label="Закрыть"><Icon name="x" size={18} /></button>
            </div>

            <div className="pv-box" ref={body}>
              <div className="pv-scroll p2-fade">
                <div className="bb-g kb-g">
                  <section className="p2-ls" aria-labelledby="kb-h-docs" style={lsDelay(160)}>
                    <h3 id="kb-h-docs" className="dd-h">Документы</h3>
                    {docs.length ? (
                      <ul className="kb-list">
                        {docs.map((d) => (
                          <li key={d.id} className="kb-card" title={d.url ?? d.name}>
                            <span className="dt-ic" aria-hidden="true"><DsIcon name={docIcon(d)} size={16} /></span>
                            <span className="kb-tx">
                              <span className="kb-nm">{d.title || d.name}</span>
                              <span className="kb-mt">{docMeta(d)}</span>
                            </span>
                            <button type="button" className="dt-x" onClick={() => void kb.remove(d.id)} aria-label={`Убрать «${d.title || d.name}» из базы`}>
                              <DsIcon name="x" size={16} />
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <button type="button" className={cls("kb-drop", drop.over && "kb-drop-on")} onClick={() => files.current?.click()}>
                        <span className="kb-dic" aria-hidden="true"><DsIcon name="upload" size={24} /></span>
                        <span className="kb-dt">Перетащите сюда документы, папку или архив</span>
                        <span className="kb-dm">DOCX, PDF, Markdown, текст, HTML · до 25 МБ каждый</span>
                      </button>
                    )}
                    {docs.length > 0 && drop.over && <p className="kb-over">Отпустите — добавлю в базу</p>}
                    <div className="kb-how">
                      <h4 className="kb-hh">Как агент использует базу</h4>
                      <ul className="kb-hl">
                        <li>Находит в документах фрагменты по вашей теме или плану — поиск идёт здесь, без внешних сервисов.</li>
                        <li>Пишет слайды по фактам из них: цифры, которых нет в документах, на слайд не попадают.</li>
                        <li>У каждого факта — документ и место: в заметках слайда и в «Почему так».</li>
                      </ul>
                      <p className={cls("kb-hint", !writer && docs.length > 0 && "kb-hint-off")}>{kbHint(writer, docs.length)}</p>
                    </div>
                  </section>

                  <section className="p2-ls" aria-labelledby="kb-h-add" style={lsDelay(200)}>
                    <h3 id="kb-h-add" className="dd-h">Добавить</h3>
                    <div className="kb-btns">
                      <button type="button" className="p2-ob kb-ob" onClick={() => files.current?.click()} disabled={!!kb.busy}>
                        <Icon name="file-text" size={18} /><span>Документы</span>
                      </button>
                      <button type="button" className="p2-ob kb-ob" onClick={() => folder.current?.click()} disabled={!!kb.busy}>
                        <Icon name="folder-down" size={18} /><span>Папку</span>
                      </button>
                    </div>
                    <form className="kb-link" onSubmit={(e) => {
                      e.preventDefault();
                      void addLink();
                    }}>
                      <label htmlFor="kb-url" className="kb-lb">Ссылка на публичную страницу</label>
                      <div className="kb-lr">
                        <input id="kb-url" className="kb-in" type="url" inputMode="url" placeholder="https://…" value={link} onChange={(e) => setLink(e.target.value)}
                          autoComplete="off" spellCheck={false} disabled={!!kb.busy} />
                        <button type="submit" className="p2-ob kb-ob" disabled={!!kb.busy || !link.trim()}>Добавить</button>
                      </div>
                      <p className="kb-note">Одна страница по ссылке: без входа и паролей, до 5 МБ. Ссылки на ней не открываются.</p>
                    </form>
                    <p className={cls("kb-st", kb.error && !kb.busy && "kb-st-bad")} role="status" aria-live="polite">
                      {status && (
                        <>
                          <span className="kb-sic" aria-hidden="true">{kb.busy ? <Spinner size={16} /> : kb.error ? <Icon name="alert" size={16} /> : <Icon name="check" size={16} />}</span>
                          <span>{status}</span>
                        </>
                      )}
                    </p>
                  </section>
                </div>
              </div>
              <div className="pv-foot">
                <button type="button" className="p2-gb pv-del" onClick={kb.clear} disabled={!docs.length}>
                  <Icon name="refresh" size={18} />
                  <span>Новая база</span>
                </button>
                <button type="button" className="p2-cta pv-cta" onClick={close}><span>Готово</span></button>
              </div>
            </div>
            <input ref={files} type="file" accept={KB_ACCEPT} multiple hidden tabIndex={-1} aria-hidden="true"
              onChange={(e) => {
                const list = Array.from(e.currentTarget.files ?? []);
                e.currentTarget.value = "";
                if (list.length) void kb.addFiles(list);
              }} />
            <input ref={folder} type="file" multiple hidden tabIndex={-1} aria-hidden="true"
              onChange={(e) => {
                const list = Array.from(e.currentTarget.files ?? []);
                e.currentTarget.value = "";
                if (list.length) void kb.addFiles(list);
              }} />
          </>
        )}
      </Layer>
    </>
  );
}
