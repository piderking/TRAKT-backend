document.addEventListener('DOMContentLoaded', () => {
  async function fetchTelemetry() {
    try {
      const res = await fetch('/telemetry/summary');
      const data = await res.json();

      const tokens = data.token_metrics || {};
      const waka = data.wakatime_metrics || {};

      document.getElementById('total-tokens').textContent = (tokens.total_tokens || 0).toLocaleString();
      document.getElementById('waka-today').textContent = waka.today_formatted || '0h 0m';
      document.getElementById('sessions-count').textContent = tokens.sessions_count || 0;

      // Populate models
      const modelsContainer = document.getElementById('models-container');
      const models = tokens.models_breakdown || {};
      
      modelsContainer.innerHTML = Object.entries(models).map(([modelName, m]) => {
        const sum = (m.prompt || 0) + (m.completion || 0);
        const pct = Math.min(100, Math.round((sum / (tokens.total_tokens || 1)) * 100));
        return `
          <div class="model-row">
            <div class="model-name">${modelName}</div>
            <div class="bar-container">
              <div class="bar-fill" style="width: ${pct}%"></div>
            </div>
            <div class="model-details">
              <span>Prompt: ${(m.prompt || 0).toLocaleString()}</span>
              <span>Completion: ${(m.completion || 0).toLocaleString()}</span>
            </div>
          </div>
        `;
      }).join('');

      // Populate recent activity
      const activityList = document.getElementById('activity-list');
      const heartbeats = data.recent_activity || [];
      
      activityList.innerHTML = heartbeats.map(hb => `
        <li class="activity-item">
          <div class="activity-main">
            <span class="activity-title">${hb.project} • ${hb.entity}</span>
            <span class="activity-meta">${hb.language} • ${hb.timestamp}</span>
          </div>
          <span class="token-badge">+${(hb.tokens || 0).toLocaleString()} tokens</span>
        </li>
      `).join('');

    } catch (err) {
      console.error('Failed to fetch telemetry summary:', err);
    }
  }

  fetchTelemetry();
  setInterval(fetchTelemetry, 10000);
});
