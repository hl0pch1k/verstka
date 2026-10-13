// Полоса колоды над открытым слоем: видимая часть колоды (0…120 px) над разделом или «Слайдами шаблона» закрывает
// его по клику. Разметка — boards/V2.dc.html: `<button class="p2-scrim" … style="… height:120px; z-index:5">`
// (раздел) и `z-index:8` («Слайды шаблона»).
export function Scrim({ open, onClose, label, z = 5, height = 120 }: {
  open: boolean;
  onClose(): void;
  /** «Закрыть «Шаблоны»», «Закрыть «Слайды шаблона»». */
  label: string;
  z?: number;
  height?: number;
}) {
  if (!open) return null;
  return (
    <button type="button" className="p2-scrim" onClick={onClose} aria-label={label}
      style={{ position: "absolute", left: 0, right: 0, top: 0, height, zIndex: z }} />
  );
}
