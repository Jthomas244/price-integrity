import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#15171F",
        paper: "#F6F7F9",
        card: "#FFFFFF",
        line: "#E4E5EA",
        muted: "#6B7280",
        accent: "#0E7C66",      // the auditor's colour: calm, certain
        accentDark: "#0A5F4E",
        high: "#B42318",
        moderate: "#B54708",
        low: "#7A5C00",
        lawful: "#027A48",
        ghost: "#FF2D6E",       // GhostCart's accent, used only when pointing at GhostCart
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
    },
  },
  plugins: [],
};
export default config;
