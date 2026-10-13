// Файл над шагом 01 (C-upload): пунктир по телу плиты, белая подложка и подсказка «Отпустите файл — разберу шаблон».
// Разметка — boards/V2.dc.html, `.up-zone.tp-zone`: проявляется и гаснет за 240 мс, подсказка — 360 мс через 80 мс.
// Файл принимается в любом месте плиты 01 (перетаскивание слушает плита — `useFileDrop`), выбор файла — скрытый
// `<input type=file>` (`FileInput`).
import { useEffect, useRef, useState, type RefObject } from "react";
import { TEMPLATE_ACCEPT } from "../../lib/templateFiles";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";

export function UploadZone({ on }: { on: boolean }) {
  return (
    <div className={cls("up-zone tp-zone", on && "tp-zone-on")} role="status" aria-live="polite">
      <span className="up-veil" aria-hidden="true" />
      <span className="up-line" aria-hidden="true" />
      {on && <span className="p2-sr">Отпустите файл — разберу шаблон</span>}
      <div className="up-msg" aria-hidden="true">
        <span className="p2-lic p2-lic-w p2-lic-up"><span className="p2-lic-b" /><span className="p2-lic-f"><Icon name="upload" size={22} /></span></span>
        <p style={{ margin: "24px 0 0", fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 24, lineHeight: "32px", letterSpacing: "-0.03em", color: "#0B1220" }}>
          Отпустите файл — разберу шаблон
        </p>
        <p style={{ margin: "8px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272" }}>.pptx, .potx, .ppt или .odp · до 200 МБ</p>
      </div>
    </div>
  );
}

/** Скрытый выбор файла шаблона; `inputRef.current.click()` открывает окно выбора. */
export function FileInput({ inputRef, onFile }: { inputRef: RefObject<HTMLInputElement>; onFile(f: File): void }) {
  return (
    <input ref={inputRef} type="file" accept={TEMPLATE_ACCEPT} hidden tabIndex={-1} aria-hidden="true"
      onChange={(e) => {
        const f = e.currentTarget.files?.[0];
        e.currentTarget.value = ""; // тот же файл ещё раз — снова событие change
        if (f) onFile(f);
      }} />
  );
}

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");

/** Файл, отпущенный мимо включённой зоны — на другой плите, в шапке, на свёрнутом шаге, во время разбора, — не должен
 *  открыться или скачаться в самой вкладке (так браузер поступает с файлом, который никто не принял). Один слушатель
 *  на окно, ставит оболочка: гасит событие и показывает «нельзя», если ни плита 01, ни другая зона файл не приняли
 *  (их слушатели стоят ниже по дереву и срабатывают раньше). Ничего не загружает. */
export function useStrayFileDrop(): void {
  useEffect(() => {
    const over = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      const taken = e.defaultPrevented;
      e.preventDefault();
      if (!taken && e.dataTransfer) e.dataTransfer.dropEffect = "none";
    };
    const drop = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault();
    };
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", drop);
    };
  }, []);
}

/** Перетаскивание файла на плиту, внутри которой стоит `anchor`: пока файл над плитой — `true` (зона видна); отпущенный
 *  файл уходит в `onFile`. Считает входы и выходы (dragenter/dragleave приходят и от вложенных элементов). */
export function useFileDrop(anchor: RefObject<HTMLElement>, enabled: boolean, onFile: (f: File) => void): boolean {
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const take = useRef(onFile);
  take.current = onFile;
  useEffect(() => {
    const plate = anchor.current?.closest("section");
    depth.current = 0;
    setOver(false);
    if (!plate || !enabled) return;
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current += 1;
      setOver(true);
    };
    const over_ = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setOver(false);
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setOver(false);
      const f = e.dataTransfer?.files?.[0];
      if (f) take.current(f);
    };
    plate.addEventListener("dragenter", enter);
    plate.addEventListener("dragover", over_);
    plate.addEventListener("dragleave", leave);
    plate.addEventListener("drop", drop);
    return () => {
      plate.removeEventListener("dragenter", enter);
      plate.removeEventListener("dragover", over_);
      plate.removeEventListener("dragleave", leave);
      plate.removeEventListener("drop", drop);
    };
  }, [anchor, enabled]);
  return over;
}
