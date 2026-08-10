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
        // Parley palette. Teal primary: 5.06:1 on white, so white button
        // text clears WCAG AA. Neutrals warmed off the old blue-purple cast.
        parley: {
          brand: "#0E7C74",
          brandhover: "#0A625B",
          accent: "#E8833A", // also the warm entry in the avatar palettes
          tint: "#E6F4F2",
          ink: "#1C2624",
          muted: "#5A6866",
          subtle: "#8A9694",
          line: "#E4E9E8",
          field: "#F5F8F7",
          dark: "#161D1C",
          darker: "#0B100F",
          panel: "#202927",
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
