document.addEventListener('DOMContentLoaded', () => {
  // DOM 요소
  const analyzeForm = document.getElementById('analyzeForm');
  const videoUrlInput = document.getElementById('videoUrl');
  const chkSubtitles = document.getElementById('chkSubtitles');
  const chkComments = document.getElementById('chkComments');
  const chkAutoAiReport = document.getElementById('chkAutoAiReport');
  const commentLimit = document.getElementById('commentLimit');
  const btnAnalyze = document.getElementById('btnAnalyze');
  const alertBox = document.getElementById('alertBox');
  
  const recentResultSection = document.getElementById('recentResultSection');
  const recentResultsContainer = document.getElementById('recentResultsContainer');
  const resultCountBadge = document.getElementById('resultCountBadge');

  const historyTableBody = document.getElementById('historyTableBody');
  const totalHistoryCount = document.getElementById('totalHistoryCount');
  const historySearch = document.getElementById('historySearch');
  const btnRefreshHistory = document.getElementById('btnRefreshHistory');

  const btnOpenFolder = document.getElementById('btnOpenFolder');
  const btnExportCsv = document.getElementById('btnExportCsv');
  const btnThemeToggle = document.getElementById('btnThemeToggle');

  const detailModal = document.getElementById('detailModal');
  const btnCloseModal = document.getElementById('btnCloseModal');
  const modalTitle = document.getElementById('modalTitle');
  const modalChapterCount = document.getElementById('modalChapterCount');
  const modalCommentCount = document.getElementById('modalCommentCount');
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabPanes = document.querySelectorAll('.tab-pane');

  // LLM 상태 배지 요소
  const llmStatusBadge = document.getElementById('llmStatusBadge');
  const llmBackendName = document.getElementById('llmBackendName');
  const llmModelBadge = document.getElementById('llmModelBadge');

  let historyData = [];
  let currentZipDownloadUrl = null;

  // XSS 방어 헬퍼 (Zero-Trust Contextual Escaping)
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // 1. 테마 토글
  btnThemeToggle.addEventListener('click', () => {
    document.body.classList.toggle('light-theme');
    const isLight = document.body.classList.contains('light-theme');
    btnThemeToggle.innerHTML = isLight 
      ? '<i class="fa-solid fa-sun" style="color:#f59e0b"></i>' 
      : '<i class="fa-solid fa-moon"></i>';
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
  });

  if (localStorage.getItem('theme') === 'light') {
    document.body.classList.add('light-theme');
    btnThemeToggle.innerHTML = '<i class="fa-solid fa-sun" style="color:#f59e0b"></i>';
  }

  // 2. 알림창 유틸
  function showAlert(message, type = 'error') {
    alertBox.className = `alert-box alert-${type}`;
    alertBox.innerHTML = type === 'error' 
      ? `<i class="fa-solid fa-triangle-exclamation"></i> <span>${escapeHtml(message)}</span>`
      : `<i class="fa-solid fa-circle-check"></i> <span>${escapeHtml(message)}</span>`;
    alertBox.style.display = 'flex';
    setTimeout(() => {
      alertBox.style.display = 'none';
    }, 7000);
  }

  function formatNumber(num) {
    if (!num) return '0';
    return Number(num).toLocaleString('ko-KR');
  }

  function formatFollowers(num) {
    if (!num) return '비공개';
    if (num >= 100000000) return `${(num / 100000000).toFixed(1)}억명`;
    if (num >= 10000) return `${(num / 10000).toFixed(1)}만명`;
    return `${formatNumber(num)}명`;
  }

  // ==============================================================
  // LLM 실시간 상태 감지 및 클릭 전환
  // ==============================================================
  async function pollLLMStatus() {
    try {
      const res = await fetch('/api/llm/status');
      if (!res.ok) return;
      const data = await res.json();
      const dot = llmStatusBadge.querySelector('.status-dot');

      if (data.active) {
        dot.className = 'status-dot online';
        const prefLabel = data.preference === 'auto' ? 'Auto' : data.active.name;
        llmBackendName.textContent = `${data.active.name} (${prefLabel})`;
        llmModelBadge.textContent = data.active.model || '온라인';
        llmModelBadge.style.display = 'inline-block';
      } else {
        dot.className = 'status-dot offline';
        llmBackendName.textContent = '로컬 AI 꺼짐';
        llmModelBadge.textContent = 'LM Studio/Ollama 실행 필요';
        llmModelBadge.style.display = 'inline-block';
      }
    } catch (e) {
      console.warn('LLM 상태 조회 실패:', e);
    }
  }

  llmStatusBadge.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/llm/status');
      const data = await res.json();
      const currentPref = data.preference || 'auto';
      // auto -> lmstudio -> ollama -> auto 순환
      const nextPref = currentPref === 'auto' ? 'lmstudio' : currentPref === 'lmstudio' ? 'ollama' : 'auto';

      const selectRes = await fetch('/api/llm/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend: nextPref })
      });
      const selectData = await selectRes.json();
      showAlert(`로컬 AI 백엔드가 [${selectData.preference.toUpperCase()}] 모드로 변경되었습니다.`, 'success');
      pollLLMStatus();
    } catch (e) {
      showAlert('백엔드 전환 오류: ' + e.message, 'error');
    }
  });

  pollLLMStatus();
  setInterval(pollLLMStatus, 10000);

  // 3. 분석 폼 제출
  analyzeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = videoUrlInput.value.trim();
    if (!url) return;

    btnAnalyze.disabled = true;
    btnAnalyze.querySelector('.btn-text').style.display = 'none';
    btnAnalyze.querySelector('.spinner').style.display = 'inline-block';
    alertBox.style.display = 'none';

    try {
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url,
          extract_subtitles: chkSubtitles.checked,
          extract_comments: chkComments.checked,
          max_comments: parseInt(commentLimit.value, 10),
          auto_generate_ai_report: chkAutoAiReport.checked
        })
      });

      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || '분석 중 오류가 발생했습니다.');
      }

      renderRecentResults(result.data);
      showAlert(`성공적으로 ${result.count}건의 메타데이터 및 댓글을 수집했습니다!`, 'success');
      videoUrlInput.value = '';
      loadHistory();

      if (result.data && result.data.length > 0) {
        openDetailModal(result.data[0].id, 'tabOverview');
      }
    } catch (err) {
      showAlert(err.message, 'error');
    } finally {
      btnAnalyze.disabled = false;
      btnAnalyze.querySelector('.btn-text').style.display = 'inline-block';
      btnAnalyze.querySelector('.spinner').style.display = 'none';
    }
  });

  // 4. 최근 분석 결과 카드 렌더링
  function renderRecentResults(items) {
    if (!items || items.length === 0) {
      recentResultSection.style.display = 'none';
      return;
    }

    resultCountBadge.textContent = `${items.length}건 수집 완료`;
    recentResultsContainer.innerHTML = '';

    items.forEach(item => {
      const card = document.createElement('div');
      card.className = 'result-card';
      const info = item.info || item;
      const commentsCount = item.comments ? item.comments.length : 0;

      card.innerHTML = `
        <div class="result-thumb-wrapper">
          <img src="${escapeHtml(info.thumbnail)}" alt="${escapeHtml(info.title)}" class="result-thumb">
          <span class="duration-badge">${escapeHtml(info.duration_string || '00:00')}</span>
        </div>
        <div class="result-info">
          <h4 class="result-title">${escapeHtml(info.title)}</h4>
          <div class="result-channel">
            <i class="fa-solid fa-circle-user"></i> ${escapeHtml(info.channel)}
          </div>
          <div class="result-stats">
            <span><i class="fa-solid fa-eye"></i> ${formatNumber(info.view_count)}</span>
            <span><i class="fa-solid fa-thumbs-up"></i> ${formatNumber(info.like_count)}</span>
            <span><i class="fa-solid fa-comments"></i> ${formatNumber(commentsCount)}</span>
          </div>
          <div class="result-actions">
            <button class="btn btn-sm btn-outline btn-view-detail" data-id="${escapeHtml(item.id)}">
              <i class="fa-solid fa-magnifying-glass"></i> 상세 확인
            </button>
            <button class="btn btn-sm btn-primary btn-open-prompt-studio" data-id="${escapeHtml(item.id)}">
              <i class="fa-solid fa-wand-magic-sparkles"></i> 이 영상으로 기획
            </button>
          </div>
        </div>
      `;
      recentResultsContainer.appendChild(card);
    });

    recentResultSection.style.display = 'block';
  }

  // 5. 히스토리 로드 및 렌더링
  async function loadHistory() {
    try {
      const response = await fetch('/api/history');
      const result = await response.json();
      if (result.status === 'success') {
        historyData = result.data || [];
        renderHistoryTable(historyData);
      }
    } catch (e) {
      console.error('히스토리 로드 실패:', e);
    }
  }

  function renderHistoryTable(data) {
    totalHistoryCount.textContent = `${data.length}개 영상`;
    if (data.length === 0) {
      historyTableBody.innerHTML = `
        <tr>
          <td colspan="9" class="text-center py-4 text-muted">
            수집된 데이터가 없습니다. 상단에서 URL을 입력해 분석을 시작하세요.
          </td>
        </tr>
      `;
      return;
    }

    historyTableBody.innerHTML = data.map(item => `
      <tr>
        <td>
          <img src="${escapeHtml(item.thumbnail)}" class="table-thumb" alt="thumb">
        </td>
        <td>
          <div class="table-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
          <div class="table-channel text-muted">${escapeHtml(item.channel)} (${formatFollowers(item.channel_follower_count)})</div>
        </td>
        <td>${escapeHtml(item.duration_string || '00:00')}</td>
        <td>${formatNumber(item.view_count)}</td>
        <td>${formatNumber(item.like_count)}</td>
        <td>${formatNumber(item.comments_extracted || item.comment_count)}</td>
        <td>
          ${item.has_ai_report 
            ? '<span class="badge badge-success"><i class="fa-solid fa-check"></i> 완료</span>' 
            : '<span class="badge badge-warning">미생성</span>'}
        </td>
        <td>${escapeHtml(item.upload_date)}</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-sm btn-outline btn-view-detail" data-id="${escapeHtml(item.id)}" title="상세 모달">
              <i class="fa-solid fa-file-lines"></i> 상세
            </button>
            <button class="btn btn-sm btn-primary btn-open-prompt-studio" data-id="${escapeHtml(item.id)}" title="프롬프트 스튜디오">
              <i class="fa-solid fa-wand-magic-sparkles"></i> 기획
            </button>
            <button class="btn btn-sm btn-icon btn-delete-item" data-id="${escapeHtml(item.id)}" title="삭제">
              <i class="fa-solid fa-trash-can text-danger"></i>
            </button>
          </div>
        </td>
      </tr>
    `).join('');
  }

  // 6. 히스토리 검색
  historySearch.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    const filtered = historyData.filter(d => 
      (d.title && d.title.toLowerCase().includes(q)) || 
      (d.channel && d.channel.toLowerCase().includes(q))
    );
    renderHistoryTable(filtered);
  });

  btnRefreshHistory.addEventListener('click', loadHistory);

  // 7. 모달 열기/닫기 및 탭 전환
  async function openDetailModal(videoId, defaultTab = 'tabOverview') {
    try {
      const response = await fetch(`/api/metadata/${videoId}`);
      if (!response.ok) throw new Error('데이터 로드 실패');
      const resData = await response.json();
      const item = resData.data;
      const info = item.info || item;

      modalTitle.textContent = info.title || '영상 상세 정보';
      modalCommentCount.textContent = item.comments ? item.comments.length : 0;
      modalChapterCount.textContent = (info.chapters || []).length;

      // 탭 내용 채우기
      document.getElementById('tabOverview').innerHTML = `
        <div class="overview-grid">
          <div class="overview-thumb-box">
            <img src="${escapeHtml(info.thumbnail)}" alt="thumb" style="width:100%; border-radius:8px;">
            <div style="margin-top:10px; display:flex; gap:8px;">
              <a href="${escapeHtml(item.url)}" target="_blank" class="btn btn-sm btn-outline btn-block">
                <i class="fa-brands fa-youtube"></i> 유튜브 열기
              </a>
              ${item.has_ai_report ? `
                <a href="/api/ai-report/${escapeHtml(item.id)}/download" class="btn btn-sm btn-primary btn-block">
                  <i class="fa-solid fa-download"></i> 리포트 TXT
                </a>
              ` : ''}
            </div>
          </div>
          <div class="overview-meta-box">
            <h4>${escapeHtml(info.title)}</h4>
            <p class="text-muted" style="margin-bottom:12px;">${escapeHtml(info.channel)} • 업로드일: ${escapeHtml(info.upload_date)}</p>
            <div class="stats-pills">
              <span><strong>조회수:</strong> ${formatNumber(info.view_count)}회</span>
              <span><strong>좋아요:</strong> ${formatNumber(info.like_count)}개</span>
              <span><strong>재생시간:</strong> ${escapeHtml(info.duration_string || '00:00')}</span>
            </div>
            <div style="margin-top:14px;">
              <strong>설명란:</strong>
              <div class="desc-box">${escapeHtml(info.description || '(설명 없음)')}</div>
            </div>
          </div>
        </div>
      `;

      document.getElementById('tabComments').innerHTML = (item.comments || []).length > 0
        ? `<div class="comments-list">${item.comments.map(c => `
            <div class="comment-item">
              <div class="comment-header">
                <strong>${escapeHtml(c.author)}</strong>
                <span class="text-muted"><i class="fa-solid fa-thumbs-up"></i> ${formatNumber(c.like_count)}</span>
              </div>
              <div class="comment-text">${escapeHtml(c.text)}</div>
            </div>
          `).join('')}</div>`
        : '<p class="text-muted py-4 text-center">수집된 댓글이 없습니다.</p>';

      document.getElementById('tabTranscript').innerHTML = `
        <div class="transcript-box">
          <pre>${escapeHtml(item.transcript || '(자막 없음)')}</pre>
        </div>
      `;

      document.getElementById('tabAiReport').innerHTML = item.report || item.ai_report
        ? `<div class="ai-report-box"><pre>${escapeHtml(item.report || item.ai_report)}</pre></div>`
        : '<p class="text-muted py-4 text-center">AI 리포트가 생성되지 않았습니다.</p>';

      document.getElementById('tabChapters').innerHTML = (info.chapters || []).length > 0
        ? `<div class="chapters-list">${info.chapters.map(ch => `
            <div class="chapter-item">
              <span class="badge badge-accent">${escapeHtml(ch.start_time_formatted || ch.title)}</span>
              <span>${escapeHtml(ch.title)}</span>
            </div>
          `).join('')}</div>`
        : '<p class="text-muted py-4 text-center">챕터 정보가 없습니다.</p>';

      document.getElementById('tabRawJson').innerHTML = `
        <div class="json-viewer-box">
          <pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre>
        </div>
      `;

      switchTab(defaultTab);
      detailModal.style.display = 'flex';
    } catch (err) {
      showAlert('상세 정보 조회 오류: ' + err.message);
    }
  }

  function switchTab(tabId) {
    tabBtns.forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tabId));
    tabPanes.forEach(pane => pane.classList.toggle('active', pane.id === tabId));
  }

  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  const closeModal = () => { detailModal.style.display = 'none'; };
  btnCloseModal.addEventListener('click', closeModal);
  detailModal.addEventListener('click', (e) => {
    if (e.target === detailModal) closeModal();
  });

  // 8. 저장 폴더 및 CSV 내보내기
  btnOpenFolder.addEventListener('click', async () => {
    try {
      await fetch('/api/open-folder', { method: 'POST' });
    } catch (e) {
      showAlert('폴더 열기 오류: ' + e.message);
    }
  });

  btnExportCsv.addEventListener('click', () => {
    window.location.href = '/api/export/csv';
  });

  // 9. 영상 삭제
  document.addEventListener('click', async (e) => {
    const delBtn = e.target.closest('.btn-delete-item');
    if (delBtn) {
      const vid = delBtn.dataset.id;
      if (confirm(`영상(${vid}) 데이터와 관련 파일을 완전히 삭제하시겠습니까?`)) {
        try {
          const res = await fetch(`/api/metadata/${vid}`, { method: 'DELETE' });
          if (res.ok) {
            showAlert('영상이 성공적으로 삭제되었습니다.', 'success');
            loadHistory();
          }
        } catch (err) {
          showAlert('삭제 실패: ' + err.message);
        }
      }
    }

    const detailBtn = e.target.closest('.btn-view-detail');
    if (detailBtn) {
      openDetailModal(detailBtn.dataset.id);
    }
  });

  // ==============================================================
  // 11. AI 프롬프트 스튜디오 & 8초 씬 비디오 기획 로직
  // ==============================================================
  const navTabAnalysis = document.getElementById('navTabAnalysis');
  const navTabPromptStudio = document.getElementById('navTabPromptStudio');
  const viewAnalysis = document.getElementById('viewAnalysis');
  const viewPromptStudio = document.getElementById('viewPromptStudio');

  const promptTopicInput = document.getElementById('promptTopicInput');
  const promptTargetModel = document.getElementById('promptTargetModel');
  const promptSceneCount = document.getElementById('promptSceneCount');
  const promptAspectRatio = document.getElementById('promptAspectRatio');
  const promptStyle = document.getElementById('promptStyle');
  const promptCustomSubject = document.getElementById('promptCustomSubject');
  const promptLanguageSelect = document.getElementById('promptLanguageSelect');
  const promptVoiceSelect = document.getElementById('promptVoiceSelect');
  const voiceDescText = document.getElementById('voiceDescText');
  const btnGeneratePrompts = document.getElementById('btnGeneratePrompts');

  const studioVideoTitle = document.getElementById('studioVideoTitle');
  const studioSceneBadge = document.getElementById('studioSceneBadge');
  const studioScenesContainer = document.getElementById('studioScenesContainer');

  const btnBatchTTS = document.getElementById('btnBatchTTS');
  const btnDownloadZip = document.getElementById('btnDownloadZip');
  const btnCopyAllPrompts = document.getElementById('btnCopyAllPrompts');
  const btnExportAutoFlowTxt = document.getElementById('btnExportAutoFlowTxt');
  const btnExportCsvPrompts = document.getElementById('btnExportCsvPrompts');

  // 보이스 클론 모달
  const voiceCloneModal = document.getElementById('voiceCloneModal');
  const btnOpenVoiceModal = document.getElementById('btnOpenVoiceModal');
  const btnCloseVoiceModal = document.getElementById('btnCloseVoiceModal');
  const btnCancelVoiceModal = document.getElementById('btnCancelVoiceModal');
  const voiceCloneForm = document.getElementById('voiceCloneForm');
  const voiceNameInput = document.getElementById('voiceNameInput');
  const voiceFileInput = document.getElementById('voiceFileInput');
  const voiceRefTextInput = document.getElementById('voiceRefTextInput');
  const btnSubmitVoiceClone = document.getElementById('btnSubmitVoiceClone');

  let currentGeneratedBatch = null;
  let availableVoices = [];

  function switchMainView(viewName) {
    if (viewName === 'promptStudio') {
      navTabPromptStudio.classList.add('active');
      navTabAnalysis.classList.remove('active');
      viewPromptStudio.style.display = 'block';
      viewAnalysis.style.display = 'none';
      loadTTSVoices();
    } else {
      navTabAnalysis.classList.add('active');
      navTabPromptStudio.classList.remove('active');
      viewAnalysis.style.display = 'block';
      viewPromptStudio.style.display = 'none';
    }
  }

  navTabAnalysis.addEventListener('click', () => switchMainView('analysis'));
  navTabPromptStudio.addEventListener('click', () => switchMainView('promptStudio'));

  document.querySelectorAll('.btn-topic-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const topic = btn.dataset.topic;
      if (promptTopicInput) {
        promptTopicInput.value = topic;
        promptTopicInput.focus();
      }
    });
  });

  async function loadTTSVoices() {
    try {
      const res = await fetch('/api/tts/voices');
      const resData = await res.json();
      if (resData.status === 'success' && resData.data) {
        availableVoices = resData.data;
        renderVoiceOptions();
      }
    } catch (e) {
      console.error('보이스 목록 로드 실패:', e);
    }
  }

  function renderVoiceOptions() {
    if (!promptVoiceSelect) return;
    const prev = promptVoiceSelect.value;
    promptVoiceSelect.innerHTML = '';

    availableVoices.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v.id;
      opt.textContent = v.name;
      if (v.id === prev) opt.selected = true;
      promptVoiceSelect.appendChild(opt);
    });

    onVoiceSelectChange();
  }

  function onVoiceSelectChange() {
    const selectedId = promptVoiceSelect.value;
    const voice = availableVoices.find(v => v.id === selectedId);
    if (voice && voiceDescText) {
      voiceDescText.textContent = voice.description || '';
    }
  }

  promptVoiceSelect.addEventListener('change', onVoiceSelectChange);

  btnOpenVoiceModal.addEventListener('click', () => {
    voiceCloneModal.style.display = 'flex';
  });

  const closeVoiceModal = () => { voiceCloneModal.style.display = 'none'; };
  btnCloseVoiceModal.addEventListener('click', closeVoiceModal);
  btnCancelVoiceModal.addEventListener('click', closeVoiceModal);

  voiceCloneForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!voiceFileInput.files || voiceFileInput.files.length === 0) {
      alert('음성 파일을 선택해주세요.');
      return;
    }

    const formData = new FormData();
    formData.append('voice_file', voiceFileInput.files[0]);
    formData.append('voice_name', voiceNameInput.value.trim() || '내 목소리');
    formData.append('ref_text', voiceRefTextInput.value.trim());

    btnSubmitVoiceClone.disabled = true;
    try {
      const res = await fetch('/api/tts/upload-voice', { method: 'POST', body: formData });
      const data = await res.json();
      if (res.ok) {
        alert('🎉 내 목소리가 등록되었습니다!');
        closeVoiceModal();
        await loadTTSVoices();
        promptVoiceSelect.value = 'my_voice';
      } else {
        throw new Error(data.detail || '등록 실패');
      }
    } catch (err) {
      alert('목소리 등록 오류: ' + err.message);
    } finally {
      btnSubmitVoiceClone.disabled = false;
    }
  });

  window.openPromptStudioForTopic = function(topicText) {
    switchMainView('promptStudio');
    if (promptTopicInput) {
      promptTopicInput.value = topicText;
      triggerPromptGeneration();
    }
  };

  async function triggerPromptGeneration() {
    const topic = (promptTopicInput ? promptTopicInput.value : '').trim();
    if (!topic) {
      alert('영상 기획 주제를 입력해주세요.');
      if (promptTopicInput) promptTopicInput.focus();
      return;
    }

    btnGeneratePrompts.disabled = true;
    btnGeneratePrompts.querySelector('.btn-text').style.display = 'none';
    btnGeneratePrompts.querySelector('.spinner').style.display = 'inline-block';
    if (btnDownloadZip) btnDownloadZip.style.display = 'none';

    studioScenesContainer.innerHTML = `
      <div class="empty-state-box" style="border-color:#8b5cf6;">
        <i class="fa-solid fa-brain fa-spin fa-3x" style="color:var(--ai-purple); animation-duration: 3s;"></i>
        <div style="font-size:15px; font-weight:700; color:#c4b5fd;">로컬 AI가 8초 씬별 대본 및 시네마틱 프롬프트 기획 중...</div>
        <p style="font-size:12px; color:var(--text-muted);">성공 공식(5초 훅, 5단계 플롯, 카메라/조명)을 결합하여 씬을 생성하고 있습니다.</p>
      </div>
    `;

    try {
      const res = await fetch('/api/prompt/generate-custom', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: topic,
          model: promptTargetModel.value,
          scene_count: parseInt(promptSceneCount.value, 10),
          aspect_ratio: promptAspectRatio.value,
          style_key: promptStyle.value,
          custom_subject: promptCustomSubject ? promptCustomSubject.value.trim() : '',
          language: promptLanguageSelect ? promptLanguageSelect.value : 'korean'
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '기획 생성 실패');
      }

      currentGeneratedBatch = await res.json();
      renderStudioScenes(currentGeneratedBatch);
    } catch (err) {
      alert('기획 생성 오류: ' + err.message);
    } finally {
      btnGeneratePrompts.disabled = false;
      btnGeneratePrompts.querySelector('.btn-text').style.display = 'inline-block';
      btnGeneratePrompts.querySelector('.spinner').style.display = 'none';
    }
  }

  btnGeneratePrompts.addEventListener('click', triggerPromptGeneration);

  function renderStudioScenes(batchData) {
    if (!batchData || !batchData.scenes || batchData.scenes.length === 0) {
      studioScenesContainer.innerHTML = `
        <div class="empty-state-box">
          <i class="fa-solid fa-triangle-exclamation fa-3x" style="color:var(--warning-color)"></i>
          <p>생성된 씬 데이터가 없습니다.</p>
        </div>
      `;
      return;
    }

    const titleText = batchData.recommended_title || batchData.topic;
    studioVideoTitle.innerHTML = `<i class="fa-solid fa-clapperboard"></i> ${escapeHtml(titleText)}`;
    studioSceneBadge.textContent = `총 ${batchData.scenes.length}개 씬 (각 8초 분량)`;

    studioScenesContainer.innerHTML = batchData.scenes.map((scene, idx) => {
      const sceneNum = scene.scene_num || (idx + 1);
      const timeRange = scene.time_range || `씬 ${sceneNum}`;
      const narration = scene.narration || scene.subtitle || '';
      const promptEn = scene.prompt_en || scene.prompt || '';
      const beat = scene.dramatic_beat || scene.stage || '8초 씬';
      const camera = scene.camera || scene.inferred_angle || 'Cinematic Push-in';
      const lighting = scene.lighting || scene.inferred_lighting || 'Volumetric Lighting';

      return `
        <div class="scene-card" data-index="${idx}" id="sceneCard_${idx}">
          <div class="scene-card-header">
            <div class="scene-badge-group">
              <span class="scene-num-badge">Scene #${sceneNum}</span>
              <span class="scene-time-badge"><i class="fa-solid fa-clock"></i> ${escapeHtml(timeRange)}</span>
              <span class="tag-chip">${escapeHtml(beat)}</span>
            </div>
          </div>

          <div class="scene-narration-box">
            <div style="margin-bottom:6px;">
              <strong><i class="fa-solid fa-quote-left"></i> 8초 나레이션 대본:</strong> 
              <span id="narrationText_${idx}">${escapeHtml(narration)}</span>
            </div>
            
            <div class="scene-audio-section">
              <div class="audio-info-label">
                <i class="fa-solid fa-waveform-lines"></i> 나레이션 음성:
              </div>
              
              <audio id="sceneAudio_${idx}" class="scene-audio-player" controls style="${scene.audio_url ? '' : 'display:none;'}">
                <source src="${scene.audio_url || ''}" type="audio/mpeg">
              </audio>

              <button class="btn-tts-single" data-index="${idx}">
                <span class="tts-btn-text"><i class="fa-solid fa-microphone"></i> 음성 생성</span>
                <span class="tts-spinner" style="display:none;"><i class="fa-solid fa-circle-notch fa-spin"></i> 합성 중...</span>
              </button>
            </div>
          </div>

          <div class="scene-prompt-editor-area">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <label><i class="fa-solid fa-sparkles"></i> AI 영상 프롬프트 (Runway / Kling / Sora / Flow):</label>
              <button class="btn btn-sm btn-outline btn-copy-single" data-index="${idx}" style="padding:2px 8px; font-size:11px;">
                <i class="fa-solid fa-copy"></i> 복사
              </button>
            </div>
            <textarea class="prompt-textarea" data-index="${idx}">${escapeHtml(promptEn)}</textarea>
          </div>

          <div class="scene-card-footer">
            <div class="scene-modifiers-info">
              <span><i class="fa-solid fa-camera" style="color:#60a5fa;"></i> 카메라: ${escapeHtml(camera)}</span>
              <span><i class="fa-solid fa-sun" style="color:#f59e0b;"></i> 조명: ${escapeHtml(lighting)}</span>
            </div>
          </div>
        </div>
      `;
    }).join('');

    // 프롬프트 수정 반영
    studioScenesContainer.querySelectorAll('.prompt-textarea').forEach(ta => {
      ta.addEventListener('input', (e) => {
        const index = parseInt(e.target.dataset.index, 10);
        if (currentGeneratedBatch && currentGeneratedBatch.scenes[index]) {
          currentGeneratedBatch.scenes[index].prompt_en = e.target.value;
        }
      });
    });

    // 개별 프롬프트 복사
    studioScenesContainer.querySelectorAll('.btn-copy-single').forEach(btn => {
      btn.addEventListener('click', () => {
        const index = parseInt(btn.dataset.index, 10);
        const promptText = currentGeneratedBatch.scenes[index].prompt_en || currentGeneratedBatch.scenes[index].prompt;
        navigator.clipboard.writeText(promptText).then(() => {
          const original = btn.innerHTML;
          btn.innerHTML = '<i class="fa-solid fa-check text-success"></i> 복사됨';
          setTimeout(() => btn.innerHTML = original, 1500);
        });
      });
    });

    // 개별 씬 음성 합성
    studioScenesContainer.querySelectorAll('.btn-tts-single').forEach(btn => {
      btn.addEventListener('click', async () => {
        const index = parseInt(btn.dataset.index, 10);
        const scene = currentGeneratedBatch.scenes[index];
        const narration = scene.narration || scene.subtitle;

        btn.disabled = true;
        btn.querySelector('.tts-btn-text').style.display = 'none';
        btn.querySelector('.tts-spinner').style.display = 'inline-block';

        try {
          const res = await fetch('/api/tts/generate-scene', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              text: narration,
              voice_id: promptVoiceSelect.value,
              scene_index: scene.scene_num || (index + 1),
              topic_slug: currentGeneratedBatch.topic || 'scene',
              language: promptLanguageSelect ? promptLanguageSelect.value : 'korean'
            })
          });

          if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || '음성 합성 실패');
          }

          const result = await res.json();
          scene.audio_url = result.audio_url;
          
          const audioElem = document.getElementById(`sceneAudio_${index}`);
          if (audioElem) {
            audioElem.src = result.audio_url + `?t=${Date.now()}`;
            audioElem.style.display = 'block';
            audioElem.load();
            audioElem.play().catch(e => console.log('Auto-play note:', e));
          }
        } catch (err) {
          alert('음성 생성 오류: ' + err.message);
        } finally {
          btn.disabled = false;
          btn.querySelector('.tts-btn-text').style.display = 'inline-block';
          btn.querySelector('.tts-spinner').style.display = 'none';
        }
      });
    });
  }

  // 전체 씬 일괄 음성 합성 (Edge-TTS 초고속 병렬 + ZIP 번들 생성)
  btnBatchTTS.addEventListener('click', async () => {
    if (!currentGeneratedBatch || !currentGeneratedBatch.scenes || currentGeneratedBatch.scenes.length === 0) {
      alert('먼저 씬을 기획/생성해주세요.');
      return;
    }

    btnBatchTTS.disabled = true;
    const originalText = btnBatchTTS.innerHTML;
    btnBatchTTS.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> 초고속 병렬 합성 중...';

    try {
      const res = await fetch('/api/tts/generate-all-scenes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenes: currentGeneratedBatch.scenes,
          voice_id: promptVoiceSelect.value,
          topic: currentGeneratedBatch.topic || 'custom_topic'
        })
      });

      if (!res.ok) throw new Error('일괄 음성 합성 실패');

      const data = await res.json();
      currentZipDownloadUrl = data.zip_download_url;

      // ZIP 다운로드 버튼 표시
      if (btnDownloadZip && currentZipDownloadUrl) {
        btnDownloadZip.style.display = 'inline-flex';
      }

      alert(`🎉 전체 ${data.total_scenes}개 씬의 음성 및 마스터 오디오 완결! [전체 ZIP 다운로드]를 클릭해 일괄 다운로드할 수 있습니다.`);
      
      // 씬 카드별 플레이어 갱신
      (data.scenes_audio || []).forEach((item, idx) => {
        if (currentGeneratedBatch.scenes[idx]) {
          currentGeneratedBatch.scenes[idx].audio_url = item.audio_url;
        }
        const audioElem = document.getElementById(`sceneAudio_${idx}`);
        if (audioElem && item.audio_url) {
          audioElem.src = item.audio_url + `?t=${Date.now()}`;
          audioElem.style.display = 'block';
          audioElem.load();
        }
      });
    } catch (err) {
      alert('일괄 음성 생성 오류: ' + err.message);
    } finally {
      btnBatchTTS.disabled = false;
      btnBatchTTS.innerHTML = originalText;
    }
  });

  // ZIP 일괄 다운로드 버튼 클릭
  btnDownloadZip.addEventListener('click', () => {
    if (currentZipDownloadUrl) {
      window.location.href = currentZipDownloadUrl;
    }
  });

  // 전체 프롬프트 복사
  btnCopyAllPrompts.addEventListener('click', () => {
    if (!currentGeneratedBatch || !currentGeneratedBatch.scenes) {
      alert('먼저 프롬프트를 생성해주세요.');
      return;
    }
    const allText = currentGeneratedBatch.scenes.map(s => s.prompt_en || s.prompt).join('\n\n');
    navigator.clipboard.writeText(allText).then(() => {
      const original = btnCopyAllPrompts.innerHTML;
      btnCopyAllPrompts.innerHTML = '<i class="fa-solid fa-check text-success"></i> 전체 복사됨!';
      setTimeout(() => btnCopyAllPrompts.innerHTML = original, 1500);
    });
  });

  async function exportPromptBatch(format) {
    if (!currentGeneratedBatch || !currentGeneratedBatch.scenes) {
      alert('먼저 프롬프트를 생성해주세요.');
      return;
    }

    try {
      const res = await fetch('/api/prompt/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenes: currentGeneratedBatch.scenes,
          format: format,
          video_title: currentGeneratedBatch.topic || 'custom_topic_prompts'
        })
      });

      if (!res.ok) throw new Error('내보내기 실패');

      const blob = await res.blob();
      const disposition = res.headers.get('Content-Disposition') || '';
      let filename = `prompts_${format}_${Date.now()}`;
      const match = disposition.match(/filename="?([^"]+)"?/);
      if (match && match[1]) filename = match[1];

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert('내보내기 오류: ' + err.message);
    }
  }

  btnExportAutoFlowTxt.addEventListener('click', () => exportPromptBatch('autoflow_txt'));
  btnExportCsvPrompts.addEventListener('click', () => exportPromptBatch('csv'));

  document.addEventListener('click', (e) => {
    const promptBtn = e.target.closest('.btn-open-prompt-studio');
    if (promptBtn) {
      const videoId = promptBtn.dataset.id;
      const targetItem = historyData.find(h => h.id === videoId);
      const topicText = targetItem ? targetItem.title : videoId;
      window.openPromptStudioForTopic(topicText);
    }
  });

  loadHistory();
});
