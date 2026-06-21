import React from "react";
import { useThemeContext } from "../context/ThemeContext";

export function SkeletonCard() {
  const { isDark } = useThemeContext();
  const base = isDark ? "bg-white/10" : "bg-black/10";
  return (
    <div className={`rounded-2xl p-5 ${isDark ? "bg-white/[0.03] border border-white/5" : "bg-black/[0.03] border border-black/5"}`}>
      <div className={`h-3 w-24 rounded mb-3 ${base} skeleton-shimmer`} />
      <div className={`h-8 w-16 rounded mb-2 ${base} skeleton-shimmer`} />
      <div className={`h-4 w-12 rounded ${base} skeleton-shimmer`} />
    </div>
  );
}

export function SkeletonTableRow({ cols = 4 }) {
  const { isDark } = useThemeContext();
  const base = isDark ? "bg-white/10" : "bg-black/10";
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="p-3">
          <div className={`h-4 rounded w-full max-w-[120px] ${base} skeleton-shimmer`} />
        </td>
      ))}
    </tr>
  );
}

export function SkeletonTable({ rows = 5, cols = 4 }) {
  const { isDark, glassPanel } = useThemeContext();
  const base = isDark ? "bg-white/10" : "bg-black/10";
  return (
    <div className={`rounded-2xl p-5 border ${isDark ? "border-white/5" : "border-black/5"} ${glassPanel}`}>
      <div className="flex items-center justify-between mb-5">
        <div className={`h-6 w-36 rounded ${base} skeleton-shimmer`} />
        <div className="flex gap-2">
          <div className={`h-9 w-24 rounded-lg ${base} skeleton-shimmer`} />
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className={`border-b ${isDark ? "border-white/5" : "border-black/5"}`}>
              {Array.from({ length: cols }).map((_, i) => (
                <th key={i} className="p-3">
                  <div className={`h-4 w-20 rounded ${base} skeleton-shimmer`} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: rows }).map((_, i) => (
              <SkeletonTableRow key={i} cols={cols} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function SkeletonForm() {
  const { isDark, glassPanel } = useThemeContext();
  const base = isDark ? "bg-white/10" : "bg-black/10";
  return (
    <div className={`rounded-2xl p-5 border ${isDark ? "border-white/5" : "border-black/5"} ${glassPanel} space-y-6`}>
      <div className={`h-6 w-48 rounded ${base} skeleton-shimmer mb-2`} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="space-y-2">
            <div className={`h-3 w-20 rounded ${base} skeleton-shimmer`} />
            <div className={`h-10 w-full rounded-lg ${base} skeleton-shimmer`} />
          </div>
        ))}
      </div>
      <div className={`flex justify-end gap-3 pt-4 border-t ${isDark ? "border-white/5" : "border-black/5"}`}>
        <div className={`h-10 w-24 rounded-lg ${base} skeleton-shimmer`} />
        <div className={`h-10 w-32 rounded-lg ${base} skeleton-shimmer`} />
      </div>
    </div>
  );
}

export function SkeletonToggleList() {
  const { isDark, glassPanel } = useThemeContext();
  const base = isDark ? "bg-white/10" : "bg-black/10";
  return (
    <div className={`rounded-2xl p-5 border ${isDark ? "border-white/5" : "border-black/5"} ${glassPanel} space-y-4`}>
      <div className={`h-6 w-32 rounded ${base} skeleton-shimmer mb-2`} />
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className={`flex items-center justify-between p-4 rounded-xl border ${isDark ? "border-white/5 bg-white/[0.01]" : "border-black/5 bg-black/[0.01]"}`}>
          <div className="space-y-2">
            <div className={`h-4 w-28 rounded ${base} skeleton-shimmer`} />
            <div className={`h-3 w-48 rounded ${base} skeleton-shimmer`} />
          </div>
          <div className={`h-6 w-11 rounded-full ${base} skeleton-shimmer`} />
        </div>
      ))}
    </div>
  );
}