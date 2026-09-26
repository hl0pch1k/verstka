// The helper's conversation: a one-line header, the feed, at most two contextual chips and the composer.
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
import { ArrowUp, FileText, Paperclip, X } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { cn, sessionId } from "../lib/utils";
import { useApp } from "../store";
import { clearEdited, useChatActions, useJustEdited } from "./ChatActions";
import { AssistantBubble, JobBubble, MessageBubble, TypingIndicator } from "./ChatParts";
import { Button } from "./ui/Button";
import { Chip } from "./ui/Chip";

const MAX_ROWS = 8;
const LINE_PX = 20; // leading-5
const PAD_PX = 16; // pt-3 + pb-1
const MAX_BRIEF_BYTES = 2 * 1024 * 1024;
const COUNT_FROM = 1000; // the length only matters for long texts

function fmtBytes(n: number): string {
  return n < 1024 ? `${n} Б` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} КБ` : `${(n / 1024 / 1024).toFixed(1)} МБ`;
}

export function Chat({ onClose }: { onClose?: () => void }) {
  const { messages, pushMessage, toast, templateId, generationId, activeJob, healthError, activeStrategy, selectedSlide, generation, screen } = useApp();
  const handleActions = useChatActions();
  const justEdited = useJustEdited();
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [attached, setAttached] = useState<{ name: string; size: number } | null>(null);
  const [scrolled, setScrolled] = useState(false); // the feed's top fades while something is scrolled away above
  const feedRef = useRef<HTMLDivElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const alive = useRef(true); // set in the effect too, so StrictMode's mount → unmount → mount leaves it true
  useEffect(() => {
    alive.current = true;
    return () => void (alive.current = false);
  }, []);

  // the build screen shows a running build itself: the feed does not repeat it
  const job = activeJob && !(activeJob.kind === "generate" && screen === "result") ? activeJob : null;
  const building = !!activeJob && activeJob.kind === "generate" && (activeJob.status === "queued" || activeJob.status === "running");

  // Keep the newest message in view; progress ticks of a job do not trigger this (only its identity/status). A reply
  // taller than the feed is shown from its first line, not from its end.
  const jobKey = job ? `${job.id}:${job.status}` : "";
  const last = messages[messages.length - 1];
  useEffect(() => {
    const feed = feedRef.current;
    if (!feed) return;
    const behavior = messages.length > 1 ? "smooth" : "auto";
    const lastEl = last && !pending && !job && last.role === "assistant" ? feed.querySelector<HTMLElement>(`[data-msg="${last.id}"]`) : null;
    if (lastEl && lastEl.offsetHeight > feed.clientHeight - 32) feed.scrollTo({ top: lastEl.offsetTop - 16, behavior });
    else feed.scrollTo({ top: feed.scrollHeight, behavior });
  }, [messages.length, pending, jobKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const resize = useCallback(() => {
    const el = areaRef.current;
    if (!el) return;
    // empty: one line (Chrome measures the placeholder too); a hidden sidebar measures 0 — one line until shown again
    if (!el.value) return void (el.style.height = `${LINE_PX + PAD_PX}px`);
    el.style.height = "auto";
    el.style.height = `${Math.max(LINE_PX + PAD_PX, Math.min(el.scrollHeight, MAX_ROWS * LINE_PX + PAD_PX))}px`;
  }, []);
  useEffect(resize, [text, resize]);

  const send = useCallback(
    async (raw: string) => {
      const message = raw.trim();
      if (!message || pending) return;
      setText("");
      setAttached(null);
      setPending(true);
      clearEdited();
      pushMessage("user", message);
      try {
        // the variant on screen: «почему слайд 3 такой» is about the slide the person looks at
        const res = await api.chat({ session_id: sessionId(), message, template_id: templateId, generation_id: generationId, strategy: activeStrategy, slide: generation ? selectedSlide : null });
        pushMessage("assistant", res.reply);
        handleActions(res);
      } catch (e) {
        const reason = errText(e);
        pushMessage("assistant", `Не получилось ответить: ${reason}. Повторите, когда сервер снова на связи.`);
      } finally {
        if (alive.current) setPending(false);
        areaRef.current?.focus();
      }
    },
    [pending, pushMessage, templateId, generationId, activeStrategy, handleActions, generation, selectedSlide],
  );

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(text);
    }
  };

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow picking the same file again
    if (!file) return;
    if (!/\.(md|txt|markdown)$/i.test(file.name)) return toast("error", "Нужен текстовый файл .txt или .md");
    if (file.size > MAX_BRIEF_BYTES) return toast("error", `Файл больше ${fmtBytes(MAX_BRIEF_BYTES)}`);
    try {
      const content = (await file.text()).replace(/\r\n/g, "\n").trim();
      if (!content) return toast("error", `Файл «${file.name}» пустой`);
      setText((cur) => (cur.trim() ? `${cur.trimEnd()}\n\n${content}` : content));
      setAttached({ name: file.name, size: file.size });
      requestAnimationFrame(() => areaRef.current?.focus());
    } catch (err) {
      toast("error", `Не удалось прочитать «${file.name}»: ${errText(err)}`);
    }
  };

  const clearDraft = () => {
    setText("");
    setAttached(null);
    areaRef.current?.focus();
  };

  // at most two chips, by where the person is; none while a build runs
  const variant = generation?.variants.find((v) => v.strategy === activeStrategy) ?? generation?.variants[0];
  const fixable = !!variant?.audit?.issues.some((i) => i.autofix && i.autofix.action !== "none");
  const empty = messages.length === 0 && !pending && !job;
  const chips: string[] = building || pending
    ? []
    : justEdited
      ? ["Верни как было"]
      : !empty
        ? []
        : generation?.variants.length
          ? [`Почему слайд ${selectedSlide} такой?`, ...(fixable ? ["Исправь всё"] : [])]
          : templateId
            ? ["Что в шаблоне?"]
            : [];

  const canSend = text.trim().length > 0 && !pending && !healthError;
  // offline: only the red dot here — the bar under the header already says it
  const status = healthError ? null : pending ? "печатает…" : activeJob && (activeJob.status === "queued" || activeJob.status === "running") ? "работает над задачей" : null;
  const intro = building
    ? "Собираю презентацию — спросите, что сейчас делает агент."
    : generation?.variants.length
      ? "Спросите про любой слайд или попросите его изменить."
      : "Спросите про шаблон или пришлите текст — соберу три варианта.";
  const placeholder = healthError
    ? "Сообщение помощнику"
    : building
      ? "Вопрос о сборке"
      : generation
        ? `Что поменять на слайде ${selectedSlide}?`
        : "Вопрос или текст презентации";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-zinc-200/70 pl-4 pr-2">
        <h2 className="text-title3 font-semibold text-zinc-900">Помощник</h2>
        {(status || healthError) && (
          <span className={cn("h-2 w-2 shrink-0 rounded-full", healthError ? "bg-red-500" : "animate-pulse bg-accent")} title={healthError ? "Нет связи с сервером" : undefined} aria-hidden />
        )}
        {status && <span className="min-w-0 truncate text-caption text-zinc-500" role="status">{status}</span>}
        {onClose && <Button variant="ghost" shape="circle" size="md" icon={X} aria-label="Закрыть помощника" onClick={onClose} className="ml-auto" />}
      </header>

      <div
        ref={feedRef}
        onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 0)}
        className={cn("scroll-thin relative min-h-0 flex-1 space-y-3 overflow-y-auto p-4", scrolled && "[mask-image:linear-gradient(to_bottom,transparent,#000_16px)]")}
      >
        {empty ? (
          <AssistantBubble>{intro}</AssistantBubble>
        ) : (
          <>
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
            {pending && <TypingIndicator />}
            {/* a failed job is told by its own message; the red bar would only repeat it */}
            {job && job.status !== "failed" && <JobBubble job={job} />}
          </>
        )}
      </div>

      <div className="shrink-0 border-t border-zinc-200/70 p-4">
        {chips.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {chips.map((label) => (
              <Chip key={label} disabled={healthError} onClick={() => void send(label)} className="animate-fade-in">
                {label}
              </Chip>
            ))}
          </div>
        )}

        <div className={cn("rounded-xl bg-zinc-100 transition-[background-color,box-shadow] duration-150 focus-within:bg-white focus-within:shadow-selected", healthError && "opacity-60")}>
          {attached && (
            <div className="flex h-10 items-center gap-2 border-b border-zinc-200/70 pl-4 pr-1 text-footnote text-zinc-700">
              <FileText className="h-4 w-4 shrink-0 text-accent" aria-hidden />
              <span className="min-w-0 flex-1 truncate" title={`${attached.name} · ${fmtBytes(attached.size)}`}>
                Текст из «{attached.name.replace(/\.(md|txt|markdown)$/i, "").replace(/_/g, " ")}»
              </span>
              <Button variant="ghost" size="sm" shape="circle" icon={X} aria-label="Убрать текст из файла" onClick={clearDraft} />
            </div>
          )}
          <textarea
            ref={areaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            disabled={healthError}
            placeholder={placeholder}
            aria-label="Сообщение помощнику"
            className="scroll-thin block w-full resize-none bg-transparent px-4 pb-1 pt-3 text-body text-zinc-900 placeholder:text-zinc-500 disabled:cursor-not-allowed"
          />
          <div className="flex items-center gap-2 px-2 pb-2">
            <input ref={fileRef} type="file" accept=".md,.txt,.markdown,text/markdown,text/plain" className="hidden" onChange={(e) => void onFile(e)} />
            <Button size="sm" variant="ghost" shape="circle" icon={Paperclip} disabled={pending || healthError} onClick={() => fileRef.current?.click()} aria-label="Вставить текст из файла" title="Вставить текст из файла" />
            {text.length > COUNT_FROM && <span className="ml-auto text-caption tabular-nums text-zinc-500">{text.length.toLocaleString("ru-RU")}</span>}
            <Button size="sm" variant="primary" shape="circle" icon={ArrowUp} loading={pending} disabled={!canSend} onClick={() => void send(text)} aria-label="Отправить" className={cn(text.length <= COUNT_FROM && "ml-auto")} />
          </div>
        </div>
      </div>
    </div>
  );
}
