// Brand mark: three layout bars in a VK-blue tile — «вёрстка» as a glyph.
export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
      <rect width="32" height="32" rx="9" fill="#0077FF" />
      <rect x="7" y="8" width="18" height="4" rx="2" fill="white" />
      <rect x="7" y="14" width="11" height="4" rx="2" fill="white" fillOpacity="0.8" />
      <rect x="7" y="20" width="15" height="4" rx="2" fill="white" fillOpacity="0.6" />
    </svg>
  );
}

export function Logo({ onClick }: { onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Verstka — на главную"
      className="group flex h-11 shrink-0 cursor-pointer items-center gap-2.5 rounded-xl pr-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
    >
      <span className="transition-transform duration-300 ease-out group-hover:-rotate-6 group-hover:scale-105 group-active:scale-95">
        <LogoMark size={36} />
      </span>
      <span className="font-display text-[26px] font-bold leading-none tracking-[-0.03em] text-zinc-900">Verstka</span>
    </button>
  );
}
