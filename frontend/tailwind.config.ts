import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Zoom brand palette (sampled from zoom.us via Playwright)
        zoom: {
          blue: "#0B5CFF",
          bluehover: "#0A4FE0",
          link: "#0D6BDE",
          orange: "#FF7A59",
          ink: "#232333",
          muted: "#666484",
          subtle: "#8B8B9A",
          line: "#E9E9EE",
          field: "#F7F7FA",
          dark: "#1A1A24",
          darker: "#0E0E14",
          panel: "#242430",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Helvetica", "Arial", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 3px rgba(16,24,40,0.06), 0 1px 2px rgba(16,24,40,0.04)",
        cardhover: "0 8px 24px rgba(16,24,40,0.12)",
        modal: "0 20px 48px rgba(16,24,40,0.24)",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "scale-in": {
          "0%": { opacity: "0", transform: "translateY(8px) scale(0.98)" },
          "100%": { opacity: "1", transform: "translateY(0) scale(1)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.15s ease-out",
        "scale-in": "scale-in 0.18s ease-out",
      },
    },
  },
  plugins: [],
};
export default config;
