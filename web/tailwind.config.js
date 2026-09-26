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
      keyframes: {
        "fade-in": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        "fade": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-in-right": { from: { opacity: "0", transform: "translateX(24px)" }, to: { opacity: "1", transform: "translateX(0)" } },
        shimmer: { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } },
        // a 30% segment from just off the left end to just off the right end (-30% → 100% of the track), at an even speed
        sweep: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(333%)" } },
        pop: { "0%": { transform: "scale(0.4)", opacity: "0" }, "60%": { transform: "scale(1.12)", opacity: "1" }, "100%": { transform: "scale(1)" } },
        "scale-in": { from: { opacity: "0", transform: "translateY(12px) scale(0.96)" }, to: { opacity: "1", transform: "translateY(0) scale(1)" } },
        "scale-out": { from: { opacity: "1", transform: "translateY(0) scale(1)" }, to: { opacity: "0", transform: "translateY(12px) scale(0.96)" } },
        "fade-out": { from: { opacity: "1" }, to: { opacity: "0" } },
        "slide-out-right": { from: { opacity: "1", transform: "translateX(0)" }, to: { opacity: "0", transform: "translateX(32px)" } },
        rise: { from: { opacity: "0", transform: "translateY(16px)" }, to: { opacity: "1", transform: "none" } },
        "zoom-in": { from: { opacity: "0", transform: "scale(0.96)" }, to: { opacity: "1", transform: "scale(1)" } },
        "zoom-out": { from: { opacity: "1", transform: "scale(1)" }, to: { opacity: "0", transform: "scale(0.97)" } },
        "drop-in": { from: { opacity: "0", transform: "translateY(-6px) scale(0.97)" }, to: { opacity: "1", transform: "translateY(0) scale(1)" } },
        "drop-out": { from: { opacity: "1", transform: "translateY(0) scale(1)" }, to: { opacity: "0", transform: "translateY(-4px) scale(0.98)" } },
        shake: { "0%, 100%": { transform: "translateX(0)" }, "20%": { transform: "translateX(-6px)" }, "40%": { transform: "translateX(5px)" }, "60%": { transform: "translateX(-3px)" }, "80%": { transform: "translateX(2px)" } },
      },
      // enters 200 (panels 300, rise 280), exits 150: ease-out curve in, ease-in out
      animation: {
        "fade-in": "fade-in 200ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        fade: "fade 200ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        "slide-in-right": "slide-in-right 300ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        shimmer: "shimmer 1.6s linear infinite",
        sweep: "sweep 1.2s linear infinite",
        pop: "pop 240ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "scale-in": "scale-in 200ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "scale-out": "scale-out 150ms ease-in both",
        "fade-out": "fade-out 150ms ease-in both",
        "slide-out-right": "slide-out-right 150ms ease-in both",
        rise: "rise 280ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "zoom-in": "zoom-in 200ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "zoom-out": "zoom-out 150ms ease-in both",
        "drop-in": "drop-in 200ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "drop-out": "drop-out 150ms ease-in both",
        shake: "shake 380ms cubic-bezier(0.36, 0.07, 0.19, 0.97)",
      },
    },
  },
  plugins: [],
};
