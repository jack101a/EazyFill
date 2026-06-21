import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import PropTypes from "prop-types";
import { AlertTriangle, X } from "lucide-react";
import { useThemeContext } from "../context/ThemeContext";

const ConfirmContext = createContext(null);

const DEFAULT_CONFIRM = {
  title: "Confirm action",
  message: "Are you sure you want to continue?",
  details: [],
  confirmLabel: "Confirm",
  cancelLabel: "Cancel",
  tone: "danger",
};

export function ConfirmProvider({ children }) {
  const { isDark, t_textHeading, t_textMuted, t_borderLight, glassPanel, glassButton } = useThemeContext();
  const [dialog, setDialog] = useState(null);

  const confirm = useCallback((options = {}) => new Promise((resolve) => {
    setDialog({
      ...DEFAULT_CONFIRM,
      ...options,
      resolve,
    });
  }), []);

  const close = useCallback((result) => {
    setDialog((current) => {
      if (current?.resolve) current.resolve(result);
      return null;
    });
  }, []);

  const value = useMemo(() => ({ confirm }), [confirm]);
  const toneClass = dialog?.tone === "warning"
    ? "bg-amber-500/15 text-amber-400 border-amber-500/30"
    : "bg-rose-500/15 text-rose-400 border-rose-500/30";

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      {dialog && (
        <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/60 p-3 sm:items-center" role="dialog" aria-modal="true">
          <div className={`${glassPanel} w-full max-w-lg rounded-2xl border ${t_borderLight} shadow-2xl`}>
            <div className={`flex items-start gap-3 border-b p-4 ${t_borderLight}`}>
              <div className={`mt-0.5 rounded-xl border p-2 ${toneClass}`}>
                <AlertTriangle size={18} />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className={`text-base font-semibold ${t_textHeading}`}>{dialog.title}</h3>
                <p className={`mt-1 text-sm leading-relaxed ${t_textMuted}`}>{dialog.message}</p>
              </div>
              <button
                type="button"
                onClick={() => close(false)}
                className={`rounded-lg p-1 transition-colors ${t_textMuted} hover:text-rose-400`}
                aria-label="Close confirmation dialog"
              >
                <X size={18} />
              </button>
            </div>

            {dialog.details?.length > 0 && (
              <div className={`mx-4 mt-4 rounded-xl border p-3 text-xs ${t_borderLight} ${isDark ? "bg-black/20" : "bg-white/70"}`}>
                <ul className={`space-y-1 ${t_textMuted}`}>
                  {dialog.details.map((detail, index) => (
                    <li key={`${detail}-${index}`}>{detail}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex flex-col-reverse gap-2 p-4 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => close(false)} className={`${glassButton} justify-center`}>
                {dialog.cancelLabel}
              </button>
              <button
                type="button"
                onClick={() => close(true)}
                className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white transition-colors ${
                  dialog.tone === "warning" ? "bg-amber-600 hover:bg-amber-500" : "bg-rose-600 hover:bg-rose-500"
                }`}
              >
                {dialog.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}

ConfirmProvider.propTypes = {
  children: PropTypes.node.isRequired,
};

export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within ConfirmProvider");
  return ctx.confirm;
}
