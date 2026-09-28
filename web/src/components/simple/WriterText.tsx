// The text the agent wrote from a topic (writer mode, planning/writer.py): a sheet opened from the result's notice
// («Показать текст») and the same text inline in the drawer's «План». «Изменить» puts the text into the create screen's
// field — the person corrects a date or adds a thesis and builds the deck strictly by it; «Скопировать» copies it.
// Every sentence of the text comes from a sentence of the article (source-anchored writing): hovering or tapping a
// sentence shows that sentence and a link to the article in one quiet line at the bottom of the sheet.
import { Fragment, useState } from "react";
import { Copy, ExternalLink, PenLine } from "lucide-react";
import { cn } from "../../lib/utils";
import { useApp } from "../../store";
import type { WriterInfo } from "../../types";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

const HEAD = /^\s*Слайд\s+\d{1,2}\.\s/;

/** One statement's source (generation.json `writer.sources`, WriterResult.meta): the statement as the text shows it,
 * the article and its sentence. */
export interface WriterSourceItem {
  text: string;
  page: string;
  url: string;
  sentence: string;
}
type WriterMeta = WriterInfo & { sources?: WriterSourceItem[]; pages?: Array<{ title: string; url: string }> };

interface Piece {
  text: string;
  src?: WriterSourceItem;
}

/** A line cut into the statements that have a source and the text between them. */
function pieces(line: string, sources: WriterSourceItem[]): Piece[] {
  const found: Array<{ at: number; end: number; src: WriterSourceItem }> = [];
  for (const s of sources) {
    let t = s.text.trim();
    let at = t ? line.indexOf(t) : -1;
    if (at < 0 && t) {
      t = t.replace(/[.;]$/, "");
      at = t ? line.indexOf(t) : -1;
    }
    if (at < 0 || found.some((f) => at < f.end && at + t.length > f.at)) continue;
    found.push({ at, end: at + t.length, src: s });
  }
  if (!found.length) return [{ text: line }];
  found.sort((a, b) => a.at - b.at);
  const out: Piece[] = [];
  let pos = 0;
  for (const f of found) {
    if (f.at > pos) out.push({ text: line.slice(pos, f.at) });
    out.push({ text: line.slice(f.at, f.end), src: f.src });
    pos = f.end;
  }
  if (pos < line.length) out.push({ text: line.slice(pos) });
  return out;
}

/** The written text as it reads: «Слайд N. …» lines semibold, the rest as written. With `sources`, each sentence that
 * has one is marked quietly on hover or tap and reported to `onSource` (the sheet shows it in one line). */
export function WriterTextBody({ text, sources, active, onSource }: {
  text: string;
  sources?: WriterSourceItem[];
  active?: WriterSourceItem | null;
  onSource?(s: WriterSourceItem | null): void;
}) {
  const lines = text.replace(/\s+$/, "").split("\n");
  const list = sources && onSource ? sources : [];
  return (
    <div className="whitespace-pre-wrap text-body leading-6 text-zinc-800">
      {lines.map((line, i) =>
        HEAD.test(line) ? (
          <p key={i} className={i > 0 ? "mt-1 font-semibold text-zinc-900" : "font-semibold text-zinc-900"}>{line}</p>
        ) : (
          <p key={i} className={line.trim() ? undefined : "h-3"}>
            {list.length
              ? pieces(line, list).map((p, k) =>
                  p.src ? (
                    <span
                      key={k}
                      tabIndex={0}
                      onMouseEnter={() => onSource?.(p.src!)}
                      onFocus={() => onSource?.(p.src!)}
                      onClick={() => onSource?.(active === p.src ? null : p.src!)}
                      className={cn(
                        "cursor-help rounded-[4px] outline-none transition-colors duration-150 [box-decoration-break:clone] hover:bg-accent-50 focus-visible:bg-accent-50",
                        active === p.src && "bg-accent-50",
                      )}
                    >
                      {p.text}
                    </span>
                  ) : (
                    <Fragment key={k}>{p.text}</Fragment>
                  ),
                )
              : line}
          </p>
        ),
      )}
    </div>
  );
}

/** A link that opens the article at the sentence (a text fragment: the browser scrolls to it and marks it). */
function sentenceLink(src: WriterSourceItem): string {
  const words = src.sentence.replace(/[«»"()]/g, " ").split(/\s+/).filter(Boolean).slice(0, 6).join(" ");
  if (!src.url) return "";
  return words ? `${src.url}#:~:text=${encodeURIComponent(words)}` : src.url;
}

/** The source of the sentence under the pointer or the finger, in one quiet line pinned to the bottom of the sheet's
 * text: «the article's sentence» · the article ↗. Always there (empty, invisible) so the text never jumps. */
function SourceLine({ src }: { src: WriterSourceItem | null }) {
  return (
    <div
      aria-live="polite"
      className={cn(
        "sticky -bottom-6 -mx-6 -mb-6 mt-3 flex min-h-10 min-w-0 flex-col items-start justify-center gap-0.5 border-t border-zinc-100 bg-white px-6 py-2 text-footnote text-zinc-500 transition-opacity duration-150 sm:flex-row sm:items-center sm:justify-start sm:gap-1.5",
        src ? "opacity-100" : "pointer-events-none opacity-0",
      )}
    >
      {src && (
        <>
          {/* one line; on a phone two, the article under them */}
          <span className="line-clamp-2 min-w-0 sm:line-clamp-1" title={src.sentence}>«{src.sentence}»</span>
          {src.url && (
            <a
              href={sentenceLink(src)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex shrink-0 items-center gap-1 text-accent-700 underline-offset-2 hover:underline"
            >
              {src.page || "Википедия"}
              <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden />
            </a>
          )}
        </>
      )}
    </div>
  );
}

function ArticleLink({ title, url }: { title: string; url: string }) {
  return (
    <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent-700 underline-offset-2 hover:underline">
      «{title}»
      <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden />
    </a>
  );
}

/** Where the text comes from, in a few words: the articles (links) or the topic. */
export function WriterSource({ writer }: { writer: WriterInfo }) {
  const meta = writer as WriterMeta;
  const pages = meta.pages?.length ? meta.pages : writer.source?.title ? [writer.source] : [];
  if (pages.length) {
    return (
      <>
        Написал агент по {pages.length > 1 ? "статьям" : "статье"}{" "}
        {pages.map((p, i) => (
          <Fragment key={p.title}>
            {i > 0 && (i === pages.length - 1 ? " и " : ", ")}
            <ArticleLink title={p.title} url={p.url} />
          </Fragment>
        ))}{" "}
        из Википедии
      </>
    );
  }
  return <>Написал агент по теме «{writer.topic ?? ""}»</>;
}

/** «Изменить» and «Скопировать» for the written text. */
export function useWriterActions(text: string) {
  const { editText, toast } = useApp();
  const copy = () =>
    void navigator.clipboard?.writeText(text).then(
      () => toast("success", "Скопировано"),
      () => toast("error", "Не удалось скопировать"),
    );
  return { edit: () => editText(text), copy };
}

export function WriterTextSheet({ writer, open, onClose }: { writer: WriterInfo; open: boolean; onClose(): void }) {
  const text = writer.text ?? "";
  const sources = (writer as WriterMeta).sources ?? [];
  const [active, setActive] = useState<WriterSourceItem | null>(null);
  const { edit, copy } = useWriterActions(text);
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title="Текст презентации"
      description={<WriterSource writer={writer} />}
      footer={
        <>
          <Button variant="ghost" size="md" icon={Copy} onClick={copy}>Скопировать</Button>
          <Button
            variant="primary"
            size="md"
            icon={PenLine}
            onClick={() => {
              onClose();
              edit();
            }}
          >
            Изменить
          </Button>
        </>
      }
    >
      <WriterTextBody text={text} sources={sources} active={active} onSource={setActive} />
      {sources.length > 0 && <SourceLine src={active} />}
    </Modal>
  );
}
