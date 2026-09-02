import './style.css';
// Resolve base API URL, normalizing trailing slashes and redundant /api prefixes
const rawBaseUrl = import.meta.env.VITE_API_BASE_URL || (import.meta.env.PROD ? 'https://safesnap-backend.vercel.app' : '');
const API_BASE_URL = rawBaseUrl.trim().replace(/\/+$/, '').replace(/\/api$/, '');

const cameraInput = document.getElementById('camera-input');
const quickTextBtns = document.querySelectorAll('.quick-text-btn');
const loadingState = document.getElementById('loading-state');
const errorState = document.getElementById('error-state');
const errorMessage = document.getElementById('error-message');
const resultsCard = document.getElementById('results-card');
const resultHazard = document.getElementById('result-hazard');
const resultSeverity = document.getElementById('result-severity');
const resultSteps = document.getElementById('result-steps');
const ttsBtn = document.getElementById('tts-btn');
const sosBtn = document.getElementById('sos-btn');

let currentStepsToRead = [];
let isSpeaking = false;

// Geolocation for SOS
function initSOS() {
  const defaultBody = encodeURIComponent("EMERGENCY! I need immediate help.");
  sosBtn.href = `sms:?body=${defaultBody}`;

  if ("geolocation" in navigator) {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = position.coords.latitude;
        const lng = position.coords.longitude;
        const mapsUrl = `https://www.google.com/maps?q=${lat},${lng}`;
        const bodyText = `EMERGENCY! I need help at my location: ${mapsUrl}`;
        sosBtn.href = `sms:?body=${encodeURIComponent(bodyText)}`;
      },
      (error) => {
        console.warn("Geolocation unavailable or denied:", error.message);
        const bodyText = "EMERGENCY! I need immediate help. (Location unavailable)";
        sosBtn.href = `sms:?body=${encodeURIComponent(bodyText)}`;
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
  } else {
    const bodyText = "EMERGENCY! I need immediate help. (Location unsupported)";
    sosBtn.href = `sms:?body=${encodeURIComponent(bodyText)}`;
  }
}
initSOS();

// UI State Management
function showLoading() {
  resultsCard.classList.add('hidden');
  if (errorState) errorState.classList.add('hidden');
  loadingState.classList.remove('hidden');
  stopSpeech();
}

function showResults(data) {
  loadingState.classList.add('hidden');
  if (errorState) errorState.classList.add('hidden');

  resultHazard.textContent = data.hazard_identified || 'Unknown Hazard';
  
  const rawSeverity = (data.severity_level || 'Medium').trim();
  const severity = rawSeverity.charAt(0).toUpperCase() + rawSeverity.slice(1).toLowerCase();
  
  resultSeverity.textContent = `Severity: ${severity}`;

  // Severity color indicator with WCAG AAA high-contrast badges
  if (severity === 'High') {
    resultSeverity.className = 'inline-flex items-center px-3 py-1 rounded-full text-xs sm:text-sm font-black bg-red-100 text-red-950 border-2 border-red-600 uppercase tracking-wider';
  } else if (severity === 'Medium') {
    resultSeverity.className = 'inline-flex items-center px-3 py-1 rounded-full text-xs sm:text-sm font-black bg-amber-100 text-amber-950 border-2 border-amber-600 uppercase tracking-wider';
  } else {
    resultSeverity.className = 'inline-flex items-center px-3 py-1 rounded-full text-xs sm:text-sm font-black bg-emerald-100 text-emerald-950 border-2 border-emerald-600 uppercase tracking-wider';
  }

  // Render 3 distinct, easily scannable triage action cards
  resultSteps.innerHTML = '';
  currentStepsToRead = data.immediate_steps || [];

  currentStepsToRead.forEach((step, index) => {
    const card = document.createElement('div');
    card.className = 'flex items-start space-x-3 p-3.5 sm:p-4 bg-slate-50 hover:bg-slate-100/80 rounded-xl border border-slate-200 transition-colors shadow-sm';
    
    const badge = document.createElement('span');
    badge.className = 'flex-shrink-0 w-7 h-7 rounded-lg bg-slate-900 text-white font-black text-sm flex items-center justify-center shadow';
    badge.textContent = `${index + 1}`;

    const text = document.createElement('span');
    text.className = 'text-slate-900 font-semibold text-sm sm:text-base pt-0.5 leading-snug';
    text.textContent = step;

    card.appendChild(badge);
    card.appendChild(text);
    resultSteps.appendChild(card);
  });

  resultsCard.classList.remove('hidden');
}

function showError(msg) {
  loadingState.classList.add('hidden');
  resultsCard.classList.add('hidden');
  stopSpeech();
  if (errorState && errorMessage) {
    errorMessage.textContent = msg;
    errorState.classList.remove('hidden');
  } else {
    alert("Error: " + msg);
  }
}

// Image Compression (HTML5 Canvas, max dimension 800px, compressed .jpg)
async function compressImage(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        let width = img.width;
        let height = img.height;
        const max = 800;

        if (width > height) {
          if (width > max) {
            height = Math.round(height * (max / width));
            width = max;
          }
        } else {
          if (height > max) {
            width = Math.round(width * (max / height));
            height = max;
          }
        }

        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, width, height);

        canvas.toBlob(
          (blob) => {
            if (!blob) {
              reject(new Error("Image compression failed"));
              return;
            }
            const baseName = (file.name || 'capture').replace(/\.[^/.]+$/, "");
            const compressedFile = new File([blob], `${baseName}.jpg`, { type: 'image/jpeg' });
            resolve(compressedFile);
          },
          'image/jpeg',
          0.8
        );
      };
      img.onerror = () => reject(new Error("Failed to load image into canvas"));
      img.src = e.target.result;
    };
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsDataURL(file);
  });
}

// API Call
async function analyze(formData) {
  showLoading();
  try {
    const endpoint = API_BASE_URL ? `${API_BASE_URL}/api/analyze` : '/api/analyze';
    const response = await fetch(endpoint, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.detail || `Server error: ${response.status}`);
    }

    const data = await response.json();
    showResults(data);
  } catch (err) {
    console.error("Analyze request error:", err);
    showError(err.message || "Unable to complete triage analysis. Please try again or call emergency services.");
  }
}

// Event Listeners
cameraInput.addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  try {
    showLoading();
    const compressedFile = await compressImage(file);
    const formData = new FormData();
    formData.append('image', compressedFile);
    await analyze(formData);
  } catch (err) {
    showError(err.message || "Failed to process captured image.");
  } finally {
    cameraInput.value = '';
  }
});

// Keyboard support for custom camera label button (Enter & Space)
const cameraLabel = document.querySelector('label[for="camera-input"]');
if (cameraLabel) {
  cameraLabel.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      cameraInput.click();
    }
  });
}

quickTextBtns.forEach((btn) => {
  btn.addEventListener('click', () => {
    const text = btn.getAttribute('data-text');
    if (!text) return;
    const formData = new FormData();
    formData.append('text', text);
    analyze(formData);
  });
});

// Text-To-Speech Controls
function stopSpeech() {
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
  }
  isSpeaking = false;
  ttsBtn.innerHTML = '<span class="text-xl" aria-hidden="true">🔊</span><span class="text-base font-black">Listen to Steps</span>';
}

ttsBtn.addEventListener('click', () => {
  if (!('speechSynthesis' in window)) {
    showError("Speech synthesis is not supported in this browser.");
    return;
  }
  
  if (isSpeaking) {
    stopSpeech();
    return;
  }

  if (currentStepsToRead.length === 0) return;

  window.speechSynthesis.cancel();

  const textToRead = `Hazard identified: ${resultHazard.textContent}. ` +
                     `${resultSeverity.textContent}. ` +
                     `Immediate steps: ${currentStepsToRead.join('. ')}`;

  const utterance = new SpeechSynthesisUtterance(textToRead);
  utterance.rate = 1.0;

  utterance.onstart = () => {
    isSpeaking = true;
    ttsBtn.innerHTML = '<span class="text-xl animate-pulse" aria-hidden="true">⏹️</span><span class="text-base font-black">Stop Audio</span>';
  };

  utterance.onend = () => {
    stopSpeech();
  };

  utterance.onerror = () => {
    stopSpeech();
  };

  window.speechSynthesis.speak(utterance);
});
