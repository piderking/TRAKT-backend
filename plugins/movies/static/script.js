document.addEventListener('DOMContentLoaded', () => {
  const fetchBtn = document.getElementById('fetch-btn');
  const statusText = document.getElementById('status-text');
  const mediaGrid = document.getElementById('media-grid');

  async function loadUpNext() {
    statusText.textContent = 'Fetching telemetry...';
    try {
      const response = await fetch('/up-next');
      const data = await response.json();
      renderGrid(data.up_next || []);
      statusText.textContent = `Loaded ${data.count || 0} items at ${new Date(data.timestamp * 1000).toLocaleTimeString()}`;
    } catch (err) {
      statusText.textContent = `Error: ${err.message}`;
    }
  }

  function renderGrid(items) {
    mediaGrid.innerHTML = items.map(item => `
      <div class="media-card">
        <img class="card-poster" src="${item.poster}" alt="${item.title}" />
        <div class="card-body">
          <h3 class="card-title">${item.title}</h3>
          <div class="card-meta">
            <span>${item.type.toUpperCase()} • ${item.year}</span>
            <span class="rating-tag">★ ${item.rating}</span>
          </div>
          <div class="progress-bar-bg">
            <div class="progress-bar-fill" style="width: ${item.progress_pct}%"></div>
          </div>
        </div>
      </div>
    `).join('');
  }

  fetchBtn.addEventListener('click', loadUpNext);
  loadUpNext();
});
