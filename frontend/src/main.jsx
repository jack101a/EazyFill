import React, { useState, useEffect } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./app/App";
import { ThemeProvider } from "./app/context/ThemeContext";
import "./styles/globals.css";

const THEME_KEY = "eazyfill_admin_theme";
const LEGACY_THEME_KEYS = ["ta_ta_admin_theme", ["ta", "ta_admin_theme"].join("")];
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function Root() {
  const [isDark, setIsDark] = useState(() => {
    try {
      const stored = localStorage.getItem(THEME_KEY)
        ?? LEGACY_THEME_KEYS.map((key) => localStorage.getItem(key)).find((value) => value !== null);
      return stored !== "light";
    } catch { return true; }
  });

  useEffect(() => {
    try {
      localStorage.setItem(THEME_KEY, isDark ? "dark" : "light");
      for (const key of LEGACY_THEME_KEYS) localStorage.removeItem(key);
    } catch {}
  }, [isDark]);

  return (
    <ThemeProvider isDark={isDark} setIsDark={setIsDark}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename="/admin">
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
