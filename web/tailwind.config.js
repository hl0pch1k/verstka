/** @type {import('tailwindcss').Config} */
// Verstka × VK Tech. Colours, radii and shadows follow VKUI's paradigmTech theme (@vkontakte/vkui-tokens — the design
// language of VK Tech's products: VK WorkSpace, VK Cloud): a cool page #F6F7FB, white paper, one accent — VK blue
// #0077FF. `zinc` is remapped on purpose: every surface, text and border of the app takes the VK Tech greys from here.
const vkGray = {
  50: "#F6F7FB", // color_background — the page
  100: "#EFF0F4", // color_background_secondary — fields at rest, chips, tracks
  200: "#E3E4E7", // color_separator_secondary — hairlines
  300: "#C9D0D9", // color_icon_tertiary
  400: "#939EAC", // color_icon_secondary
  500: "#66717E", // color_text_secondary (a shade deeper than #697481: 4.6:1 on the page, 5:1 on white)
  600: "#565F6B",
  700: "#40464F",
  800: "#2E3035",
  900: "#252629", // color_text_primary
  950: "#17181B",
};

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        zinc: vkGray,
        accent: {
          DEFAULT: "#0077FF", // color_background_accent
          50: "#EBF4FF",
          100: "#D6E9FF",
          200: "#ADD3FF",
          300: "#7AB8FF",
          400: "#439BFB", // color_background_accent_tint
          500: "#0077FF",
          600: "#006EE9", // color_text_accent
          700: "#0055B8",
          800: "#004494",
          900: "#003370",
          // fills that carry white text (primary buttons, done circles, solid badges): 4.9:1 with white
          fill: "#0070F0",
        },
        ink: { DEFAULT: "#111214" },
        canvas: "#F6F7FB",
      },
      fontFamily: {
        // VK Sans is VK's own typeface (TypeType, not openly licensed): used when installed on the machine, otherwise
        // Onest — the closest open grotesque with a full Cyrillic set — loaded from Google Fonts
        sans: ["VK Sans Text", "VK Sans Display", "Onest", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        display: ["VK Sans Display", "Onest", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      // the one type scale: nothing else is used for UI text (template font previews and the logo are data/brand)
      fontSize: {
        caption: ["12px", "16px"], // badges, chips, slide tags, table heads
        footnote: ["13px", "20px"], // meta lines, dense rows, sm buttons
        body: ["15px", "20px"], // labels, list rows, md/lg buttons (+ leading-6 for reading text)
        title3: ["17px", "24px"], // card titles
        title2: ["20px", "28px"], // step titles, drawer hero, modal title
        title1: ["28px", "36px"], // page H1
        display: ["40px", "48px"],
      },
      // paradigmTech radii: 8 for controls, 12 for paper (cards), 16 for sheets and dialogs
      borderRadius: {
        lg: "8px",
        xl: "10px",
        "2xl": "12px",
        "3xl": "16px",
      },
      boxShadow: {
        // paradigmTech elevations, tinted with the VK greys' blue
        card: "0 0 0 1px rgba(0, 16, 61, 0.04), 0 1px 2px rgba(0, 16, 61, 0.06), 0 2px 6px rgba(0, 16, 61, 0.04)",
        raise: "0 0 0 1px rgba(0, 16, 61, 0.04), 0 0 6px rgba(0, 16, 61, 0.06), 0 6px 12px rgba(0, 16, 61, 0.06)",
        pop: "0 2px 6px rgba(0, 16, 61, 0.06), 0 16px 48px rgba(0, 16, 61, 0.08), 0 24px 68px rgba(0, 16, 61, 0.16)",
        "inner-line": "inset 0 0 0 1px rgba(0, 16, 61, 0.08)",
        // selection is 2px VK blue everywhere
        selected: "0 0 0 2px #0077FF",
        "selected-hover": "0 0 0 2px #ADD3FF",
        "selected-inset": "inset 0 0 0 1.5px #0077FF",
        danger: "0 0 0 2px #F23741",
        knob: "0 1px 2px rgba(0, 16, 61, 0.2)",
      },
      // motion tokens (MOTION_SPEC §1): the same curves live as CSS variables in index.css and as EASE in lib/motion.ts.
      // `ease-out` / `ease-in` / `ease-in-out` are overridden on purpose: every arrival decelerates on the strong curve.
      transitionTimingFunction: {
        DEFAULT: "cubic-bezier(0.2, 0, 0, 1)",
        out: "cubic-bezier(0.23, 1, 0.32, 1)",
        in: "cubic-bezier(0.4, 0, 1, 1)",
        "in-out": "cubic-bezier(0.77, 0, 0.175, 1)",
        glide: "cubic-bezier(0.32, 0.72, 0, 1)",
        spring: "cubic-bezier(0.34, 1.56, 0.64, 1)",
      },
      transitionDuration: { DEFAULT: "150ms", 250: "250ms", 600: "600ms" },
      keyframes: {
        // enters: `from` only (the element's own values are the end), played with fill `backwards`; nothing grows from
        // nothing — a scale starts at 0.9 at least
        fade: { from: { opacity: "0" } },
        "fade-in": { from: { opacity: "0", transform: "translateY(4px)" } },
        rise: { from: { opacity: "0", transform: "translateY(8px)" } },
        "screen-in": { from: { opacity: "0", transform: "translateY(8px)" } },
        pop: { from: { opacity: "0", transform: "scale(0.9)" } },
        "zoom-in": { from: { opacity: "0", transform: "translateY(8px) scale(0.97)" } },
        "drop-in": { from: { opacity: "0", transform: "translateY(-4px) scale(0.97)" } },
        "sheet-in": { from: { transform: "translateX(100%)" } },
        "slide-in-l": { from: { opacity: "0", transform: "translateX(-12px)" } },
        "slide-in-r": { from: { opacity: "0", transform: "translateX(12px)" } },
        "frame-in": { from: { opacity: "0", transform: "scale(1.03)" } },
        "msg-in": { from: { opacity: "0", transform: "translateY(8px) scale(0.98)" } },
        reveal: { from: { opacity: "0", transform: "scale(1.012)" } },
        // a planned slide of the build's storyboard takes its place
        "fill-in": { from: { opacity: "0", transform: "scale(0.97)" } },
        // a storyboard sketch draws itself: bars grow from their baseline, rules run out from their start, a chart's line
        // draws (pathLength 100)
        "grow-x": { from: { transform: "scaleX(0)" } },
        "grow-y": { from: { transform: "scaleY(0)" } },
        draw: { from: { strokeDashoffset: "100" } },
        // exits: `to` only, played with fill `forwards` (held until unmount)
        "fade-out": { to: { opacity: "0" } },
        "zoom-out": { to: { opacity: "0", transform: "scale(0.98)" } },
        "drop-out": { to: { opacity: "0", transform: "translateY(-4px) scale(0.98)" } },
        "sheet-out": { to: { transform: "translateX(100%)" } },
        "pop-out": { to: { opacity: "0", transform: "scale(0.9)" } },
        // feedback and loops (loops run only while their work runs)
        shake: { "0%, 100%": { transform: "translateX(0)" }, "20%": { transform: "translateX(-6px)" }, "40%": { transform: "translateX(5px)" }, "60%": { transform: "translateX(-3px)" }, "80%": { transform: "translateX(2px)" } },
        "ring-ping": { from: { opacity: "0.6", transform: "scale(1)" }, to: { opacity: "0", transform: "scale(2.4)" } },
        typing: { "0%, 60%, 100%": { opacity: "0.35", transform: "translateY(0)" }, "30%": { opacity: "1", transform: "translateY(-3px)" } },
        breathe: { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
        shimmer: { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } },
        // a 30% segment from just off the left end to just off the right end (-30% → 100% of the track)
        sweep: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(333%)" } },
        scan: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(300%)" } },
      },
      // enters 200–300 on ease-out, exits 150 on ease-in, travel on glide, confirmations on spring (fill: enters
      // backwards, exits forwards)
      animation: {
        fade: "fade 200ms var(--ease-in-out) backwards",
        "fade-in": "fade-in 200ms var(--ease-out) backwards",
        rise: "rise 260ms var(--ease-out) backwards",
        "screen-in": "screen-in 260ms var(--ease-out) backwards",
        pop: "pop 240ms var(--ease-spring) backwards",
        "zoom-in": "zoom-in 220ms var(--ease-out) backwards",
        "drop-in": "drop-in 180ms var(--ease-out) backwards",
        "sheet-in": "sheet-in 300ms var(--ease-glide) backwards",
        "slide-in-l": "slide-in-l 220ms var(--ease-out) backwards",
        "slide-in-r": "slide-in-r 220ms var(--ease-out) backwards",
        "frame-in": "frame-in 260ms var(--ease-out) backwards",
        "msg-in": "msg-in 220ms var(--ease-out) backwards",
        reveal: "reveal 300ms var(--ease-out) backwards",
        "fill-in": "fill-in 260ms var(--ease-out) backwards",
        "grow-x": "grow-x 500ms var(--ease-out) backwards",
        "grow-y": "grow-y 500ms var(--ease-out) backwards",
        draw: "draw 700ms var(--ease-out) backwards",
        "fade-out": "fade-out 150ms var(--ease-in) forwards",
        "zoom-out": "zoom-out 150ms var(--ease-in) forwards",
        "drop-out": "drop-out 150ms var(--ease-in) forwards",
        "sheet-out": "sheet-out 200ms var(--ease-in) forwards",
        "pop-out": "pop-out 150ms var(--ease-in) forwards",
        shake: "shake 380ms cubic-bezier(0.36, 0.07, 0.19, 0.97)",
        // a gentler deceleration than --ease-out, so the halo stays readable while it grows (two pings, then still)
        "ring-ping": "ring-ping 800ms cubic-bezier(0, 0, 0.2, 1) 2",
        typing: "typing 1.2s var(--ease-in-out) infinite",
        breathe: "breathe 1.6s var(--ease-in-out) infinite",
        shimmer: "shimmer 1.6s linear infinite",
        sweep: "sweep 1.4s var(--ease-in-out) infinite",
        scan: "scan 1.6s var(--ease-in-out) infinite",
      },
    },
  },
  plugins: [],
};
