// Every timestamp on this dashboard should read in the grid region's own local time, not
// the viewer's browser timezone — demand cycles and "hour of day" only mean something
// relative to the grid's own clock (same lesson learned the hard way in the backend's
// Prophet/feature-engineering code — see NOTES.md).
export function formatTime(iso, timezone) {
  return new Date(iso).toLocaleTimeString([], { timeZone: timezone, hour: '2-digit', minute: '2-digit' });
}

export function formatDateTime(iso, timezone) {
  return new Date(iso).toLocaleString([], {
    timeZone: timezone, month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}
