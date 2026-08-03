document.addEventListener('DOMContentLoaded', () => {
  const fileInput = document.getElementById('file-input');
  const dropzone = document.getElementById('dropzone');

  async function fetchSummary() {
    try {
      const res = await fetch('/import/summary');
      const data = await res.json();
      const st = data.stats || {};

      document.getElementById('stat-watched').textContent = st.movies_watched || '--';
      document.getElementById('stat-ratings').textContent = st.ratings || '--';
      document.getElementById('stat-diary').textContent = st.diary_entries || '--';
      document.getElementById('stat-watchlist').textContent = st.watchlist || '--';

      const historyList = document.getElementById('history-list');
      const recent = data.recent_imports || [];

      historyList.innerHTML = recent.map(r => `
        <li class="history-item">
          <div>
            <div class="history-file">📦 ${r.filename}</div>
            <div style="font-size: 11px; color: #9ca3af;">${r.timestamp} • Watched: ${r.watched_count} • Ratings: ${r.ratings_count}</div>
          </div>
          <span style="font-size: 10px; font-family: monospace; color: #00e054; background: rgba(0,224,84,0.1); padding: 2px 8px; border-radius: 4px;">COMPLETED</span>
        </li>
      `).join('');
    } catch (err) {
      console.error('Failed to fetch import summary:', err);
    }
  }

  async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/import/upload', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      alert(`Import Successful! Watched: ${data.imported_counts.watched}, Ratings: ${data.imported_counts.ratings}`);
      fetchSummary();
    } catch (err) {
      console.error('Upload failed:', err);
      alert('Upload failed. Please ensure the file is a valid Letterboxd export zip.');
    }
  }

  fileInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      uploadFile(e.target.files[0]);
    }
  });

  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.style.borderColor = '#00e054';
  });

  dropzone.addEventListener('dragleave', () => {
    dropzone.style.borderColor = '#ff8000';
  });

  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.style.borderColor = '#ff8000';
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      uploadFile(e.dataTransfer.files[0]);
    }
  });

  fetchSummary();
});
