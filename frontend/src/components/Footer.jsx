import { colors } from '../theme';

export default function Footer({ apiOk, heroLabel, heroColor }) {
  return (
    <footer
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '8px 24px',
        background: colors.footerBg,
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderTop: `1px solid ${colors.hairline}`,
        flexShrink: 0,
      }}
      className="label-caps"
    >
      <div style={{ display: 'flex', gap: 24 }}>
        <span style={{ color: colors.textMuted, fontWeight: 400 }}>
          API:{' '}
          <span style={{ color: apiOk ? colors.green : colors.rose, fontWeight: 700 }}>
            {apiOk ? 'REACHABLE' : 'UNREACHABLE'}
          </span>
        </span>
        <span style={{ color: colors.textMuted, fontWeight: 400 }}>
          GRID STATE: <span style={{ color: heroColor, fontWeight: 700 }}>{heroLabel}</span>
        </span>
      </div>
      <span style={{ color: colors.textMuted, fontWeight: 400 }}>PROMETHEUS GRID MONITORING — PORTFOLIO PROJECT</span>
    </footer>
  );
}
