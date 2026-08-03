document.addEventListener('DOMContentLoaded', () => {
  async function fetchSpotifyTelemetry() {
    try {
      const res = await fetch('/telemetry/summary');
      const data = await res.json();

      const np = data.now_playing || {};
      const st = data.stats || {};
      const af = np.audio_features || {};

      document.getElementById('track-title').textContent = np.track_name || 'No Track Playing';
      document.getElementById('track-artist').textContent = np.artist_name || '';
      document.getElementById('track-album').textContent = `Album • ${np.album_name || ''}`;

      if (np.album_art_url) {
        document.getElementById('album-art').src = np.album_art_url;
      }

      if (np.duration_ms && np.progress_ms) {
        const pct = Math.min(100, Math.round((np.progress_ms / np.duration_ms) * 100));
        document.getElementById('progress-bar-fill').style.width = `${pct}%`;

        const curMins = Math.floor(np.progress_ms / 60000);
        const curSecs = Math.floor((np.progress_ms % 60000) / 1000);
        const totMins = Math.floor(np.duration_ms / 60000);
        const totSecs = Math.floor((np.duration_ms % 60000) / 1000);

        document.getElementById('time-current').textContent = `${curMins}:${curSecs < 10 ? '0' : ''}${curSecs}`;
        document.getElementById('time-total').textContent = `${totMins}:${totSecs < 10 ? '0' : ''}${totSecs}`;
      }

      document.getElementById('stat-tracks').textContent = st.tracks_played_today || 0;
      document.getElementById('stat-mins').textContent = `${st.total_listening_minutes || 0}m`;
      document.getElementById('stat-bpm').textContent = af.bpm || 128;
      document.getElementById('stat-energy').textContent = `${Math.round((af.energy || 0.8) * 100)}%`;

      // History list
      const historyList = document.getElementById('history-list');
      const history = data.history || [];

      historyList.innerHTML = history.map(item => `
        <li class="history-item">
          <div>
            <div class="track-title-item">♬ ${item.track_name}</div>
            <div class="track-artist-item">${item.artist_name} • ${item.album_name}</div>
          </div>
          <div style="text-align: right; font-family: monospace; font-size: 11px; color: #9ca3af;">
            <div>${item.played_at}</div>
            <div style="color: #1db954;">${item.duration_formatted}</div>
          </div>
        </li>
      `).join('');

    } catch (err) {
      console.error('Failed to fetch Spotify telemetry:', err);
    }
  }

  fetchSpotifyTelemetry();
  setInterval(fetchSpotifyTelemetry, 4000);
});
