// Left column: the conversation with the Verstka agent — feed, composer, brief attachment and quick actions.
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
import { FileText, Layers, Paperclip, SendHorizontal, Upload, X } from "lucide-react";
import { LogoMark } from "./shell/Logo";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { cn, sessionId } from "../lib/utils";
import { useApp } from "../store";
import { useChatActions } from "./ChatActions";
import { JobBubble, MessageBubble, TypingIndicator } from "./ChatParts";
import { Button } from "./ui/Button";

// labels in plain words; the messages are the phrases the server's intent router knows
const QUICK_ACTIONS: Array<{ label: string; message: string }> = [
  { label: "Что в шаблоне?", message: "Расскажи о шаблоне" },
  { label: "Покажи план", message: "Покажи план" },
  { label: "Проверь качество", message: "Проверь качество" },
  { label: "Исправь всё", message: "Исправь всё" },
  { label: "Где файлы?", message: "Где скачать файлы?" },
];
// with a deck on screen: questions about it first (the slide on screen, the agent's work)
const deckActions = (slide: number): Array<{ label: string; message: string }> => [
  { label: `Почему слайд ${slide} такой?`, message: `Почему слайд ${slide} такой?` },
  { label: "Как работал агент?", message: "Как работал агент?" },
  ...QUICK_ACTIONS.filter((a) => a.label !== "Что в шаблоне?" && a.label !== "Покажи план"),
];
const MAX_ROWS = 8;
const LINE_PX = 20; // leading-5
const PAD_PX = 20; // py-2.5, top + bottom
const MAX_BRIEF_BYTES = 2 * 1024 * 1024;

const STEPS = [
  { icon: Upload, title: "Соберу презентацию из текста", text: "Вставьте текст сюда или напишите «сделай 8 слайдов для руководства: …» — получите три варианта." },
  { icon: FileText, title: "Объясню любой слайд", text: "Спросите «почему слайд 4 такой» — расскажу, почему агент выбрал такую форму и что ещё рассматривал." },
  { icon: Layers, title: "Исправлю замечания", text: "Скажите «исправь всё» — применю автоматические исправления и пересоберу файлы." },
] as const;

function fmtBytes(n: number): string {
  return n < 1024 ? `${n} Б` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} КБ` : `${(n / 1024 / 1024).toFixed(1)} МБ`;
}

function Intro() {
  return (
    <div className="mt-5 animate-fade-in">
      <div className="rounded-2xl bg-zinc-100 p-4">
        <p className="text-[15px] font-semibold leading-6 text-zinc-900">Привет! Я помощник Verstka</p>
        <p className="mt-1 text-[13px] leading-5 text-zinc-600">Пишите обычными словами — я пойму. Вот что я умею:</p>
      </div>
      <ol className="mt-3 space-y-1">
        {STEPS.map((s, i) => (
          <li key={s.title} className="flex gap-3 rounded-xl px-2 py-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-50 text-[13px] font-bold text-accent">{i + 1}</span>
            <div className="min-w-0">
              <p className="text-[13px] font-semibold leading-5 text-zinc-900">{s.title}</p>
              <p className="text-xs leading-[18px] text-zinc-500">{s.text}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-2 px-2 text-xs leading-5 text-zinc-500">
        <kbd className="rounded-md bg-zinc-100 px-1.5 py-0.5 font-sans text-[11px] font-semibold text-zinc-700">Enter</kbd> — отправить,{" "}
        <kbd className="rounded-md bg-zinc-100 px-1.5 py-0.5 font-sans text-[11px] font-semibold text-zinc-700">Shift+Enter</kbd> — новая строка
      </p>
    </div>
  );
}

export function Chat({ onClose }: { onClose?: () => void }) {
  const { messages, pushMessage, toast, templateId, generationId, manifest, activeJob, healthError, activeStrategy, selectedSlide, generation } = useApp();
  const handleActions = useChatActions();
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [attached, setAttached] = useState<{ name: string; size: number } | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const alive = useRef(true); // set in the effect too, so StrictMode's mount → unmount → mount leaves it true
  useEffect(() => {
    alive.current = true;
    return () => void (alive.current = false);
  }, []);

  // Keep the newest message in view; progress ticks of a job do not trigger this (only its identity/status).
  const jobKey = activeJob ? `${activeJob.id}:${activeJob.status}` : "";
  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: messages.length > 1 ? "smooth" : "auto" });
  }, [messages.length, pending, jobKey]);

  const resize = useCallback(() => {
    const el = areaRef.current;
    if (!el) return;
    el.style.height = "auto";
    // a hidden dock measures 0 — keep one line until it is shown and measured again
    el.style.height = `${Math.max(LINE_PX + PAD_PX + 4, Math.min(el.scrollHeight, MAX_ROWS * LINE_PX + PAD_PX))}px`;
  }, []);
  useEffect(resize, [text, resize]);

  const send = useCallback(
    async (raw: string) => {
      const message = raw.trim();
      if (!message || pending) return;
      setText("");
      setAttached(null);
      setPending(true);
      pushMessage("user", message);
      try {
        // the variant on screen: «почему слайд 3 такой» is about the slide the person looks at
        const res = await api.chat({ session_id: sessionId(), message, template_id: templateId, generation_id: generationId, strategy: activeStrategy });
        pushMessage("assistant", res.reply);
        handleActions(res);
      } catch (e) {
        const reason = errText(e);
        toast("error", `Агент не ответил: ${reason}`);
        pushMessage("assistant", `Не удалось получить ответ: ${reason}. Проверьте, что сервер запущен, и повторите.`);
      } finally {
        if (alive.current) setPending(false);
        areaRef.current?.focus();
      }
    },
    [pending, pushMessage, templateId, generationId, activeStrategy, handleActions, toast],
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
    if (!/\.(md|txt|markdown)$/i.test(file.name)) return toast("error", "Бриф должен быть файлом .md или .txt");
    if (file.size > MAX_BRIEF_BYTES) return toast("error", `Файл слишком большой (${fmtBytes(file.size)}), лимит ${fmtBytes(MAX_BRIEF_BYTES)}`);
    try {
      const content = (await file.text()).replace(/\r\n/g, "\n").trim();
      if (!content) return toast("error", `Файл «${file.name}» пустой`);
      setText((cur) => (cur.trim() ? `${cur.trimEnd()}\n\n${content}` : content));
      setAttached({ name: file.name, size: file.size });
      toast("info", `Бриф «${file.name}» вставлен в поле ввода — проверьте и отправьте`);
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

  const canSend = text.trim().length > 0 && !pending && !healthError;
  const context = manifest ? `Шаблон: ${manifest.source_file}` : templateId ? "Шаблон загружается…" : "Шаблон не выбран";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-16 shrink-0 items-center gap-3 border-b border-zinc-100 px-5">
        <span className="relative shrink-0">
          <LogoMark size={36} />
          <span className={cn("absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full ring-2 ring-white", healthError ? "bg-red-500" : pending || activeJob ? "animate-pulse bg-accent-300" : "bg-emerald-500")} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[15px] font-semibold leading-5 text-zinc-900">Помощник Verstka</h2>
          <p className="truncate text-xs leading-4 text-zinc-500">
            {healthError ? "нет связи с сервером" : pending ? "печатает…" : activeJob ? "работает над задачей" : context}
          </p>
        </div>
        {onClose && (
          <button type="button" onClick={onClose} aria-label="Скрыть агента" className="flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30">
            <X className="h-[18px] w-[18px]" aria-hidden />
          </button>
        )}
      </header>

      <div ref={feedRef} className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 pb-4">
        {messages.length === 0 && !pending && !activeJob ? (
          <Intro />
        ) : (
          <>
            {messages.map((m, i) => (
              <MessageBubble key={m.id} message={m} first={i === 0 || messages[i - 1].role !== m.role} />
            ))}
            {pending && <TypingIndicator first={messages.length === 0 || messages[messages.length - 1].role !== "assistant"} />}
            {activeJob && <JobBubble job={activeJob} />}
          </>
        )}
      </div>

      <div className="shrink-0 border-t border-zinc-100 bg-white px-4 pb-4 pt-3">
        <div className="mb-2.5 flex flex-wrap gap-1.5">
          {(generation?.variants.length ? deckActions(selectedSlide) : QUICK_ACTIONS).map(({ label, message }) => (
            <button
              key={label}
              type="button"
              disabled={pending || healthError}
              onClick={() => void send(message)}
              className="h-8 cursor-pointer rounded-full bg-accent-50 px-3 text-xs font-semibold text-accent-700 transition-colors hover:bg-accent-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {label}
            </button>
          ))}
        </div>

        <div className={cn("rounded-2xl bg-zinc-100 transition-shadow focus-within:bg-white focus-within:shadow-[0_0_0_2px_#0077FF]", healthError && "shadow-[0_0_0_1px_#FCA5A5]")}>
          {attached && (
            <div className="flex items-center gap-2 border-b border-zinc-200/70 px-3.5 py-2 text-xs text-zinc-600">
              <FileText className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden />
              <span className="min-w-0 flex-1 truncate">
                <span className="font-medium text-zinc-800">{attached.name}</span> · {fmtBytes(attached.size)}
              </span>
              <button type="button" onClick={clearDraft} aria-label="Убрать бриф" className="rounded p-0.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700">
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
          )}
          <textarea
            ref={areaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            disabled={healthError}
            placeholder={healthError ? "API недоступен — дождитесь переподключения" : "Напишите вопрос или текст презентации…"}
            aria-label="Сообщение агенту"
            className="scroll-thin block w-full resize-none bg-transparent px-4 py-3 text-sm leading-5 text-zinc-900 placeholder:text-zinc-500 focus:outline-none disabled:cursor-not-allowed"
          />
          <div className="flex items-center gap-2 px-2 pb-2">
            <input ref={fileRef} type="file" accept=".md,.txt,.markdown,text/markdown,text/plain" className="hidden" onChange={(e) => void onFile(e)} />
            <Button size="sm" variant="ghost" icon={Paperclip} disabled={pending || healthError} onClick={() => fileRef.current?.click()} title="Вставить текст из файла .txt или .md">
              Файл
            </Button>
            <span className="ml-auto text-[11px] tabular-nums text-zinc-400">{text.length > 0 && `${text.length.toLocaleString("ru-RU")} зн.`}</span>
            <Button size="sm" variant="primary" icon={SendHorizontal} loading={pending} disabled={!canSend} onClick={() => void send(text)} aria-label="Отправить" className="w-8 rounded-full px-0" />
          </div>
        </div>
      </div>
    </div>
  );
}
