// Brand mark: three layout bars in a tile of the brand gradient (VK blue → violet) — «вёрстка» as a glyph.
import { useId } from "react";

export function LogoMark({ size = 32 }: { size?: number }) {
  // one gradient per mark: two marks on a page must not share (and lose) an id
  const id = `logo-${useId().replace(/:/g, "")}`;
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#0066F5" />
          <stop offset="1" stopColor="#6A4DFF" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${id})`} />
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
      className="group -ml-2 flex h-10 shrink-0 cursor-pointer items-center gap-2 rounded-xl px-2"
    >
      <span className="transition-transform duration-300 ease-spring group-hover:-rotate-6 group-hover:scale-105 group-active:scale-95 group-active:duration-100">
        <LogoMark size={32} />
      </span>
      <span className="font-display text-[26px] font-bold leading-none tracking-[-0.03em] text-zinc-900">Verstka</span>
    </button>
  );
}
