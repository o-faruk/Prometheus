import { colors } from '../theme';

// EIA's respondent codes (region_code) aren't the names people actually recognize —
// CAISO/ERCOT are the industry-standard short names, "CISO"/"ERCO" are just EIA's internal keys.
const SHORT_LABELS = { CISO: 'CAISO', ERCO: 'ERCOT', PJM: 'PJM' };

function formatAgo(minutes) {
  if (minutes == null) return '—';
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${Math.round(minutes)}m ago`;
  return `${(minutes / 60).toFixed(1)}h ago`;
}

export default function Header({ regions, activeRegion, onChangeRegion, minutesSinceUpdate }) {
  return (
    <header
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '12px 24px',
        background: colors.headerBg,
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderBottom: `1px solid ${colors.hairline}`,
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 32 }}>
        <span style={{ fontSize: 22, fontWeight: 900, letterSpacing: '-0.03em', color: colors.textPrimary }}>
          PROMETHEUS
        </span>
        <nav style={{ display: 'flex', alignItems: 'center', gap: 24 }} className="label-caps">
          {regions.map((r) => {
            const active = r.region_code === activeRegion;
            return (
              <button
                key={r.region_code}
                onClick={() => onChangeRegion(r.region_code)}
                className="label-caps"
                style={{
                  background: 'none',
                  border: 'none',
                  padding: 0,
                  paddingBottom: 3,
                  color: active ? colors.textHeading : colors.textLabel,
                  borderBottom: active ? `2px solid ${colors.textHeading}` : '2px solid transparent',
                }}
              >
                {SHORT_LABELS[r.region_code] ?? r.region_code}
              </button>
            );
          })}
        </nav>
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          background: 'rgba(28,29,33,0.5)',
          border: `1px solid ${colors.hairline}`,
          borderRadius: 6,
          padding: '6px 12px',
        }}
      >
        <span className="pulse-dot" style={{ background: colors.green }} />
        <span className="label-caps" style={{ color: 'rgba(184,186,192,0.85)' }}>
          LIVE · UPDATED {formatAgo(minutesSinceUpdate).toUpperCase()}
        </span>
      </div>
    </header>
  );
}
