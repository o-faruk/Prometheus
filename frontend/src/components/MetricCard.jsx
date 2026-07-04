import { colors } from '../theme';

export default function MetricCard({ label, value, unit, valueColor, subtext, subtextColor, dotColor }) {
  return (
    <div className="panel" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span className="label-caps" style={{ color: colors.textLabel }}>{label}</span>
        {dotColor && <span className="pulse-dot" style={{ background: dotColor }} />}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ fontSize: 40, fontWeight: 700, letterSpacing: '-0.02em', color: valueColor ?? colors.textHeading }}>
          {value}
        </span>
        {unit && <span className="label-caps" style={{ color: colors.textMuted }}>{unit}</span>}
      </div>
      {subtext && (
        <span className="data-mono" style={{ fontSize: 12, color: subtextColor ?? colors.textMuted }}>
          {subtext}
        </span>
      )}
    </div>
  );
}
