import { colors, fonts } from '../theme';

const NAV_ITEMS = ['DASHBOARD', 'ANALYSIS', 'ALERTS', 'DOCS'];

export default function Sidebar({ onExport }) {
  return (
    <aside
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 24,
        width: 248,
        flexShrink: 0,
        padding: 16,
        background: colors.sidebarBg,
        backdropFilter: 'blur(18px)',
        WebkitBackdropFilter: 'blur(18px)',
        borderRight: `1px solid ${colors.hairline}`,
      }}
    >
      <div style={{ padding: '12px 8px 0' }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: colors.textHeading, letterSpacing: '-0.01em' }}>
          GRID OPS
        </div>
        <div className="label-caps" style={{ color: 'rgba(184,186,192,0.6)', marginTop: 4 }}>
          PROMETHEUS
        </div>
      </div>
      <nav style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
        {NAV_ITEMS.map((item) => {
          const active = item === 'DASHBOARD';
          return (
            <div
              key={item}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '9px 14px',
                borderRadius: 6,
                background: active ? '#d2d5db' : 'transparent',
                color: active ? '#17181c' : colors.textLabel,
                fontWeight: active ? 700 : 400,
                opacity: active ? 1 : 0.55,
              }}
            >
              <span
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: 3,
                  border: '2px solid currentColor',
                  display: 'inline-block',
                }}
              />
              <span className="label-caps">{item}</span>
            </div>
          );
        })}
      </nav>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, borderTop: `1px solid ${colors.hairline}`, paddingTop: 20 }}>
        <button
          onClick={onExport}
          className="label-caps"
          style={{
            width: '100%',
            padding: 11,
            background: '#cdd0d6',
            color: '#17181c',
            border: 'none',
            borderRadius: 6,
            fontFamily: fonts.mono,
          }}
        >
          EXPORT DATA
        </button>
      </div>
    </aside>
  );
}
