/**
 * Sack Counter — Frontend Logic
 */

// ── Tab switching ──────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${tab}`).classList.add('active');
  });
});

// ── Utilities ──────────────────────────────────────────────────────────────
function showLoading(text = 'Memproses...', sub = 'Mohon tunggu sebentar') {
  document.getElementById('loading-text').textContent = text;
  document.getElementById('loading-sub').textContent = sub;
  document.getElementById('loading-overlay').classList.remove('hidden');
}

function hideLoading() {
  document.getElementById('loading-overlay').classList.add('hidden');
}

function showToast(msg, duration = 3500) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.classList.remove('hidden');
  setTimeout(() => toast.classList.add('hidden'), duration);
}

function setupDropZone(dropZoneId, inputId, acceptTypes, onFile) {
  const zone = document.getElementById(dropZoneId);
  const input = document.getElementById(inputId);

  zone.addEventListener('click', () => input.click());

  zone.addEventListener('dragover', e => {
    e.preventDefault();
    zone.classList.add('dragover');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) onFile(file);
  });

  input.addEventListener('change', () => {
    if (input.files[0]) onFile(input.files[0]);
  });
}

async function postFile(url, file, loadingText, loadingSubText) {
  const formData = new FormData();
  formData.append('file', file);

  showLoading(loadingText, loadingSubText);
  try {
    const res = await fetch(url, { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || 'Terjadi kesalahan pada server');
    }
    return await res.json();
  } finally {
    hideLoading();
  }
}

// ── IMAGE ──────────────────────────────────────────────────────────────────
let selectedImage = null;

function setImageFile(file) {
  selectedImage = file;
  const reader = new FileReader();
  reader.onload = e => {
    document.getElementById('image-preview').src = e.target.result;
    document.getElementById('image-preview-box').classList.remove('hidden');
    document.getElementById('image-drop-zone').classList.add('hidden');
    document.getElementById('image-result').classList.add('hidden');
    document.getElementById('image-detect-btn').disabled = false;
  };
  reader.readAsDataURL(file);
}

setupDropZone('image-drop-zone', 'image-input', '.jpg,.jpeg,.png,.bmp,.webp', setImageFile);

document.getElementById('image-clear-btn').addEventListener('click', () => {
  selectedImage = null;
  document.getElementById('image-input').value = '';
  document.getElementById('image-preview-box').classList.add('hidden');
  document.getElementById('image-drop-zone').classList.remove('hidden');
  document.getElementById('image-detect-btn').disabled = true;
  document.getElementById('image-result').classList.add('hidden');
});

document.getElementById('image-detect-btn').addEventListener('click', async () => {
  if (!selectedImage) return;
  try {
    const data = await postFile(
      '/detect/image',
      selectedImage,
      'Mendeteksi karung...',
      'Model AI sedang menganalisis gambar'
    );

    document.getElementById('image-count').textContent = data.count;

    const boxInfo = document.getElementById('image-boxes-info');
    if (data.confidence_scores.length > 0) {
      const avg = (data.confidence_scores.reduce((a, b) => a + b, 0) / data.confidence_scores.length * 100).toFixed(0);
      boxInfo.textContent = `Rata-rata kepercayaan: ${avg}% | ${data.bounding_boxes.length} objek terdeteksi`;
    } else {
      boxInfo.textContent = 'Tidak ada karung terdeteksi pada gambar ini.';
    }

    const resultUrl = data.result_url;
    const img = document.getElementById('image-annotated');
    img.src = resultUrl;

    const dlBtn = document.getElementById('image-download-btn');
    dlBtn.href = resultUrl;
    dlBtn.download = `sack_result_${Date.now()}.jpg`;

    document.getElementById('image-result').classList.remove('hidden');
  } catch (err) {
    showToast(`Error: ${err.message}`);
  }
});

// ── VIDEO ──────────────────────────────────────────────────────────────────
let selectedVideo = null;

function setVideoFile(file) {
  selectedVideo = file;
  const url = URL.createObjectURL(file);
  const vid = document.getElementById('video-preview');
  vid.src = url;
  document.getElementById('video-preview-box').classList.remove('hidden');
  document.getElementById('video-drop-zone').classList.add('hidden');
  document.getElementById('video-result').classList.add('hidden');
  document.getElementById('video-detect-btn').disabled = false;
}

setupDropZone('video-drop-zone', 'video-input', '.mp4,.avi,.mov,.mkv,.webm', setVideoFile);

document.getElementById('video-clear-btn').addEventListener('click', () => {
  selectedVideo = null;
  document.getElementById('video-input').value = '';
  document.getElementById('video-preview-box').classList.add('hidden');
  document.getElementById('video-drop-zone').classList.remove('hidden');
  document.getElementById('video-detect-btn').disabled = true;
  document.getElementById('video-result').classList.add('hidden');
});

document.getElementById('video-detect-btn').addEventListener('click', async () => {
  if (!selectedVideo) return;
  try {
    const data = await postFile(
      '/detect/video',
      selectedVideo,
      'Memproses video...',
      'Ini mungkin memerlukan beberapa menit tergantung panjang video'
    );

    document.getElementById('video-avg').textContent = data.avg_count;
    document.getElementById('video-max').textContent = data.max_count;
    document.getElementById('video-min').textContent = data.min_count;
    document.getElementById('video-frames').textContent = data.total_frames;

    const vid = document.getElementById('video-annotated');
    vid.src = data.result_url;

    const dlBtn = document.getElementById('video-download-btn');
    dlBtn.href = data.result_url;
    dlBtn.download = `sack_result_${Date.now()}.mp4`;

    document.getElementById('video-result').classList.remove('hidden');
  } catch (err) {
    showToast(`Error: ${err.message}`);
  }
});
