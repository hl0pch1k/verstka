// Раздел «Мои презентации» (G-history; V2 `#p2-lay-h`, `openDoc`): голубой слой поднимается до 120 px — над ним видна
// полоса колоды, она закрывает раздел (Scrim в AppShell). Презентации по дням («Сегодня», «Вчера», дата, «Раньше»),
// четыре колонки: обложка — первый слайд лучшего варианта, название, оценка или бейдж «собирается» / «не удалось»,
// время, шаблон и слайды. Открытая сейчас — только обводка обложки, значка выделения нет. Клик (history.ts `openPlan`):
// готовая открывается в «Результате» — когда она загрузилась и первый слайд декодирован, слой уезжает вниз, колода
// складывается, а из «Создать» плита результата поднимается снизу одним движением с плитами 02/03 (`rise`,
// `p2-s4-up`, 520 мс); идущая — экран «Сборка» с её задачей; неудачная — «Создать» с той же темой и шаблоном. Пока
// презентация грузится, на её обложке — дуга загрузки; неудача — красной строкой в шапке слоя.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import { humanError } from "../../lib/errors";
import { decodeImage } from "../../lib/motion";
import { errText } from "../../lib/narrate";
import { useApp } from "../../store";
import type { Generation, GenerationMeta } from "../../types";
import { buildRunning } from "../create/params";
import { cls } from "../kit/cls";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { Spinner } from "../kit/Spinner";
import { usePresence } from "../kit/usePresence";
import { deckPreset, slideSrc } from "../result/resultView";
import { useGoDown } from "../result/useGoDown";
import { historyView, openPlan, type HistItem, type OpenPlan } from "./history";
import { Layer, LAYER_MS, lsDelay } from "./Layer";

/** Плита результата поднимается 520 мс; `rise` снимается, когда плиты встали (V2 `openDoc`: 560 мс). */
const RISE_MS = 560;
/** Сколько открытие ждёт декодирования первого слайда, прежде чем ехать как есть. */
const DECODE_WAIT = 800;
const OPEN_FAILED = "Не удалось открыть презентацию";

export function HistoryLayer() {
  const {
    ui, dispatch, generations, refreshGenerations, generation, generationId, loadGeneration, templateLabel, templates, selectTemplate,
    editText, buildJob, followDeck, notices, clearNotice,
  } = useApp();
  const goDown = useGoDown();
  const open = ui.sect === "hist";
  const close = () => dispatch({ type: "sect", sect: null });

  // карточка, которая открывается (дуга на обложке), и строка неудачи в шапке слоя
  const [wait, setWait] = useState<{ id: string; on: boolean } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const seq = useRef(0);
  const askAt = useRef<number | null>(null);
  const screen = useRef(ui.screen);
  screen.current = ui.screen;
  const riseTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(riseTimer.current), []);

  // слой открылся: список свежий (статусы сборок могли смениться), прежняя дуга и строка ушли вместе со слоем
  useEffect(() => {
    if (!open) return;
    seq.current++;
    setWait(null);
    setErr(null);
    askAt.current = null;
    void refreshGenerations();
  }, [open, refreshGenerations]);

  // неудачу загрузки store пишет строкой области «Результат»: её показывает слой (рядом с местом действия), а под
  // слоем она не остаётся — открытая презентация осталась прежней
  const failed = notices.result;
  useEffect(() => {
    if (!failed || failed.kind !== "error" || askAt.current === null || failed.at < askAt.current) return;
    askAt.current = null;
    setErr(humanError(failed.text, OPEN_FAILED));
    clearNotice("result");
  }, [failed, clearNotice]);

  // список считается, только пока слой на экране (и доигрывает уход), — колода перерисовывается часто, раздел закрыт
  const shown = usePresence(open, LAYER_MS).mounted;
  const current = ui.screen === "result" ? generationId : ui.screen === "build" ? buildJob?.generation ?? null : null;
  const view = useMemo(
    () => (shown ? historyView(generations, { now: new Date(), label: (g) => templateLabel(g.template_id, g.template_file), current }) : null),
    [shown, generations, templateLabel, current],
  );
  const byId = useMemo(() => new Map(generations.map((g) => [g.id, g])), [generations]);

  /** Ход начат: дуга на обложке, строка прежней неудачи уходит. Возвращает номер хода — он устарел, если начат новый. */
  const begin = (id: string) => {
    const n = ++seq.current;
    setWait({ id, on: true });
    setErr(null);
    return n;
  };
  const fail = (n: number, text: string) => {
    if (n !== seq.current) return;
    setWait((w) => (w ? { ...w, on: false } : w));
    setErr(text);
  };
  /** Ход ещё в силе: не начат новый и экран тот же, что при клике (иначе человек уже ушёл сам). */
  const live = (n: number, at: string) => n === seq.current && screen.current === at;

  const toResult = async (g: GenerationMeta, plan: Extract<OpenPlan, { kind: "result" }>, at: string) => {
    if (plan.load) {
      const n = begin(g.id);
      askAt.current = Date.now();
      const d = await loadGeneration(g.id, { hold: true });
      if (n !== seq.current) return;
      if (!d) {
        setWait((w) => (w ? { ...w, on: false } : w));
        void refreshGenerations(); // удалённая — уходит из списка
        return;
      }
      askAt.current = null;
      // список отстал: сборка ещё идёт — store уже перевёл на её экран
      if (d.status === "running" || d.status === "queued") return;
      // первый слайд декодирован до движения: плита едет уже со слайдом
      const first = slideSrc(d.variants[0], 1);
      if (first) await Promise.race([decodeImage(first).catch(() => {}), new Promise((r) => window.setTimeout(r, DECODE_WAIT))]);
      if (!live(n, at)) return;
    }
    dispatch({ type: "go", screen: "result" });
    if (plan.rise) {
      // `go` сбрасывает `rise`, поэтому он ставится после; снимается, когда плиты встали
      dispatch({ type: "set", patch: { rise: true } });
      window.clearTimeout(riseTimer.current);
      riseTimer.current = window.setTimeout(() => dispatch({ type: "set", patch: { rise: false } }), RISE_MS);
    }
  };

  const toCreate = (d: GenerationMeta, plan: Extract<OpenPlan, { kind: "create" }>) => {
    if (templates.some((t) => t.template_id === d.template_id)) selectTemplate(d.template_id);
    if (d.brief) editText(d.brief, deckPreset(d));
    else dispatch({ type: "go", screen: "create" });
    // с результата плита уходит вниз непрозрачной со своей презентацией, как с логотипа (`go` сбрасывает `down`)
    if (plan.down) goDown();
  };

  /** Полная мета (у списка текст обрезан): тема для «Создать» и запрос для «Собрать ещё раз». */
  const fetchFull = async (g: GenerationMeta, n: number): Promise<Generation | null> => {
    try {
      return await api.generation(g.id);
    } catch (e) {
      fail(n, humanError(`${OPEN_FAILED}: ${errText(e)}`, OPEN_FAILED));
      if (e instanceof ApiError && e.status === 404) void refreshGenerations();
      return null;
    }
  };

  const pick = async (g: GenerationMeta) => {
    if (wait?.on) return; // одна презентация за раз
    const at = ui.screen;
    const plan = openPlan(g, { screen: at, openId: generation?.id ?? null, buildId: buildJob?.generation ?? null });
    if (plan.kind === "stay") return close();
    if (plan.kind === "result") return toResult(g, plan, at);
    // идущая, которую страница уже ведёт, — сразу к её сборке
    if (plan.kind === "build" && buildRunning(buildJob) && buildJob?.generation === g.id && followDeck(g)) return;
    const n = begin(g.id);
    const d = await fetchFull(g, n);
    if (!d || !live(n, at)) return;
    // статус — по свежей мете: сборка могла кончиться, пока список стоял
    const now = openPlan(d, { screen: at, openId: generation?.id ?? null, buildId: buildJob?.generation ?? null });
    if (now.kind === "stay") return close();
    if (now.kind === "result") return toResult(d, now, at);
    if (now.kind === "create") return toCreate(d, now);
    if (!followDeck(d)) fail(n, `${OPEN_FAILED}: сборка не найдена`);
  };

  return (
    <Layer id="p2-lay-h" open={open} top={120} z={open ? 7 : 6} height={692} label="Мои презентации" onClose={close}
      plateStyle={{ display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 24, height: 64, flex: "none" }}>
        <h2 className="p2-ttl" style={{ margin: 0, color: "#0B1220" }}>Мои презентации</h2>
        <span style={{ flex: 1, minWidth: 0, display: "flex", justifyContent: "flex-end" }}>
          {err && <span className="p2-in" style={{ display: "flex", minWidth: 0 }}><ErrorLine text={err} lines={1} /></span>}
        </span>
        <span style={{ fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272", whiteSpace: "nowrap" }}>{view?.total}</span>
        <button type="button" className="p2-rbl" onClick={close} aria-label="Закрыть"><Icon name="x" size={18} /></button>
      </div>

      <div className="gh-list">
        {view?.groups.length === 0 && (
          <p className="p2-ls" style={{ ...lsDelay(200), margin: "8px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272" }}>
            Здесь появятся презентации, которые вы соберёте.
          </p>
        )}
        {view?.groups.map((gr) => (
          <section key={gr.key} className="gh-group" aria-label={gr.day}>
            <h3 className="gh-day">{gr.day}<span className="gh-dayn">{gr.count}</span></h3>
            <ul className="gh-grid">
              {gr.items.map((d) => {
                const g = byId.get(d.id);
                return (
                  <li key={d.id} className="p2-ls" style={lsDelay(d.delay)}>
                    <DeckCard d={d} wait={wait?.id === d.id ? wait.on : null} onPick={() => g && void pick(g)} />
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </Layer>
  );
}

/** Карточка презентации (G-history `gh-card`): обложка 16:9 с радиусом 16, название до двух строк, оценка или бейдж,
 *  мета. `wait`: карточка открывается (true — дуга проявляется, false — гаснет), null — нет. */
function DeckCard({ d, wait, onPick }: { d: HistItem; wait: boolean | null; onPick(): void }) {
  return (
    <button type="button" className="p2-card gh-card" onClick={onPick} aria-current={d.current || undefined} aria-label={d.aria}
      aria-busy={wait || undefined}>
      <span className={cls("p2-cover gh-cover", d.current && "p2-sel")}>
        {d.state === "done" && <CoverImg key={d.cover ?? ""} src={d.cover} alt={`Обложка презентации «${d.title}»`} />}
        {d.state === "run" && <span className="gh-ph"><span className="gh-ic gh-ic-run"><Spinner size={20} /></span></span>}
        {d.state === "fail" && <span className="gh-ph"><span className="gh-ic gh-ic-fail"><Icon name="alert" size={20} /></span></span>}
        {wait !== null && <span className={cls("gh-wait", wait && "gh-wait-on")} aria-hidden="true"><Spinner size={20} /></span>}
      </span>
      <span className="gh-row">
        <span className="gh-title">{d.title}</span>
        {d.score !== null && <span className="gh-score" title="Лучшая оценка качества среди вариантов">{d.score}</span>}
        {d.state === "run" && <span className="gh-badge gh-badge-run"><span className="gh-bdot" aria-hidden="true" /><span>собирается</span></span>}
        {d.state === "fail" && <span className="gh-badge gh-badge-fail"><Icon name="alert" size={12} /><span>не удалось</span></span>}
      </span>
      <span className="gh-meta">{d.meta}</span>
    </button>
  );
}

/** Обложка: белая рамка, пока слайд грузится, затем он проявляется 240 мс (уже в кэше — стоит сразу); нет слайда —
 *  тихая заглушка. */
function CoverImg({ src, alt }: { src: string | null; alt: string }) {
  const [st, setSt] = useState<"wait" | "ok" | "bad">("wait");
  const img = useRef<HTMLImageElement>(null);
  useLayoutEffect(() => {
    const el = img.current;
    if (el?.complete && el.naturalWidth > 0) setSt("ok");
  }, []);
  if (!src || st === "bad") return <span className="gh-ph"><span className="gh-ic gh-ic-none"><Icon name="image-off" size={20} /></span></span>;
  return (
    <>
      <span className="gh-ph" />
      <img ref={img} className={cls("gh-img", st === "wait" && "gh-img-wait")} src={src} alt={alt} loading="lazy" decoding="async"
        onLoad={() => setSt("ok")} onError={() => setSt("bad")} />
    </>
  );
}
