// Left column: the conversation with the Verstka agent — feed, composer, brief attachment and quick actions.
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
import { FileText, Layers, Paperclip, SendHorizontal, Sparkles, Upload, X } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { cn, sessionId } from "../lib/utils";
import { useApp } from "../store";
import { useChatActions } from "./ChatActions";
import { JobBubble, MessageBubble, TypingIndicator } from "./ChatParts";
import { Button } from "./ui/Button";

const QUICK_ACTIONS = ["Расскажи о шаблоне", "Покажи план", "Покажи аудит", "Исправь всё", "Экспорт"] as const;
const MAX_ROWS = 8;
const LINE_PX = 20; // leading-5
const PAD_PX = 20; // py-2.5, top + bottom
const MAX_BRIEF_BYTES = 2 * 1024 * 1024;

const STEPS = [
  { icon: Upload, title: "Загрузите шаблон", text: "Файл .pptx — я разберу его дизайн-систему: цвета, шрифты, сетку и паттерны слайдов." },
  { icon: FileText, title: "Пришлите бриф", text: "Текстом в чат или файлом .md/.txt. Чем больше фактов и цифр, тем точнее получатся слайды." },
  { icon: Layers, title: "Получите три варианта", text: "Структурный, визуальный и компактный — каждый с аудитом и экспортом в PPTX, PDF и HTML." },
] as const;

function fmtBytes(n: number): string {
  return n < 1024 ? `${n} Б` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} КБ` : `${(n / 1024 / 1024).toFixed(1)} МБ`;
}

function Intro() {
  return (
    <div className="mt-4 animate-fade-in rounded-xl border border-zinc-200 bg-gradient-to-b from-white to-zinc-50 p-4 shadow-card">
      <div className="flex items-center gap-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-50 text-accent ring-1 ring-inset ring-accent-100">
          <Sparkles className="h-4 w-4" strokeWidth={2.25} aria-hidden />
        </span>
        <div>
          <p className="text-sm font-semibold text-zinc-900">Здравствуйте! Я соберу презентацию в стиле вашего шаблона</p>
          <p className="text-xs text-zinc-500">Три шага — и у вас три варианта вёрстки с аудитом</p>
        </div>
      </div>
      <ol className="mt-4 space-y-3">
        {STEPS.map((s, i) => (
          <li key={s.title} className="flex gap-3">
            <span className="relative mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-zinc-200 bg-white text-zinc-600 shadow-card">
              <s.icon className="h-3.5 w-3.5" aria-hidden />
              <span className="absolute -left-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-accent text-[10px] font-semibold leading-none text-white">{i + 1}</span>
            </span>
            <div className="min-w-0">
              <p className="text-[13px] font-medium leading-5 text-zinc-900">{s.title}</p>
              <p className="text-xs leading-[18px] text-zinc-500">{s.text}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-4 border-t border-zinc-200 pt-3 text-xs text-zinc-500">
        Спросите «почему слайд 4 такой», попросите «исправь всё» или «экспорт» — я отвечу и сделаю. <kbd className="rounded border border-zinc-300 bg-white px-1 font-sans text-[11px]">Enter</kbd> — отправить,{" "}
        <kbd className="rounded border border-zinc-300 bg-white px-1 font-sans text-[11px]">Shift+Enter</kbd> — новая строка.
      </p>
    </div>
  );
}

export function Chat() {
  const { messages, pushMessage, toast, templateId, generationId, manifest, activeJob, healthError } = useApp();
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
    el.style.height = `${Math.min(el.scrollHeight, MAX_ROWS * LINE_PX + PAD_PX)}px`;
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
        const res = await api.chat({ session_id: sessionId(), message, template_id: templateId, generation_id: generationId });
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
    [pending, pushMessage, templateId, generationId, handleActions, toast],
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
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-zinc-200 px-5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-white shadow-sm">
          <Sparkles className="h-4 w-4" strokeWidth={2.25} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold leading-5 text-zinc-900">Агент Verstka</h2>
          <p className="truncate text-xs leading-4 text-zinc-500">
            {context}
            {generationId && <span className="text-zinc-400"> · генерация {generationId.slice(0, 8)}</span>}
          </p>
        </div>
        <span className={cn("flex items-center gap-1.5 text-[11px] font-medium", healthError ? "text-red-600" : pending || activeJob ? "text-accent" : "text-emerald-600")}>
          <span className={cn("h-1.5 w-1.5 rounded-full", healthError ? "bg-red-500" : pending || activeJob ? "animate-pulse bg-accent" : "bg-emerald-500")} aria-hidden />
          {healthError ? "Нет связи" : pending ? "Отвечает" : activeJob ? "Работает" : "На связи"}
        </span>
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

      <div className="shrink-0 border-t border-zinc-200 bg-zinc-50/70 px-4 pb-4 pt-3">
        <div className="mb-2.5 flex flex-wrap gap-1.5">
          {QUICK_ACTIONS.map((q) => (
            <button
              key={q}
              type="button"
              disabled={pending || healthError}
              onClick={() => void send(q)}
              className="h-7 rounded-full border border-zinc-200 bg-white px-2.5 text-xs font-medium text-zinc-700 shadow-sm transition-colors hover:border-accent-200 hover:bg-accent-50 hover:text-accent-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {q}
            </button>
          ))}
        </div>

        <div className={cn("rounded-xl border bg-white shadow-card transition-colors focus-within:border-accent focus-within:ring-1 focus-within:ring-accent/30", healthError ? "border-red-200" : "border-zinc-200")}>
          {attached && (
            <div className="flex items-center gap-2 border-b border-zinc-100 px-3 py-1.5 text-xs text-zinc-600">
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
            placeholder={healthError ? "API недоступен — дождитесь переподключения" : "Опишите презентацию или вставьте бриф…"}
            aria-label="Сообщение агенту"
            className="scroll-thin block w-full resize-none bg-transparent px-3.5 py-2.5 text-[13px] leading-5 text-zinc-900 placeholder:text-zinc-400 focus:outline-none disabled:cursor-not-allowed"
          />
          <div className="flex items-center gap-2 border-t border-zinc-100 px-2 py-1.5">
            <input ref={fileRef} type="file" accept=".md,.txt,.markdown,text/markdown,text/plain" className="hidden" onChange={(e) => void onFile(e)} />
            <Button size="sm" variant="ghost" icon={Paperclip} disabled={pending || healthError} onClick={() => fileRef.current?.click()}>
              Прикрепить бриф (.md/.txt)
            </Button>
            <span className="ml-auto text-[11px] tabular-nums text-zinc-400">{text.length > 0 && `${text.length.toLocaleString("ru-RU")} зн.`}</span>
            <Button size="sm" variant="primary" icon={SendHorizontal} loading={pending} disabled={!canSend} onClick={() => void send(text)} aria-label="Отправить">
              Отправить
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
