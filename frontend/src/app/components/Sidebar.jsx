import React, { useEffect, useState } from "react";
import PropTypes from "prop-types";
import { Link, NavLink, useLocation } from "react-router-dom";
import {
  LogOut,
  Menu,
  Moon,
  Sun,
  X,
} from "lucide-react";
import { useThemeContext } from "../context/ThemeContext";
import { getNavigationItem, NAV_SECTIONS } from "../navigation";

function navItemClass({ active, isDark }) {
  if (active) {
    return isDark
      ? "bg-[#8B5CF6]/15 text-violet-100 border-[#A83AFB]/30 shadow-[0_0_20px_rgba(168,58,251,0.16)]"
      : "bg-[#8B5CF6]/10 text-[#5b21b6] border-[#A83AFB]/20 shadow-sm";
  }
  return isDark
    ? "border-transparent text-slate-300 hover:bg-white/[0.04] hover:text-[#FF5FB8]"
    : "border-transparent text-slate-600 hover:bg-white/70 hover:text-[#8B5CF6]";
}

function SidebarNavItems({ onNavigate }) {
  const { isDark } = useThemeContext();

  return (
    <div className="space-y-5">
      {NAV_SECTIONS.map((section) => (
        <div key={section.label}>
          <div className="px-3 pb-2 text-[10px] font-black uppercase tracking-[0.12em] text-slate-500">
            {section.label}
          </div>
          <div className="space-y-1">
            {section.items.map(({ path, label, icon: Icon }) => (
              <NavLink
                key={path}
                to={path}
                onClick={onNavigate}
                className={({ isActive }) => [
                  "group flex items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-semibold transition-all",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#A83AFB]/50",
                  navItemClass({ active: isActive, isDark }),
                ].join(" ")}
              >
                <Icon size={17} className="shrink-0" />
                <span className="truncate">{label}</span>
              </NavLink>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

SidebarNavItems.propTypes = {
  onNavigate: PropTypes.func,
};

function BrandBlock() {
  const { isDark, t_textMuted } = useThemeContext();

  return (
    <Link to="/dashboard" className="flex min-w-0 flex-col items-start gap-1 px-2 py-1" aria-label="EazyFill Console home">
      <img
        src={isDark ? "/brand/dashboard-sidebar-logo-light.png" : "/brand/dashboard-sidebar-logo-dark.png"}
        alt="EazyFill Console"
        className="h-[72px] w-[240px] shrink-0 object-contain object-left"
      />
      <span className={`truncate text-[10px] font-bold uppercase tracking-[0.12em] ${t_textMuted}`}>Extension Operations</span>
    </Link>
  );
}

function SidebarControls({ handleLogout }) {
  const { isDark, toggleDark, t_textMuted } = useThemeContext();

  return (
    <div className={`mt-auto flex items-center justify-between border-t px-2 pt-4 ${isDark ? "border-white/[0.06]" : "border-black/[0.06]"}`}>
      <button
        type="button"
        onClick={toggleDark}
        className={`rounded-xl border p-2.5 transition-all ${
          isDark
            ? "border-white/10 bg-white/[0.04] text-amber-300 hover:bg-white/[0.08]"
            : "border-slate-200 bg-white/70 text-slate-700 hover:bg-white"
        }`}
        title="Toggle theme"
        aria-label="Toggle dark/light theme"
      >
        {isDark ? <Sun size={18} /> : <Moon size={18} />}
      </button>
      <button
        type="button"
        onClick={handleLogout}
        className={`rounded-xl p-2.5 transition-all ${t_textMuted} hover:bg-rose-500/10 hover:text-rose-500`}
        title="Logout"
        aria-label="Logout"
      >
        <LogOut size={18} />
      </button>
    </div>
  );
}

SidebarControls.propTypes = {
  handleLogout: PropTypes.func.isRequired,
};

export function Sidebar({ handleLogout }) {
  const { isDark, glassNav, glassPanel, t_textHeading, t_textMuted } = useThemeContext();
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const currentItem = getNavigationItem(location.pathname);

  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    document.body.style.overflow = mobileMenuOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileMenuOpen]);

  return (
    <>
      <aside className={`fixed left-0 top-0 z-50 hidden h-screen w-72 flex-col border-r px-4 py-5 lg:flex ${glassNav} ${isDark ? "border-white/[0.06]" : "border-white/70"}`}>
        <BrandBlock />
        <div className={`mt-5 rounded-2xl border p-3 ${isDark ? "border-white/[0.06] bg-white/[0.03]" : "border-white/70 bg-white/50"}`}>
          <div className={`text-[11px] font-black uppercase tracking-[0.12em] ${t_textMuted}`}>Current View</div>
          <div className={`mt-1 truncate text-sm font-bold ${t_textHeading}`}>{currentItem.label}</div>
        </div>
        <nav className="mt-6 min-h-0 flex-1 overflow-y-auto pr-1 custom-scrollbar" aria-label="Admin sections">
          <SidebarNavItems />
        </nav>
        <SidebarControls handleLogout={handleLogout} />
      </aside>

      <nav className={`sticky top-0 z-40 lg:hidden ${glassNav}`}>
        <div className="flex h-16 items-center justify-between px-4">
          <BrandBlock />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setMobileMenuOpen(true)}
              className={`rounded-xl border p-2 ${isDark ? "border-white/10 text-slate-200" : "border-slate-200 text-slate-700"}`}
              aria-label="Open navigation menu"
              aria-expanded={mobileMenuOpen}
            >
              <Menu size={20} />
            </button>
          </div>
        </div>
      </nav>

      {mobileMenuOpen && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm lg:hidden"
            onClick={() => setMobileMenuOpen(false)}
            aria-label="Close navigation backdrop"
          />
          <div
            className={`fixed left-0 top-0 z-[60] h-full w-[min(20rem,86vw)] overflow-y-auto border-r p-4 lg:hidden ${glassPanel}`}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation menu"
          >
            <div className="mb-5 flex items-center justify-between">
              <BrandBlock />
              <button
                type="button"
                onClick={() => setMobileMenuOpen(false)}
                className={`rounded-xl p-2 ${t_textMuted} hover:text-rose-500`}
                aria-label="Close navigation menu"
              >
                <X size={20} />
              </button>
            </div>
            <SidebarNavItems onNavigate={() => setMobileMenuOpen(false)} />
            <SidebarControls handleLogout={handleLogout} />
          </div>
        </>
      )}
    </>
  );
}

Sidebar.propTypes = {
  handleLogout: PropTypes.func.isRequired,
};
