// The composer: one large white card that holds the field (what the deck is about) with its overlays, the toolbar (the
// template, a file, the sample, the slide count, the settings and «Создать») and the settings that unfold inside it.
// While anything inside has the focus, the card's edge lights up in the brand gradient over a soft glow; a field that
// fails the check rings red instead; a missing text shakes the card once.
import { forwardRef, type CSSProperties, type ReactNode, type RefObject } from "react";
import { cn } from "../../lib/utils";

export interface ComposerProps {
  /** The field and its overlays (the typing examples, the counter). */
  field: ReactNode;
  toolbar: ReactNode;
  /** The toolbar's row: the create screen watches it to float its bar once «Создать» has scrolled away. */
  toolbarRef?: RefObject<HTMLDivElement>;
  settings: ReactNode;
  settingsOpen: boolean;
  settingsId: string;
  invalid: boolean;
  shake: boolean;
  className?: string;
  style?: CSSProperties;
}

export const Composer = forwardRef<HTMLDivElement, ComposerProps>(function Composer({ field, toolbar, toolbarRef, settings, settingsOpen, settingsId, invalid, shake, className, style }, ref) {
  return (
    <div ref={ref} className={cn("group/composer relative isolate rounded-[28px]", shake && "animate-shake", className)} style={style}>
      {/* the glow and the gradient edge (1.5px around the card), shown while something inside has the focus */}
      <div aria-hidden className={cn("pointer-events-none absolute -inset-3 -z-10 rounded-[40px] bg-brand opacity-0 blur-2xl transition-opacity duration-300", !invalid && "group-focus-within/composer:opacity-[0.16]")} />
      <div aria-hidden className={cn("pointer-events-none absolute -inset-[1.5px] rounded-[29.5px] bg-brand opacity-0 transition-opacity duration-200", !invalid && "group-focus-within/composer:opacity-100")} />
      <div className={cn("relative rounded-[28px] bg-white transition-shadow duration-150", invalid ? "shadow-danger" : "shadow-float")}>
        {field}
        {/* the settings unfold between the text and the toolbar, so «Создать» comes after the options it depends on (the
            rows glide open, the panel fades in just after them, and fades out first on the way back); while folded they
            leave the tab order once the animation has played */}
        <div className={cn("grid transition-[grid-template-rows] duration-300 ease-glide", settingsOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
          <div id={settingsId} className="min-h-0 overflow-hidden" style={{ visibility: settingsOpen ? "visible" : "hidden", transition: `visibility 0s linear ${settingsOpen ? "0s" : "300ms"}` }}>
            <div className={cn("mx-6 mt-3 border-y border-zinc-900/[0.06] py-6 transition-opacity", settingsOpen ? "opacity-100 delay-[60ms] duration-200 ease-out" : "opacity-0 duration-150 ease-in")}>
              {settings}
            </div>
          </div>
        </div>
        <div ref={toolbarRef} className="flex min-h-[72px] flex-wrap items-center gap-2 px-6 pb-5 pt-3">
          {toolbar}
        </div>
      </div>
    </div>
  );
});
