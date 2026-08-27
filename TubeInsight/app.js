// TubeInsight AI — Application Logic, 8-Second Video Studio & Voice Cloning Engine

// State
let currentReportData = null;
let currentPlanData = null;

// Voice Recording State
let mediaRecorder = null;
let recordedAudioChunks = [];
let currentRecordedBase64 = null;
let isRecording = false;

document.addEventListener('DOMContentLoaded', () => {
  initLucide();
  checkServerStatus();
  setInterval(checkServerStatus, 15000); // LM Studio/Ollama 상태 15초마다 자동 갱신
  loadVoiceProfiles();
  setupEventListeners();

  // Load default sample (ws1Clj0vOAM)
  loadVideoData('ws1Clj0vOAM');
});

function initLucide() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

// 1. Server Status Check — LM Studio / Ollama 두 pill을 각각 갱신 (검은 테두리 = 사용 중)
async function checkServerStatus() {
  const pills = {
    lmstudio: { pill: document.getElementById('lmsPill'), dot: document.getElementById('lmsDot'), label: document.getElementById('lmsLabel'), name: 'LM Studio' },
    ollama: { pill: document.getElementById('ollamaPill'), dot: document.getElementById('ollamaDot'), label: document.getElementById('ollamaLabel'), name: 'Ollama' }
  };
  if (!pills.lmstudio.pill || !pills.ollama.pill) return;

  const basePill = 'flex items-center gap-1.5 px-2.5 py-1 rounded-full whitespace-nowrap transition-all cursor-pointer select-none';

  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    const backends = data.backends || {};
    const active = data.llm ? data.llm.active : null;
    const pref = (data.llm && data.llm.preference) || 'auto';
    window.__llmPreference = pref;

    for (const key of ['lmstudio', 'ollama']) {
      const p = pills[key];
      const st = backends[key] || {};
      const isActive = active === key;
      const isChosen = pref === key; // 사용자가 수동으로 이 백엔드를 선택함

      p.dot.className = 'w-2 h-2 rounded-full ' + (st.online
        ? (st.model ? 'bg-emerald-500' + (isActive ? ' animate-pulse' : '') : 'bg-amber-500')
        : (isChosen ? 'bg-red-500' : 'bg-neutral-300'));

      let text = p.name;
      if (isActive && st.model) text += ' · ' + String(st.model).split('/').pop();
      else if (isChosen && !st.online) text += ' · 꺼짐';
      else if (st.online && !st.model) text += ' · 모델 없음';
      p.label.innerText = text;

      p.pill.className = basePill + (isActive
        ? ' bg-white border border-black text-black font-semibold shadow-sm'
        : isChosen && !st.online
          ? ' bg-white border border-red-400 text-red-500 font-semibold'
          : ' bg-neutral-50 border border-neutral-200 ' + (st.online ? 'text-neutral-600' : 'text-neutral-400'));

      const modeTag = pref === 'auto' ? '자동 감지' : '수동 선택';
      p.pill.title = !st.online
        ? (isChosen ? `${p.name} 선택됨 — 꺼져 있습니다. 실행하거나 다시 클릭해 자동 모드로 전환하세요.` : `${p.name} 꺼짐 · 클릭하면 이 백엔드를 사용합니다`)
        : isActive ? `${p.name} 사용 중 (${modeTag} · 모델: ${st.model || '없음'})${isChosen ? ' — 다시 클릭하면 자동 모드' : ''}`
        : st.model ? `${p.name} 실행 중 (대기) · 클릭하면 이 백엔드를 사용합니다` : `${p.name} 실행 중 — 모델 설치 필요 (ollama pull)`;
    }
  } catch (err) {
    for (const key of ['lmstudio', 'ollama']) {
      const p = pills[key];
      p.dot.className = 'w-2 h-2 rounded-full bg-neutral-300';
      p.label.innerText = p.name;
      p.pill.className = basePill + ' bg-neutral-50 border border-neutral-200 text-neutral-400';
      p.pill.title = '서버 연결 대기 중';
    }
  }
}

// 1-1. 백엔드 수동 선택 — pill 클릭 시 해당 백엔드 사용, 이미 선택된 것을 다시 클릭하면 자동 모드
async function selectBackend(key) {
  const current = window.__llmPreference || 'auto';
  const next = current === key ? 'auto' : key;
  const names = { lmstudio: 'LM Studio', ollama: 'Ollama' };
  try {
    const res = await fetch('/api/llm/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backend: next })
    });
    const result = await res.json();
    if (result.status === 'success') {
      showToast(next === 'auto'
        ? '자동 감지 모드로 전환했습니다 (LM Studio 우선)'
        : `${names[key]}를 사용하도록 설정했습니다.`);
    } else {
      showToast(result.error || '백엔드 선택 실패');
    }
  } catch (err) {
    showToast('서버 통신 오류');
  }
  checkServerStatus();
}

// 2. Load Voice Profiles (Presets + User Cloned Voices)
async function loadVoiceProfiles() {
  const select = document.getElementById('voiceSelect');
  if (!select) return;

  try {
    const res = await fetch('/api/voice/profiles');
    const data = await res.json();
    if (data.status === 'success' && data.voices) {
      const curVal = select.value;
      select.innerHTML = data.voices.map(v => `
        <option value="${v.id}" ${v.id === curVal ? 'selected' : ''}>
          ${v.is_custom ? '[내 목소리] ' : ''}${v.name}
        </option>
      `).join('');
    }
  } catch (err) {
    console.error('Voice profiles load error:', err);
  }
}

// 3. Setup Event Listeners
function setupEventListeners() {
  // LLM Backend Pills (클릭으로 LM Studio / Ollama 선택)
  const lmsPill = document.getElementById('lmsPill');
  const ollamaPill = document.getElementById('ollamaPill');
  if (lmsPill) lmsPill.addEventListener('click', () => selectBackend('lmstudio'));
  if (ollamaPill) ollamaPill.addEventListener('click', () => selectBackend('ollama'));

  // Mode Switching
  const btnModeAnalyze = document.getElementById('btnModeAnalyze');
  const btnModeGenerate = document.getElementById('btnModeGenerate');
  const analyzerSection = document.getElementById('analyzerSection');
  const generatorSection = document.getElementById('generatorSection');
  const samplePillsBox = document.getElementById('samplePillsBox');

  if (btnModeAnalyze && btnModeGenerate) {
    btnModeAnalyze.addEventListener('click', () => {
      btnModeAnalyze.classList.add('active');
      btnModeGenerate.classList.remove('active');
      analyzerSection.style.display = 'block';
      generatorSection.style.display = 'none';
      if (samplePillsBox) samplePillsBox.style.display = 'flex';
      initLucide();
    });

    btnModeGenerate.addEventListener('click', () => {
      btnModeGenerate.classList.add('active');
      btnModeAnalyze.classList.remove('active');
      analyzerSection.style.display = 'none';
      generatorSection.style.display = 'block';
      if (samplePillsBox) samplePillsBox.style.display = 'none';
      loadVoiceProfiles();
      initLucide();
    });
  }

  // Analyzer Inputs
  const urlInput = document.getElementById('urlInput');
  const btnClear = document.getElementById('btnClear');
  const btnAnalyze = document.getElementById('btnAnalyze');
  const btnCopyReport = document.getElementById('btnCopyReport');
  const btnDownloadReport = document.getElementById('btnDownloadReport');
  const btnCopyTranscript = document.getElementById('btnCopyTranscript');

  if (btnClear) {
    btnClear.addEventListener('click', () => {
      urlInput.value = '';
      urlInput.focus();
    });
  }

  if (urlInput) {
    urlInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        btnAnalyze.click();
      }
    });
  }

  if (btnAnalyze) {
    btnAnalyze.addEventListener('click', () => {
      const url = urlInput.value.trim();
      if (!url) {
        showToast('유튜브 링크를 입력해주세요!');
        return;
      }
      startAnalysis(url);
    });
  }

  // Generator Inputs
  const topicInput = document.getElementById('topicInput');
  const btnGenerate = document.getElementById('btnGenerate');
  const sceneCountSelect = document.getElementById('sceneCountSelect');
  const voiceSelect = document.getElementById('voiceSelect');

  if (topicInput) {
    topicInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        btnGenerate.click();
      }
    });
  }

  if (btnGenerate) {
    btnGenerate.addEventListener('click', () => {
      const topic = topicInput.value.trim();
      const scenes = sceneCountSelect ? parseInt(sceneCountSelect.value) : 10;
      const voice = voiceSelect ? voiceSelect.value : 'ko-KR-InJoonNeural';
      if (!topic) {
        showToast('생성할 영상 주제를 입력해주세요!');
        return;
      }
      startGeneration(topic, scenes, voice);
    });
  }

  // Voice Cloning Modal/Drawer
  const voiceClonePanel = document.getElementById('voiceClonePanel');
  const btnOpenVoiceModal = document.getElementById('btnOpenVoiceModal');
  const btnCloseVoicePanel = document.getElementById('btnCloseVoicePanel');
  const btnRecordVoice = document.getElementById('btnRecordVoice');
  const recordBtnText = document.getElementById('recordBtnText');
  const voiceFileInput = document.getElementById('voiceFileInput');
  const recordedAudioPreview = document.getElementById('recordedAudioPreview');
  const btnSaveVoiceProfile = document.getElementById('btnSaveVoiceProfile');

  if (btnOpenVoiceModal && voiceClonePanel) {
    btnOpenVoiceModal.addEventListener('click', () => {
      voiceClonePanel.classList.remove('hidden');
      voiceClonePanel.style.display = 'flex';
      initLucide();
    });
  }

  if (btnCloseVoicePanel && voiceClonePanel) {
    btnCloseVoicePanel.addEventListener('click', () => {
      voiceClonePanel.classList.add('hidden');
      voiceClonePanel.style.display = 'none';
    });
  }

  // Microphone Recording (Web Audio API)
  if (btnRecordVoice) {
    btnRecordVoice.addEventListener('click', async () => {
      if (!isRecording) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          recordedAudioChunks = [];
          mediaRecorder = new MediaRecorder(stream);

          mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) recordedAudioChunks.push(e.data);
          };

          mediaRecorder.onstop = () => {
            const audioBlob = new Blob(recordedAudioChunks, { type: 'audio/wav' });
            const audioUrl = URL.createObjectURL(audioBlob);
            recordedAudioPreview.src = audioUrl;
            recordedAudioPreview.style.display = 'block';

            // Convert to Base64
            const reader = new FileReader();
            reader.readAsDataURL(audioBlob);
            reader.onloadend = () => {
              currentRecordedBase64 = reader.result;
            };

            // Stop all tracks
            stream.getTracks().forEach(track => track.stop());
          };

          mediaRecorder.start();
          isRecording = true;
          btnRecordVoice.classList.add('recording-red');
          recordBtnText.innerText = '녹음 중... (완료 시 클릭)';
        } catch (err) {
          showToast('마이크 접근 권한이 필요합니다.');
        }
      } else {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
          mediaRecorder.stop();
        }
        isRecording = false;
        btnRecordVoice.classList.remove('recording-red');
        recordBtnText.innerText = '녹음 완료 (다시 녹음)';
      }
    });
  }

  // File Upload
  if (voiceFileInput) {
    voiceFileInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (file) {
        const reader = new FileReader();
        reader.readAsDataURL(file);
        reader.onloadend = () => {
          currentRecordedBase64 = reader.result;
          recordedAudioPreview.src = URL.createObjectURL(file);
          recordedAudioPreview.style.display = 'block';
          showToast(`음성 파일 '${file.name}' 첨부 완료`);
        };
      }
    });
  }

  // Save Voice Profile
  if (btnSaveVoiceProfile) {
    btnSaveVoiceProfile.addEventListener('click', async () => {
      const name = document.getElementById('voiceProfileName').value.trim() || '내 목소리';
      const refText = document.getElementById('voiceRefText').value.trim();

      if (!currentRecordedBase64) {
        showToast('먼저 3초 이상 녹음하거나 음성 파일을 첨부해주세요!');
        return;
      }

      btnSaveVoiceProfile.disabled = true;
      btnSaveVoiceProfile.innerHTML = `<i data-lucide="loader-2" class="spin w-3.5 h-3.5"></i> 저장 및 학습 중...`;
      initLucide();

      try {
        const res = await fetch('/api/voice/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: name,
            ref_text: refText,
            audio_base64: currentRecordedBase64
          })
        });
        const result = await res.json();
        if (result.status === 'success') {
          showToast(`'${name}' 목소리 프로필이 성공적으로 저장되었습니다!`);
          voiceClonePanel.style.display = 'none';
          await loadVoiceProfiles();
          if (voiceSelect) {
            voiceSelect.value = `custom:${result.profile.id}`;
          }
        } else {
          showToast(result.error || '목소리 저장 실패');
        }
      } catch (err) {
        showToast('서버 통신 오류');
      } finally {
        btnSaveVoiceProfile.disabled = false;
        btnSaveVoiceProfile.innerHTML = `<i data-lucide="check" class="w-3.5 h-3.5"></i> 내 목소리 학습 및 영구 저장하기`;
        initLucide();
      }
    });
  }

  // Topic Chips
  document.querySelectorAll('.topic-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const topic = chip.dataset.topic;
      if (topicInput) topicInput.value = topic;
      if (btnGenerate) btnGenerate.click();
    });
  });

  // Generator Actions
  const btnPlayFullAudio = document.getElementById('btnPlayFullAudio');
  const btnDownloadAudioZip = document.getElementById('btnDownloadAudioZip');
  const btnRegenerateAudios = document.getElementById('btnRegenerateAudios');
  const btnCopyAllPrompts = document.getElementById('btnCopyAllPrompts');
  const btnCopyFullScript = document.getElementById('btnCopyFullScript');
  const btnDownloadPlan = document.getElementById('btnDownloadPlan');

  if (btnPlayFullAudio) {
    btnPlayFullAudio.addEventListener('click', () => {
      if (currentPlanData && currentPlanData.audio_data && currentPlanData.audio_data.full_audio_url) {
        const fullAudio = new Audio(currentPlanData.audio_data.full_audio_url);
        fullAudio.play();
        showToast('전체 나레이션을 재생합니다.');
      } else {
        showToast('먼저 오디오를 생성해주세요.');
      }
    });
  }

  if (btnDownloadAudioZip) {
    btnDownloadAudioZip.addEventListener('click', async () => {
      if (currentPlanData && currentPlanData.audio_data && currentPlanData.audio_data.zip_download_url) {
        const link = document.createElement('a');
        link.href = currentPlanData.audio_data.zip_download_url;
        link.download = `${currentPlanData.topic || 'video'}_전체오디오_일괄다운로드.zip`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showToast('전체 씬 오디오 ZIP 파일을 다운로드합니다!');
      } else {
        showToast('먼저 오디오를 생성해주세요 (씬별 오디오 재생성 클릭).');
      }
    });
  }

  if (btnRegenerateAudios) {
    btnRegenerateAudios.addEventListener('click', async () => {
      if (!currentPlanData || !currentPlanData.structured_scenes) {
        showToast('기획서 씬 데이터가 없습니다.');
        return;
      }
      const voice = voiceSelect ? voiceSelect.value : 'ko-KR-InJoonNeural';
      btnRegenerateAudios.disabled = true;
      btnRegenerateAudios.innerHTML = `<i data-lucide="loader-2" class="spin w-3 h-3"></i> 오디오 생성 중...`;
      initLucide();

      try {
        const res = await fetch('/api/tts/generate-scenes', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            topic: currentPlanData.topic,
            scenes: currentPlanData.structured_scenes,
            voice_id: voice
          })
        });
        const result = await res.json();
        if (result.status === 'success' && result.data) {
          currentPlanData.audio_data = result.data;
          renderGenerationResults(currentPlanData, currentPlanData.structured_scenes.length);
          showToast('모든 씬의 나레이션 오디오와 ZIP 파일이 생성되었습니다!');
        }
      } catch (err) {
        showToast('오디오 생성 중 오류');
      } finally {
        btnRegenerateAudios.disabled = false;
        btnRegenerateAudios.innerHTML = `<i data-lucide="refresh-cw" class="w-3 h-3"></i> 오디오 재생성`;
        initLucide();
      }
    });
  }

  if (btnCopyAllPrompts) {
    btnCopyAllPrompts.addEventListener('click', () => {
      if (currentPlanData && currentPlanData.prompts_text) {
        copyToClipboard(currentPlanData.prompts_text, '전체 씬의 AI 비디오 생성 프롬프트가 복사되었습니다!');
      }
    });
  }

  if (btnCopyFullScript) {
    btnCopyFullScript.addEventListener('click', () => {
      if (currentPlanData && currentPlanData.scenes_text) {
        copyToClipboard(currentPlanData.scenes_text, '8초 씬별 전체 나레이션 대본이 복사되었습니다!');
      }
    });
  }

  if (btnDownloadPlan) {
    btnDownloadPlan.addEventListener('click', () => {
      if (currentPlanData && currentPlanData.full_document) {
        downloadFile(`${currentPlanData.topic || 'video'}_콘텐츠기획.txt`, currentPlanData.full_document);
      }
    });
  }

  // Sample Buttons
  document.querySelectorAll('.sample-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.sample-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const vid = btn.dataset.id;
      loadVideoData(vid);
    });
  });

  // Tabs
  document.querySelectorAll('.tab-btn').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      tab.classList.add('active');
      const targetId = tab.dataset.target;
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add('active');
    });
  });

  // Copy & Download for Report
  if (btnCopyReport) {
    btnCopyReport.addEventListener('click', () => {
      if (currentReportData && currentReportData.report) {
        copyToClipboard(currentReportData.report, '리포트 전문이 클립보드에 복사되었습니다.');
      }
    });
  }

  if (btnDownloadReport) {
    btnDownloadReport.addEventListener('click', () => {
      if (currentReportData && currentReportData.report) {
        downloadFile(`${currentReportData.id || 'youtube'}_분석리포트.txt`, currentReportData.report);
      }
    });
  }

  if (btnCopyTranscript) {
    btnCopyTranscript.addEventListener('click', () => {
      if (currentReportData && currentReportData.transcript) {
        copyToClipboard(currentReportData.transcript, '타임스탬프 자막 전문이 복사되었습니다.');
      }
    });
  }
}

// 4. Load Cached or Specific Video Data
async function loadVideoData(vid) {
  try {
    const res = await fetch(`/api/report?id=${vid}`);
    const result = await res.json();
    if (result.status === 'success' && result.data) {
      renderDashboard(result.data);
      setSampleBadge(true);
      const urlInput = document.getElementById('urlInput');
      if (urlInput) urlInput.value = result.data.url || `https://youtu.be/${vid}`;
    }
  } catch (err) {
    console.error('Error loading video data:', err);
  }
}

// 5. Start Live Analysis
async function startAnalysis(url) {
  const btnAnalyze = document.getElementById('btnAnalyze');
  const progressBox = document.getElementById('analysisProgress');
  const progressFill = document.getElementById('progressBarFill');
  const statusMsg = document.getElementById('progressStatusMsg');

  btnAnalyze.classList.add('loading');
  btnAnalyze.innerHTML = `<i data-lucide="loader-2" class="spin w-4 h-4"></i> <span>분석 중...</span>`;
  initLucide();

  progressBox.style.display = 'block';
  progressFill.style.width = '20%';
  setStepActive('step1');
  statusMsg.innerText = '1/4 영상 메타데이터 및 통계 수집 중...';

  let stepTimer = setTimeout(() => {
    progressFill.style.width = '45%';
    setStepActive('step2');
    statusMsg.innerText = '2/4 타임스탬프 자막 및 스크립트 추출 중...';
  }, 2500);

  let stepTimer2 = setTimeout(() => {
    progressFill.style.width = '70%';
    setStepActive('step3');
    statusMsg.innerText = '3/4 상위 댓글 및 시청자 반응 수집 중...';
  }, 5000);

  let stepTimer3 = setTimeout(() => {
    progressFill.style.width = '90%';
    setStepActive('step4');
    statusMsg.innerText = '4/4 로컬 AI 3단계 분할 심층 분석 진행 중...';
  }, 8000);

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const result = await res.json();

    clearTimeout(stepTimer);
    clearTimeout(stepTimer2);
    clearTimeout(stepTimer3);

    if (result.status === 'success' && result.data) {
      progressFill.style.width = '100%';
      document.querySelectorAll('#analysisProgress .step-item').forEach(s => s.classList.add('done'));
      statusMsg.innerText = '✅ 분석 완료!';

      setTimeout(() => {
        progressBox.style.display = 'none';
        renderDashboard(result.data);
        setSampleBadge(false);
        showToast('유튜브 영상 분석이 성공적으로 완료되었습니다!');
      }, 700);
    } else {
      statusMsg.innerText = `❌ 오류: ${result.error || '분석 실패'}`;
      showToast(result.error || '분석 중 오류가 발생했습니다.');
    }
  } catch (err) {
    statusMsg.innerText = `❌ 네트워크 오류: ${err.message}`;
    showToast('서버 통신 오류가 발생했습니다.');
  } finally {
    btnAnalyze.classList.remove('loading');
    btnAnalyze.innerHTML = `<i data-lucide="sparkles" class="w-4 h-4"></i> <span>분석 시작</span>`;
    initLucide();
  }
}

// 6. Start Generation for New Topic (8-Sec Video Pipeline + Scene Audios)
async function startGeneration(topic, scenes = 10, voice_id = "ko-KR-InJoonNeural") {
  const btnGenerate = document.getElementById('btnGenerate');
  const progressBox = document.getElementById('genProgress');
  const progressFill = document.getElementById('genProgressBarFill');
  const statusMsg = document.getElementById('genStatusMsg');
  const resultsSection = document.getElementById('genResultsSection');

  btnGenerate.classList.add('loading');
  btnGenerate.innerHTML = `<i data-lucide="loader-2" class="spin w-4 h-4"></i> <span>기획 & 음성 생성 중...</span>`;
  initLucide();

  progressBox.style.display = 'block';
  progressFill.style.width = '20%';
  setGenStepActive('genStep1');
  statusMsg.innerText = `1/4 '${topic}' 훅 제목 및 설명란 기획 중...`;

  let timer1 = setTimeout(() => {
    progressFill.style.width = '50%';
    setGenStepActive('genStep2');
    statusMsg.innerText = `2/4 8초 단위 씬별 타임스탬프 나레이션 대본 작성 중 (${scenes}개 씬)...`;
  }, 4000);

  let timer2 = setTimeout(() => {
    progressFill.style.width = '75%';
    setGenStepActive('genStep3');
    statusMsg.innerText = `3/4 씬별 AI 비디오 생성 프롬프트(Runway/Kling) 작성 중...`;
  }, 8000);

  let timer3 = setTimeout(() => {
    progressFill.style.width = '90%';
    statusMsg.innerText = `4/4 각 씬별 고음질 나레이션 오디오 파일 합성 중...`;
  }, 12000);

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic, scenes, voice_id, generate_audio: true })
    });
    const result = await res.json();

    clearTimeout(timer1);
    clearTimeout(timer2);
    clearTimeout(timer3);

    if (result.status === 'success' && result.data) {
      progressFill.style.width = '100%';
      document.querySelectorAll('#genProgress .step-item').forEach(s => s.classList.add('done'));
      statusMsg.innerText = '✅ 8초 비디오 기획, 프롬프트 및 씬별 오디오 생성 완료!';

      setTimeout(() => {
        progressBox.style.display = 'none';
        renderGenerationResults(result.data, scenes);
        resultsSection.style.display = 'block';
        resultsSection.scrollIntoView({ behavior: 'smooth' });
        showToast(`'${topic}' 영상 기획서와 씬별 오디오가 완성되었습니다!`);
      }, 700);
    } else {
      statusMsg.innerText = `❌ 오류: ${result.error || '생성 실패'}`;
      showToast(result.error || '생성 중 오류가 발생했습니다.');
    }
  } catch (err) {
    statusMsg.innerText = `❌ 네트워크 오류: ${err.message}`;
    showToast('생성 서버와 통신 중 오류가 발생했습니다.');
  } finally {
    btnGenerate.classList.remove('loading');
    btnGenerate.innerHTML = `<i data-lucide="film" class="w-4 h-4"></i> <span>비디오 기획 & 음성 생성</span>`;
    initLucide();
  }
}

// 샘플 데이터인지 실제 분석 결과인지 배지로 구분 표시
function setSampleBadge(isSample) {
  const badge = document.getElementById('sampleDataBadge');
  if (badge) badge.style.display = isSample ? 'inline-flex' : 'none';
}

function setStepActive(stepId) {
  document.querySelectorAll('#analysisProgress .step-item').forEach(s => s.classList.remove('active'));
  const el = document.getElementById(stepId);
  if (el) el.classList.add('active');
}

function setGenStepActive(stepId) {
  document.querySelectorAll('#genProgress .step-item').forEach(s => s.classList.remove('active'));
  const el = document.getElementById(stepId);
  if (el) el.classList.add('active');
}

// 7. Render Generation Results (Titles, SEO Desc, 8-Sec Scene Cards with Audio Player)
function renderGenerationResults(data, numScenes = 10) {
  currentPlanData = data;

  // Header & Badges
  const topicBadge = document.getElementById('genTopicBadge');
  const mainTitle = document.getElementById('genMainTitle');
  const durationBadge = document.getElementById('totalDurationBadge');

  if (topicBadge) topicBadge.innerText = `주제: ${data.topic || '신규 주제'}`;
  if (mainTitle) mainTitle.innerText = `[${data.topic || '기획'}] 8초 비디오 제작 플레이북`;
  if (durationBadge) durationBadge.innerText = `총 ${numScenes}개 씬 (${numScenes * 8}초 분량)`;

  // Titles & Description Markdown
  const titlesContent = document.getElementById('genTitlesContent');
  const descContent = document.getElementById('genDescContent');

  if (titlesContent) {
    titlesContent.innerHTML = window.marked ? window.marked.parse(data.meta_text || '') : data.meta_text;
  }
  if (descContent) {
    descContent.innerHTML = window.marked ? window.marked.parse(data.scenes_text || '') : data.scenes_text;
  }

  // Audio map if available
  const audioMap = {};
  if (data.audio_data && data.audio_data.scenes_audio) {
    data.audio_data.scenes_audio.forEach(sa => {
      audioMap[sa.scene_num] = sa.audio_url;
    });
  }

  // 8-Second Scene Cards Grid
  // 서버가 파싱한 structured_scenes를 우선 사용 → 화면 자막과 TTS 녹음 내용이 항상 일치
  const scenesGrid = document.getElementById('scenesGrid');
  if (scenesGrid) {
    const rawScenesText = data.scenes_text || '';
    const rawPromptsText = data.prompts_text || '';
    const structured = Array.isArray(data.structured_scenes) ? data.structured_scenes : [];

    let cardsHtml = '';
    for (let i = 1; i <= numScenes; i++) {
      const sc = structured[i - 1] || null;
      const startSec = (i - 1) * 8;
      const endSec = i * 8;
      const timeStr = (sc && sc.time_range) ||
        `${String(Math.floor(startSec / 60)).padStart(2, '0')}:${String(startSec % 60).padStart(2, '0')} ~ ${String(Math.floor(endSec / 60)).padStart(2, '0')}:${String(endSec % 60).padStart(2, '0')}`;

      let subtitle = sc ? (sc.subtitle || '') : '';
      let promptEn = (sc && sc.prompt_en) || '';
      let camera = (sc && sc.camera) || '';

      // 구버전 데이터(structured_scenes 없음) 대비 텍스트 재파싱 폴백
      if (!sc) {
        const subMatch = rawScenesText.match(new RegExp(`씬\\s*${i}[^\\n]*\\n([\\s\\S]*?)(?=씬\\s*${i + 1}|\\Z)`));
        if (subMatch) {
          const body = subMatch[1];
          const quoteMatch = body.match(/"([^"]+)"/);
          if (quoteMatch) {
            subtitle = quoteMatch[1];
          } else {
            const lines = body.split('\n').map(l => l.replace(/[\*\#]/g, '').trim()).filter(l => l.length > 5);
            if (lines.length > 0) subtitle = lines[0];
          }
        }
        const promptMatch = rawPromptsText.match(new RegExp(`씬\\s*${i}[^\\n]*\\n([\\s\\S]*?)(?=씬\\s*${i + 1}|\\Z)`));
        if (promptMatch) {
          const pBody = promptMatch[1];
          const enMatch = pBody.match(/(?:Scene Prompt|Prompt|프롬프트)[^:\n]*:\s*([^\n]+)/i);
          if (enMatch) promptEn = enMatch[1].replace(/[\*]/g, '').trim();
          const camMatch = pBody.match(/(?:Camera|카메라)[^:\n]*:\s*([^\n]+)/i);
          if (camMatch) camera = camMatch[1].replace(/[\*]/g, '').trim();
        }
      }

      const parseFailed = !subtitle;
      if (!promptEn) promptEn = `Cinematic documentary 8k footage of ${data.topic || 'scene'}, hyper-detailed, photorealistic, dramatic lighting, masterpiece --ar 16:9`;
      if (!camera) camera = 'Slow cinematic push-in shot';

      const audioUrl = audioMap[i];

      cardsHtml += `
        <div class="glass-card rounded-xl p-5 border-l-2 border-l-black flex flex-col gap-3 relative overflow-hidden">
          <div class="flex justify-between items-center">
            <span class="font-mono font-bold text-xs text-black bg-neutral-100 px-2.5 py-0.5 rounded border border-neutral-200 tracking-wider">SCENE 0${i}</span>
            <span class="text-[11px] font-mono text-neutral-500 flex items-center gap-1">
              <i data-lucide="clock" class="w-3 h-3"></i> ${timeStr} (8초)
            </span>
          </div>

          <div class="bg-neutral-50 rounded-lg p-3 border border-neutral-200/60 space-y-1">
            <div class="text-[10px] font-mono font-bold uppercase tracking-wider text-neutral-400 flex items-center gap-1">
              <i data-lucide="mic" class="w-3 h-3"></i> 나레이션 자막 대본
            </div>
            ${parseFailed ? `
              <p class="text-xs text-amber-700 font-medium leading-relaxed flex items-center gap-1">
                <i data-lucide="alert-triangle" class="w-3 h-3"></i> 대본 파싱 실패 — '대본 복사'에서 원문을 확인하세요.
              </p>
            ` : `
              <p class="text-xs text-neutral-900 font-medium leading-relaxed">"${escapeHtml(subtitle)}"</p>
            `}
          </div>

          <!-- Scene Audio Player -->
          <div class="bg-white rounded-lg p-2.5 border border-neutral-200 space-y-1.5">
            <div class="flex justify-between items-center">
              <span class="text-xs font-bold text-black flex items-center gap-1">
                <i data-lucide="volume-2" class="w-3 h-3"></i> 씬 ${i} 나레이션
              </span>
              <div class="flex items-center gap-1.5">
                <span class="text-[10px] px-1.5 py-0.2 rounded bg-neutral-100 text-neutral-600 font-mono font-medium border border-neutral-200">8s Sync</span>
                ${audioUrl ? `
                  <a href="${audioUrl}" download="씬${i}_0${i}_나레이션.mp3" class="px-2 py-0.5 rounded bg-black text-white text-[11px] font-semibold hover:bg-neutral-800 transition-all flex items-center gap-1">
                    <i data-lucide="download" class="w-2.5 h-2.5"></i> 다운
                  </a>
                ` : ''}
              </div>
            </div>
            ${audioUrl ? `
              <audio controls src="${audioUrl}" class="w-full h-7 rounded mt-1" preload="none"></audio>
            ` : (parseFailed ? `
              <p class="text-[11px] text-amber-700">대본이 없어 이 씬의 오디오는 생성되지 않았습니다.</p>
            ` : `
              <p class="text-[11px] text-neutral-400">상단 '오디오 재생성'을 누르면 즉시 합성됩니다.</p>
            `)}
          </div>

          <!-- AI Video Prompt -->
          <div class="bg-neutral-50 rounded-lg p-3 border border-neutral-200/60 space-y-1.5">
            <div class="flex justify-between items-center">
              <span class="text-[10px] font-mono font-bold uppercase tracking-wider text-neutral-500 flex items-center gap-1">
                <i data-lucide="palette" class="w-3 h-3"></i> Runway / Kling 프롬프트
              </span>
              <button class="btn-copy-prompt px-2 py-0.5 rounded bg-white border border-neutral-200 text-xs text-neutral-700 hover:border-black hover:text-black transition-all flex items-center gap-1" data-prompt="${escapeHtml(promptEn)}">
                <i data-lucide="copy" class="w-2.5 h-2.5"></i> 복사
              </button>
            </div>
            <p class="font-mono text-xs text-neutral-800 bg-white p-2 rounded border border-neutral-200 leading-relaxed">${escapeHtml(promptEn)}</p>
            <div class="flex items-center gap-1 text-[11px] text-neutral-500">
              <i data-lucide="video" class="w-3 h-3 text-neutral-400"></i> <span>${escapeHtml(camera)}</span>
            </div>
          </div>
        </div>
      `;
    }

    scenesGrid.innerHTML = cardsHtml;

    // 프롬프트 복사 버튼 — data 속성 방식 (특수문자가 있어도 안전)
    scenesGrid.querySelectorAll('.btn-copy-prompt').forEach(btn => {
      btn.addEventListener('click', () => {
        copyToClipboard(btn.dataset.prompt || '', '8초 영상 생성 프롬프트가 복사되었습니다!');
      });
    });
  }

  initLucide();
}

// 8. Render All Dashboard Components (Analyzer Mode)
function renderDashboard(data) {
  currentReportData = data;
  const info = data.info || {};

  // Header & Meta
  document.getElementById('videoTitle').innerText = info.title || '제목 없음';
  document.getElementById('channelName').innerText = info.channel || '채널명 미상';
  document.getElementById('videoDuration').innerText = info.duration_string || '00:00';
  document.getElementById('uploadDate').innerText = info.upload_date ? `${formatDate(info.upload_date)} 게시` : '';

  if (info.thumbnail) {
    document.getElementById('videoThumb').src = info.thumbnail;
  }
  if (data.id) {
    document.getElementById('videoLink').href = `https://youtu.be/${data.id}`;
  }

  if (info.channel_follower_count) {
    document.getElementById('channelSubs').innerText = `구독자 ${formatNumber(info.channel_follower_count)}명`;
  } else {
    document.getElementById('channelSubs').innerText = `구독자 정보 비공개`;
  }

  // Metrics
  const views = info.view_count || 0;
  const likes = info.like_count || 0;
  const comments = info.comment_count || 0;

  document.getElementById('viewCount').innerText = views.toLocaleString();
  document.getElementById('likeCount').innerText = likes ? likes.toLocaleString() : '-';
  document.getElementById('commentCount').innerText = comments ? comments.toLocaleString() : '-';

  if (views > 0 && (likes || comments)) {
    const rate = (((likes + comments) / views) * 100).toFixed(2);
    document.getElementById('engagementRate').innerText = `${rate}%`;
  } else {
    document.getElementById('engagementRate').innerText = `2.4% (추정)`;
  }

  // Render Subtitles / Transcript with Timestamps
  renderTimestampedTranscript(data.transcript || '', data.id);

  // Render Top Comments if available
  renderTopComments(data.comments || []);

  // Parse and Render AI Report Visuals
  const reportText = data.report || '';
  renderMarkdownReport(reportText);
  parseReportToVisuals(reportText, info);

  initLucide();
}

// 9. Parse AI Report to Visual Cards
function parseReportToVisuals(report, info) {
  if (!report) return;

  const title = info.title || '';

  // 1. Hook Extraction
  const hookAnalysisEl = document.getElementById('hookAnalysisText');
  const hookPart1El = document.getElementById('hookPart1');
  const hookPart2El = document.getElementById('hookPart2');

  if (title.includes(',')) {
    const parts = title.split(',');
    hookPart1El.innerText = `"${parts[0].trim()}"`;
    hookPart2El.innerText = `"${parts.slice(1).join(',').trim()}"`;
  } else if (title.includes('-')) {
    const parts = title.split('-');
    hookPart1El.innerText = `"${parts[0].trim()}"`;
    hookPart2El.innerText = `"${parts.slice(1).join('-').trim()}"`;
  } else {
    hookPart1El.innerText = `"${title.slice(0, Math.floor(title.length / 2))}"`;
    hookPart2El.innerText = `"${title.slice(Math.floor(title.length / 2))}"`;
  }

  // Extract Hook Section Prose
  const hookMatch = report.match(/###\s*1\.\s*제목·훅[^\n]*\n([\s\S]*?)(?=###\s*2\.|$)/);
  if (hookMatch && hookAnalysisEl) {
    const cleanProse = hookMatch[1].replace(/\*\*|__|#|\*/g, '').trim();
    hookAnalysisEl.innerText = cleanProse.slice(0, 240) + '...';
  }

  // 3. Core Message Extraction (새 디자인 ID: coreMessageText)
  const coreQuoteEl = document.getElementById('coreMessageText');
  const coreMatch = report.match(/###\s*3\.\s*핵심\s*메시지[^\n]*\n([\s\S]*?)(?=###\s*4\.|$)/);
  if (coreMatch && coreQuoteEl) {
    const lines = coreMatch[1].split('\n').map(l => l.trim()).filter(l => l.length > 10);
    if (lines.length > 0) {
      coreQuoteEl.innerText = `"${lines[0].replace(/^[#\*\-:\s]+|[\*"]/g, '')}"`;
    }
  }

  // 5. 내 채널 적용 플레이북 — 리포트의 '### 5.' 섹션을 그대로 렌더 (실데이터)
  const playbookEl = document.getElementById('playbookContent');
  const playMatch = report.match(/#{2,3}\s*5[\.\)]\s*[^\n]*\n([\s\S]*?)$/);
  if (playbookEl && playMatch) {
    playbookEl.innerHTML = window.marked ? window.marked.parse(playMatch[1].trim()) : playMatch[1];
  }
}

// 10. Render Top Comments
function renderTopComments(comments) {
  const list = document.getElementById('topCommentsList');
  if (!list) return;

  if (!comments || comments.length === 0) {
    list.innerHTML = `
      <p class="text-xs text-neutral-400">댓글 분석 데이터를 준비 중이거나 댓글이 비활성화된 영상입니다.</p>
    `;
    return;
  }

  list.innerHTML = comments.slice(0, 4).map(c => `
    <div class="bg-neutral-50 rounded-lg p-3 border border-neutral-200/60">
      <div class="flex justify-between items-center mb-1">
        <span class="text-xs font-bold text-black">${escapeHtml(c.author || '시청자')}</span>
        <span class="text-[11px] text-neutral-400 font-mono flex items-center gap-1"><i data-lucide="thumbs-up" class="w-3 h-3"></i> ${(c.like_count || 0).toLocaleString()}</span>
      </div>
      <p class="text-xs text-neutral-600 leading-relaxed">${escapeHtml(c.text || '')}</p>
    </div>
  `).join('');
}

// 11. Render Timestamped Transcript
function renderTimestampedTranscript(transcriptText, vid) {
  const container = document.getElementById('transcriptContainer');
  if (!container) return;

  if (!transcriptText || transcriptText.trim() === '(자막 없음)') {
    container.innerHTML = `
      <div class="transcript-row">
        <span class="transcript-text text-neutral-400">자막(스크립트)이 제공되지 않거나 비활성화된 영상입니다.</span>
      </div>
    `;
    return;
  }

  const lines = transcriptText.split('\n').filter(l => l.trim().length > 0);
  let html = '';

  lines.forEach(line => {
    const match = line.match(/^\[(\d{2}:\d{2})\]\s*(.*)$/);
    if (match) {
      const timeStr = match[1];
      const text = match[2];
      const [m, s] = timeStr.split(':').map(Number);
      const totalSec = m * 60 + s;
      const ytUrl = vid ? `https://youtu.be/${vid}?t=${totalSec}` : '#';

      html += `
        <div class="transcript-row" data-text="${escapeHtml(text.toLowerCase())}">
          <a href="${ytUrl}" target="_blank" class="time-badge" title="유튜브 해당 시점으로 이동">
            <i data-lucide="play-circle"></i> ${timeStr}
          </a>
          <span class="transcript-text">${escapeHtml(text)}</span>
        </div>
      `;
    } else {
      html += `
        <div class="transcript-row" data-text="${escapeHtml(line.toLowerCase())}">
          <span class="time-badge"><i data-lucide="align-left"></i> 자막</span>
          <span class="transcript-text">${escapeHtml(line)}</span>
        </div>
      `;
    }
  });

  container.innerHTML = html;
  setupTranscriptSearch();
  initLucide();
}

function setupTranscriptSearch() {
  const searchInput = document.getElementById('transcriptSearchInput');
  if (!searchInput) return;

  searchInput.addEventListener('input', (e) => {
    const query = e.target.value.trim().toLowerCase();
    const rows = document.querySelectorAll('.transcript-row');

    rows.forEach(row => {
      const rowText = row.dataset.text || '';
      if (!query || rowText.includes(query)) {
        row.style.display = 'flex';
        if (query) {
          row.classList.add('highlight');
        } else {
          row.classList.remove('highlight');
        }
      } else {
        row.style.display = 'none';
        row.classList.remove('highlight');
      }
    });
  });
}

// 12. Render Markdown AI Report
function renderMarkdownReport(markdownText) {
  const container = document.getElementById('markdownReportContent');
  if (!container) return;

  if (window.marked) {
    container.innerHTML = window.marked.parse(markdownText || '(생성된 리포트가 없습니다)');
  } else {
    container.innerText = markdownText;
  }
}

// 13. Helpers & Utilities
function copyToClipboard(text, successMsg = '클립보드에 복사되었습니다.') {
  navigator.clipboard.writeText(text).then(() => {
    showToast(successMsg);
  }).catch(() => {
    showToast('복사 실패');
  });
}

function downloadFile(filename, content) {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  showToast(`'${filename}' 파일이 다운로드되었습니다.`);
}

function showToast(msg) {
  const toast = document.getElementById('toast');
  const toastMsg = document.getElementById('toastMsg');
  toastMsg.innerText = msg;
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
  }, 3000);
}

function formatNumber(num) {
  if (num >= 100000000) return (num / 100000000).toFixed(1) + '억';
  if (num >= 10000) return (num / 10000).toFixed(1) + '만';
  return num.toLocaleString();
}

function formatDate(dateStr) {
  if (dateStr && dateStr.length === 8) {
    return `${dateStr.slice(0, 4)}.${dateStr.slice(4, 6)}.${dateStr.slice(6, 8)}`;
  }
  return dateStr || '';
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
