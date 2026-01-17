/**
 * Video Clip Annotator - Main Application
 */

const API_BASE = 'http://127.0.0.1:8093/api';

// Global state
const state = {
  config: null,
  mediaFiles: [],
  currentMedia: null,
  markers: {},        // { filename: [{ id, start, end }] }
  timeline: {
    order: []         // Media file order for export
  },
  ttsClips: [],       // [{ id, text, emotion, audioFile, duration }]
  pendingMarker: { start: null, end: null }
};

// DOM Elements
const elements = {};

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
  cacheElements();
  setupEventListeners();
  await loadConfig();
  await loadMediaFiles();
  await loadSavedData();
  updateUI();
  // Preload durations in background
  preloadMediaDurations();
});

function cacheElements() {
  elements.mediaList = document.getElementById('media-list');
  elements.mediaCount = document.getElementById('media-count');
  elements.videoPlayer = document.getElementById('video-player');
  elements.playerOverlay = document.getElementById('player-overlay');
  elements.waveformCanvas = document.getElementById('waveform-canvas');
  elements.playhead = document.getElementById('playhead');
  elements.markersOverlay = document.getElementById('markers-overlay');
  elements.markerPreview = document.getElementById('marker-preview');
  elements.btnMarkStart = document.getElementById('btn-mark-start');
  elements.btnMarkEnd = document.getElementById('btn-mark-end');
  elements.btnAddMarker = document.getElementById('btn-add-marker');
  elements.clipMarkers = document.getElementById('clip-markers');
  elements.markerCount = document.getElementById('marker-count');
  elements.ttsText = document.getElementById('tts-text');
  elements.ttsEmotion = document.getElementById('tts-emotion');
  elements.ttsList = document.getElementById('tts-list');
  elements.btnGenerateTts = document.getElementById('btn-generate-tts');
  elements.btnSave = document.getElementById('btn-save');
  elements.btnExport = document.getElementById('btn-export');
  elements.statusMessage = document.getElementById('status-message');
  elements.statusDuration = document.getElementById('status-duration');
  elements.modalExport = document.getElementById('modal-export');
  elements.exportProgress = document.getElementById('export-progress');
  elements.exportStatus = document.getElementById('export-status');
}

function setupEventListeners() {
  // Video player events
  elements.videoPlayer.addEventListener('timeupdate', onTimeUpdate);
  elements.videoPlayer.addEventListener('loadedmetadata', onMediaLoaded);

  // Marker controls
  elements.btnMarkStart.addEventListener('click', () => markTime('start'));
  elements.btnMarkEnd.addEventListener('click', () => markTime('end'));
  elements.btnAddMarker.addEventListener('click', addMarkerToList);

  // Keyboard shortcuts
  document.addEventListener('keydown', onKeyDown);

  // TTS
  elements.btnGenerateTts.addEventListener('click', generateTTS);

  // Save & Export
  elements.btnSave.addEventListener('click', saveProject);
  elements.btnExport.addEventListener('click', exportVideo);

  // Waveform click
  elements.waveformCanvas.addEventListener('click', onWaveformClick);
}

// ============================================================
// Config & Data Loading
// ============================================================

async function loadConfig() {
  try {
    const resp = await fetch('./config.json');
    state.config = await resp.json();
    setStatus(`Loaded project: ${state.config.dir}`);
  } catch (e) {
    console.error('Failed to load config:', e);
    setStatus('Error: Failed to load config.json', true);
  }
}

async function loadMediaFiles() {
  if (!state.config?.dir) return;

  // Use mediaFiles from config.json (already scanned and sorted by workflow)
  if (state.config.mediaFiles && state.config.mediaFiles.length > 0) {
    state.mediaFiles = state.config.mediaFiles;
    state.timeline.order = state.mediaFiles.map(f => f.name);
    renderMediaList();
    setStatus(`Loaded ${state.mediaFiles.length} media files`);
  } else {
    setStatus('No media files found in config', true);
  }
}

async function loadSavedData() {
  if (!state.config?.dir) return;

  // Load markers.json
  try {
    const resp = await fetch(`${API_BASE}/file?path=${encodeURIComponent(state.config.dir + '/markers.json')}`);
    if (resp.ok) {
      state.markers = await resp.json();
    }
  } catch (e) {
    console.log('No saved markers found');
  }

  // Load timeline.json
  try {
    const resp = await fetch(`${API_BASE}/file?path=${encodeURIComponent(state.config.dir + '/timeline.json')}`);
    if (resp.ok) {
      const data = await resp.json();
      state.timeline = { ...state.timeline, ...data };
    }
  } catch (e) {
    console.log('No saved timeline found');
  }

  // Load TTS clips
  try {
    const resp = await fetch(`${API_BASE}/file?path=${encodeURIComponent(state.config.dir + '/tts_clips.json')}`);
    if (resp.ok) {
      state.ttsClips = await resp.json();
    }
  } catch (e) {
    console.log('No TTS clips found');
  }
}

// ============================================================
// Media List
// ============================================================

function renderMediaList() {
  elements.mediaList.innerHTML = '';
  elements.mediaCount.textContent = state.mediaFiles.length;

  state.mediaFiles.forEach((file, index) => {
    const li = document.createElement('li');
    li.className = 'media-item';
    li.dataset.filename = file.name;
    li.draggable = true;

    const markerCount = (state.markers[file.name] || []).length;
    const isVideo = /\.(mp4|webm|mov)$/i.test(file.name);
    const icon = isVideo ? '🎬' : '🎵';

    li.innerHTML = `
      <span class="drag-handle">⋮⋮</span>
      <span class="media-icon">${icon}</span>
      <div class="media-info">
        <div class="media-name">${file.name}</div>
        <div class="media-duration">${formatDuration(file.duration || 0)}</div>
      </div>
      ${markerCount > 0 ? `<span class="media-markers">${markerCount} markers</span>` : ''}
    `;

    li.addEventListener('click', () => selectMedia(file));
    li.addEventListener('dragstart', onDragStart);
    li.addEventListener('dragover', onDragOver);
    li.addEventListener('drop', onDrop);
    li.addEventListener('dragend', onDragEnd);

    if (state.currentMedia?.name === file.name) {
      li.classList.add('active');
    }

    elements.mediaList.appendChild(li);
  });
}

function selectMedia(file) {
  state.currentMedia = file;
  state.pendingMarker = { start: null, end: null };

  // Update active state
  document.querySelectorAll('.media-item').forEach(el => {
    el.classList.toggle('active', el.dataset.filename === file.name);
  });

  // Load media
  const mediaPath = `${state.config.dir}/${file.name}`;
  elements.videoPlayer.src = `${API_BASE}/file?path=${encodeURIComponent(mediaPath)}`;
  elements.playerOverlay.classList.add('hidden');

  // Load and render waveform
  loadWaveform(mediaPath);

  // Update marker list
  renderClipMarkers();
  updateMarkerPreview();
}

// ============================================================
// Waveform
// ============================================================

async function loadWaveform(mediaPath) {
  const canvas = elements.waveformCanvas;
  const ctx = canvas.getContext('2d');
  const width = canvas.offsetWidth;
  const height = canvas.offsetHeight;

  // Set canvas size for retina
  canvas.width = width * window.devicePixelRatio;
  canvas.height = height * window.devicePixelRatio;
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

  // Clear canvas
  ctx.fillStyle = '#21262d';
  ctx.fillRect(0, 0, width, height);

  try {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const response = await fetch(`${API_BASE}/file?path=${encodeURIComponent(mediaPath)}`);
    const arrayBuffer = await response.arrayBuffer();
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

    const data = audioBuffer.getChannelData(0);
    const step = Math.ceil(data.length / width);
    const centerY = height / 2;

    // Calculate RMS values for smooth waveform
    const rmsValues = [];
    for (let i = 0; i < width; i++) {
      let sum = 0;
      for (let j = 0; j < step; j++) {
        const idx = i * step + j;
        if (idx < data.length) {
          sum += data[idx] * data[idx];
        }
      }
      rmsValues.push(Math.sqrt(sum / step));
    }

    // Normalize and smooth
    const maxRms = Math.max(...rmsValues, 0.01);
    const normalized = rmsValues.map(v => (v / maxRms) * (height * 0.45));

    // Draw gradient fill
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, 'rgba(88, 166, 255, 0.8)');
    gradient.addColorStop(0.5, 'rgba(88, 166, 255, 0.3)');
    gradient.addColorStop(1, 'rgba(88, 166, 255, 0.8)');

    // Draw smooth waveform using quadratic curves
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.moveTo(0, centerY);

    // Upper half (smooth curve)
    for (let i = 0; i < width; i++) {
      const y = centerY - normalized[i];
      if (i === 0) {
        ctx.lineTo(i, y);
      } else {
        const prevY = centerY - normalized[i - 1];
        const cpX = i - 0.5;
        const cpY = (prevY + y) / 2;
        ctx.quadraticCurveTo(cpX, prevY, i, y);
      }
    }

    // Right edge
    ctx.lineTo(width, centerY);

    // Lower half (mirror, going backwards)
    for (let i = width - 1; i >= 0; i--) {
      const y = centerY + normalized[i];
      if (i === width - 1) {
        ctx.lineTo(i, y);
      } else {
        const nextY = centerY + normalized[i + 1];
        const cpX = i + 0.5;
        const cpY = (nextY + y) / 2;
        ctx.quadraticCurveTo(cpX, nextY, i, y);
      }
    }

    ctx.closePath();
    ctx.fill();

    // Draw center line
    ctx.strokeStyle = 'rgba(88, 166, 255, 0.5)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, centerY);
    ctx.lineTo(width, centerY);
    ctx.stroke();

    // Render markers on waveform
    renderWaveformMarkers();
  } catch (e) {
    console.error('Failed to load waveform:', e);
    ctx.fillStyle = '#8b949e';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Unable to load waveform', width / 2, height / 2);
  }
}

function renderWaveformMarkers() {
  elements.markersOverlay.innerHTML = '';

  if (!state.currentMedia) return;

  const markers = state.markers[state.currentMedia.name] || [];
  const duration = elements.videoPlayer.duration || 1;
  const width = elements.waveformCanvas.offsetWidth;

  markers.forEach(marker => {
    const left = (marker.start / duration) * width;
    const right = (marker.end / duration) * width;

    const div = document.createElement('div');
    div.className = 'marker-region';
    div.style.left = `${left}px`;
    div.style.width = `${right - left}px`;
    div.dataset.markerId = marker.id;

    elements.markersOverlay.appendChild(div);
  });
}

// ============================================================
// Playback & Markers
// ============================================================

function onTimeUpdate() {
  const video = elements.videoPlayer;
  const progress = video.currentTime / (video.duration || 1);
  const width = elements.waveformCanvas.offsetWidth;
  elements.playhead.style.left = `${progress * width}px`;
}

function onMediaLoaded() {
  // Update duration in mediaFiles
  if (state.currentMedia) {
    const duration = elements.videoPlayer.duration;
    if (duration && !isNaN(duration)) {
      state.currentMedia.duration = duration;
      // Update in mediaFiles array
      const file = state.mediaFiles.find(f => f.name === state.currentMedia.name);
      if (file) {
        file.duration = duration;
      }
      renderMediaList();
    }
  }
  renderWaveformMarkers();
  renderClipMarkers();
}

// Preload all media durations
async function preloadMediaDurations() {
  for (const file of state.mediaFiles) {
    if (file.duration) continue;
    try {
      const duration = await getMediaDuration(file.name);
      file.duration = duration;
    } catch (e) {
      console.warn(`Failed to get duration for ${file.name}`);
    }
  }
  renderMediaList();
}

function getMediaDuration(filename) {
  return new Promise((resolve, reject) => {
    const mediaPath = `${state.config.dir}/${filename}`;
    const video = document.createElement('video');
    video.preload = 'metadata';
    video.onloadedmetadata = () => {
      resolve(video.duration);
      video.src = '';
    };
    video.onerror = reject;
    video.src = `${API_BASE}/file?path=${encodeURIComponent(mediaPath)}`;
  });
}

function onWaveformClick(e) {
  const rect = elements.waveformCanvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const progress = x / rect.width;
  elements.videoPlayer.currentTime = progress * elements.videoPlayer.duration;
}

function markTime(type) {
  const time = elements.videoPlayer.currentTime;
  state.pendingMarker[type] = time;
  updateMarkerPreview();
}

function updateMarkerPreview() {
  const { start, end } = state.pendingMarker;
  const startStr = start !== null ? formatTime(start) : '--:--';
  const endStr = end !== null ? formatTime(end) : '--:--';
  elements.markerPreview.textContent = `${startStr} ~ ${endStr}`;

  const canAdd = start !== null && end !== null && end > start;
  elements.btnAddMarker.disabled = !canAdd;
}

function addMarkerToList() {
  if (!state.currentMedia) return;

  const { start, end } = state.pendingMarker;
  if (start === null || end === null || end <= start) return;

  const filename = state.currentMedia.name;
  if (!state.markers[filename]) {
    state.markers[filename] = [];
  }

  const marker = {
    id: `m${Date.now()}`,
    start: parseFloat(start.toFixed(3)),
    end: parseFloat(end.toFixed(3))
  };

  state.markers[filename].push(marker);
  state.pendingMarker = { start: null, end: null };

  updateMarkerPreview();
  renderClipMarkers();
  renderWaveformMarkers();
  renderMediaList();
  autoSave();
}

function removeMarker(markerId, filename) {
  const targetFile = filename || state.currentMedia?.name;
  if (!targetFile) return;

  const markers = state.markers[targetFile];
  if (!markers) return;

  const index = markers.findIndex(m => m.id === markerId);
  if (index !== -1) {
    markers.splice(index, 1);
    renderClipMarkers();
    renderWaveformMarkers();
    renderMediaList();
    autoSave();
  }
}

function renderClipMarkers() {
  // Update marker count badge - count all markers across all files
  const totalMarkers = Object.values(state.markers).reduce((sum, arr) => sum + arr.length, 0);
  elements.markerCount.textContent = totalMarkers;

  if (totalMarkers === 0) {
    elements.clipMarkers.innerHTML = '<li class="empty-state">No markers yet. Use [I] and [O] to mark clips.</li>';
    return;
  }

  // Render all markers grouped by file, in timeline order
  let html = '';
  for (const filename of state.timeline.order) {
    const markers = state.markers[filename] || [];
    if (markers.length === 0) continue;

    const isCurrentFile = state.currentMedia?.name === filename;
    const shortName = filename.replace(/\.[^.]+$/, '');

    html += `<li class="marker-group ${isCurrentFile ? 'active' : ''}" data-filename="${filename}">
      <div class="marker-group-header" onclick="selectMediaByName('${filename}')">
        <span class="marker-group-name">${shortName}</span>
        <span class="marker-group-count">${markers.length}</span>
      </div>
    </li>`;

    html += markers.map((m, index) => {
      const linkedTts = m.ttsId ? state.ttsClips.find(t => t.id === m.ttsId) : null;
      const ttsOptions = state.ttsClips.map(t =>
        `<option value="${t.id}" ${m.ttsId === t.id ? 'selected' : ''}>${escapeHtml(t.text.slice(0, 20))}${t.text.length > 20 ? '...' : ''}</option>`
      ).join('');

      return `
        <li class="marker-item ${isCurrentFile ? 'current-file' : ''}" data-marker-id="${m.id}" data-filename="${filename}" data-index="${index}" draggable="true">
          <span class="drag-handle">⋮⋮</span>
          <div class="marker-info">
            <span class="marker-time">${formatTime(m.start)} - ${formatTime(m.end)}</span>
            <span class="marker-duration">${formatDuration(m.end - m.start)}</span>
            <div class="marker-tts-link">
              <select class="tts-select" onchange="linkTtsToMarker('${m.id}', this.value, '${filename}')">
                <option value="">-- No TTS --</option>
                ${ttsOptions}
              </select>
              ${linkedTts ? `<button class="btn btn-small btn-icon" onclick="playTTS('${linkedTts.id}')" title="Play TTS">🔊</button>` : ''}
            </div>
          </div>
          <div class="marker-actions">
            <button class="btn btn-small btn-icon" onclick="seekToMarker('${m.id}', '${filename}')" title="Jump to">▶</button>
            <button class="btn btn-delete" onclick="removeMarker('${m.id}', '${filename}')" title="Delete">×</button>
          </div>
        </li>
      `;
    }).join('');
  }

  elements.clipMarkers.innerHTML = html;

  // Setup drag-and-drop for marker reordering
  setupMarkerDragAndDrop();
}

function selectMediaByName(filename) {
  const file = state.mediaFiles.find(f => f.name === filename);
  if (file) {
    selectMedia(file);
  }
}

function linkTtsToMarker(markerId, ttsId, filename) {
  const targetFile = filename || state.currentMedia?.name;
  if (!targetFile) return;
  const markers = state.markers[targetFile] || [];
  const marker = markers.find(m => m.id === markerId);
  if (marker) {
    marker.ttsId = ttsId || null;
    autoSave();
    // Re-render to update UI
    renderClipMarkers();
  }
}

function setupMarkerDragAndDrop() {
  const items = elements.clipMarkers.querySelectorAll('.marker-item');
  items.forEach(item => {
    item.addEventListener('dragstart', onMarkerDragStart);
    item.addEventListener('dragover', onMarkerDragOver);
    item.addEventListener('drop', onMarkerDrop);
    item.addEventListener('dragend', onMarkerDragEnd);
  });
}

let draggedMarkerItem = null;

function onMarkerDragStart(e) {
  draggedMarkerItem = e.target.closest('.marker-item');
  if (!draggedMarkerItem) return;
  draggedMarkerItem.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
}

function onMarkerDragOver(e) {
  e.preventDefault();
  const item = e.target.closest('.marker-item');
  if (!item || item === draggedMarkerItem) return;

  const rect = item.getBoundingClientRect();
  const midY = rect.top + rect.height / 2;

  if (e.clientY < midY) {
    item.parentNode.insertBefore(draggedMarkerItem, item);
  } else {
    item.parentNode.insertBefore(draggedMarkerItem, item.nextSibling);
  }
}

function onMarkerDrop(e) {
  e.preventDefault();
}

function onMarkerDragEnd(e) {
  if (draggedMarkerItem) {
    draggedMarkerItem.classList.remove('dragging');
  }

  // Update markers order in state
  if (state.currentMedia) {
    const items = elements.clipMarkers.querySelectorAll('.marker-item');
    const newOrder = Array.from(items).map(item => item.dataset.markerId);
    const currentMarkers = state.markers[state.currentMedia.name] || [];

    // Reorder markers based on DOM order
    const reordered = newOrder.map(id => currentMarkers.find(m => m.id === id)).filter(Boolean);
    state.markers[state.currentMedia.name] = reordered;

    autoSave();
  }

  draggedMarkerItem = null;
}

function seekToMarker(markerId, filename) {
  const targetFile = filename || state.currentMedia?.name;
  if (!targetFile) return;

  // Switch to the file if different
  if (state.currentMedia?.name !== targetFile) {
    const file = state.mediaFiles.find(f => f.name === targetFile);
    if (file) {
      selectMedia(file);
      // Wait for video to load, then seek
      elements.videoPlayer.addEventListener('loadedmetadata', function onLoad() {
        elements.videoPlayer.removeEventListener('loadedmetadata', onLoad);
        const markers = state.markers[targetFile] || [];
        const marker = markers.find(m => m.id === markerId);
        if (marker) {
          elements.videoPlayer.currentTime = marker.start;
          elements.videoPlayer.play();
        }
      });
      return;
    }
  }

  const markers = state.markers[targetFile] || [];
  const marker = markers.find(m => m.id === markerId);
  if (marker) {
    elements.videoPlayer.currentTime = marker.start;
    elements.videoPlayer.play();
  }
}

// ============================================================
// Export Data Management
// ============================================================

function getClipDuration(source, markerId) {
  const markers = state.markers[source] || [];
  const marker = markers.find(m => m.id === markerId);
  return marker ? marker.end - marker.start : 0;
}

function getTotalDuration() {
  // Calculate total duration from all markers in order
  let total = 0;
  for (const filename of state.timeline.order) {
    const markers = state.markers[filename] || [];
    for (const m of markers) {
      total += m.end - m.start;
    }
  }
  // Add TTS duration
  for (const clip of state.ttsClips) {
    total = Math.max(total, clip.duration);
  }
  return total;
}

// ============================================================
// TTS Generation
// ============================================================

async function generateTTS() {
  const text = elements.ttsText.value.trim();
  if (!text) {
    setStatus('Please enter narration text', true);
    return;
  }

  const emotion = elements.ttsEmotion.value;
  let finalText = text;

  // Add emotion marker if selected and not already present
  if (emotion && !text.startsWith('[#')) {
    const emotionMap = {
      'excited': '用兴奋激动的语气说',
      'calm': '用平静的语气说',
      'sad': '用伤感的语气说',
      'serious': '用严肃的语气说',
      'friendly': '用亲切友好的语气说'
    };
    finalText = `[#${emotionMap[emotion] || emotion}]${text}`;
  }

  setStatus('Generating TTS...');
  elements.btnGenerateTts.disabled = true;

  try {
    const ttsId = `tts_${Date.now()}`;
    const outputFile = `${state.config.dir}/tts/${ttsId}.wav`;

    const resp = await fetch(`${API_BASE}/recipes/volcengine_tts_with_emotion/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        params: {
          text: finalText,
          output_file: outputFile
        }
      })
    });

    const result = await resp.json();

    if (result.status === 'completed' || result.status === 'ok') {
      const ttsClip = {
        id: ttsId,
        text: text,
        emotion: emotion,
        audioFile: outputFile,
        duration: (result.duration_ms || 3000) / 1000
      };

      state.ttsClips.push(ttsClip);
      renderTTSList();
      renderClipMarkers();  // Refresh to update TTS dropdown options
      elements.ttsText.value = '';
      setStatus('TTS generated successfully');

      // Save TTS metadata
      await saveTTSMetadata(ttsClip);
    } else {
      throw new Error(result.error || 'TTS generation failed');
    }
  } catch (e) {
    console.error('TTS error:', e);
    setStatus(`TTS error: ${e.message}`, true);
  } finally {
    elements.btnGenerateTts.disabled = false;
  }
}

async function saveTTSMetadata(ttsClip) {
  try {
    await fetch(`${API_BASE}/file?path=${encodeURIComponent(state.config.dir + '/tts/' + ttsClip.id + '.json')}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: JSON.stringify(ttsClip, null, 2) })
    });
  } catch (e) {
    console.error('Failed to save TTS metadata:', e);
  }
}

function renderTTSList() {
  if (state.ttsClips.length === 0) {
    elements.ttsList.innerHTML = '<li class="empty-state">No narration clips yet</li>';
    return;
  }

  elements.ttsList.innerHTML = state.ttsClips.map(clip => `
    <li class="tts-item" data-tts-id="${clip.id}">
      <div class="tts-text">${escapeHtml(clip.text)}</div>
      <div class="tts-meta">
        ${clip.emotion ? `<span class="tts-emotion">${clip.emotion}</span>` : ''}
        <span class="tts-duration">${formatDuration(clip.duration)}</span>
      </div>
      <div class="tts-actions">
        <button class="btn btn-small" onclick="playTTS('${clip.id}')" title="Play">▶</button>
        <button class="btn btn-small btn-delete" onclick="deleteTTS('${clip.id}')" title="Delete">×</button>
      </div>
    </li>
  `).join('');
}

function deleteTTS(ttsId) {
  // Remove TTS from list
  const index = state.ttsClips.findIndex(c => c.id === ttsId);
  if (index === -1) return;

  state.ttsClips.splice(index, 1);

  // Clear any marker links to this TTS
  for (const filename in state.markers) {
    for (const marker of state.markers[filename]) {
      if (marker.ttsId === ttsId) {
        marker.ttsId = null;
      }
    }
  }

  renderTTSList();
  renderClipMarkers();
  autoSave();
}

function playTTS(ttsId) {
  const clip = state.ttsClips.find(c => c.id === ttsId);
  if (!clip) return;

  const audio = new Audio(`${API_BASE}/file?path=${encodeURIComponent(clip.audioFile)}`);
  audio.play();
}

// ============================================================
// Save & Export
// ============================================================

async function saveProject() {
  setStatus('Saving project...');

  try {
    // Save markers
    await fetch(`${API_BASE}/file?path=${encodeURIComponent(state.config.dir + '/markers.json')}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: JSON.stringify(state.markers, null, 2) })
    });

    // Save timeline
    await fetch(`${API_BASE}/file?path=${encodeURIComponent(state.config.dir + '/timeline.json')}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: JSON.stringify(state.timeline, null, 2) })
    });

    // Save TTS clips
    await fetch(`${API_BASE}/file?path=${encodeURIComponent(state.config.dir + '/tts_clips.json')}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: JSON.stringify(state.ttsClips, null, 2) })
    });

    setStatus('Project saved');
  } catch (e) {
    console.error('Save error:', e);
    setStatus('Failed to save project', true);
  }
}

async function autoSave() {
  // Debounced auto-save
  if (state.autoSaveTimeout) clearTimeout(state.autoSaveTimeout);
  state.autoSaveTimeout = setTimeout(saveProject, 2000);
}

async function exportVideo() {
  // Collect all clips from markers in order
  const allClips = [];
  for (const filename of state.timeline.order) {
    const markers = state.markers[filename] || [];
    for (const marker of markers) {
      // Find linked TTS
      const linkedTts = marker.ttsId ? state.ttsClips.find(t => t.id === marker.ttsId) : null;
      allClips.push({
        source: filename,
        markerId: marker.id,
        start: marker.start,
        end: marker.end,
        ttsId: marker.ttsId,
        ttsFile: linkedTts?.audioFile || null
      });
    }
  }

  if (allClips.length === 0) {
    setStatus('No clip markers to export', true);
    return;
  }

  elements.modalExport.classList.remove('hidden');
  elements.exportProgress.style.width = '0%';
  elements.exportStatus.textContent = 'Preparing clips...';

  const tempDir = `${state.config.dir}/temp`;
  const timestamp = Date.now();

  try {
    // Step 1: Trim each clip and optionally replace audio with TTS
    const processedClips = [];
    const totalSteps = allClips.length * 2 + 1; // trim + audio replace + merge
    let currentStep = 0;

    for (let i = 0; i < allClips.length; i++) {
      const clip = allClips[i];
      const inputFile = `${state.config.dir}/${clip.source}`;
      const trimmedFile = `${tempDir}/trim_${timestamp}_${i}.mp4`;

      // Step 1a: Trim the clip
      elements.exportStatus.textContent = `Trimming clip ${i + 1}/${allClips.length}...`;

      const trimResp = await fetch(`${API_BASE}/recipes/video_trim_clip/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          params: {
            input_file: inputFile,
            output_file: trimmedFile,
            start: clip.start,
            end: clip.end
          }
        })
      });

      const trimResult = await trimResp.json();
      if (!trimResult.success && trimResult.data && !trimResult.data.success) {
        throw new Error(trimResult.error || trimResult.data?.error || `Failed to trim clip ${i + 1}`);
      }

      currentStep++;
      elements.exportProgress.style.width = `${(currentStep / totalSteps) * 100}%`;

      let finalClipFile = trimmedFile;

      // Step 1b: Replace audio with TTS if linked
      if (clip.ttsFile) {
        elements.exportStatus.textContent = `Adding TTS to clip ${i + 1}/${allClips.length}...`;

        const withTtsFile = `${tempDir}/tts_${timestamp}_${i}.mp4`;

        const audioResp = await fetch(`${API_BASE}/recipes/video_add_audio_track/run`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            params: {
              video_file: trimmedFile,
              audio_file: clip.ttsFile,
              output_file: withTtsFile,
              replace_audio: true
            }
          })
        });

        const audioResult = await audioResp.json();
        if (!audioResult.success && audioResult.data && !audioResult.data.success) {
          console.warn(`Failed to add TTS to clip ${i + 1}, using original audio`);
        } else {
          finalClipFile = withTtsFile;
        }
      }

      currentStep++;
      elements.exportProgress.style.width = `${(currentStep / totalSteps) * 100}%`;

      processedClips.push(finalClipFile);
    }

    // Step 2: Merge all processed clips
    elements.exportStatus.textContent = 'Merging video clips...';

    const outputFile = `${state.config.dir}/output/final_${timestamp}.mp4`;

    const mergeResp = await fetch(`${API_BASE}/recipes/video_merge_clips/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        params: {
          clips: processedClips,
          output_file: outputFile,
          codec: 'libx264'  // Re-encode for compatibility
        }
      })
    });

    const mergeResult = await mergeResp.json();

    if (!mergeResult.success && mergeResult.data && !mergeResult.data.success) {
      throw new Error(mergeResult.error || mergeResult.data?.error || 'Video merge failed');
    }

    currentStep++;
    elements.exportProgress.style.width = '100%';
    elements.exportStatus.textContent = `Export complete!`;

    // Show success with output path
    setTimeout(() => {
      elements.exportStatus.textContent = `Saved: ${outputFile}`;
    }, 500);

    setTimeout(() => {
      elements.modalExport.classList.add('hidden');
      setStatus(`Export complete: ${outputFile.split('/').pop()}`);
    }, 3000);

  } catch (e) {
    console.error('Export error:', e);
    elements.exportStatus.textContent = `Error: ${e.message}`;
    setTimeout(() => {
      elements.modalExport.classList.add('hidden');
      setStatus(`Export failed: ${e.message}`, true);
    }, 3000);
  }
}

// ============================================================
// Drag & Drop for Media List
// ============================================================

let draggedItem = null;

function onDragStart(e) {
  draggedItem = e.target;
  e.target.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
}

function onDragOver(e) {
  e.preventDefault();
  const item = e.target.closest('.media-item');
  if (item && item !== draggedItem) {
    const rect = item.getBoundingClientRect();
    const midY = rect.top + rect.height / 2;
    if (e.clientY < midY) {
      item.parentNode.insertBefore(draggedItem, item);
    } else {
      item.parentNode.insertBefore(draggedItem, item.nextSibling);
    }
  }
}

function onDrop(e) {
  e.preventDefault();
}

function onDragEnd(e) {
  e.target.classList.remove('dragging');

  // Update order in state
  const items = elements.mediaList.querySelectorAll('.media-item');
  state.timeline.order = Array.from(items).map(item => item.dataset.filename);
  autoSave();
}

// ============================================================
// Keyboard Shortcuts
// ============================================================

function onKeyDown(e) {
  // Don't trigger shortcuts when typing in input fields
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  switch (e.key.toLowerCase()) {
    case 'i':
      markTime('start');
      break;
    case 'o':
      markTime('end');
      break;
    case ' ':
      e.preventDefault();
      if (elements.videoPlayer.paused) {
        elements.videoPlayer.play();
      } else {
        elements.videoPlayer.pause();
      }
      break;
    case 'arrowleft':
      elements.videoPlayer.currentTime -= e.shiftKey ? 5 : 1;
      break;
    case 'arrowright':
      elements.videoPlayer.currentTime += e.shiftKey ? 5 : 1;
      break;
    case 's':
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        saveProject();
      }
      break;
  }
}

// ============================================================
// Utility Functions
// ============================================================

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`;
}

function formatDuration(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${m}:${s.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`;
}

function formatTimeShort(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m > 0) {
    return `${m}:${s.toString().padStart(2, '0')}`;
  }
  return `${s}s`;
}

function extractNumber(filename) {
  const match = filename.match(/(\d+)/);
  return match ? parseInt(match[1], 10) : null;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function setStatus(message, isError = false) {
  elements.statusMessage.textContent = message;
  elements.statusMessage.style.color = isError ? 'var(--accent-red)' : 'var(--text-secondary)';
}

function updateTotalDuration() {
  const total = getTotalDuration();
  elements.statusDuration.textContent = `Total: ${formatDuration(total)}`;
}

function updateUI() {
  renderMediaList();
  renderClipMarkers();
  renderTTSList();
  updateTotalDuration();
}

// Make functions available globally for onclick handlers
window.removeMarker = removeMarker;
window.seekToMarker = seekToMarker;
window.playTTS = playTTS;
window.deleteTTS = deleteTTS;
window.linkTtsToMarker = linkTtsToMarker;
window.selectMediaByName = selectMediaByName;
