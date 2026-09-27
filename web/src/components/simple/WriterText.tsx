// The text the agent wrote from a topic (writer mode, planning/writer.py): a sheet opened from the result's notice
// («Показать текст») and the same text inline in the drawer's «План». «Изменить» puts the text into the create screen's
// field — the person corrects a date or adds a thesis and builds the deck strictly by it; «Скопировать» copies it.
import { Copy, ExternalLink, PenLine } from "lucide-react";
import { useApp } from "../../store";
import type { WriterInfo } from "../../types";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

const HEAD = /^\s*Слайд\s+\d{1,2}\.\s/;

/** The written text as it reads: «Слайд N. …» lines semibold, the rest as written. */
export function WriterTextBody({ text }: { text: string }) {
  const lines = text.replace(/\s+$/, "").split("\n");
  return (
    <div className="whitespace-pre-wrap text-body leading-6 text-zinc-800">
      {lines.map((line, i) =>
        HEAD.test(line) ? (
          <p key={i} className={i > 0 ? "mt-1 font-semibold text-zinc-900" : "font-semibold text-zinc-900"}>{line}</p>
        ) : (
          <p key={i} className={line.trim() ? undefined : "h-3"}>{line}</p>
        ),
      )}
    </div>
  );
}

/** Where the text comes from, in a few words: the article (a link) or the topic. */
export function WriterSource({ writer }: { writer: WriterInfo }) {
  const src = writer.source;
  if (src?.title) {
    return (
      <>
        Написал агент по статье{" "}
        <a href={src.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent-700 underline-offset-2 hover:underline">
          «{src.title}»
          <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden />
        </a>{" "}
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
      <WriterTextBody text={text} />
    </Modal>
  );
}
