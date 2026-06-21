/** useTheme — all glassmorphism CSS class strings derived from isDark flag. */
export function useTheme(isDark) {
  return {
    t_bg:          isDark ? "bg-[#08020F] text-slate-200" : "bg-[#F8F7FC] text-slate-800",
    t_textHeading: isDark ? "text-white"      : "text-slate-900",
    t_textMuted:   isDark ? "text-slate-300"  : "text-slate-500",
    t_rowHover:    isDark ? "hover:bg-white/[0.03]" : "hover:bg-white/50",
    t_borderLight: isDark ? "border-white/[0.05]"   : "border-black/[0.05]",
    glassPanel:  isDark
      ? "bg-white/[0.02] backdrop-blur-2xl border border-white/[0.05] shadow-[0_8px_32px_0_rgba(0,0,0,0.3)]"
      : "bg-white/40 backdrop-blur-2xl border border-white/60 shadow-[0_8px_32px_0_rgba(31,38,135,0.07)]",
    glassNav: isDark
      ? "bg-[#020617]/40 backdrop-blur-3xl border-b border-white/[0.05]"
      : "bg-white/40 backdrop-blur-3xl border-b border-white/60 shadow-sm",
    glassInput: [
      "w-full rounded-xl px-4 py-2.5 text-sm focus:ring-2 focus:ring-[#A83AFB]/50 focus:outline-none transition-all backdrop-blur-md",
      isDark
        ? "bg-black/20 border border-white/10 text-white placeholder-slate-500 focus:bg-black/40 shadow-inner"
        : "bg-white/50 border border-white/60 text-slate-900 placeholder-slate-400 focus:bg-white/80 shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)]"
    ].join(" "),
    glassButton: [
      "rounded-xl px-4 py-2 text-sm font-medium transition-all backdrop-blur-md flex items-center justify-center gap-2",
      isDark
        ? "bg-white/[0.05] hover:bg-white/[0.1] border border-white/10 text-slate-300 hover:text-white"
        : "bg-white/60 hover:bg-white border border-white/80 text-slate-700 hover:text-[#8B5CF6] shadow-sm"
    ].join(" "),
    solidButton: [
      "bg-[#8B5CF6] hover:bg-[#A83AFB] text-white transition-all rounded-xl px-5 py-2.5 font-medium text-sm flex items-center justify-center gap-2",
      isDark
        ? "shadow-[0_0_20px_rgba(168,58,251,0.32)] hover:shadow-[0_0_30px_rgba(240,64,200,0.42)]"
        : "shadow-lg shadow-[#A83AFB]/25"
    ].join(" "),
    dangerButton: [
      "border rounded-lg px-3 py-1.5 text-xs font-medium transition-all backdrop-blur-md",
      isDark ? "bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border-rose-500/20"
             : "bg-rose-100/50 hover:bg-rose-100 text-rose-600 border-rose-200"
    ].join(" "),
    iconBtn: (color) => {
      const colors = {
        success: isDark ? "bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30" : "bg-emerald-100/50 text-emerald-600 hover:bg-emerald-100",
        danger:  isDark ? "bg-rose-500/20 text-rose-400 hover:bg-rose-500/30"   : "bg-rose-100/50 text-rose-600 hover:bg-rose-100",
        edit:    isDark ? "bg-[#8B5CF6]/10 text-[#C4B5FD] hover:bg-[#8B5CF6]/20" : "bg-[#8B5CF6]/10 text-[#6d28d9] hover:bg-[#8B5CF6]/15",
        ghost:   isDark ? "bg-white/5 text-slate-400 hover:bg-white/10"         : "bg-black/5 text-slate-500 hover:bg-black/10",
      };
      return `p-1.5 rounded cursor-pointer transition-colors ${colors[color] || colors.ghost}`;
    },
    smallGlassInput: [
      "px-2 py-1 rounded-lg text-xs outline-none border transition-all",
      isDark ? "bg-black/30 border-white/10 text-slate-200 focus:border-[#A83AFB]/50" : "bg-white/80 border-slate-200 text-slate-700 focus:border-[#A83AFB]/50"
    ].join(" "),
    tabButton: (active) =>
      `px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors cursor-pointer ${
        active
          ? (isDark ? "bg-[#8B5CF6]/20 text-[#C4B5FD] border border-[#A83AFB]/30" : "bg-[#8B5CF6]/10 text-[#6d28d9] border border-[#A83AFB]/20")
          : `${isDark ? "text-slate-400 hover:text-[#FF5FB8]" : "text-slate-500 hover:text-[#8B5CF6]"}`
      }`,
    viewSwitcherBtn: (active) =>
      `flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold transition-all cursor-pointer border-b-2 ${
        active
          ? "border-[#A83AFB] text-[#A83AFB]"
          : `border-transparent ${isDark ? "text-slate-400 hover:text-[#FF5FB8]" : "text-slate-500 hover:text-[#8B5CF6]"}`
      }`,
    badgeSuccess: [
      "px-2.5 py-1 rounded-md text-[10px] uppercase tracking-wider font-semibold border backdrop-blur-md",
      isDark ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
             : "bg-emerald-100/50 text-emerald-700 border-emerald-200"
    ].join(" "),
    badgeWarning: [
      "px-2.5 py-1 rounded-md text-[10px] uppercase tracking-wider font-semibold border backdrop-blur-md",
      isDark ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
             : "bg-amber-100/50 text-amber-700 border-amber-200"
    ].join(" "),
  };
}
