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
    <button type="button" onClick={onClick} className="group flex shrink-0 cursor-pointer items-center gap-3 rounded-xl pr-2 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-white/40" aria-label="Verstka — на главную">
      <span className="transition-transform duration-200 group-hover:scale-105">
        <LogoMark />
      </span>
      <span className="leading-tight">
        <span className="block text-[17px] font-bold tracking-tight text-white">Verstka</span>
        <span className="hidden text-[11px] font-medium text-white/45 min-[1600px]:block">дизайнер презентаций</span>
      </span>
    </button>
  );
}
