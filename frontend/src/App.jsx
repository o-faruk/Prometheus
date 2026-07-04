import { useEffect, useState } from 'react';
import { api } from './api';
import { useDashboardData } from './hooks/useDashboardData';
import GridAmbientBackground from './components/GridAmbientBackground';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import Footer from './components/Footer';
import MetricsRow from './components/MetricsRow';
import ForecastChart from './components/ForecastChart';
import GenerationMixPanel from './components/GenerationMixPanel';
import ModelComparisonChart from './components/ModelComparisonChart';
import AlertPanel from './components/AlertPanel';
import PredictionsTable from './components/PredictionsTable';
import { colors } from './theme';

function worstLevel(alerts) {
  if (!alerts?.alerts?.length) return 'normal';
  return alerts.alerts.some((a) => a.level === 'warning')
    ? 'warning'
    : alerts.alerts.some((a) => a.level === 'watch')
      ? 'watch'
      : 'normal';
}

function downloadCsv(points) {
  if (!points?.length) return;
  const header = 'target_time,predicted_demand_mwh,actual_demand_mwh\n';
  const rows = points.map((p) => `${p.target_time},${p.predicted_demand_mwh},${p.actual_demand_mwh}`).join('\n');
  const blob = new Blob([header + rows], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'prometheus-predictions.csv';
  a.click();
  URL.revokeObjectURL(url);
}

export default function App() {
  const [regions, setRegions] = useState([]);
  const [activeRegion, setActiveRegion] = useState(null);

  useEffect(() => {
    api.regions().then((list) => {
      setRegions(list);
      setActiveRegion((prev) => prev ?? list[0]?.region_code);
    });
  }, []);

  const data = useDashboardData(activeRegion);
  const level = worstLevel(data.alerts);
  const status = colors.status[level];
  const timezone = regions.find((r) => r.region_code === activeRegion)?.timezone;

  return (
    <div style={{ position: 'relative', width: '100%', height: '100vh', overflow: 'hidden', background: colors.bg }}>
      <GridAmbientBackground level={level} />

      <div style={{ position: 'relative', zIndex: 10, display: 'flex', height: '100vh', width: '100%', overflow: 'hidden' }}>
        <Sidebar onExport={() => downloadCsv(data.predictionsHistory?.points)} />

        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, height: '100vh', overflow: 'hidden' }}>
          <Header
            regions={regions}
            activeRegion={activeRegion}
            onChangeRegion={setActiveRegion}
            minutesSinceUpdate={data.current?.minutes_since_update}
          />

          <div className="prom-scroll" style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
            <MetricsRow current={data.current} generationMix={data.generationMix} alerts={data.alerts} timezone={timezone} />

            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 20, marginBottom: 20 }}>
              <ForecastChart forecast={data.forecast} timezone={timezone} />
              <GenerationMixPanel generationMix={data.generationMix} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>
              <ModelComparisonChart accuracy={data.accuracy} />
              <AlertPanel alerts={data.alerts} timezone={timezone} />
            </div>

            <PredictionsTable predictionsHistory={data.predictionsHistory} timezone={timezone} />
          </div>

          <Footer apiOk={!data.error} heroLabel={status.label} heroColor={status.color} />
        </main>
      </div>
    </div>
  );
}
