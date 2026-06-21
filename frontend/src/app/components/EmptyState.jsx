import React from "react";
import PropTypes from "prop-types";
import { useThemeContext } from "../context/ThemeContext";

function EmptyStateContent({ icon: Icon, title, description }) {
  const { t_textMuted, t_textHeading, isDark } = useThemeContext();
  return (
    <div className="flex flex-col items-center gap-4">
      {Icon && <div className={`p-4 rounded-2xl border ${isDark ? 'bg-white/[0.03] border-white/[0.05]' : 'bg-black/[0.02] border-black/[0.05]'}`}>
        <Icon size={36} className={t_textMuted} />
      </div>}
      <p className={`text-sm font-semibold ${t_textHeading}`}>{title}</p>
      {description && <p className={`text-xs ${t_textMuted} max-w-sm`}>{description}</p>}
    </div>
  );
}

export function EmptyState({ icon, title, description, colSpan = 99, asRow = false }) {
  if (asRow) {
    return (
      <tr>
        <td colSpan={colSpan} className="py-16 text-center">
          <EmptyStateContent icon={icon} title={title} description={description} />
        </td>
      </tr>
    );
  }

  return (
    <div className="py-16 text-center">
      <EmptyStateContent icon={icon} title={title} description={description} />
    </div>
  );
}

EmptyStateContent.propTypes = {
  icon: PropTypes.elementType,
  title: PropTypes.string.isRequired,
  description: PropTypes.string,
};

EmptyState.propTypes = {
  icon: PropTypes.elementType,
  title: PropTypes.string.isRequired,
  description: PropTypes.string,
  colSpan: PropTypes.number,
  asRow: PropTypes.bool,
};
