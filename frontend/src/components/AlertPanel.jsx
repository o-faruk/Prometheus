import { colors } from '../theme';
import { formatDateTime } from '../formatTime';

const LEVEL_STYLE = {
  warning: { bg: 'rgba(255,92,103,0.12)', fg: colors.roseSoft, border: 'rgba(255,180,171,0.25)' },
  watch: { bg: 'rgba(255,177,71,0.14)', fg: colors.amberSoft, border: 'rgba(255,177,71,0.25)' },
};

export default function AlertPanel({ alerts, timezone }) {
  const list = alerts?.alerts ?? [];

  return (
    <div className="panel" style={{ padding: 24, height: 380, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 600, color: colors.textHeading }}>ACTIVE ALERTS</div>
          <div className="label-caps" style={{ color: colors.textLabel, marginTop: 2 }}>
            NEXT 24H, STRESS RELATIVE TO HISTORICAL DEMAND
          </div>
        </div>
        {list.length > 0 && (
          <span className="label-caps" style={{ color: colors.rose }}>{list.length} ACTIVE</span>
        )}
      </div>
      <div className="prom-scroll" style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {list.length === 0 ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: colors.green }} className="data-mono">
            No active alerts — all clear for the next 24h.
          </div>
        ) : (
          list.map((alert) => {
            const style = LEVEL_STYLE[alert.level] ?? LEVEL_STYLE.watch;
            return (
              <div
                key={alert.target_time}
                style={{ padding: 12, borderRadius: 4, background: 'rgba(255,255,255,0.02)', border: `1px solid ${colors.hairline}` }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <span
                    className="label-caps"
                    style={{ background: style.bg, color: style.fg, border: `1px solid ${style.border}`, padding: '2px 8px', borderRadius: 3 }}
                  >
                    {alert.level.toUpperCase()}
                  </span>
                  <span className="data-mono" style={{ fontSize: 11, color: colors.textMuted }}>
                    {formatDateTime(alert.target_time, timezone)}
                  </span>
                </div>
                <div style={{ fontSize: 13, lineHeight: 1.5, color: colors.textLabel }}>{alert.explanation}</div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
