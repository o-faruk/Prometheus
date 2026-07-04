const BASE = '/api';

async function getJson(path) {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}`);
  }
  return response.json();
}

export const api = {
  regions: () => getJson('/regions'),
  current: (region) => getJson(`/${region}/current`),
  generationMix: (region) => getJson(`/${region}/generation-mix`),
  forecast: (region) => getJson(`/${region}/forecast`),
  accuracy: (region) => getJson(`/${region}/accuracy`),
  alerts: (region, includeNormal = false) => getJson(`/${region}/alerts?include_normal=${includeNormal}`),
  predictionsHistory: (region, limit = 72) => getJson(`/${region}/predictions-history?limit=${limit}`),
};
