/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Match extension CSS custom property palette for cross-surface consistency
        brand: {
          primary: "#6366f1",  // indigo-500
          accent:  "#8b5cf6",  // violet-500
          success: "#10b981",  // emerald-500
          danger:  "#f43f5e",  // rose-500
          warning: "#f59e0b",  // amber-500
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
      },
      animation: {
        blob:  "blob 15s infinite alternate",
        "blob-delay-2": "blob 15s 2s infinite alternate",
        "blob-delay-4": "blob 15s 4s infinite alternate",
        shimmer: "shimmer 1.5s infinite",
        "fade-in": "fadeIn 0.3s ease-out",
        "slide-in-bottom": "slideInBottom 0.3s ease-out",
      },
      keyframes: {
        blob: {
          "0%":   { transform: "translate(0,0) scale(1)" },
          "33%":  { transform: "translate(30px,-50px) scale(1.1)" },
          "66%":  { transform: "translate(-20px,20px) scale(0.9)" },
          "100%": { transform: "translate(0,0) scale(1)" },
        },
        shimmer: {
          "0%":   { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition:  "200% 0" },
        },
        fadeIn: {
          from: { opacity: "0", transform: "translateY(5px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        slideInBottom: {
          from: { transform: "translateY(20px)", opacity: "0" },
          to:   { transform: "translateY(0)",    opacity: "1" },
        },
      },
      backdropBlur: {
        xs: "2px",
      },
    },
  },
  plugins: [],
};
