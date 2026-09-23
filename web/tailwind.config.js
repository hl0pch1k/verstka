/** @type {import('tailwindcss').Config} */
// Verstka × VK: the grey scale follows VKUI (cool greys of VK products), the accent is VK blue #0077FF.
// `zinc` is remapped on purpose: every surface, text and border of the app picks up the VK greys from one place.
const vkGray = {
  50: "#F7F8FA",
  100: "#F0F2F5",
  200: "#E1E3E6",
  300: "#C9CDD2",
  400: "#99A2AD",
  500: "#6D7885",
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
        },
        ink: {
          DEFAULT: "#111214",
          800: "#1B1C1F",
          700: "#26282C",
          600: "#34373C",
          line: "rgba(255,255,255,0.08)",
        },
        canvas: "#F2F3F5",
      },
      fontFamily: {
        sans: ["Onest", "VK Sans Display", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        display: ["Onest", "VK Sans Display", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["11px", "14px"],
      },
      borderRadius: {
        "4xl": "28px",
      },
      boxShadow: {
        card: "0 0 0 1px rgba(0, 16, 61, 0.04), 0 1px 2px rgba(0, 16, 61, 0.05)",
        raise: "0 0 0 1px rgba(0, 16, 61, 0.05), 0 4px 16px rgba(0, 16, 61, 0.06)",
        pop: "0 0 0 1px rgba(0, 16, 61, 0.06), 0 12px 40px rgba(0, 16, 61, 0.14)",
        glow: "0 8px 24px rgba(0, 119, 255, 0.28)",
        "inner-line": "inset 0 0 0 1px rgba(0, 16, 61, 0.08)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        "fade": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-in-right": { from: { opacity: "0", transform: "translateX(24px)" }, to: { opacity: "1", transform: "translateX(0)" } },
        shimmer: { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } },
        "pulse-ring": { "0%": { transform: "scale(0.9)", opacity: "0.7" }, "100%": { transform: "scale(1.6)", opacity: "0" } },
        sweep: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        "fade-in": "fade-in 220ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        fade: "fade 180ms ease-out",
        "slide-in-right": "slide-in-right 240ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        shimmer: "shimmer 1.6s linear infinite",
        "pulse-ring": "pulse-ring 1.6s cubic-bezier(0.2, 0.8, 0.2, 1) infinite",
        sweep: "sweep 1.4s cubic-bezier(0.4, 0, 0.2, 1) infinite",
      },
    },
  },
  plugins: [],
};
