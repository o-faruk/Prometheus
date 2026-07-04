import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { colors } from '../theme';
import { formatTime } from '../formatTime';

export default function ForecastChart({ forecast, timezone }) {
  const points = forecast?.points ?? [];
  const chartData = points.map((p) => ({
    time: formatTime(p.target_time, timezone),
    predicted: Math.round(p.predicted_demand_mwh),
    actual: p.actual_demand_mwh != null ? Math.round(p.actual_demand_mwh) : null,
  }));

  return (
    <div className="panel" style={{ padding: 24, height: 388, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 600, color: colors.textHeading }}>LOAD FORECAST: LIGHTGBM</div>
          <div className="label-caps" style={{ color: colors.textLabel, marginTop: 2 }}>
            NEXT 24 HOUR PREDICTION
          </div>
        </div>
        <div style={{ display: 'flex', gap: 16 }}>
          <LegendSwatch color={colors.textMuted} dashed label="ACTUAL" />
          <LegendSwatch color={colors.cyan} label="LIGHTGBM" />
        </div>
      </div>
      <div style={{ flex: 1 }}>
        {chartData.length === 0 ? (
          <EmptyState text="No forecast scored yet for this region." />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="rgba(201,203,209,0.06)" vertical={false} />
              <XAxis
                dataKey="time"
                tick={{ fill: colors.textMuted, fontSize: 11, fontFamily: 'JetBrains Mono' }}
                axisLine={{ stroke: 'rgba(60,73,76,0.3)' }}
                tickLine={false}
                interval={2}
              />
              <YAxis
                tick={{ fill: colors.textMuted, fontSize: 11, fontFamily: 'JetBrains Mono' }}
                axisLine={false}
                tickLine={false}
                width={48}
                tickFormatter={(v) => `${Math.round(v / 1000)}k`}
              />
              <Tooltip
                contentStyle={{ background: '#1c1d21', border: `1px solid ${colors.hairline}`, borderRadius: 6 }}
                labelStyle={{ color: colors.textLabel, fontFamily: 'JetBrains Mono', fontSize: 11 }}
                itemStyle={{ fontFamily: 'JetBrains Mono', fontSize: 12 }}
                formatter={(value) => `${value.toLocaleString()} MWh`}
              />
              <Line
                type="monotone"
                dataKey="actual"
                stroke={colors.textMuted}
                strokeWidth={1.5}
                strokeDasharray="6 4"
                dot={false}
                connectNulls={false}
              />
              <Line type="monotone" dataKey="predicted" stroke={colors.cyan} strokeWidth={2.5} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

function LegendSwatch({ color, label, dashed }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 14, height: dashed ? 0 : 3, borderTop: dashed ? `1.5px dashed ${color}` : 'none', background: dashed ? 'none' : color }} />
      <span className="label-caps" style={{ color }}>{label}</span>
    </div>
  );
}

export function EmptyState({ text }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: colors.textMuted }} className="data-mono">
      {text}
    </div>
  );
}
