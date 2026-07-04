import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import { colors, fuelColors } from '../theme';
import { EmptyState } from './ForecastChart';

const FUEL_LABELS = {
  SUN: 'SOLAR', WND: 'WIND', WAT: 'HYDRO', NUC: 'NUCLEAR',
  NG: 'NATURAL GAS', COL: 'COAL', GEO: 'GEOTHERMAL', OIL: 'OIL', OTH: 'OTHER',
};

export default function GenerationMixPanel({ generationMix }) {
  const rawFuels = generationMix?.fuels ?? [];
  // EIA occasionally reports small negative generation for solar at night (self-consumption
  // slightly exceeding zero output) — real data, but a pie chart can't render a negative
  // slice, so floor at 0 for display only; the true signed value is still in the API response.
  const hasClipped = rawFuels.some((f) => f.share_pct < 0);
  const fuels = rawFuels.map((f) => ({ ...f, share_pct: Math.max(0, f.share_pct) }));

  return (
    <div className="panel" style={{ padding: 24, height: 388, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 600, color: colors.textPrimary }}>GENERATION MIX</div>
          <div className="label-caps" style={{ color: colors.textLabel, marginTop: 2 }}>
            LATEST HOUR BY FUEL TYPE
          </div>
        </div>
        <span
          className="label-caps"
          style={{ background: 'rgba(78,222,163,0.12)', color: colors.green, border: '1px solid rgba(78,222,163,0.25)', padding: '3px 8px', borderRadius: 3 }}
        >
          LIVE
        </span>
      </div>
      {fuels.length === 0 ? (
        <EmptyState text="No generation-mix data yet." />
      ) : (
        <div style={{ flex: 1, display: 'flex', gap: 8, minHeight: 0 }}>
          <div style={{ width: '55%' }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={fuels}
                  dataKey="share_pct"
                  nameKey="fuel_type"
                  innerRadius="58%"
                  outerRadius="85%"
                  paddingAngle={2}
                  stroke="none"
                >
                  {fuels.map((f) => (
                    <Cell key={f.fuel_type} fill={fuelColors[f.fuel_type] ?? colors.textMuted} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: '#1c1d21', border: `1px solid ${colors.hairline}`, borderRadius: 6 }}
                  itemStyle={{ fontFamily: 'JetBrains Mono', fontSize: 12 }}
                  formatter={(value, _name, entry) => [`${value.toFixed(1)}%`, FUEL_LABELS[entry.payload.fuel_type]]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div style={{ flex: 1, overflowY: 'hidden', display: 'flex', flexDirection: 'column', gap: 8, paddingTop: 4 }}>
            {fuels.map((f) => (
              <div key={f.fuel_type} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: fuelColors[f.fuel_type] ?? colors.textMuted, flexShrink: 0 }} />
                <span className="label-caps" style={{ color: colors.textLabel, flex: 1 }}>{FUEL_LABELS[f.fuel_type] ?? f.fuel_type}</span>
                <span className="data-mono" style={{ fontSize: 12, color: colors.textHeading }}>{f.share_pct.toFixed(1)}%</span>
              </div>
            ))}
            {hasClipped && (
              <div className="data-mono" style={{ fontSize: 10, color: colors.textMuted, marginTop: 4 }}>
                Note: solar reported slightly negative overnight (self-consumption), shown as 0%.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
