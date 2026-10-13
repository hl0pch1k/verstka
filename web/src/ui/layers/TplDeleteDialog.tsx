// «Удалить шаблон?» (C-tpldelete): затемнение колоды (240 мс, только opacity) и белая плита 560 по центру (360 мс,
// scale .98 → 1, через 40 мс) над «Слайдами шаблона». Разметка — boards/V2.dc.html, `.dl-scrim.tp-dls` и
// `.dl-wrap.tp-dlw`. «Удалить» — `deleteTemplate`: диалог гаснет, слой уезжает вниз, лента уже без шаблона. Отказ
// сервера (409 — на шаблоне идёт сборка) — строкой в диалоге.
import { useEffect, useRef, useState } from "react";
import { useApp } from "../../store";
import { errText } from "../../lib/narrate";
import { tplLabel } from "../../lib/plain";
import { plural } from "../../lib/utils";
import type { TemplateListItem } from "../../types";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { Spinner } from "../kit/Spinner";
import { usePresence } from "../kit/usePresence";
import { Cover, inkOf } from "../create/TemplateRibbon";

const OUT_MS = 240;

export function TplDeleteDialog() {
  const { ui, dispatch, templates, deleteTemplate } = useApp();
  const id = ui.tplPreview && ui.tplDelete === ui.tplPreview ? ui.tplDelete : null;
  const p = usePresence(!!id, OUT_MS);
  const found = id ? templates.find((t) => t.template_id === id) : undefined;
  const last = useRef<TemplateListItem | null>(null);
  if (found) last.current = found;
  const t = last.current;

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setErr(null);
    setBusy(false);
  }, [id]);

  const cancel = useRef<HTMLButtonElement>(null);
  // фокус — на «Отмена»; диалог закрылся — обратно туда, откуда его открыли («Удалить» в «Слайдах шаблона»)
  useEffect(() => {
    if (!p.shown) return;
    const back = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    cancel.current?.focus({ preventScroll: true });
    return () => {
      if (back?.isConnected) back.focus({ preventScroll: true });
    };
  }, [p.shown]);
  // кнопка «Удалить» на время запроса недоступна и теряет фокус: после отказа фокус — снова на «Отмена»
  useEffect(() => {
    if (err) cancel.current?.focus({ preventScroll: true });
  }, [err]);

  // Esc закрывает диалог, где бы ни стоял фокус, и не доходит до слоя «Слайды шаблона» под ним
  const open = !!id;
  const noRef = useRef<() => void>(() => {});
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      noRef.current();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [open]);

  if (!p.mounted || !t) return null;
  const on = p.shown && !!id;
  const no = () => {
    if (!busy) dispatch({ type: "set", patch: { tplDelete: null } });
  };
  const yes = async () => {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      await deleteTemplate(t.template_id);
      dispatch({ type: "set", patch: { tplDelete: null, tplPreview: null } });
    } catch (e) {
      setErr(errText(e));
      setBusy(false);
    }
  };
  noRef.current = no;
  const name = tplLabel(t);
  const n = t.n_slides ?? 0;
  return (
    <>
      <div className={cls("dl-scrim tp-dls", on && "tp-dl-on")} onClick={no} aria-hidden="true" />
      <div className={cls("dl-wrap tp-dlw", on && "tp-dl-on")}>
        <section className="dl-dlg" role="dialog" aria-modal="true" aria-labelledby="dl-ttl" aria-describedby="dl-desc">
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <Cover src={t.cover_url} kind="d" ink={inkOf(t)} label={`Обложка шаблона ${name}`} />
            <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
              <h2 id="dl-ttl" style={{ margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 24, lineHeight: "32px", letterSpacing: "-0.03em", color: "#0B1220" }}>Удалить шаблон?</h2>
              <span style={{ fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                <b style={{ fontWeight: 700, color: "#0B1220" }}>{name}</b>{n ? ` · ${plural(n, "слайд", "слайда", "слайдов")}` : ""}
              </span>
            </div>
          </div>
          <p id="dl-desc" style={{ margin: "16px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272" }}>Уже собранные презентации останутся.</p>
          {err && (
            <p role="alert" style={{ display: "flex", alignItems: "flex-start", gap: 8, margin: "16px 0 0", fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#DC2626" }}>
              <span style={{ display: "flex", flex: "none", paddingTop: 2 }}><Icon name="alert" size={16} /></span>
              <span>{err}</span>
            </p>
          )}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 16, marginTop: 24 }}>
            <button ref={cancel} type="button" className="p2-ob" onClick={no} disabled={busy}>Отмена</button>
            <button type="button" className="p2-cta" onClick={() => void yes()} disabled={busy} aria-busy={busy} style={{ height: 48, padding: "0 24px", fontSize: 15 }}>
              {busy ? <Spinner size={18} /> : <Icon name="trash" size={18} />}
              <span>Удалить</span>
            </button>
          </div>
        </section>
      </div>
    </>
  );
}
