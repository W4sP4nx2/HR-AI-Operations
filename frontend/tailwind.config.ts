import type { Config } from "tailwindcss";

/**
 * Tailwind configuration with the HR Command Center brand palette.
 * Brand colours: deep purple (#5D1C6A), magenta (#CA5995),
 * peach (#FFB090), cream (#FFF1D3).
 */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./app/components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          purple: "#5D1C6A",
          magenta: "#CA5995",
          peach: "#FFB090",
          cream: "#FFF1D3",
        },
        ink: {
          900: "#1b0a20",
          800: "#2a0f32",
          700: "#3a1545",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      keyframes: {
        pulseGreen: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(34,197,94,0.7)" },
          "50%": { boxShadow: "0 0 0 6px rgba(34,197,94,0)" },
        },
      },
      animation: {
        pulseGreen: "pulseGreen 1.5s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
