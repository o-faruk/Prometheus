// Design tokens transcribed directly from the "Prometheus Grid Ambient" mockup
// (Downloads/Mockup/Prometheus Grid Ambient.dc.html) so the real dashboard matches it exactly.
export const colors = {
  bg: '#141518',
  panel: 'rgba(23,24,28,0.78)',
  panelBorder: 'rgba(201,203,209,0.08)',
  sidebarBg: 'rgba(18,19,22,0.7)',
  headerBg: 'rgba(14,15,18,0.72)',
  footerBg: 'rgba(11,12,14,0.8)',
  hairline: 'rgba(60,73,76,0.25)',

  textPrimary: '#e4e6ea',
  textHeading: '#cdd0d6',
  textLabel: '#b6b9c0',
  textMuted: '#859397',

  cyan: '#8aebff',
  green: '#4edea3',
  amber: '#ffb147',
  amberSoft: '#ffd6a7',
  rose: '#ff5c67',
  roseSoft: '#ffb4ab',

  // Grid status tint, indexed by alert level — drives both the metric card and the
  // ambient WebGL background, so the whole page reflects real current stress state.
  status: {
    normal: { label: 'NOMINAL', color: '#8aebff', dot: '#4edea3', shaderTint: [0.06, 0.42, 0.52] },
    watch: { label: 'ELEVATED', color: '#ffd6a7', dot: '#ffb147', shaderTint: [0.55, 0.36, 0.07] },
    warning: { label: 'CRITICAL', color: '#ffb4ab', dot: '#ff5c67', shaderTint: [0.60, 0.11, 0.15] },
  },
};

// Fuel-type colors for the generation mix panel — chosen to read intuitively
// (yellow=solar, teal=wind, blue=hydro, purple=nuclear) rather than an arbitrary palette.
export const fuelColors = {
  SUN: '#ffd166',
  WND: '#4edea3',
  WAT: '#5aa9e6',
  NUC: '#b48ef0',
  NG: '#8a94a6',
  COL: '#6b5b52',
  GEO: '#ff9f5a',
  OIL: '#5c5f66',
  OTH: '#3c494c',
};

export const modelColors = {
  seasonal_naive_168h: '#859397',
  prophet: '#b48ef0',
  lightgbm: '#8aebff',
  eia_day_ahead_forecast: '#4edea3',
};

export const modelLabels = {
  seasonal_naive_168h: 'NAIVE (168H)',
  prophet: 'PROPHET',
  lightgbm: 'LIGHTGBM',
  eia_day_ahead_forecast: "EIA'S OWN FORECAST",
};

export const fonts = {
  ui: "'Inter', system-ui, sans-serif",
  mono: "'JetBrains Mono', monospace",
};
