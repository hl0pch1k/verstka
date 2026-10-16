// Плита 03 на экране «Сборка» (слот `b3` колоды; boards/B-start, B-sketch, B-failed, живой ход — V2 модуль bd): слева
// фаза, часы и полоса хода, раскадровка или коробка «Не получилось»; справа — «Как думает агент». Данные — buildView
// из сборки, которую держит store (`buildJob`: идущая или законченная — неудача остаётся, пока с экрана не ушли).
// Содержимое входит лесенкой p2-in (40/80/120 мс, карточки по 40 мс, роли с 160 мс), уходит прозрачностью 240 мс
// (bd-out): со «Сборки» на «Создать» или под поднимающуюся плиту результата. «Собрать ещё раз»: содержимое гаснет,
// уходит тот же запрос, и плита собирается заново лесенкой, когда сервер ответил (новая сборка или новая строка
// неудачи). Сборка кончилась, а её презентация не открылась (сбой связи): строка области «Сборка» рядом с полосой хода и
// «Открыть ещё раз». «Вернуться к тексту» у чужой сборки (другая вкладка, помощник) — её собственный текст и параметры.
// Помощник сужает колоду, и плита перестраивается вместе с ней каждый кадр, на той же кривой (V2 версии 100; build.css,
// блок «Колода, суженная помощником»): колонка агента 416 → 320 и зазор 48 → 24 — дорожки сетки, фаза остаётся в своей
// клетке и мельчает transform'ом, раскадровка — те же колонки, сужаются, многострочный текст ленты агента — стопки из
// двух копий. Что зависит от ширины окна (колонка агента в тесной колоде, кегль фазы, колонки раскадровки, слова хода в
// сегментах, коробка «Не получилось»), считается по ширине обёртки колоды сразу для обеих раскладок (columns.ts
// `buildMorph`) и посреди хода не меняется. Ничего, что есть в обеих раскладках, не гаснет.
import { createContext, useContext, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { ActiveJob } from "../../lib/jobState";
import { useApp } from "../../store";
import { variantCards } from "../create/params";
import { cls } from "../kit/cls";
import { usePresence } from "../kit/usePresence";
import { useDeckWrap } from "../deck/useDeckFit";
import { useNarrow, useWideScreen } from "../create/useNarrow";
import { humanError } from "../../lib/errors";
import { ErrorLine } from "../kit/ErrorLine";
import { useSwap } from "../kit/useSwap";
import { useHeld } from "../create/ImproveNote";
import { GoLink } from "../create/ParamsPlate";
import { buildView } from "./buildView";
import { buildMorph, buildVars } from "./columns";
import { backToText } from "./resume";
import { Failed } from "./Failed";
import { Phases } from "./Phases";
import { Roles } from "./Roles";
import { Storyboard, type VariantSeg } from "./Storyboard";
import { usePreviews } from "./usePreviews";

const LEAVE_MS = 240;
/** Превью пишет экспорт: с этой доли хода их есть смысл спрашивать (generate.py: «export: …» — 0.86). */
const EXPORT_AT = 0.86;

/** Только для реплея записанной сборки (dev/StageReplay): его сборка вместо сборки store и его «Собрать ещё раз». */
export const BuildReplay = createContext<{ job: ActiveJob | null; retry(): Promise<boolean> } | null>(null);

export function BuildPlate() {
  const { ui, buildJob } = useApp();
  const replay = useContext(BuildReplay);
  const on = ui.screen === "build";
  const p = usePresence(on, LEAVE_MS);
  if (!p.mounted) return null;
  return <BuildContent job={replay ? replay.job : buildJob} leaving={!on} />;
}

function BuildContent({ job, leaving }: { job: ActiveJob | null; leaving: boolean }) {
  const {
    strategies, strategyTitle, templates, manifest, notices, retryBuild: storeRetry, dispatch, buildAsk, ownBuild, editText, loadGeneration, clearNotice,
    selectTemplate, ui, generations,
  } = useApp();
  const replay = useContext(BuildReplay);
  const retryBuild = replay?.retry ?? storeRetry;
  const live = !!job && (job.status === "queued" || job.status === "running");
  // часы идущей сборки — раз в секунду; законченная стоит на своём конце (endedAt)
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [live]);
  // сборку ещё не нашли (страница открыта заново, store спрашивает сервер) — подготовка
  const j: ActiveJob = job ?? { id: "", label: "", progress: 0, message: "", status: "queued", kind: "generate", startedAt: now };

  const [picked, setPicked] = useState<string | null>(null);
  const names = j.items?.length ? j.items : Object.keys(j.variants ?? {});
  const shown = picked && names.includes(picked) ? picked : names[0] ?? null;
  const own = shown ? j.variants?.[shown] : undefined;
  const exporting = j.progress >= EXPORT_AT || /^сохраняю файлы/i.test(j.message) || j.status === "done";
  // превью — этой генерации (у повтора свои); опрос идёт, пока идёт сборка; у упавшей раскадровку закрывает коробка
  const previews = usePreviews(j.generation, shown, own?.of ?? 0, exporting && j.status !== "failed", live);
  // строка неудачи области «Сборка» этой сборки (переживает задачу); прежняя сборка своей строки сюда не приносит
  const note = notices.build;
  const error = note && note.kind === "error" && note.at >= j.startedAt ? note.text : null;
  // сборка с файлами данных (её запрос, если он этой сборки, или мета её презентации; иначе — строки аналитика данных):
  // «Изучаю данные» и «Аналитик данных» с самого начала
  const asked = !!j.generation && (buildAsk?.gid === j.generation ? !!buildAsk.request.dataset_ids?.length
    : !!generations.find((g) => g.id === j.generation)?.dataset_ids?.length);
  const view = useMemo(() => buildView(j, previews, { variant: shown, now, error, titleOf: strategyTitle, data: asked }), [j, previews, shown, now, error, strategyTitle, asked]);

  const namesKey = names.join("|");
  const segs: VariantSeg[] = useMemo(() => {
    const list = namesKey ? namesKey.split("|") : [];
    const cards = variantCards(strategies, list);
    return list.map((name) => {
      const c = cards.find((x) => x.name === name);
      return { name, label: c?.title ?? strategyTitle(name), desc: c?.desc ?? "" };
    });
  }, [strategies, strategyTitle, namesKey]);
  const tpl = templates.find((t) => t.template_id === j.template);
  const aspect = tpl?.aspect && tpl.aspect > 0 ? tpl.aspect
    : manifest && manifest.template_id === j.template && manifest.slide_size.h > 0 ? manifest.slide_size.w / manifest.slide_size.h : 16 / 9;

  // «Собрать ещё раз»: гаснет (240 мс), уходит тот же запрос; ответ сервера — новая сборка или новая строка неудачи —
  // собирает плиту заново
  const [retry, setRetry] = useState<{ from: string; at: number } | null>(null);
  // плита собирается заново лесенкой, когда одну сборку сменила другая (повтор); подготовка, которую сменила найденная
  // после перезагрузки сборка, остаётся на месте — второго входа нет
  const [epoch, setEpoch] = useState(0);
  const [shownId, setShownId] = useState(job?.id ?? "");
  if (job && job.id !== shownId) {
    setShownId(job.id);
    if (shownId) setEpoch((e) => e + 1);
  }
  // запрос уходит, когда плита погасла; ушли с экрана раньше — не уходит
  const retryTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(retryTimer.current), []);
  const onRetry = () => {
    if (retry) return;
    setRetry({ from: j.id, at: Date.now() });
    retryTimer.current = window.setTimeout(() => {
      void retryBuild().then((ok) => {
        if (!ok) dispatch({ type: "go", screen: "create" }); // повторять нечего — к тексту
      });
    }, LEAVE_MS);
  };
  useEffect(() => {
    if (!retry) return;
    const started = !!job && job.id !== retry.from;
    const refused = !!note && note.kind === "error" && note.at >= retry.at;
    if (started || refused) setRetry(null);
    if (refused) setEpoch((e) => e + 1); // та же неудача с новой строкой — плита встаёт заново
  }, [retry, job, note]);

  const failed = view.failed;
  const queued = view.phase === "queued";
  // сборка кончилась, а её презентация не открылась (строка области «Сборка» после конца): причина и «Открыть ещё раз»
  const ended = j.endedAt ?? null;
  const openErr = j.status === "done" && !replay && note && note.kind === "error" && ended !== null && note.at >= ended
    ? humanError(note.text, "Не удалось открыть презентацию") : null;
  // «Открыть ещё раз»: строка стоит с дугой у кнопки, пока презентация грузится; не открылась — новая причина сменяет
  // прежнюю затуханием; открылась — строка уходит вместе с плитой (держит своё, пока плита гаснет)
  const [opening, setOpening] = useState(false);
  const screen = useRef(ui.screen);
  screen.current = ui.screen;
  const openAgain = () => {
    const gid = j.generation;
    if (!gid || opening) return;
    setOpening(true);
    void loadGeneration(gid, { area: "build" }).then((g) => {
      setOpening(false);
      if (!g) return;
      if (screen.current === "build") {
        dispatch({ type: "go", screen: "result" });
        if (g.template_id && templates.some((t) => t.template_id === g.template_id)) selectTemplate(g.template_id);
      }
      clearNotice("build");
    });
  };
  const heldErr = useHeld(openErr);
  const lineErr = openErr ?? (leaving ? heldErr : null);
  const errSwap = useSwap(lineErr ?? "");
  // «Вернуться к тексту»: своя сборка — к черновику поля; чужая (другая вкладка, помощник) — к её тексту и параметрам
  const back = () => {
    const own = replay ? null : backToText(buildAsk, ownBuild, j.generation);
    if (own) editText(own.brief, own.preset);
    else dispatch({ type: "go", screen: "create" });
  };
  const nowRole = view.roles.find((r) => r.status === "now");
  const vt = failed ? `остановилась на шаге ${view.step.replace(/^ошибка на шаге /, "")}` : queued ? "в очереди" : view.phase === "done" ? "готово"
    : `${view.step}${nowRole ? ` — ${nowRole.title.toLowerCase()}` : ""}`;
  const prog = view.progress ?? 0;
  // обе раскладки плиты — по ширине обёртки колоды (columns.ts): колонка агента в узкой, ширины текста ролей ленты
  // агента в обеих (копии стопок — постоянной ширины), кегль фазы; активная копия стопок — по раскладке
  const wrap = useDeckWrap();
  const morph = useMemo(() => buildMorph(wrap), [wrap]);
  const narrow = useNarrow();
  const wide = useWideScreen();
  const vars = buildVars(morph) as CSSProperties;

  return (
    <div key={epoch} className={cls("p2-two bd-two", morph.tight && "bd-tight", (leaving || retry) && "bd-out")}
      style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 416px", gridTemplateRows: "64px minmax(0, 1fr)", columnGap: 48, height: 652, ...vars }}>
      <Phases phase={view.phase} morph={morph} data={view.data} />
      <div className="bd-body" style={{ display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0 }}>
        <div className="p2-in" style={{ display: "flex", alignItems: "center", gap: 24, height: 24, marginTop: 16, animationDelay: "80ms" }}>
          <p style={{ margin: 0, fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "rgba(255,255,255,.64)", whiteSpace: "nowrap" }}>
            <b style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums", color: "#FFFFFF" }}>{view.clock}</b>
          </p>
          <div role="progressbar" aria-label="Ход сборки" aria-valuemin={0} aria-valuemax={view.roles.length} aria-valuenow={view.doneRoles} aria-valuetext={vt}
            style={{ position: "relative", flex: 1, height: 4, borderRadius: 999, background: "rgba(255,255,255,.12)", overflow: "hidden" }}>
            <span className={cls("bs-seg bs-seg-run bd-fx", !queued && "bd-hide")} aria-hidden="true" />
            <span className={cls("p2-bar bd-bar", (queued || failed) && "bd-hide")}
              style={{ position: "absolute", inset: 0, borderRadius: 999, background: "#38BDF8", transformOrigin: "left center", transform: `scaleX(${prog})` }} />
            <span className={cls("p2-bar bd-bar", !failed && "bd-hide")} aria-hidden="true"
              style={{ position: "absolute", inset: 0, borderRadius: 999, background: "rgba(255,255,255,.24)", transformOrigin: "left center", transform: `scaleX(${prog})` }} />
          </div>
          {lineErr && (
            <div className="p2-in pp-busy" style={{ flex: "0 1 auto", animationDelay: "0ms" }}>
              <span className={errSwap.cls} style={{ display: "flex", minWidth: 0 }}>
                <ErrorLine text={errSwap.shown || lineErr} lines={1} style={{ color: "#F87171" }} />
              </span>
              <GoLink label="Открыть ещё раз" busy={opening} onClick={openAgain} />
            </div>
          )}
        </div>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
          <div className={failed ? "p2-off" : "p2-on"} style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
            <Storyboard view={view} segs={segs} onPick={setPicked} aspect={aspect} morph={morph} wide={wide} />
          </div>
          {failed && (
            <Failed text={failed.text} onRetry={onRetry} onBack={back} morph={morph} wide={wide} narrow={narrow} />
          )}
        </div>
      </div>
      <Roles view={view} narrow={narrow} widths={`${morph.textWide}/${morph.textNarrow}`} />
    </div>
  );
}
