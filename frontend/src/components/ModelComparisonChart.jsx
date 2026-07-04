import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import { colors, modelColors, modelLabels } from '../theme';
import { EmptyState } from './ForecastChart';

export default function ModelComparisonChart({ accuracy }) {
  const models = accuracy?.models ?? [];
  const chartData = [...models]
    .sort((a, b) => a.mape - b.mape)
    .map((m) => ({ name: modelLabels[m.model_name] ?? m.model_name, mape: Number(m.mape.toFixed(2)), key: m.model_name }));

  return (
    <div className="panel" style={{ padding: 24, height: 380, display: 'flex', flexDirection: 'column' }}>
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 18, fontWeight: 600, color: colors.textHeading }}>MODEL COMPARISON</div>
        <div className="label-caps" style={{ color: colors.textLabel, marginTop: 2 }}>
          BACKTESTED MAPE, 90-DAY HELD-OUT WINDOW
        </div>
      </div>
      {chartData.length === 0 ? (
        <EmptyState text="No backtest results stored yet for this region." />
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 32, bottom: 0, left: 0 }} barCategoryGap="28%">
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fill: colors.textLabel, fontSize: 11, fontFamily: 'JetBrains Mono' }}
              axisLine={false}
              tickLine={false}
              width={150}
            />
            <Bar dataKey="mape" radius={[0, 3, 3, 0]} barSize={26}>
              {chartData.map((d) => (
                <Cell key={d.key} fill={modelColors[d.key] ?? colors.textMuted} />
              ))}
              <LabelList
                dataKey="mape"
                position="right"
                formatter={(v) => `${v}%`}
                style={{ fill: colors.textHeading, fontFamily: 'JetBrains Mono', fontSize: 12, fontWeight: 600 }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
