/** @type {import('tailwindcss').Config} */
// Verstka × VK: the grey scale follows VKUI (cool greys of VK products), the accent is VK blue #0077FF.
// `zinc` is remapped on purpose: every surface, text and border of the app picks up the VK greys from one place.
const vkGray = {
  50: "#F7F8FA",
  100: "#F0F2F5",
  200: "#E1E3E6",
  300: "#C9CDD2",
  400: "#99A2AD",
  500: "#626D7A", // 5.3:1 on white, 4.7:1 on canvas
  600: "#5A6169",
  700: "#3D4249",
  800: "#2C2D2E",
  900: "#19191A",
  950: "#0E0F10",
};

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        zinc: vkGray,
        accent: {
          DEFAULT: "#0077FF",
          50: "#EBF4FF",
          100: "#D6E9FF",
          200: "#ADD3FF",
          300: "#7AB8FF",
          400: "#4296FF",
          500: "#0077FF",
          600: "#0066DB",
          700: "#0055B8",
          800: "#004494",
          900: "#003370",
          // fills that carry white text (primary buttons, done circles, solid badges): 4.9:1 with white
          fill: "#0070F0",
        },
        ink: { DEFAULT: "#111214" },
        canvas: "#F2F3F5",
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
        title1: ["28px", "36px"], // page H1 (result, build)
        display: ["40px", "48px"], // create H1, build percent
      },
      boxShadow: {
        card: "0 0 0 1px rgba(0, 16, 61, 0.04), 0 1px 2px rgba(0, 16, 61, 0.05)",
        raise: "0 0 0 1px rgba(0, 16, 61, 0.05), 0 4px 16px rgba(0, 16, 61, 0.06)",
        pop: "0 0 0 1px rgba(0, 16, 61, 0.06), 0 12px 40px rgba(0, 16, 61, 0.14)",
        "inner-line": "inset 0 0 0 1px rgba(0, 16, 61, 0.08)",
        // selection is 2px VK blue everywhere
        selected: "0 0 0 2px #0077FF",
        "selected-hover": "0 0 0 2px #ADD3FF",
        "selected-inset": "inset 0 0 0 1.5px #0077FF",
        danger: "0 0 0 2px #EF4444",
        knob: "0 1px 2px rgba(0, 16, 61, 0.2)",
      },
      // motion tokens (MOTION_SPEC §1): the same curves live as CSS variables in index.css and as EASE in lib/motion.ts.
      // `ease-out` / `ease-in` / `ease-in-out` are overridden on purpose: every arrival decelerates on the expressive curve.
      transitionTimingFunction: {
        DEFAULT: "cubic-bezier(0.2, 0, 0, 1)",
        out: "cubic-bezier(0.16, 1, 0.3, 1)",
        in: "cubic-bezier(0.4, 0, 1, 1)",
        "in-out": "cubic-bezier(0.65, 0, 0.35, 1)",
        glide: "cubic-bezier(0.32, 0.72, 0, 1)",
        spring: "cubic-bezier(0.34, 1.56, 0.64, 1)",
      },
      transitionDuration: { DEFAULT: "150ms", 250: "250ms", 600: "600ms" },
      keyframes: {
        // enters: `from` only (the element's own values are the end), played with fill `backwards`
        fade: { from: { opacity: "0" } },
        "fade-in": { from: { opacity: "0", transform: "translateY(4px)" } },
        rise: { from: { opacity: "0", transform: "translateY(12px)" } },
        "screen-in": { from: { opacity: "0", transform: "translateY(8px)" } },
        pop: { from: { opacity: "0", transform: "scale(0.5)" } },
        "zoom-in": { from: { opacity: "0", transform: "translateY(8px) scale(0.97)" } },
        "drop-in": { from: { opacity: "0", transform: "translateY(-4px) scale(0.97)" } },
        "sheet-in": { from: { transform: "translateX(100%)" } },
        "slide-in-l": { from: { opacity: "0", transform: "translateX(-12px)" } },
        "slide-in-r": { from: { opacity: "0", transform: "translateX(12px)" } },
        "frame-in": { from: { opacity: "0", transform: "scale(1.06)" } },
        "msg-in": { from: { opacity: "0", transform: "translateY(8px) scale(0.98)" } },
        reveal: { from: { opacity: "0", transform: "scale(1.012)" } },
        // exits: `to` only, played with fill `forwards` (held until unmount)
        "fade-out": { to: { opacity: "0" } },
        "zoom-out": { to: { opacity: "0", transform: "scale(0.98)" } },
        "drop-out": { to: { opacity: "0", transform: "translateY(-4px) scale(0.98)" } },
        "sheet-out": { to: { transform: "translateX(100%)" } },
        "pop-out": { to: { opacity: "0", transform: "scale(0.6)" } },
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
      // enters 200–300 on ease-out, exits 150–200 on ease-in, travel on glide, confirmations on spring (fill: enters backwards, exits forwards)
      animation: {
        fade: "fade 200ms var(--ease-in-out) backwards",
        "fade-in": "fade-in 200ms var(--ease-out) backwards",
        rise: "rise 300ms var(--ease-out) backwards",
        "screen-in": "screen-in 300ms var(--ease-out) backwards",
        pop: "pop 300ms var(--ease-spring) backwards",
        "zoom-in": "zoom-in 240ms var(--ease-out) backwards",
        "drop-in": "drop-in 200ms var(--ease-out) backwards",
        "sheet-in": "sheet-in 300ms var(--ease-glide) backwards",
        "slide-in-l": "slide-in-l 240ms var(--ease-out) backwards",
        "slide-in-r": "slide-in-r 240ms var(--ease-out) backwards",
        "frame-in": "frame-in 260ms var(--ease-out) backwards",
        "msg-in": "msg-in 240ms var(--ease-out) backwards",
        reveal: "reveal 400ms var(--ease-out) backwards",
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
