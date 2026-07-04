import MetricCard from './MetricCard';
import { colors } from '../theme';
import { formatTime } from '../formatTime';

function worstLevel(alerts) {
  if (!alerts?.alerts?.length) return 'normal';
  return alerts.alerts.some((a) => a.level === 'warning')
    ? 'warning'
    : alerts.alerts.some((a) => a.level === 'watch')
      ? 'watch'
      : 'normal';
}

export default function MetricsRow({ current, generationMix, alerts, timezone }) {
  const level = worstLevel(alerts);
  const status = colors.status[level];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 20, marginBottom: 20 }}>
      <MetricCard
        label="TOTAL LOAD"
        value={current ? (current.demand_mwh / 1000).toFixed(1) : '—'}
        unit="GW"
        dotColor={colors.green}
        subtext={current ? `AS OF ${formatTime(current.time, timezone)} LOCAL` : ''}
      />
      <MetricCard
        label="RENEWABLE GEN"
        value={generationMix ? generationMix.renewable_share_pct.toFixed(1) : '—'}
        unit="%"
        valueColor={colors.green}
        dotColor={colors.green}
        subtext={generationMix ? `${(generationMix.total_mwh / 1000).toFixed(1)} GW TOTAL GENERATION` : ''}
      />
      <MetricCard
        label="GRID STATUS"
        value={status.label}
        valueColor={status.color}
        dotColor={status.dot}
        subtext={
          level === 'normal'
            ? 'NO ACTIVE STRESS ALERTS'
            : `${alerts.alerts.length} ACTIVE ALERT${alerts.alerts.length > 1 ? 'S' : ''} NEXT 24H`
        }
        subtextColor={status.color}
      />
      <MetricCard
        label="TEMPERATURE"
        value={current?.temperature_c != null ? current.temperature_c.toFixed(0) : '—'}
        unit="°C"
        dotColor={colors.amber}
        subtext={current?.temperature_c != null ? `${(current.temperature_c * 9 / 5 + 32).toFixed(0)}°F` : ''}
      />
    </div>
  );
}
