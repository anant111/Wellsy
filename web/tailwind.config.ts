import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0b0c",
        panel: "#15151a",
        border: "#26262e",
        muted: "#8a8a96",
        accent: "#6366f1",
      },
    },
  },
  plugins: [],
} satisfies Config;
