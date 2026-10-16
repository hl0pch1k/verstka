// Разбор брендбука в теле шага 01 (boards/V2.dc.html версии 105, модуль ds, `bbRunOn`; язык C-analyzing): слева файл с
// полосой хода и три плитки, которые заполняются по ходу разбора — шрифты, палитра, логотипы (пульс гаснет, содержимое
// проявляется); справа на две колонки — шаги разбора по событиям задачи. Когда помощник сужает колоду, вторая дорожка
// сжимается до нуля и её плитки (шрифты, логотипы) гаснут на месте (`tp-anl`, как у разбора шаблона). Все шаги готовы —
// галочки держатся 560 мс, разбор гаснет 240 мс (`tp-out`) и возвращается лента. Неудача — строка в той же коробке.
import type { CSSProperties } from "react";
import { api } from "../../api";
import { useApp } from "../../store";
import { tplLabel } from "../../lib/plain";
import type { BrandLogo } from "../../types";
import { cls } from "../kit/cls";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { BRAND_STEPS, brandName, brandRows, brandTiles, type BrandTile } from "./dataRules";

const H2: CSSProperties = {
  margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: "28px", letterSpacing: "-0.02em",
  color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
};

const LOGO: Record<BrandLogo["variant"], string> = { primary: "", white: "bb-lg-white", mark: "bb-lg-mark", mono: "bb-lg-mono" };

/** Логотип-плитка: картинка из брендбука (GET /api/brandbooks/{id}/files/…) на светлом или синем поле; картинки нет —
 *  знак и полоса слова (как на холсте). */
export function LogoTile({ logo, brandId, className }: { logo: BrandLogo; brandId: string | null; className?: string }) {
  const src = brandId && logo.file ? api.brandbookFileUrl(brandId, logo.file) : null;
  return (
    <span className={cls("bb-lg", LOGO[logo.variant], src && "bb-lg-has", className)} role="img" aria-label={`Логотип: ${logo.name}`}>
      {src ? <img className="bb-lgi" src={src} alt="" onError={(e) => { e.currentTarget.style.display = "none"; e.currentTarget.parentElement?.classList.remove("bb-lg-has"); }} /> : null}
      <span className="bb-lgm" /><span className="bb-lgw" />
    </span>
  );
}

function Tile({ t, delay, cut }: { t: BrandTile; delay: number; cut: boolean }) {
  const { data } = useApp();
  const b = data.brand;
  const spec = b.run.brand ?? {};
  const out = b.phase === "out";
  const font = spec.fonts?.find((f) => f.role === "heading") ?? spec.fonts?.[0];
  return (
    <div className={cls("p2-stag p2-in", out && "tp-out", cut && "tp-cut")} style={{ animationDelay: `${delay}ms`, transitionDelay: `${delay}ms` }}>
      <div className={cut ? "hp-wo" : undefined}>
        <span className={cls("bb-at", t.on && "bb-at-on")} role="img" aria-label={t.on ? `${t.name}: ${t.meta}` : `${t.name} — разбираю`}>
          <span className="an-pulse" aria-hidden="true" />
          {t.key === "fonts" && (
            <span className="bb-atin">
              <span className="bb-aa" style={font ? { fontWeight: font.weight >= 600 ? 700 : 400 } : undefined}>Аа</span>
              <span className="bb-aan">{font?.family ?? ""}</span>
            </span>
          )}
          {t.key === "palette" && (
            <span className="bb-atin bb-atpal">{(spec.colors ?? []).slice(0, 6).map((c, i) => <span key={`${c.hex}-${i}`} style={{ background: c.hex }} />)}</span>
          )}
          {/* картинки логотипов сервер отдаёт, когда разбор кончился (до того — 409): пока идёт — знаки */}
          {t.key === "logos" && (
            <span className="bb-atin bb-atlg">{(spec.logos ?? []).slice(0, 4).map((l, i) => <LogoTile key={`${l.file}-${i}`} logo={l} brandId={b.phase === "run" ? null : b.id} />)}</span>
          )}
        </span>
        <span className="an-cap">
          <span className="an-name">{t.name}</span>
          <span className="an-meta">{t.meta}</span>
        </span>
      </div>
    </div>
  );
}

export function BrandAnalysis({ onOther }: { onOther(): void }) {
  const { data, templates, templateId } = useApp();
  const b = data.brand;
  const tpl = templates.find((t) => t.template_id === templateId);
  const rows = brandRows(b.run, b.source, tpl ? tplLabel(tpl) : null);
  const done = Math.min(BRAND_STEPS.length, b.run.done);
  const out = b.phase === "out";
  const failed = b.phase === "fail";
  const name = brandName(b.run.brand?.name ? { name: b.run.brand.name } : null, b.file);
  const tiles = brandTiles(b.run);
  // плитки по местам сетки (V2 `bbTiles`): шрифты и логотипы — во второй дорожке (уходят в узкой колоде), палитра — в первой
  return (
    <>
      <div className={cls("p2-stag p2-in", out && "tp-out")} style={{ animationDelay: "0ms", transitionDelay: "0ms" }} aria-busy={!failed && done < BRAND_STEPS.length}>
        <div className="an-sk">
          {!failed && <span className="an-pulse" aria-hidden="true" />}
          {failed && <span aria-hidden="true" style={{ position: "absolute", inset: 0, background: "#F3F4F1" }} />}
          <span className="an-skin">
            <span style={{ fontSize: 14, fontWeight: 700, lineHeight: "20px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{b.file}</span>
            <span className="an-track" role="progressbar" aria-label="Разбор брендбука" aria-valuemin={0} aria-valuemax={BRAND_STEPS.length} aria-valuenow={done}>
              <span className="an-fill tp-fill" style={{ transform: `scaleX(${(done / BRAND_STEPS.length).toFixed(4)})`, background: failed ? "#DC2626" : undefined }} />
            </span>
            <span style={{ marginTop: 8, fontSize: 13, fontWeight: 600, lineHeight: "20px", color: failed ? "#DC2626" : "#5A6272" }}>
              {failed ? "не получилось" : done >= BRAND_STEPS.length ? "готово" : "разбираю…"}
            </span>
          </span>
        </div>
        <span className="an-cap" aria-hidden="true" style={{ alignItems: "center" }}>
          <span className="an-line" style={{ width: 112 }} />
          <span className="an-line" style={{ width: 56 }} />
        </span>
      </div>

      <Tile t={tiles[0]} delay={40} cut />
      <Tile t={tiles[1]} delay={80} cut={false} />
      <Tile t={tiles[2]} delay={120} cut />

      <section className={cls("an-box p2-stag p2-in", out && "tp-out")} aria-labelledby="bb-job" aria-live="polite"
        style={{ gridColumn: "3 / span 2", gridRow: "1 / span 2", animationDelay: "160ms", transitionDelay: "160ms" }}>
        {failed ? (
          <>
            <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                <h2 id="bb-job" style={{ ...H2, flex: 1, minWidth: 0 }}>Не получилось разобрать брендбук</h2>
                <button type="button" className="p2-rbl pv-rbw" onClick={data.dismissBrand} aria-label="Закрыть разбор" title="Вернуться к шаблонам" style={{ flex: "none", margin: "-6px 0" }}>
                  <Icon name="x" size={18} />
                </button>
              </div>
              <ErrorLine text={b.error ?? "Не удалось разобрать брендбук"} lines={6} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {b.canRetry && (
                <button type="button" className="p2-ob" onClick={data.retryBrand} style={{ height: 40, padding: "0 16px" }}>
                  <Icon name="refresh" size={16} />
                  <span>Попробовать ещё раз</span>
                </button>
              )}
              <button type="button" className={b.canRetry ? "p2-gb" : "p2-ob"} onClick={onOther} style={b.canRetry ? undefined : { height: 40, padding: "0 16px" }}>
                {b.canRetry ? "Другой файл" : "Выбрать брендбук"}
              </button>
            </div>
          </>
        ) : (
          <>
            <h2 id="bb-job" style={H2}>Разбираю брендбук «{name}»</h2>
            <ol className="an-steps">
              {rows.map((r, i) => (
                <li key={i} className={cls("an-step", `an-${r.state}`, i === BRAND_STEPS.length - 1 && "an-last")} aria-current={r.state === "cur" ? "step" : undefined}>
                  <span className="an-dot" aria-hidden="true"><Icon name="check" size={12} /></span>
                  <span className="an-txt">{r.a}{r.b && <b>{r.b}</b>}{r.state === "done" && <span className="p2-sr"> — готово</span>}</span>
                  <span className="an-now">{r.state === "cur" ? "сейчас" : ""}</span>
                </li>
              ))}
            </ol>
          </>
        )}
      </section>
    </>
  );
}
