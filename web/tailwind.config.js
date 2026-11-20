/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { 50: "#e8f0fe", 100: "#d2e3fc", 500: "#4285f4", 600: "#1a73e8", 700: "#1967d2" },
        ok: { 50: "#e6f4ea", 500: "#34a853", 700: "#188038" },
        warn: { 50: "#fef7e0", 500: "#f9ab00", 700: "#b06000" },
        bad: { 50: "#fce8e6", 500: "#ea4335", 700: "#c5221f" },
        ink: { 900: "#1f2937", 700: "#374151", 500: "#6b7280", 300: "#cbd5e1", 100: "#eef2f7" },
        surface: "#f6f8fc",
      },
      boxShadow: { card: "0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.06)", pop: "0 12px 32px rgba(16,24,40,.16)" },
      fontFamily: { sans: ['"Google Sans"', "Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"] },
    },
  },
  plugins: [],
};
