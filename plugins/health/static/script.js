document.addEventListener('DOMContentLoaded', () => {
  async function fetchHealthTelemetry() {
    try {
      const res = await fetch('/telemetry/summary');
      const data = await res.json();

      const bio = data.biometrics || {};
      const hr = bio.heart_rate || {};
      const act = bio.activity || {};
      const rec = bio.recovery || {};

      document.getElementById('bpm-val').textContent = hr.current_bpm || '--';
      document.getElementById('bpm-sub').textContent = `Resting: ${hr.resting_bpm || '--'} BPM`;

      document.getElementById('steps-val').textContent = (act.steps_today || 0).toLocaleString();
      const pct = act.goal_pct || 0;
      document.getElementById('steps-bar').style.width = `${Math.min(100, pct)}%`;

      document.getElementById('cal-val').textContent = (act.calories_active_kcal || 0).toLocaleString();
      document.getElementById('sleep-val').textContent = rec.sleep_hours || '--';
      document.getElementById('spo2-sub').textContent = `SpO2: ${rec.spo2_percentage || '--'}%`;

      // Populate sync list
      const syncList = document.getElementById('sync-list');
      const syncs = data.recent_syncs || [];

      syncList.innerHTML = syncs.map(s => `
        <li class="sync-item">
          <div>
            <div class="sync-device">${s.device}</div>
            <div style="font-size: 11px; color: #9ca3af;">${s.timestamp} • ${s.hr} BPM • ${s.steps.toLocaleString()} steps</div>
          </div>
          <span class="sync-badge">${s.status.toUpperCase()}</span>
        </li>
      `).join('');

    } catch (err) {
      console.error('Failed to fetch health telemetry:', err);
    }
  }

  fetchHealthTelemetry();
  setInterval(fetchHealthTelemetry, 5000);
});
