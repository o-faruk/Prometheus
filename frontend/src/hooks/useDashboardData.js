import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';

const POLL_MS = 60_000;

export function useDashboardData(regionCode) {
  const [data, setData] = useState({
    current: null,
    generationMix: null,
    forecast: null,
    accuracy: null,
    alerts: null,
    predictionsHistory: null,
    loading: true,
    error: null,
  });

  const refresh = useCallback(async () => {
    if (!regionCode) return;
    try {
      const [current, generationMix, forecast, accuracy, alerts, predictionsHistory] = await Promise.all([
        api.current(regionCode),
        api.generationMix(regionCode).catch(() => null),
        api.forecast(regionCode).catch(() => null),
        api.accuracy(regionCode),
        api.alerts(regionCode),
        api.predictionsHistory(regionCode).catch(() => ({ points: [] })),
      ]);
      setData({ current, generationMix, forecast, accuracy, alerts, predictionsHistory, loading: false, error: null });
    } catch (err) {
      setData((prev) => ({ ...prev, loading: false, error: err.message }));
    }
  }, [regionCode]);

  useEffect(() => {
    setData((prev) => ({ ...prev, loading: true }));
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return data;
}
