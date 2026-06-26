import React, { useEffect, useState } from "react";
import PropTypes from "prop-types";
import { CheckCircle2, AlertCircle, Loader2, X } from "lucide-react";
import { Sidebar } from "../components/Sidebar";
import { useThemeContext } from "../context/ThemeContext";

export function DashboardLayout({
  children,
  handleLogout,
  loading, toast,
}) {
  const { isDark, t_bg, t_textHeading, t_textMuted, glassPanel, glassButton } = useThemeContext();

  const [cheatSheetOpen, setCheatSheetOpen] = useState(false);

  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (e.key === "?" || (e.key === "/" && e.shiftKey)) {
        e.preventDefault();
        setCheatSheetOpen(true);
      }
      if (e.key === "Escape" && cheatSheetOpen) {
        setCheatSheetOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cheatSheetOpen]);

  return (
    <div className={`min-h-screen font-sans selection:bg-[#A83AFB]/30 relative overflow-x-hidden transition-colors duration-500 ${t_bg}`}>
      <Sidebar handleLogout={handleLogout} />

      <main className="relative min-h-screen px-4 py-6 sm:px-6 lg:ml-72 lg:px-8 lg:py-8 xl:px-10">
        <div className="mx-auto max-w-[1600px] space-y-6">

        {loading && (
          <div className="fixed top-20 right-6 z-40 flex items-center gap-2 px-4 py-2 rounded-xl bg-[#8B5CF6]/20 border border-[#A83AFB]/30 backdrop-blur-md">
            <Loader2 className="animate-spin text-[#C4B5FD]" size={16} />
            <span className={`text-xs font-medium ${t_textMuted}`}>Syncing data...</span>
          </div>
        )}

        {toast.message && (
          <div role="alert" aria-live="polite" className="fixed bottom-4 left-4 right-4 z-50 sm:bottom-6 sm:left-auto sm:right-6" style={{ animation: "slideInBottom 0.3s ease-out, fadeOut 0.3s ease-in 2.7s forwards" }}>
            <div className={`backdrop-blur-2xl border rounded-2xl px-5 py-3 shadow-2xl flex items-center gap-3
              ${toast.type === "error" ? "bg-rose-500/10 border-rose-500/30 text-rose-500" : "bg-emerald-500/10 border-emerald-500/30 text-emerald-500"}
              ${isDark ? "" : "bg-white/80"}`}>
              {toast.type === "error" ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
              <span className="text-sm font-medium drop-shadow-sm">{toast.message}</span>
            </div>
          </div>
        )}

        {cheatSheetOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setCheatSheetOpen(false)}>
            <div className={`${glassPanel} w-full max-w-sm rounded-2xl p-5`} onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-3">
                <h3 className={`text-lg font-semibold ${t_textHeading}`}>Keyboard Shortcuts</h3>
                <button onClick={() => setCheatSheetOpen(false)} className={`p-1 rounded ${t_textMuted} hover:text-rose-500`}><X size={18}/></button>
              </div>
              <div className="space-y-2 text-sm">
                {[
                  ["/", "Focus search input"],
                  ["Esc", "Close modals / cancel editing"],
                  ["Shift+/", "Show this cheat sheet"],
                ].map(([key, desc]) => (
                  <div key={key} className="flex items-center gap-3">
                    <kbd className="px-2 py-0.5 text-xs font-mono rounded bg-white/10 border border-white/10 text-[#C4B5FD]">{key}</kbd>
                    <span className={t_textMuted}>{desc}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {children}
        </div>
      </main>

    </div>
  );
}

DashboardLayout.propTypes = {
  children: PropTypes.node.isRequired,
  handleLogout: PropTypes.func.isRequired,
  loading: PropTypes.bool.isRequired,
  toast: PropTypes.shape({
    message: PropTypes.string,
    type: PropTypes.string,
  }).isRequired,
};
