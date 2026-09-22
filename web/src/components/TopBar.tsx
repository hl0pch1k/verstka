// STUB — replaced by the panel owner. Contract: named export `TopBar`, no props, state via useApp().
// Rendered by App as the first row of the full-height column: keep it `shrink-0` with a fixed height (h-14).
// (A static header instead of <EmptyState/>: an empty-state block does not fit a 56px bar.)
export function TopBar() {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-zinc-200 bg-white px-6">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-sm font-bold text-white">V</span>
      <span className="text-[15px] font-semibold tracking-tight text-zinc-900">Verstka</span>
      <span className="text-[13px] text-zinc-500">цифровой дизайнер презентаций</span>
    </header>
  );
}
