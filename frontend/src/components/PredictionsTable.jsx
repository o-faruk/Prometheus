import { colors } from '../theme';
import { EmptyState } from './ForecastChart';
import { formatDateTime } from '../formatTime';

const COLUMNS = '1.6fr 1fr 1fr 1fr';

export default function PredictionsTable({ predictionsHistory, timezone }) {
  const points = predictionsHistory?.points ?? [];

  return (
    <div className="panel" style={{ overflow: 'hidden' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '14px 24px',
          borderBottom: `1px solid ${colors.hairline}`,
        }}
      >
        <span className="label-caps" style={{ color: colors.textPrimary }}>PREDICTIONS VS. OUTCOMES</span>
        <span className="label-caps" style={{ color: colors.textMuted }}>DAY-AHEAD FORECASTS, MOST RECENT FIRST</span>
      </div>
      {points.length === 0 ? (
        <div style={{ padding: 24 }}>
          <EmptyState text="No resolved forecasts yet — check back after the scheduler has run for a few hours." />
        </div>
      ) : (
        <>
          <div
            className="label-caps"
            style={{
              display: 'grid',
              gridTemplateColumns: COLUMNS,
              color: colors.textMuted,
              background: 'rgba(31,32,36,0.5)',
              padding: '10px 24px',
            }}
          >
            <span>TARGET TIME</span>
            <span>PREDICTED</span>
            <span>ACTUAL</span>
            <span style={{ textAlign: 'right' }}>ERROR</span>
          </div>
          <div className="prom-scroll" style={{ maxHeight: 320, overflowY: 'auto' }}>
            {[...points].reverse().map((p) => {
              const error = ((p.predicted_demand_mwh - p.actual_demand_mwh) / p.actual_demand_mwh) * 100;
              const errorColor = Math.abs(error) > 10 ? colors.rose : Math.abs(error) > 5 ? colors.amber : colors.green;
              return (
                <div
                  key={p.target_time}
                  className="data-mono"
                  style={{
                    display: 'grid',
                    gridTemplateColumns: COLUMNS,
                    alignItems: 'center',
                    fontSize: 12,
                    color: colors.textLabel,
                    padding: '12px 24px',
                    borderBottom: '1px solid rgba(60,73,76,0.12)',
                  }}
                >
                  <span style={{ color: colors.textPrimary }}>
                    {formatDateTime(p.target_time, timezone)}
                  </span>
                  <span>{Math.round(p.predicted_demand_mwh).toLocaleString()} MWh</span>
                  <span>{Math.round(p.actual_demand_mwh).toLocaleString()} MWh</span>
                  <span style={{ textAlign: 'right', color: errorColor }}>
                    {error > 0 ? '+' : ''}{error.toFixed(1)}%
                  </span>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
