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
  // LLM 실시간 상태 감지 및 모델 선택 팝업
  // ==============================================================

  // 모델 선택 팝업 생성 (최초 1회)
  function ensureModelPickerDOM() {
    if (document.getElementById('llmModelPicker')) return;
    const overlay = document.createElement('div');
    overlay.id = 'llmModelPickerOverlay';
    overlay.style.cssText = `
      display:none; position:fixed; inset:0; z-index:9999;
      background:rgba(0,0,0,0.55); backdrop-filter:blur(4px);
      align-items:center; justify-content:center;
    `;
    overlay.innerHTML = `
      <div id="llmModelPicker" style="
        background:var(--surface,#1e1e2e); border:1px solid var(--border,#333);
        border-radius:16px; padding:28px 32px; min-width:360px; max-width:520px;
        box-shadow:0 24px 64px rgba(0,0,0,0.6); color:var(--text,#e0e0e0);
        font-family:inherit;
      ">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
          <h3 style="margin:0;font-size:1.1rem;font-weight:700;">
            <i class="fa-solid fa-microchip" style="color:#8b5cf6;margin-right:8px;"></i>
            로컬 AI 모델 선택
          </h3>
          <button id="llmPickerClose" style="
            background:none;border:none;color:var(--text-muted,#888);
            font-size:1.3rem;cursor:pointer;padding:4px 8px;border-radius:6px;
            transition:background 0.2s;
          " onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='none'">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <p style="margin:0 0 16px;font-size:0.85rem;color:var(--text-muted,#888);line-height:1.5;">
          LM Studio 또는 Ollama에서 감지된 모델 목록입니다.<br>
          원하는 모델을 선택하면 즉시 적용됩니다.
        </p>
        <div id="llmModelList" style="
          display:flex; flex-direction:column; gap:8px;
          max-height:340px; overflow-y:auto; padding-right:4px;
        ">
          <div style="text-align:center;padding:20px;color:#888;">
            <i class="fa-solid fa-spinner fa-spin"></i> 모델 목록 조회 중...
          </div>
        </div>
        <div style="margin-top:18px;padding-top:14px;border-top:1px solid var(--border,#333);display:flex;gap:8px;justify-content:flex-end;">
          <button id="llmPickerAutoBtn" style="
            padding:8px 16px;border-radius:8px;border:1px solid #4f4f6a;
            background:transparent;color:var(--text,#e0e0e0);cursor:pointer;
            font-size:0.85rem;transition:background 0.2s;
          " onmouseover="this.style.background='rgba(255,255,255,0.08)'" onmouseout="this.style.background='transparent'">
            <i class="fa-solid fa-rotate"></i> 자동 선택 초기화
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    // 닫기 버튼
    overlay.querySelector('#llmPickerClose').addEventListener('click', () => {
      overlay.style.display = 'none';
    });
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) overlay.style.display = 'none';
    });

    // 자동 선택 초기화
    overlay.querySelector('#llmPickerAutoBtn').addEventListener('click', async () => {
      await fetch('/api/llm/select-model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: null })
      });
      overlay.style.display = 'none';
      showAlert('자동 모델 선택으로 초기화되었습니다.', 'success');
      pollLLMStatus();
    });
  }

  async function openModelPicker() {
    ensureModelPickerDOM();
    const overlay = document.getElementById('llmModelPickerOverlay');
    const listEl = document.getElementById('llmModelList');
    overlay.style.display = 'flex';
    listEl.innerHTML = '<div style="text-align:center;padding:20px;color:#888;"><i class="fa-solid fa-spinner fa-spin"></i> 조회 중...</div>';

    try {
      const [modelsRes, statusRes] = await Promise.all([
        fetch('/api/llm/models'),
        fetch('/api/llm/status')
      ]);
      const modelsData = await modelsRes.json();
      const statusData = await statusRes.json();
      const selectedModel = modelsData.selected_model || statusData?.active?.model;
      const models = modelsData.models || [];

      if (models.length === 0) {
        listEl.innerHTML = `
          <div style="text-align:center;padding:24px;color:#f87171;">
            <i class="fa-solid fa-circle-xmark" style="font-size:1.8rem;margin-bottom:10px;display:block;"></i>
            감지된 모델이 없습니다.<br>
            <span style="font-size:0.82rem;color:#888;margin-top:6px;display:block;">
              LM Studio 또는 Ollama를 실행한 뒤 다시 시도해주세요.
            </span>
          </div>`;
        return;
      }

      // 백엔드별 그룹핑
      const grouped = {};
      models.forEach(m => {
        if (!grouped[m.backend_label]) grouped[m.backend_label] = [];
        grouped[m.backend_label].push(m);
      });

      let html = '';
      for (const [label, items] of Object.entries(grouped)) {
        html += `<div style="font-size:0.75rem;font-weight:700;color:#8b5cf6;text-transform:uppercase;
          letter-spacing:0.08em;margin:8px 0 4px;padding-left:4px;">${label}</div>`;
        items.forEach(m => {
          const isActive = m.id === selectedModel;
          html += `
            <button class="llm-model-item" data-model="${escapeHtml(m.id)}" style="
              display:flex; align-items:center; gap:12px; width:100%;
              padding:10px 14px; border-radius:10px; border:1px solid ${isActive ? '#8b5cf6' : 'transparent'};
              background:${isActive ? 'rgba(139,92,246,0.15)' : 'rgba(255,255,255,0.04)'};
              color:var(--text,#e0e0e0); cursor:pointer; text-align:left;
              transition:all 0.15s; font-size:0.88rem;
            "
            onmouseover="this.style.background='rgba(139,92,246,0.1)';this.style.borderColor='#7c3aed'"
            onmouseout="this.style.background='${isActive ? 'rgba(139,92,246,0.15)' : 'rgba(255,255,255,0.04)'}';this.style.borderColor='${isActive ? '#8b5cf6' : 'transparent'}'"
            >
              <i class="fa-solid fa-${isActive ? 'circle-check' : 'circle'}" style="color:${isActive ? '#8b5cf6' : '#555'};font-size:1rem;flex-shrink:0;"></i>
              <span style="flex:1;font-weight:${isActive ? '600' : '400'};word-break:break-all;">${escapeHtml(m.id)}</span>
              ${isActive ? '<span style="font-size:0.72rem;background:#8b5cf6;color:#fff;padding:2px 8px;border-radius:20px;flex-shrink:0;">사용 중</span>' : ''}
            </button>`;
        });
      }
      listEl.innerHTML = html;

      listEl.querySelectorAll('.llm-model-item').forEach(btn => {
        btn.addEventListener('click', async () => {
          const modelId = btn.dataset.model;
          await fetch('/api/llm/select-model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: modelId })
          });
          overlay.style.display = 'none';
          showAlert(`모델이 [${modelId}]로 변경되었습니다.`, 'success');
          pollLLMStatus();
        });
      });
    } catch (e) {
      listEl.innerHTML = `<div style="color:#f87171;padding:12px;">오류: ${escapeHtml(e.message)}</div>`;
    }
  }

  async function pollLLMStatus() {
    try {
      const res = await fetch('/api/llm/status');
      if (!res.ok) return;
      const data = await res.json();
      const dot = llmStatusBadge.querySelector('.status-dot');

      if (data.active) {
        dot.className = 'status-dot online';
        // 선택된 모델 우선 표시
        const modelRes = await fetch('/api/llm/models');
        const modelData = await modelRes.json();
        const displayModel = modelData.selected_model || data.active.model || '온라인';
        llmBackendName.textContent = data.active.name;
        llmModelBadge.textContent = displayModel;
        llmModelBadge.style.display = 'inline-block';
        llmStatusBadge.title = '클릭하여 모델 변경';
      } else {
        dot.className = 'status-dot offline';
        llmBackendName.textContent = '로컬 AI 꺼짐';
        llmModelBadge.textContent = 'LM Studio/Ollama 실행 필요';
        llmModelBadge.style.display = 'inline-block';
        llmStatusBadge.title = 'LM Studio 또는 Ollama를 실행해주세요';
      }
    } catch (e) {
      console.warn('LLM 상태 조회 실패:', e);
    }
  }

  // 배지 클릭 → 모델 선택 팝업
  llmStatusBadge.addEventListener('click', openModelPicker);
  llmStatusBadge.style.cursor = 'pointer';

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
      if (!vid) return;
      if (confirm(`영상(${vid}) 데이터와 관련 파일을 완전히 삭제하시겠습니까?`)) {
        try {
          const res = await fetch(`/api/metadata/${encodeURIComponent(vid)}`, { method: 'DELETE' });
          const data = await res.json().catch(() => ({}));
          if (res.ok && data.status === 'success') {
            showAlert('영상이 성공적으로 삭제되었습니다.', 'success');
            if (typeof detailModal !== 'undefined' && detailModal.style.display !== 'none') {
              detailModal.style.display = 'none';
            }
            loadHistory();
          } else {
            showAlert('삭제 실패: ' + (data.detail || data.message || res.statusText || '서버 오류가 발생했습니다.'), 'error');
          }
        } catch (err) {
          showAlert('삭제 실패: ' + err.message, 'error');
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
  // 6대 통합 탭 네비게이션 & 뷰 스위처
  // ==============================================================
  const navTabAnalysis = document.getElementById('navTabAnalysis');
  const navTabChannel = document.getElementById('navTabChannel');
  const navTabPromptStudio = document.getElementById('navTabPromptStudio');
  const navTabProducer = document.getElementById('navTabProducer');
  const navTabMarketing = document.getElementById('navTabMarketing');
  const navTabMusic = document.getElementById('navTabMusic');

  const viewAnalysis = document.getElementById('viewAnalysis');
  const viewChannel = document.getElementById('viewChannel');
  const viewPromptStudio = document.getElementById('viewPromptStudio');
  const viewProducer = document.getElementById('viewProducer');
  const viewMarketing = document.getElementById('viewMarketing');
  const viewMusic = document.getElementById('viewMusic');

  const allNavTabs = [
    { tab: navTabAnalysis, view: viewAnalysis, id: 'analysis' },
    { tab: navTabChannel, view: viewChannel, id: 'channel' },
    { tab: navTabPromptStudio, view: viewPromptStudio, id: 'promptStudio' },
    { tab: navTabProducer, view: viewProducer, id: 'producer' },
    { tab: navTabMarketing, view: viewMarketing, id: 'marketing' },
    { tab: navTabMusic, view: viewMusic, id: 'music' }
  ];

  function switchMainView(targetId) {
    allNavTabs.forEach(item => {
      if (!item.tab || !item.view) return;
      if (item.id === targetId) {
        item.tab.classList.add('active');
        item.view.style.display = 'block';
        item.view.classList.add('active');
      } else {
        item.tab.classList.remove('active');
        item.view.style.display = 'none';
        item.view.classList.remove('active');
      }
    });

    if (targetId === 'analysis') {
      loadTrends();
    } else if (targetId === 'channel') {
      loadChannelDiagnostics();
    } else if (targetId === 'promptStudio') {
      loadTTSVoices();
    } else if (targetId === 'producer') {
      loadProducerPlans();
      checkYoutubeStatus();
    } else if (targetId === 'marketing') {
      loadMarketingHistory();
    } else if (targetId === 'music') {
      loadLunaHistory();
    }
  }

  if (navTabAnalysis) navTabAnalysis.addEventListener('click', () => switchMainView('analysis'));
  if (navTabChannel) navTabChannel.addEventListener('click', () => switchMainView('channel'));
  if (navTabPromptStudio) navTabPromptStudio.addEventListener('click', () => switchMainView('promptStudio'));
  if (navTabProducer) navTabProducer.addEventListener('click', () => switchMainView('producer'));
  if (navTabMarketing) navTabMarketing.addEventListener('click', () => switchMainView('marketing'));
  if (navTabMusic) navTabMusic.addEventListener('click', () => switchMainView('music'));

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

  // 트렌드 추천 주제에서 넘어온 '차별화 앵글'. 주제를 직접 수정하면 무효화한다.
  let pendingTopicAngle = '';

  // 사용자가 주제를 직접 고치면 이전 앵글은 더 이상 유효하지 않다
  if (promptTopicInput) {
    promptTopicInput.addEventListener('input', () => { pendingTopicAngle = ''; });
  }

  window.openPromptStudioForTopic = function(topicText, angleText) {
    switchMainView('promptStudio');
    if (promptTopicInput) {
      promptTopicInput.value = topicText;
      pendingTopicAngle = (angleText || '').trim();
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
          angle: pendingTopicAngle,
          language: promptLanguageSelect ? promptLanguageSelect.value : 'korean'
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '기획 생성 실패');
      }

      currentGeneratedBatch = await res.json();
      renderThumbnailRedline(currentGeneratedBatch);
      renderEngagementCard(currentGeneratedBatch);
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

  // 화면 비율 변경 시 힌트 텍스트 전환
  const aspectRatioHint = document.getElementById('aspectRatioHint');
  const thumbnailRedlineSection = document.getElementById('thumbnailRedlineSection');

  if (promptAspectRatio && aspectRatioHint) {
    promptAspectRatio.addEventListener('change', () => {
      if (promptAspectRatio.value === '9:16') {
        aspectRatioHint.textContent = '9:16 세로 쇼츠 구도 (상단 훅 문구, 하단 자막 여백, 세로 치수선) 적용';
        aspectRatioHint.style.color = '#f43f5e';
      } else {
        aspectRatioHint.textContent = '16:9 가로 시네마틱 구도 및 엔지니어링 주석 적용';
        aspectRatioHint.style.color = 'var(--text-muted)';
      }
    });
  }

  function renderThumbnailRedline(batchData) {
    if (!thumbnailRedlineSection) return;

    if (!batchData || !batchData.thumbnail_redline) {
      thumbnailRedlineSection.style.display = 'none';
      thumbnailRedlineSection.innerHTML = '';
      return;
    }

    const tData = batchData.thumbnail_redline;
    const textLayer = tData.text_layer || {};
    const hookText = textLayer.hook_text || '';
    const labels = Array.isArray(textLayer.labels) ? textLayer.labels.join(', ') : (textLayer.labels || '');
    const dimensions = Array.isArray(textLayer.dimensions) ? textLayer.dimensions.join(', ') : (textLayer.dimensions || '');
    const jsonPretty = JSON.stringify(tData, null, 2);
    const isVertical = (tData.format && tData.format.aspect_ratio === '9:16');

    thumbnailRedlineSection.style.display = 'block';
    thumbnailRedlineSection.innerHTML = `
      <div class="card redline-thumbnail-card">
        <div class="redline-card-header">
          <div class="redline-title-group">
            <span class="redline-live-badge"><i class="fa-solid fa-crosshairs"></i> NANO-BANANA REDLINE</span>
            <span class="redline-type-badge">🔥 풀 레드라인 썸네일</span>
            <span class="badge ${isVertical ? 'badge-warning' : 'badge-accent'}">
              <i class="fa-solid fa-crop-simple"></i> ${escapeHtml(tData.format?.aspect_ratio || '16:9')} (${isVertical ? '쇼츠 세로' : '롱폼 가로'})
            </span>
          </div>
          <button id="btnCopyThumbnailRedline" class="btn btn-sm btn-danger btn-redline-copy">
            <i class="fa-solid fa-copy"></i> 썸네일 JSON 복사
          </button>
        </div>

        <div class="redline-summary-chips">
          <div class="redline-chip">
            <span class="chip-label"><i class="fa-solid fa-bolt"></i> 훅 문구:</span>
            <span class="chip-value">${escapeHtml(hookText)}</span>
          </div>
          <div class="redline-chip">
            <span class="chip-label"><i class="fa-solid fa-tags"></i> 주석 라벨:</span>
            <span class="chip-value">${escapeHtml(labels)}</span>
          </div>
          <div class="redline-chip">
            <span class="chip-label"><i class="fa-solid fa-ruler-combined"></i> 정밀 수치:</span>
            <span class="chip-value text-red">${escapeHtml(dimensions)}</span>
          </div>
        </div>

        <div class="redline-json-container">
          <pre class="redline-json-code"><code>${escapeHtml(jsonPretty)}</code></pre>
        </div>
      </div>
    `;

    const copyBtn = document.getElementById('btnCopyThumbnailRedline');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(jsonPretty).then(() => {
          const original = copyBtn.innerHTML;
          copyBtn.innerHTML = '<i class="fa-solid fa-check"></i> 썸네일 JSON 복사 완료!';
          setTimeout(() => copyBtn.innerHTML = original, 1800);
        });
      });
    }
  }

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
      const sfx = scene.sfx || '';
      const firstFrameRedline = scene.first_frame_redline || null;
      const redlineJsonStr = firstFrameRedline ? JSON.stringify(firstFrameRedline, null, 2) : '';

      const charLen = narration.length;
      const estSec = scene.estimated_sec || (Math.round(charLen / 5.2 * 10) / 10);
      // 판정 기준은 백엔드(35~45자)를 단일 소스로 삼는다. 값이 없을 때만 동일 기준으로 계산.
      const isOptimal = (typeof scene.is_8s_optimized === 'boolean')
        ? scene.is_8s_optimized
        : (charLen >= 35 && charLen <= 45);
      const lengthWarning = scene.length_warning || '';

      return `
        <div class="scene-card" data-index="${idx}" id="sceneCard_${idx}">
          <div class="scene-card-header">
            <div class="scene-badge-group">
              <span class="scene-num-badge">Scene #${sceneNum}</span>
              <span class="scene-time-badge"><i class="fa-solid fa-clock"></i> ${escapeHtml(timeRange)}</span>
              <span class="tag-chip">${escapeHtml(beat)}</span>
              <span class="badge ${isOptimal ? 'badge-success' : 'badge-warning'}" style="font-size:11px;" title="${escapeHtml(lengthWarning || '한국어 다큐 기준 8초 영상에 최적화된 35~45자 분량입니다.')}">
                <i class="fa-solid fa-stopwatch"></i> 8초 맞춤 대사: ${charLen}자 (약 ${estSec}초)${isOptimal ? '' : ' ⚠️'}
              </span>
            </div>
          </div>

          <div class="scene-narration-box">
            <div style="margin-bottom:6px; display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
              <div>
                <strong><i class="fa-solid fa-quote-left"></i> 8초 나레이션 대본:</strong> 
                <span id="narrationText_${idx}">${escapeHtml(narration)}</span>
              </div>
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

          <!-- 8초 비디오 생성용 영문 프롬프트 -->
          <div class="scene-prompt-editor-area">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
              <label>
                <i class="fa-solid fa-video"></i> 8초 비디오 생성 프롬프트:
                <span class="badge badge-accent" style="font-size:10px; margin-left:6px;"><i class="fa-solid fa-volume-xmark"></i> BGM·대사 제외</span>
                <span class="badge badge-subtle" style="font-size:10px;"><i class="fa-solid fa-waveform"></i> SFX 전용</span>
              </label>
              <button class="btn btn-sm btn-outline btn-copy-single" data-index="${idx}" style="padding:2px 8px; font-size:11px;">
                <i class="fa-solid fa-copy"></i> 비디오 프롬프트 복사
              </button>
            </div>
            <textarea class="prompt-textarea" data-index="${idx}">${escapeHtml(promptEn)}</textarea>
          </div>

          <!-- 🔴 나노바나나 첫 프레임 레드라인 이미지 프롬프트 (JSON) -->
          ${firstFrameRedline ? `
            <div class="scene-redline-block">
              <div class="scene-redline-header">
                <div class="scene-redline-title">
                  <i class="fa-solid fa-crosshairs text-red"></i> 
                  <strong>첫 프레임 레드라인 이미지 프롬프트 (JSON)</strong>
                  <span class="badge-subtle">주석 그래픽 위주 · 텍스트 뭉개짐 방지</span>
                </div>
                <button class="btn btn-sm btn-danger-outline btn-copy-scene-redline" data-index="${idx}">
                  <i class="fa-solid fa-copy"></i> 첫 프레임 JSON 복사
                </button>
              </div>
              <pre class="scene-redline-json"><code>${escapeHtml(redlineJsonStr)}</code></pre>
            </div>
          ` : ''}

          <div class="scene-card-footer">
            <div class="scene-modifiers-info">
              <span><i class="fa-solid fa-camera" style="color:#60a5fa;"></i> 카메라: ${escapeHtml(camera)}</span>
              <span><i class="fa-solid fa-sun" style="color:#f59e0b;"></i> 조명: ${escapeHtml(lighting)}</span>
              ${sfx ? `<span><i class="fa-solid fa-volume-high" style="color:#34d399;"></i> 현장효과음(SFX): ${escapeHtml(sfx)}</span>` : ''}
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

    // 개별 비디오 프롬프트 복사
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

    // 개별 씬 첫 프레임 레드라인 JSON 복사
    studioScenesContainer.querySelectorAll('.btn-copy-scene-redline').forEach(btn => {
      btn.addEventListener('click', () => {
        const index = parseInt(btn.dataset.index, 10);
        const redlineData = currentGeneratedBatch.scenes[index].first_frame_redline;
        if (redlineData) {
          const jsonText = JSON.stringify(redlineData, null, 2);
          navigator.clipboard.writeText(jsonText).then(() => {
            const original = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-check"></i> JSON 복사 완료!';
            setTimeout(() => btn.innerHTML = original, 1500);
          });
        }
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

  // [1순위 최적화] 3단계에서 캡컷으로 바로 직행하는 원클릭 조립
  const btnDirectExportCapcut = document.getElementById('btnDirectExportCapcut');
  if (btnDirectExportCapcut) {
    btnDirectExportCapcut.addEventListener('click', async () => {
      if (!currentGeneratedBatch || !currentGeneratedBatch.scenes || currentGeneratedBatch.scenes.length === 0) {
        showAlert('먼저 좌측에서 씬을 생성해주세요.', 'error');
        return;
      }

      btnDirectExportCapcut.disabled = true;
      const originalHtml = btnDirectExportCapcut.innerHTML;
      btnDirectExportCapcut.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> 캡컷 조립 중...';

      // 씬 데이터 수집
      const scenes = (currentGeneratedBatch.scenes || []).map((s, idx) => {
        let aud = s.audio_url || '';
        if (aud.startsWith('/data/')) {
          aud = aud.substring(1); // 'data/...'
        }
        return {
          scene_idx: s.scene_idx || idx + 1,
          media_file: s.image_url || s.video_url || '',
          audio_file: aud,
          subtitle: s.narration || s.script || ''
        };
      });

      const topicName = currentGeneratedBatch.topic || 'TubeInsight_Project';

      try {
        const res = await fetch('/api/capcut/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_name: topicName,
            scenes: scenes,
            transition_type: 'dissolve',
            aspect_ratio: currentGeneratedBatch.aspect_ratio || '16:9'
          })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || '캡컷 조립 실패');
        }

        const data = await res.json();
        const doOpen = confirm(`🎉 캡컷 프로젝트 '${data.project_name}' 조립이 완료되었습니다!\n\n총 ${data.total_scenes}개 씬의 대사와 자막, 컷 전환 디졸브가 캡컷 타임라인에 완벽히 동기화되었습니다.\n\n지금 바로 CapCut 앱을 실행하시겠습니까?`);
        if (doOpen) {
          await fetch('/api/capcut/open', { method: 'POST' });
          showAlert('CapCut 앱을 실행했습니다.', 'success');
        } else {
          showAlert(`캡컷 프로젝트가 저장되었습니다: ${data.project_dir}`, 'success');
        }
      } catch (err) {
        showAlert('캡컷 내보내기 오류: ' + err.message, 'error');
      } finally {
        btnDirectExportCapcut.disabled = false;
        btnDirectExportCapcut.innerHTML = originalHtml;
      }
    });
  }

  // [1순위 최적화] 3단계에서 4단계 비디오 제작으로 플랜 가지고 직행
  const btnGoToProducer = document.getElementById('btnGoToProducer');
  if (btnGoToProducer) {
    btnGoToProducer.addEventListener('click', () => {
      switchMainView('producer');
      showAlert('4단계 비디오 프로듀서로 이동했습니다.', 'success');
    });
  }

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

  // ==============================================================
  // 12. 에이전트 레오의 인게이지먼트 해킹 & 추천 고정 댓글
  // ==============================================================
  const engagementSection = document.getElementById('engagementSection');
  const engagementQuestionText = document.getElementById('engagementQuestionText');
  const pinnedCommentText = document.getElementById('pinnedCommentText');
  const btnCopyEngagementQ = document.getElementById('btnCopyEngagementQ');
  const btnCopyPinnedComment = document.getElementById('btnCopyPinnedComment');

  function renderEngagementCard(batchData) {
    if (!engagementSection) return;
    const q = batchData?.engagement_question;
    const c = batchData?.pinned_comment;
    if (q || c) {
      engagementSection.style.display = 'block';
      if (engagementQuestionText) engagementQuestionText.textContent = q || '등록된 오픈 퀘스천이 없습니다.';
      if (pinnedCommentText) pinnedCommentText.textContent = c || '등록된 추천 고정 댓글이 없습니다.';
    } else {
      engagementSection.style.display = 'none';
    }
  }

  if (btnCopyEngagementQ) {
    btnCopyEngagementQ.addEventListener('click', () => {
      const text = engagementQuestionText?.textContent || '';
      if (text) {
        navigator.clipboard.writeText(text).then(() => {
          showAlert('도발적 오픈 퀘스천이 복사되었습니다!', 'success');
        });
      }
    });
  }

  if (btnCopyPinnedComment) {
    btnCopyPinnedComment.addEventListener('click', () => {
      const text = pinnedCommentText?.textContent || '';
      if (text) {
        navigator.clipboard.writeText(text).then(() => {
          showAlert('추천 고정 댓글이 복사되었습니다!', 'success');
        });
      }
    });
  }

  // ==============================================================
  // 13. [Phase 1] 트렌드 스카우터 (Top 20 & 알고리즘 트렌드 리포트)
  // ==============================================================
  const trendCategorySelect = document.getElementById('trendCategorySelect');
  const btnFetchTrends = document.getElementById('btnFetchTrends');
  const btnAnalyzeTrends = document.getElementById('btnAnalyzeTrends');
  const trendReportBox = document.getElementById('trendReportBox');
  const trendReportDate = document.getElementById('trendReportDate');
  const trendKeywordsList = document.getElementById('trendKeywordsList');
  const trendHookPatterns = document.getElementById('trendHookPatterns');
  const trendAudienceTriggers = document.getElementById('trendAudienceTriggers');
  const trendRecommendedTopics = document.getElementById('trendRecommendedTopics');
  const trendLeoTip = document.getElementById('trendLeoTip');
  const trendItemsCount = document.getElementById('trendItemsCount');
  const trendSourceBadge = document.getElementById('trendSourceBadge');
  const trendItemsGrid = document.getElementById('trendItemsGrid');

  let currentTrendsData = null;

  async function loadTrends() {
    const catId = trendCategorySelect ? trendCategorySelect.value : '0';
    if (trendItemsGrid) {
      trendItemsGrid.innerHTML = `
        <div style="grid-column: 1/-1; text-align: center; padding: 24px; color: var(--text-muted);">
          <i class="fa-solid fa-circle-notch fa-spin"></i> 실시간 트렌드 목록을 불러오는 중...
        </div>
      `;
    }

    try {
      const res = await fetch(`/api/trends/top20?category_id=${catId}&region_code=KR`);
      const data = await res.json();
      currentTrendsData = data;

      if (trendItemsCount) trendItemsCount.textContent = data.total_items || (data.items || []).length;
      if (trendSourceBadge) {
        trendSourceBadge.textContent = `출처: ${data.source === 'youtube_api' ? 'YouTube API v3' : '실시간 피드'}`;
      }

      renderTrendItems(data.items || []);
    } catch (err) {
      if (trendItemsGrid) {
        trendItemsGrid.innerHTML = `<div style="grid-column: 1/-1; text-align:center; color:#f43f5e; padding:20px;">트렌드 조회 오류: ${escapeHtml(err.message)}</div>`;
      }
    }
  }

  function renderTrendItems(items) {
    if (!trendItemsGrid) return;
    if (!items || items.length === 0) {
      trendItemsGrid.innerHTML = '<div style="grid-column: 1/-1; text-align:center; padding:20px; color:var(--text-muted);">조회된 급상승 영상이 없습니다.</div>';
      return;
    }

    trendItemsGrid.innerHTML = items.map(item => `
      <div class="trend-item-card">
        <span class="trend-rank-badge">#${item.rank}</span>
        <div class="trend-thumb-wrap">
          <img src="${item.thumbnail || 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=400'}" alt="thumb" loading="lazy" onerror="this.src='https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=400'">
        </div>
        <h4 class="trend-card-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</h4>
        <div class="trend-card-meta">
          <span><i class="fa-solid fa-tv"></i> ${escapeHtml(item.channel_title)}</span>
          <span><i class="fa-solid fa-eye"></i> ${(item.view_count || 0).toLocaleString()}회</span>
        </div>
        <div style="display: flex; gap: 6px; margin-top: 4px;">
          <a href="${escapeHtml(item.url)}" target="_blank" class="btn btn-xs btn-outline" style="flex: 1; text-align: center;">
            <i class="fa-brands fa-youtube"></i> 영상보기
          </a>
          <button class="btn btn-xs btn-primary btn-trend-analyze" data-url="${escapeHtml(item.url)}" style="flex: 1;">
            <i class="fa-solid fa-magnifying-glass-chart"></i> 즉시분석
          </button>
        </div>
      </div>
    `).join('');

    trendItemsGrid.querySelectorAll('.btn-trend-analyze').forEach(btn => {
      btn.addEventListener('click', () => {
        const url = btn.dataset.url;
        const input = document.getElementById('videoUrl');
        if (input) {
          input.value = url;
          input.scrollIntoView({ behavior: 'smooth' });
          const form = document.getElementById('analyzeForm');
          if (form) form.dispatchEvent(new Event('submit'));
        }
      });
    });
  }

  if (trendCategorySelect) trendCategorySelect.addEventListener('change', loadTrends);
  if (btnFetchTrends) btnFetchTrends.addEventListener('click', loadTrends);

  if (btnAnalyzeTrends) {
    btnAnalyzeTrends.addEventListener('click', async () => {
      btnAnalyzeTrends.disabled = true;
      btnAnalyzeTrends.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> 분석 중...';

      try {
        const catId = trendCategorySelect ? trendCategorySelect.value : '0';
        const res = await fetch('/api/trends/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ category_id: catId, trends_payload: currentTrendsData })
        });
        const data = await res.json();
        const a = data.analysis || {};

        if (trendReportBox) trendReportBox.style.display = 'block';
        if (trendReportDate) trendReportDate.textContent = data.generated_at || '';
        if (trendKeywordsList) {
          trendKeywordsList.innerHTML = (a.top_keywords || []).map(k => `<span class="badge badge-accent">${escapeHtml(k)}</span>`).join('');
        }
        if (trendHookPatterns) {
          trendHookPatterns.innerHTML = (a.hook_patterns || []).map(p => `<div><strong>• ${escapeHtml(p.pattern || '')}:</strong> ${escapeHtml(p.description || '')}</div>`).join('');
        }
        if (trendAudienceTriggers) trendAudienceTriggers.textContent = a.audience_triggers || '';
        if (trendRecommendedTopics) {
          trendRecommendedTopics.innerHTML = (a.recommended_topics || []).map(t => `
            <div style="display:flex; align-items:flex-start; gap:8px; margin-bottom:10px;">
              <div style="flex:1; min-width:0;">
                <strong>• ${escapeHtml(t.topic || '')}</strong><br>
                <span class="text-muted" style="font-size:0.8rem;">${escapeHtml(t.angle || '')}</span>
              </div>
              <button type="button" class="btn btn-xs btn-accent js-plan-topic"
                      data-topic="${escapeHtml(t.topic || '')}" data-angle="${escapeHtml(t.angle || '')}"
                      style="flex:none; white-space:nowrap;"
                      title="이 주제와 앵글로 8초 씬 기획을 바로 시작합니다">
                <i class="fa-solid fa-wand-magic-sparkles"></i> 이 주제로 기획
              </button>
            </div>`).join('');

          trendRecommendedTopics.querySelectorAll('.js-plan-topic').forEach((btn) => {
            btn.addEventListener('click', () => {
              window.openPromptStudioForTopic(btn.dataset.topic, btn.dataset.angle);
            });
          });
        }
        if (trendLeoTip) trendLeoTip.textContent = a.leo_algorithm_tip || '';

        showAlert('트렌드 인사이트 리포트가 생성되었습니다!', 'success');
      } catch (err) {
        showAlert('트렌드 분석 오류: ' + err.message, 'error');
      } finally {
        btnAnalyzeTrends.disabled = false;
        btnAnalyzeTrends.innerHTML = '<i class="fa-solid fa-brain"></i> AI 트렌드 리포트 생성';
      }
    });
  }

  // ==============================================================
  // 14. [Phase 1] 채널 빌더 & 레오의 알고리즘 진단
  // ==============================================================
  // 14. [Phase 1] 채널 빌더 & 레오의 알고리즘 진단
  // ==============================================================
  const channelHandleInput = document.getElementById('channelHandleInput');
  const btnCheckHandle = document.getElementById('btnCheckHandle');
  const handleCheckResult = document.getElementById('handleCheckResult');

  const channelGenForm = document.getElementById('channelGenForm');
  const channelTopicInput = document.getElementById('channelTopicInput');
  const channelLangSelect = document.getElementById('channelLangSelect');
  const channelPersonaSelect = document.getElementById('channelPersonaSelect');
  const channelToneSelect = document.getElementById('channelToneSelect');
  const channelAudienceInput = document.getElementById('channelAudienceInput');
  const channelCategorySelect = document.getElementById('channelCategorySelect');
  const channelAudioLangSelect = document.getElementById('channelAudioLangSelect');
  const btnRunChannelGen = document.getElementById('btnRunChannelGen');

  const channelGenResultBox = document.getElementById('channelGenResultBox');
  const btnApplyChannelBranding = document.getElementById('btnApplyChannelBranding');
  const resChannelNameText = document.getElementById('resChannelNameText');
  const btnCopyChannelName = document.getElementById('btnCopyChannelName');
  const resChannelHandlesList = document.getElementById('resChannelHandlesList');
  const resChannelDesc = document.getElementById('resChannelDesc');
  const btnCopyChannelDesc = document.getElementById('btnCopyChannelDesc');
  const resChannelKeywordsList = document.getElementById('resChannelKeywordsList');
  const btnCopyChannelKeywords = document.getElementById('btnCopyChannelKeywords');
  const btnCopyAvatarPrompt = document.getElementById('btnCopyAvatarPrompt');
  const btnCopyAvatarPromptNoText = document.getElementById('btnCopyAvatarPromptNoText');
  const btnCopyBannerPrompt = document.getElementById('btnCopyBannerPrompt');
  const btnCopyBannerPromptNoText = document.getElementById('btnCopyBannerPromptNoText');
  const resUploadDefaultsCard = document.getElementById('resUploadDefaultsCard');
  const btnCopyUploadDefaults = document.getElementById('btnCopyUploadDefaults');
  const resSetupStepsList = document.getElementById('resSetupStepsList');

  const btnRefreshChannelDiag = document.getElementById('btnRefreshChannelDiag');
  const diagSubsCount = document.getElementById('diagSubsCount');
  const diagViewsCount = document.getElementById('diagViewsCount');
  const diagVideosCount = document.getElementById('diagVideosCount');
  const diagAvgViews = document.getElementById('diagAvgViews');
  const diagStageText = document.getElementById('diagStageText');
  const diagHealthScore = document.getElementById('diagHealthScore');
  const diagBottleneck = document.getElementById('diagBottleneck');
  const diagActionPlans = document.getElementById('diagActionPlans');
  const diagMilestoneTip = document.getElementById('diagMilestoneTip');

  let currentChannelPlan = null;

  if (btnCheckHandle) {
    btnCheckHandle.addEventListener('click', async () => {
      const handle = (channelHandleInput ? channelHandleInput.value : '').trim();
      if (!handle) {
        showAlert('핸들을 입력해주세요 (예: @MyName)', 'error');
        return;
      }
      btnCheckHandle.disabled = true;
      btnCheckHandle.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> 확인 중...';
      try {
        const res = await fetch(`/api/channel/check-handle?handle=${encodeURIComponent(handle)}`);
        const data = await res.json();
        if (handleCheckResult) {
          if (data.available) {
            handleCheckResult.innerHTML = `<span style="color:#34d399; font-weight:600;"><i class="fa-solid fa-check"></i> ${escapeHtml(data.message)}</span>`;
          } else {
            handleCheckResult.innerHTML = `<span style="color:#f43f5e; font-weight:600;"><i class="fa-solid fa-xmark"></i> ${escapeHtml(data.message)}</span>`;
          }
        }
      } catch (err) {
        if (handleCheckResult) handleCheckResult.textContent = '확인 오류: ' + err.message;
      } finally {
        btnCheckHandle.disabled = false;
        btnCheckHandle.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> 중복검사';
      }
    });
  }

  if (channelGenForm) {
    channelGenForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const topic = (channelTopicInput ? channelTopicInput.value : '').trim();
      const lang = channelLangSelect ? channelLangSelect.value : '';
      if (!topic) {
        showAlert('채널 주제를 입력해주세요.', 'error');
        return;
      }
      if (!lang) {
        showAlert('채널 언어(BCP-47)를 필수로 선택해주세요.', 'error');
        return;
      }

      btnRunChannelGen.disabled = true;
      btnRunChannelGen.querySelector('.btn-text').style.display = 'none';
      btnRunChannelGen.querySelector('.spinner').style.display = 'inline-block';

      try {
        const res = await fetch('/api/channel/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            topic: topic,
            lang: lang,
            persona_type: channelPersonaSelect ? channelPersonaSelect.value : 'character',
            tone: channelToneSelect ? channelToneSelect.value : '',
            audience: channelAudienceInput ? channelAudienceInput.value.trim() : '',
            category_id: channelCategorySelect ? parseInt(channelCategorySelect.value, 10) : 27,
            audio_lang: channelAudioLangSelect ? channelAudioLangSelect.value : ''
          })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || '기획 생성 실패');
        }

        const plan = await res.json();
        currentChannelPlan = plan;
        renderChannelSetupResult(plan);
        showAlert('유튜브 채널 8대 세팅 기획이 완벽하게 생성되었습니다!', 'success');
      } catch (err) {
        showAlert('채널 기획 생성 실패: ' + err.message, 'error');
      } finally {
        btnRunChannelGen.disabled = false;
        btnRunChannelGen.querySelector('.btn-text').style.display = 'inline-block';
        btnRunChannelGen.querySelector('.spinner').style.display = 'none';
      }
    });
  }

  function renderChannelSetupResult(plan) {
    if (!channelGenResultBox) return;
    channelGenResultBox.style.display = 'block';

    // ① 채널 이름
    if (resChannelNameText) resChannelNameText.textContent = plan.channel_name || plan.topic;

    // ② 핸들 후보 목록
    if (resChannelHandlesList) {
      const handles = plan.handles || [];
      resChannelHandlesList.innerHTML = handles.map(h => {
        const isAvail = h.available;
        const handleName = h.handle;
        const url = h.url || `https://www.youtube.com/@${handleName}`;
        return `
          <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.03); border:1px solid var(--border-color); border-radius:6px; padding:6px 10px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span class="badge ${isAvail ? 'badge-success' : 'badge-danger'}" style="${isAvail ? '' : 'text-decoration:line-through;'}">
                <i class="fa-solid ${isAvail ? 'fa-check' : 'fa-xmark'}"></i> @${escapeHtml(handleName)}
              </span>
              <span style="font-size:0.75rem; color:${isAvail ? '#34d399' : '#f43f5e'};">${escapeHtml(h.status_text || (isAvail ? '사용 가능' : '선점됨'))}</span>
            </div>
            <div style="display:flex; gap:6px;">
              <a href="${escapeHtml(url)}" target="_blank" class="btn btn-xs btn-outline" title="채널 링크 열기"><i class="fa-brands fa-youtube"></i> 확인</a>
              <button class="btn btn-xs btn-outline btn-copy-handle" data-handle="@${escapeHtml(handleName)}"><i class="fa-solid fa-copy"></i> 복사</button>
            </div>
          </div>
        `;
      }).join('');

      resChannelHandlesList.querySelectorAll('.btn-copy-handle').forEach(b => {
        b.addEventListener('click', () => {
          navigator.clipboard.writeText(b.dataset.handle).then(() => showAlert(`${b.dataset.handle} 핸들이 복사되었습니다!`, 'success'));
        });
      });
    }

    // ③ 채널 설명란
    if (resChannelDesc) resChannelDesc.value = plan.description || '';

    // ④ 채널 키워드
    if (resChannelKeywordsList) {
      const kws = plan.keywords || [];
      resChannelKeywordsList.innerHTML = kws.map(k => `<span class="badge badge-accent">${escapeHtml(k)}</span>`).join('');
    }

    // ⑦ 업로드 기본값
    if (resUploadDefaultsCard) {
      const ud = plan.upload_defaults || {};
      resUploadDefaultsCard.innerHTML = `
        <div><strong>제목 템플릿:</strong> <code style="color:#38bdf8;">${escapeHtml(ud.title_template || '')}</code></div>
        <div style="margin-top:4px;"><strong>카테고리 ID:</strong> ${ud.category_id || 27} | <strong>공개 상태:</strong> ${ud.privacy_status || 'private'} | <strong>아동용:</strong> ${ud.made_for_kids ? '예' : '아니오'}</div>
        <div style="margin-top:4px;"><strong>기본 언어:</strong> ${ud.default_language || plan.lang} (음성: ${ud.default_audio_language || plan.audio_lang})</div>
        <div style="margin-top:4px;"><strong>기본 태그:</strong> ${(ud.tags || []).map(t => `<span class="badge badge-subtle" style="font-size:10px;">${escapeHtml(t)}</span>`).join(' ')}</div>
      `;
    }

    // ⑧ 개설 8단계 체크리스트
    if (resSetupStepsList) {
      const steps = plan.setup_steps || [];
      resSetupStepsList.innerHTML = steps.map((s, idx) => `
        <label class="checkbox-label" style="background:rgba(255,255,255,0.02); border:1px solid var(--border-color); border-radius:6px; padding:6px 10px; font-size:0.8rem;">
          <input type="checkbox" id="chkStep_${idx}">
          <span class="custom-checkbox"></span>
          <span>${escapeHtml(s)}</span>
        </label>
      `).join('');
    }
  }

  // 복사 버튼들 바인딩
  if (btnCopyChannelName) {
    btnCopyChannelName.addEventListener('click', () => {
      const text = resChannelNameText?.textContent || '';
      if (text) navigator.clipboard.writeText(text).then(() => showAlert('채널 이름이 복사되었습니다!', 'success'));
    });
  }

  if (btnCopyChannelDesc) {
    btnCopyChannelDesc.addEventListener('click', () => {
      const text = resChannelDesc?.value || '';
      if (text) navigator.clipboard.writeText(text).then(() => showAlert('채널 설명이 복사되었습니다!', 'success'));
    });
  }

  if (btnCopyChannelKeywords) {
    btnCopyChannelKeywords.addEventListener('click', () => {
      if (currentChannelPlan && currentChannelPlan.keywords_formatted) {
        const text = currentChannelPlan.keywords_formatted.join(', ');
        navigator.clipboard.writeText(text).then(() => showAlert('채널 키워드가 복사되었습니다! (유튜브 스튜디오 붙여넣기 가능)', 'success'));
      }
    });
  }

  if (btnCopyAvatarPrompt) {
    btnCopyAvatarPrompt.addEventListener('click', () => {
      if (currentChannelPlan?.avatar_prompt) {
        navigator.clipboard.writeText(currentChannelPlan.avatar_prompt).then(() => showAlert('프로필 아바타 기본 프롬프트가 복사되었습니다!', 'success'));
      }
    });
  }

  if (btnCopyAvatarPromptNoText) {
    btnCopyAvatarPromptNoText.addEventListener('click', () => {
      if (currentChannelPlan?.avatar_prompt_no_text) {
        navigator.clipboard.writeText(currentChannelPlan.avatar_prompt_no_text).then(() => showAlert('프로필 아바타 (no text 순수 심볼) 프롬프트가 복사되었습니다!', 'success'));
      }
    });
  }

  if (btnCopyBannerPrompt) {
    btnCopyBannerPrompt.addEventListener('click', () => {
      if (currentChannelPlan?.banner_prompt) {
        navigator.clipboard.writeText(currentChannelPlan.banner_prompt).then(() => showAlert('채널 배너 기본 프롬프트가 복사되었습니다!', 'success'));
      }
    });
  }

  if (btnCopyBannerPromptNoText) {
    btnCopyBannerPromptNoText.addEventListener('click', () => {
      if (currentChannelPlan?.banner_prompt_no_text) {
        navigator.clipboard.writeText(currentChannelPlan.banner_prompt_no_text).then(() => showAlert('채널 배너 (no text 순수 배경) 프롬프트가 복사되었습니다!', 'success'));
      }
    });
  }

  if (btnCopyUploadDefaults) {
    btnCopyUploadDefaults.addEventListener('click', () => {
      const descTmpl = currentChannelPlan?.upload_defaults?.description_template || currentChannelPlan?.description || '';
      if (descTmpl) navigator.clipboard.writeText(descTmpl).then(() => showAlert('업로드 설명란 템플릿이 복사되었습니다!', 'success'));
    });
  }

  // 유튜브 채널에 설명 & 키워드 원클릭 자동 등록 API 통신
  if (btnApplyChannelBranding) {
    btnApplyChannelBranding.addEventListener('click', async () => {
      if (!currentChannelPlan) {
        showAlert('먼저 채널 세팅을 생성해주세요.', 'error');
        return;
      }

      if (!confirm(`'${currentChannelPlan.channel_name}'의 설명란과 키워드를 현재 연결된 유튜브 채널에 즉시 등록하시겠습니까?\n(API 할당량 50포인트 소모)`)) {
        return;
      }

      btnApplyChannelBranding.disabled = true;
      btnApplyChannelBranding.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> 유튜브 채널에 등록 중...';

      try {
        const res = await fetch('/api/channel/apply-branding', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            description: currentChannelPlan.description,
            keywords: currentChannelPlan.keywords,
            default_language: currentChannelPlan.lang || 'ko'
          })
        });

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || '채널 등록 실패');
        }

        showAlert('유튜브 채널의 설명란 및 키워드가 성공적으로 자동 등록되었습니다!', 'success');
      } catch (err) {
        showAlert('채널 등록 실패: ' + err.message + '\n(유튜브 계정 연결 상태를 확인해주세요)', 'error');
      } finally {
        btnApplyChannelBranding.disabled = false;
        btnApplyChannelBranding.innerHTML = '<i class="fa-solid fa-cloud-arrow-up"></i> 내 채널에 설명·키워드 원클릭 자동 등록';
      }
    });
  }

  async function loadChannelDiagnostics() {
    if (btnRefreshChannelDiag) {
      btnRefreshChannelDiag.disabled = true;
      btnRefreshChannelDiag.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';
    }
    try {
      const res = await fetch('/api/channel/my-status');
      const data = await res.json();
      const m = data.metrics || {};
      const d = data.diagnosis || {};

      if (diagSubsCount) diagSubsCount.textContent = (m.subscribers || 0).toLocaleString() + '명';
      if (diagViewsCount) diagViewsCount.textContent = (m.views || 0).toLocaleString() + '회';
      if (diagVideosCount) diagVideosCount.textContent = (m.videos || 0) + '개';
      if (diagAvgViews) diagAvgViews.textContent = (m.avg_views || 0).toLocaleString() + '회';

      if (diagStageText) diagStageText.textContent = m.stage || d.growth_stage || '';
      if (diagHealthScore) diagHealthScore.textContent = `건강도: ${d.health_score || 80}점`;
      if (diagBottleneck) diagBottleneck.textContent = d.bottleneck || '';
      if (diagActionPlans) {
        diagActionPlans.innerHTML = (d.action_plans || []).map(p => `<li>${escapeHtml(p)}</li>`).join('');
      }
      if (diagMilestoneTip) diagMilestoneTip.textContent = d.next_milestone_tip || '';
    } catch (err) {
      console.warn('채널 진단 실패:', err);
    } finally {
      if (btnRefreshChannelDiag) {
        btnRefreshChannelDiag.disabled = false;
        btnRefreshChannelDiag.innerHTML = '<i class="fa-solid fa-rotate"></i> 새로고침';
      }
    }
  }
  if (btnRefreshChannelDiag) btnRefreshChannelDiag.addEventListener('click', loadChannelDiagnostics);

  // ==============================================================
  // 15. [Phase 4] 영상 자동 제작 (Producer) & 유튜브 업로더
  // ==============================================================
  const producerPlanSelect = document.getElementById('producerPlanSelect');
  const producerResSelect = document.getElementById('producerResSelect');
  const producerTransitionSelect = document.getElementById('producerTransitionSelect');
  const producerBurnSubtitles = document.getElementById('producerBurnSubtitles');
  const producerFitNarration = document.getElementById('producerFitNarration');
  const producerBuildForm = document.getElementById('producerBuildForm');
  const btnStartRender = document.getElementById('btnStartRender');
  const producerProgressBox = document.getElementById('producerProgressBox');
  const producerStepText = document.getElementById('producerStepText');
  const producerPercentText = document.getElementById('producerPercentText');
  const producerProgressBar = document.getElementById('producerProgressBar');
  const producerPlayerBox = document.getElementById('producerPlayerBox');
  const producerVideoPlayer = document.getElementById('producerVideoPlayer');
  const btnDownloadRenderedVideo = document.getElementById('btnDownloadRenderedVideo');

  const ytAuthBadge = document.getElementById('ytAuthBadge');
  const youtubeUploadForm = document.getElementById('youtubeUploadForm');
  const ytUploadVideoPath = document.getElementById('ytUploadVideoPath');
  const ytUploadTitle = document.getElementById('ytUploadTitle');
  const ytUploadDesc = document.getElementById('ytUploadDesc');
  const ytUploadPrivacy = document.getElementById('ytUploadPrivacy');
  const ytUploadCategory = document.getElementById('ytUploadCategory');
  const ytUploadPinnedComment = document.getElementById('ytUploadPinnedComment');
  const btnSubmitYoutubeUpload = document.getElementById('btnSubmitYoutubeUpload');

  async function loadProducerPlans() {
    if (!producerPlanSelect) return;
    try {
      const res = await fetch('/api/channel/history');
      const list = await res.json();
      producerPlanSelect.innerHTML = '<option value="">기획서를 선택하세요...</option>';
      if (Array.isArray(list) && list.length > 0) {
        list.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.id;
          opt.textContent = `[${p.id}] ${p.topic || '채널 기획서'}`;
          producerPlanSelect.appendChild(opt);
        });
      }
      if (currentGeneratedBatch) {
        const opt = document.createElement('option');
        opt.value = currentGeneratedBatch.topic;
        opt.textContent = `[현재 기획] ${currentGeneratedBatch.recommended_title || currentGeneratedBatch.topic}`;
        opt.selected = true;
        producerPlanSelect.appendChild(opt);
      }
    } catch (err) {
      console.warn('플랜 목록 로드 실패:', err);
    }
  }

  async function checkYoutubeStatus() {
    if (!ytAuthBadge) return;
    try {
      const res = await fetch('/api/youtube/status');
      const st = await res.json();
      if (st.authorized && st.channel) {
        ytAuthBadge.className = 'badge badge-accent';
        ytAuthBadge.textContent = `인증됨: ${st.channel.title || '내 채널'}`;
      } else {
        ytAuthBadge.className = 'badge badge-subtle';
        ytAuthBadge.textContent = 'OAuth 인증 필요';
      }
    } catch (err) {
      ytAuthBadge.textContent = '상태 확인 불가';
    }
  }

  if (producerBuildForm) {
    producerBuildForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const planId = producerPlanSelect ? producerPlanSelect.value : '';
      if (!planId) {
        showAlert('합성할 기획서를 선택해주세요.', 'error');
        return;
      }

      btnStartRender.disabled = true;
      btnStartRender.querySelector('.btn-text').style.display = 'none';
      btnStartRender.querySelector('.spinner').style.display = 'inline-block';

      if (producerProgressBox) producerProgressBox.style.display = 'block';
      if (producerProgressBar) producerProgressBar.style.width = '5%';

      try {
        const res = await fetch('/api/producer/build', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            plan_id: planId,
            resolution: producerResSelect ? producerResSelect.value : '1080p',
            burn_subtitles: producerBurnSubtitles ? producerBurnSubtitles.checked : true,
            fit_narration: producerFitNarration ? producerFitNarration.checked : true,
            transition: producerTransitionSelect ? producerTransitionSelect.value : 'fade'
          })
        });

        const data = await res.json();
        const jobId = data.job_id;
        pollProducerJob(jobId);
      } catch (err) {
        showAlert('합성 시작 실패: ' + err.message, 'error');
        btnStartRender.disabled = false;
        btnStartRender.querySelector('.btn-text').style.display = 'inline-block';
        btnStartRender.querySelector('.spinner').style.display = 'none';
      }
    });
  }

  function pollProducerJob(jobId) {
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/api/producer/status/${jobId}`);
        const job = await res.json();
        const pct = job.percent || 0;

        if (producerProgressBar) producerProgressBar.style.width = pct + '%';
        if (producerPercentText) producerPercentText.textContent = pct + '%';
        if (producerStepText) producerStepText.textContent = job.message || '렌더링 중...';

        if (job.status === 'completed') {
          clearInterval(timer);
          btnStartRender.disabled = false;
          btnStartRender.querySelector('.btn-text').style.display = 'inline-block';
          btnStartRender.querySelector('.spinner').style.display = 'none';

          const r = job.result || {};
          if (producerPlayerBox) producerPlayerBox.style.display = 'block';
          if (producerVideoPlayer && r.video_url) producerVideoPlayer.src = r.video_url;
          if (btnDownloadRenderedVideo && r.video_url) btnDownloadRenderedVideo.href = r.video_url;
          if (ytUploadVideoPath && r.video_file) ytUploadVideoPath.value = r.video_file;

          showAlert('영상 렌더링 합성이 성공적으로 완료되었습니다!', 'success');
        } else if (job.status === 'failed') {
          clearInterval(timer);
          btnStartRender.disabled = false;
          btnStartRender.querySelector('.btn-text').style.display = 'inline-block';
          btnStartRender.querySelector('.spinner').style.display = 'none';
          showAlert('영상 렌더링 실패: ' + job.message, 'error');
        }
      } catch (err) {
        clearInterval(timer);
        btnStartRender.disabled = false;
        btnStartRender.querySelector('.btn-text').style.display = 'inline-block';
        btnStartRender.querySelector('.spinner').style.display = 'none';
      }
    }, 1500);
  }

  if (youtubeUploadForm) {
    youtubeUploadForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const videoPath = ytUploadVideoPath ? ytUploadVideoPath.value.trim() : '';
      const title = ytUploadTitle ? ytUploadTitle.value.trim() : '';
      if (!videoPath || !title) {
        showAlert('비디오 파일 경로와 제목은 필수입니다.', 'error');
        return;
      }

      btnSubmitYoutubeUpload.disabled = true;
      btnSubmitYoutubeUpload.querySelector('.btn-text').style.display = 'none';
      btnSubmitYoutubeUpload.querySelector('.spinner').style.display = 'inline-block';

      try {
        const res = await fetch('/api/youtube/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            video_file: videoPath,
            title: title,
            description: ytUploadDesc ? ytUploadDesc.value : '',
            privacy_status: ytUploadPrivacy ? ytUploadPrivacy.value : 'unlisted',
            category_id: ytUploadCategory ? ytUploadCategory.value : '28',
            pinned_comment: ytUploadPinnedComment ? ytUploadPinnedComment.value : ''
          })
        });
        const data = await res.json();
        if (data.status === 'success') {
          showAlert('유튜브 업로드가 성공적으로 완료되었습니다!', 'success');
        } else {
          showAlert('업로드 오류: ' + JSON.stringify(data), 'error');
        }
      } catch (err) {
        showAlert('유튜브 업로드 실패: ' + err.message, 'error');
      } finally {
        btnSubmitYoutubeUpload.disabled = false;
        btnSubmitYoutubeUpload.querySelector('.btn-text').style.display = 'inline-block';
        btnSubmitYoutubeUpload.querySelector('.spinner').style.display = 'none';
      }
    });
  }

  // ==============================================================
  // 16. [Phase 3] 원소스 멀티유즈(OSMU) 마케팅 엔진
  // ==============================================================
  const marketingTopicInput = document.getElementById('marketingTopicInput');
  const marketingContextInput = document.getElementById('marketingContextInput');
  const marketingModeSelect = document.getElementById('marketingModeSelect');
  const marketingToneSelect = document.getElementById('marketingToneSelect');
  const marketingAudienceInput = document.getElementById('marketingAudienceInput');
  const marketingGenForm = document.getElementById('marketingGenForm');
  const btnRunMarketingGen = document.getElementById('btnRunMarketingGen');
  const btnImportFromScript = document.getElementById('btnImportFromScript');
  const btnCopyCurrentMarketing = document.getElementById('btnCopyCurrentMarketing');

  const threadsCountBadge = document.getElementById('threadsCountBadge');
  const threadsPostList = document.getElementById('threadsPostList');
  const blogPostContent = document.getElementById('blogPostContent');
  const newsletterContent = document.getElementById('newsletterContent');
  const marketingHistoryList = document.getElementById('marketingHistoryList');

  let currentMarketingResult = null;
  let currentMarketingActiveTab = 'tabThreads';

  if (btnImportFromScript) {
    btnImportFromScript.addEventListener('click', () => {
      if (currentGeneratedBatch) {
        if (marketingTopicInput) marketingTopicInput.value = currentGeneratedBatch.recommended_title || currentGeneratedBatch.topic || '';
        const scriptText = (currentGeneratedBatch.scenes || []).map(s => `[씬 ${s.scene_num}] ${s.narration}`).join('\n');
        if (marketingContextInput) marketingContextInput.value = scriptText;
        showAlert('현재 기획서의 주제와 대본을 마케팅 폼으로 가져왔습니다!', 'success');
      } else {
        showAlert('가져올 활성 기획 대본이 없습니다. 먼저 씬 기획을 생성해주세요.', 'error');
      }
    });
  }

  document.querySelectorAll('[data-market-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-market-tab]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const target = btn.dataset.marketTab;
      currentMarketingActiveTab = target;

      ['tabThreads', 'tabBlog', 'tabNewsletter'].forEach(tId => {
        const pane = document.getElementById(tId);
        if (pane) pane.style.display = (tId === target) ? 'block' : 'none';
      });
    });
  });

  if (marketingGenForm) {
    marketingGenForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const topic = (marketingTopicInput ? marketingTopicInput.value : '').trim();
      if (!topic) return;

      btnRunMarketingGen.disabled = true;
      btnRunMarketingGen.querySelector('.btn-text').style.display = 'none';
      btnRunMarketingGen.querySelector('.spinner').style.display = 'inline-block';

      try {
        const res = await fetch('/api/marketing/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            topic: topic,
            context: marketingContextInput ? marketingContextInput.value : '',
            mode: marketingModeSelect ? marketingModeSelect.value : 'all',
            tone: marketingToneSelect ? marketingToneSelect.value : 'viral_hook',
            audience: marketingAudienceInput ? marketingAudienceInput.value : '크리에이터, 직장인, 마케터'
          })
        });
        const data = await res.json();
        currentMarketingResult = data.result;
        renderMarketingResult(data.result);
        loadMarketingHistory();
        showAlert('마케팅 콘텐츠 생성이 완료되었습니다!', 'success');
      } catch (err) {
        showAlert('마케팅 생성 오류: ' + err.message, 'error');
      } finally {
        btnRunMarketingGen.disabled = false;
        btnRunMarketingGen.querySelector('.btn-text').style.display = 'inline-block';
        btnRunMarketingGen.querySelector('.spinner').style.display = 'none';
      }
    });
  }

  function renderMarketingResult(result) {
    if (!result) return;
    const threads = result.threads_x || (result.posts ? result : null);
    const blog = result.blog_post;
    const nl = result.newsletter;

    // Threads
    if (threads && threads.posts && threadsPostList) {
      if (threadsCountBadge) threadsCountBadge.textContent = threads.posts.length;
      threadsPostList.innerHTML = threads.posts.map(p => `
        <div class="threads-post-card">
          <div class="threads-post-header">
            <span class="threads-post-number">${p.index}/${threads.posts.length}</span>
            <button class="btn btn-xs btn-outline btn-copy-single" data-text="${escapeHtml(p.content || '')}">
              <i class="fa-solid fa-copy"></i>
            </button>
          </div>
          <div class="threads-post-body">${escapeHtml(p.content || '')}</div>
        </div>
      `).join('');

      threadsPostList.querySelectorAll('.btn-copy-single').forEach(b => {
        b.addEventListener('click', () => {
          navigator.clipboard.writeText(b.dataset.text || '').then(() => showAlert('포스트가 복사되었습니다!', 'success'));
        });
      });
    }

    // Blog
    if (blog && blogPostContent) {
      blogPostContent.innerHTML = `
        <h2 style="margin-top:0; color:#38bdf8;">${escapeHtml(blog.title || '')}</h2>
        <div style="color:var(--text-muted); font-size:0.8rem; margin-bottom:12px;"><strong>메타 설명:</strong> ${escapeHtml(blog.meta_description || '')}</div>
        <div style="white-space: pre-wrap;">${escapeHtml(blog.content_markdown || '')}</div>
      `;
    }

    // Newsletter
    if (nl && newsletterContent) {
      newsletterContent.innerHTML = `
        <div style="background:rgba(255,255,255,0.04); padding:10px; border-radius:6px; margin-bottom:12px;">
          <strong>제목 A/B 테스트:</strong><br>
          • A: ${escapeHtml(nl.subject_line_a || '')}<br>
          • B: ${escapeHtml(nl.subject_line_b || '')}
        </div>
        <div style="white-space: pre-wrap;">${escapeHtml(nl.body_markdown || '')}</div>
      `;
    }
  }

  if (btnCopyCurrentMarketing) {
    btnCopyCurrentMarketing.addEventListener('click', () => {
      let textToCopy = '';
      if (currentMarketingActiveTab === 'tabThreads' && currentMarketingResult?.threads_x?.posts) {
        textToCopy = currentMarketingResult.threads_x.posts.map(p => `[${p.index}/${currentMarketingResult.threads_x.posts.length}]\n${p.content}`).join('\n\n');
      } else if (currentMarketingActiveTab === 'tabBlog' && currentMarketingResult?.blog_post) {
        textToCopy = `# ${currentMarketingResult.blog_post.title}\n\n${currentMarketingResult.blog_post.content_markdown}`;
      } else if (currentMarketingActiveTab === 'tabNewsletter' && currentMarketingResult?.newsletter) {
        textToCopy = `[Subject] ${currentMarketingResult.newsletter.subject_line_a}\n\n${currentMarketingResult.newsletter.body_markdown}`;
      }

      if (textToCopy) {
        navigator.clipboard.writeText(textToCopy).then(() => showAlert('현재 마케팅 콘텐츠가 복사되었습니다!', 'success'));
      } else {
        showAlert('복사할 콘텐츠가 없습니다.', 'error');
      }
    });
  }

  async function loadMarketingHistory() {
    if (!marketingHistoryList) return;
    try {
      const res = await fetch('/api/marketing/history');
      const list = await res.json();
      if (Array.isArray(list) && list.length > 0) {
        marketingHistoryList.innerHTML = list.map(item => `
          <div class="card" style="padding:8px 12px; display:flex; justify-content:space-between; align-items:center; cursor:pointer;" data-entry-id="${item.id}">
            <div>
              <span style="font-weight:600; font-size:0.85rem;">${escapeHtml(item.topic || '무제')}</span>
              <span class="badge badge-subtle" style="margin-left:6px; font-size:0.75rem;">${item.mode}</span>
            </div>
            <button class="btn btn-xs btn-outline btn-load-market" data-id="${item.id}"><i class="fa-solid fa-folder-open"></i> 열기</button>
          </div>
        `).join('');

        marketingHistoryList.querySelectorAll('.btn-load-market').forEach(b => {
          b.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = b.dataset.id;
            try {
              const res2 = await fetch(`/api/marketing/${id}`);
              const full = await res2.json();
              currentMarketingResult = full.result;
              renderMarketingResult(full.result);
              showAlert('보관함에서 콘텐츠를 불러왔습니다.', 'success');
            } catch (err) {
              showAlert('로드 실패: ' + err.message, 'error');
            }
          });
        });
      }
    } catch (err) {
      console.warn('마케팅 히스토리 로드 실패:', err);
    }
  }

  // ==============================================================
  // 17. [Phase 6] 에이전트 루나(Agent Luna) AI 음악 자동화 스튜디오
  // ==============================================================
  const lunaMusicForm = document.getElementById('lunaMusicForm');
  const lunaGenreSelect = document.getElementById('lunaGenreSelect');
  const lunaMoodSelect = document.getElementById('lunaMoodSelect');
  const lunaTopicInput = document.getElementById('lunaTopicInput');
  const lunaDurationSelect = document.getElementById('lunaDurationSelect');
  const lunaVideoQualitySelect = document.getElementById('lunaVideoQualitySelect');
  const btnRunLunaGen = document.getElementById('btnRunLunaGen');

  const lunaEmptyState = document.getElementById('lunaEmptyState');
  const lunaActiveView = document.getElementById('lunaActiveView');
  const lunaStatusBadge = document.getElementById('lunaStatusBadge');

  const lunaCoverImg = document.getElementById('lunaCoverImg');
  const lunaGenreBadge = document.getElementById('lunaGenreBadge');
  const lunaTrackTitle = document.getElementById('lunaTrackTitle');
  const lunaTrackStory = document.getElementById('lunaTrackStory');
  const lunaAudioPlayer = document.getElementById('lunaAudioPlayer');

  const btnRenderLunaVideo = document.getElementById('btnRenderLunaVideo');
  const lunaVideoPlayerBox = document.getElementById('lunaVideoPlayerBox');
  const lunaVideoPlayer = document.getElementById('lunaVideoPlayer');
  const lunaVideoDownloadBtn = document.getElementById('lunaVideoDownloadBtn');

  const lunaPrivacySelect = document.getElementById('lunaPrivacySelect');
  const lunaYtTitlePreview = document.getElementById('lunaYtTitlePreview');
  const lunaYtTagsPreview = document.getElementById('lunaYtTagsPreview');
  const btnUploadLunaYt = document.getElementById('btnUploadLunaYt');
  const lunaUploadResultBadge = document.getElementById('lunaUploadResultBadge');

  const btnRefreshLunaHistory = document.getElementById('btnRefreshLunaHistory');
  const lunaHistoryList = document.getElementById('lunaHistoryList');

  let currentLunaTrack = null;

  if (lunaMusicForm) {
    lunaMusicForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const genre = lunaGenreSelect ? lunaGenreSelect.value : 'lofi';
      const mood = lunaMoodSelect ? lunaMoodSelect.value : 'dawn';
      const customTopic = lunaTopicInput ? lunaTopicInput.value.trim() : '';
      const duration = lunaDurationSelect ? parseInt(lunaDurationSelect.value, 10) : 180;

      btnRunLunaGen.disabled = true;
      btnRunLunaGen.querySelector('.btn-text').style.display = 'none';
      btnRunLunaGen.querySelector('.spinner').style.display = 'inline-block';
      if (lunaStatusBadge) {
        lunaStatusBadge.className = 'badge badge-accent';
        lunaStatusBadge.textContent = '작곡 & 앨범아트 생성 중...';
      }

      try {
        const res = await fetch('/api/luna/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            genre: genre,
            mood: mood,
            custom_topic: customTopic,
            duration_seconds: duration
          })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || '음원 생성 실패');
        }

        const track = await res.json();
        currentLunaTrack = track;
        renderLunaTrackView(track);
        loadLunaHistory();
        showAlert(`'${track.title}' 완곡 음원과 앨범아트가 성공적으로 생성되었습니다!`, 'success');
      } catch (err) {
        showAlert('루나 음원 생성 실패: ' + err.message, 'error');
        if (lunaStatusBadge) {
          lunaStatusBadge.className = 'badge badge-danger';
          lunaStatusBadge.textContent = '생성 오류';
        }
      } finally {
        btnRunLunaGen.disabled = false;
        btnRunLunaGen.querySelector('.btn-text').style.display = 'inline-block';
        btnRunLunaGen.querySelector('.spinner').style.display = 'none';
      }
    });
  }

  function renderLunaTrackView(track) {
    if (!track) return;
    if (lunaEmptyState) lunaEmptyState.style.display = 'none';
    if (lunaActiveView) lunaActiveView.style.display = 'block';

    if (lunaCoverImg) lunaCoverImg.src = track.cover_url || '';
    if (lunaGenreBadge) lunaGenreBadge.textContent = `${track.genre} • ${track.mood}`;
    if (lunaTrackTitle) lunaTrackTitle.textContent = track.title || 'Untitled Track';
    if (lunaTrackStory) lunaTrackStory.textContent = track.story || '';
    if (lunaAudioPlayer) {
      lunaAudioPlayer.src = track.audio_url || '';
      lunaAudioPlayer.load();
    }

    const meta = track.metadata || {};
    if (lunaYtTitlePreview) lunaYtTitlePreview.textContent = meta.youtube_title || track.title;
    if (lunaYtTagsPreview) lunaYtTagsPreview.textContent = (meta.youtube_tags || []).slice(0, 5).join(', ') + '...';

    if (track.video_url) {
      if (lunaVideoPlayerBox) lunaVideoPlayerBox.style.display = 'block';
      if (lunaVideoPlayer) {
        lunaVideoPlayer.src = track.video_url;
        lunaVideoPlayer.load();
      }
      if (lunaVideoDownloadBtn) lunaVideoDownloadBtn.href = track.video_url;
      if (lunaStatusBadge) {
        lunaStatusBadge.className = 'badge badge-success';
        lunaStatusBadge.textContent = '영상 렌더링 완료';
      }
    } else {
      if (lunaVideoPlayerBox) lunaVideoPlayerBox.style.display = 'none';
      if (lunaStatusBadge) {
        lunaStatusBadge.className = 'badge badge-accent';
        lunaStatusBadge.textContent = '음원 준비 완료';
      }
    }

    if (lunaUploadResultBadge) {
      if (track.uploaded_video_id) {
        lunaUploadResultBadge.style.display = 'block';
        lunaUploadResultBadge.innerHTML = `
          <a href="https://youtu.be/${track.uploaded_video_id}" target="_blank" class="badge badge-success" style="font-size:12px; padding:6px 12px; text-decoration:none;">
            <i class="fa-brands fa-youtube"></i> 유튜브 업로드 완료 (youtu.be/${track.uploaded_video_id})
          </a>
        `;
      } else {
        lunaUploadResultBadge.style.display = 'none';
      }
    }
  }

  // 2. 비디오 렌더링
  if (btnRenderLunaVideo) {
    btnRenderLunaVideo.addEventListener('click', async () => {
      if (!currentLunaTrack || !currentLunaTrack.track_id) {
        showAlert('먼저 음원을 생성해주세요.', 'error');
        return;
      }

      btnRenderLunaVideo.disabled = true;
      btnRenderLunaVideo.querySelector('.btn-text').style.display = 'none';
      btnRenderLunaVideo.querySelector('.spinner').style.display = 'inline-block';
      if (lunaStatusBadge) {
        lunaStatusBadge.className = 'badge badge-accent';
        lunaStatusBadge.textContent = '시네마틱 영상 렌더링 중...';
      }

      const quality = lunaVideoQualitySelect ? lunaVideoQualitySelect.value : '1080p';

      try {
        const res = await fetch('/api/luna/render', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            track_id: currentLunaTrack.track_id,
            quality: quality
          })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || '영상 렌더링 실패');
        }

        const updated = await res.json();
        currentLunaTrack = updated;
        renderLunaTrackView(updated);
        loadLunaHistory();
        showAlert('에이전트 루나 감성 음악 비디오 렌더링이 완료되었습니다!', 'success');
      } catch (err) {
        showAlert('비디오 렌더링 오류: ' + err.message, 'error');
      } finally {
        btnRenderLunaVideo.disabled = false;
        btnRenderLunaVideo.querySelector('.btn-text').style.display = 'inline-block';
        btnRenderLunaVideo.querySelector('.spinner').style.display = 'none';
      }
    });
  }

  // 3. 루나 채널 유튜브 업로드
  if (btnUploadLunaYt) {
    btnUploadLunaYt.addEventListener('click', async () => {
      if (!currentLunaTrack || !currentLunaTrack.track_id) {
        showAlert('먼저 트랙을 선택하거나 생성해주세요.', 'error');
        return;
      }
      if (!currentLunaTrack.video_file && !currentLunaTrack.video_url) {
        showAlert('먼저 [2. 비디오 렌더링]을 완료해주세요.', 'error');
        return;
      }

      if (!confirm(`'${currentLunaTrack.title}' 음악 영상을 루나 유튜브 채널에 즉시 업로드하시겠습니까?`)) {
        return;
      }

      btnUploadLunaYt.disabled = true;
      btnUploadLunaYt.querySelector('.btn-text').style.display = 'none';
      btnUploadLunaYt.querySelector('.spinner').style.display = 'inline-block';

      const privacy = lunaPrivacySelect ? lunaPrivacySelect.value : 'public';

      try {
        const res = await fetch('/api/luna/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            track_id: currentLunaTrack.track_id,
            privacy_status: privacy
          })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || '유튜브 업로드 실패');
        }

        const data = await res.json();
        showAlert(`루나 유튜브 채널에 성공적으로 업로드되었습니다! (${data.url || ''})`, 'success');
        if (currentLunaTrack) {
          currentLunaTrack.uploaded_video_id = data.video_id;
        }
        renderLunaTrackView(currentLunaTrack);
        loadLunaHistory();
      } catch (err) {
        showAlert('유튜브 업로드 실패: ' + err.message + '\n(YouTube 계정 연결 상태를 확인해주세요)', 'error');
      } finally {
        btnUploadLunaYt.disabled = false;
        btnUploadLunaYt.querySelector('.btn-text').style.display = 'inline-block';
        btnUploadLunaYt.querySelector('.spinner').style.display = 'none';
      }
    });
  }

  // 4. 루나 히스토리 로드
  async function loadLunaHistory() {
    if (!lunaHistoryList) return;
    try {
      const res = await fetch('/api/luna/history');
      if (!res.ok) return;
      const tracks = await res.json();

      if (!tracks || tracks.length === 0) {
        lunaHistoryList.innerHTML = '<div style="text-align: center; color: var(--text-muted); font-size: 0.8rem; padding: 12px;">저장된 루나 음원이 없습니다.</div>';
        return;
      }

      lunaHistoryList.innerHTML = tracks.map(t => {
        const isRendered = !!t.video_url;
        const isUploaded = !!t.uploaded_video_id;
        return `
          <div class="luna-track-card" data-id="${escapeHtml(t.track_id)}" style="display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.02); border:1px solid var(--border-color); border-radius:6px; padding:8px 10px; cursor:pointer; transition:background 0.2s;">
            <div style="display:flex; align-items:center; gap:10px; min-width:0;">
              <img src="${t.cover_url || '/static/favicon.ico'}" style="width:36px; height:36px; border-radius:4px; object-fit:cover;">
              <div style="min-width:0;">
                <div style="font-size:0.85rem; font-weight:600; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(t.title || 'Untitled')}</div>
                <div style="font-size:0.75rem; color:var(--text-secondary);">${escapeHtml(t.genre || '')} • ${escapeHtml(t.mood || '')}</div>
              </div>
            </div>
            <div style="display:flex; gap:6px; align-items:center; flex-shrink:0;">
              ${isUploaded ? '<span class="badge badge-success" style="font-size:10px;"><i class="fa-brands fa-youtube"></i> 업로드됨</span>' : ''}
              ${isRendered ? '<span class="badge badge-accent" style="font-size:10px;"><i class="fa-solid fa-film"></i> 영상완료</span>' : '<span class="badge badge-subtle" style="font-size:10px;">음원만</span>'}
              <button class="btn btn-xs btn-outline btn-load-luna-track" data-id="${escapeHtml(t.track_id)}"><i class="fa-solid fa-play"></i></button>
            </div>
          </div>
        `;
      }).join('');

      lunaHistoryList.querySelectorAll('.btn-load-luna-track, .luna-track-card').forEach(elem => {
        elem.addEventListener('click', async (e) => {
          const id = elem.dataset.id || elem.closest('.luna-track-card')?.dataset.id;
          if (!id) return;
          try {
            const trackRes = await fetch(`/api/luna/history`);
            const allT = await trackRes.json();
            const found = allT.find(x => x.track_id === id);
            if (found) {
              currentLunaTrack = found;
              renderLunaTrackView(found);
              showAlert(`'${found.title}' 트랙을 로드했습니다.`, 'success');
            }
          } catch (err) {
            console.warn('트랙 로드 실패:', err);
          }
        });
      });
    } catch (err) {
      console.warn('루나 히스토리 로드 실패:', err);
    }
  }

  if (btnRefreshLunaHistory) {
    btnRefreshLunaHistory.addEventListener('click', loadLunaHistory);
  }

  // ==============================================================
  // 18. [Phase 7] API 키 및 시스템 환경설정 통합 관리 모달
  // ==============================================================
  const btnOpenEnvSettingsModal = document.getElementById('btnOpenEnvSettingsModal');
  const envSettingsModal = document.getElementById('envSettingsModal');
  const btnCloseEnvSettingsModal = document.getElementById('btnCloseEnvSettingsModal');

  const envGeminiKeyBadge = document.getElementById('envGeminiKeyBadge');
  const envGeminiKeyInput = document.getElementById('envGeminiKeyInput');
  const btnToggleGeminiKeyVisibility = document.getElementById('btnToggleGeminiKeyVisibility');
  const btnSaveGeminiKey = document.getElementById('btnSaveGeminiKey');
  const btnImportLunaKeys = document.getElementById('btnImportLunaKeys');

  const envYtAuthBadge = document.getElementById('envYtAuthBadge');
  const envClientSecretStatus = document.getElementById('envClientSecretStatus');
  const envYtChannelList = document.getElementById('envYtChannelList');
  const btnConnectYoutube = document.getElementById('btnConnectYoutube');
  const btnDisconnectYoutube = document.getElementById('btnDisconnectYoutube');

  const envLlmPreference = document.getElementById('envLlmPreference');
  const envFfmpegStatus = document.getElementById('envFfmpegStatus');

  async function loadEnvSettings() {
    try {
      const res = await fetch('/api/settings/env');
      if (!res.ok) return;
      const data = await res.json();

      // 1. Gemini Key 상태
      if (envGeminiKeyBadge) {
        if (data.gemini_api_key_configured) {
          envGeminiKeyBadge.className = 'badge badge-success';
          envGeminiKeyBadge.innerHTML = `<i class="fa-solid fa-check"></i> 등록됨 (${escapeHtml(data.gemini_api_key_masked)})`;
        } else {
          envGeminiKeyBadge.className = 'badge badge-subtle';
          envGeminiKeyBadge.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> 미등록';
        }
      }

      // 2. YouTube 상태
      if (envClientSecretStatus) {
        envClientSecretStatus.innerHTML = data.has_client_secret 
          ? '<span style="color:#34d399;"><i class="fa-solid fa-check"></i> data/youtube/ 에 정상 배치됨</span>' 
          : '<span style="color:#f43f5e;"><i class="fa-solid fa-xmark"></i> data/youtube/client_secret.json 파일 없음</span>';
      }

      if (envYtAuthBadge) {
        if (data.youtube_authorized) {
          envYtAuthBadge.className = 'badge badge-success';
          envYtAuthBadge.innerHTML = '<i class="fa-solid fa-circle-check"></i> 인증 완료';
        } else {
          envYtAuthBadge.className = 'badge badge-subtle';
          envYtAuthBadge.innerHTML = '미인증';
        }
      }

      renderYoutubeChannels(data.youtube_channels, data.youtube_active_channel_id);

      // 3. 엔진 상태
      if (envLlmPreference) {
        const prefMap = { auto: 'Auto (자동 감지)', lmstudio: 'LM Studio (로컬)', ollama: 'Ollama (로컬)' };
        envLlmPreference.textContent = prefMap[data.llm_preference] || data.llm_preference;
      }

      if (envFfmpegStatus) {
        envFfmpegStatus.innerHTML = data.ffmpeg_installed 
          ? '<span style="color:#34d399;"><i class="fa-solid fa-check"></i> 정상 설치 및 사용 가능</span>' 
          : '<span style="color:#f43f5e;"><i class="fa-solid fa-xmark"></i> 시스템 미설치</span>';
      }
    } catch (err) {
      console.warn('환경설정 조회 실패:', err);
    }
  }

  // 연결된 유튜브 채널 목록 렌더링 (활성 채널 전환 / 개별 연결 해제)
  function renderYoutubeChannels(channels, activeId) {
    if (!envYtChannelList) return;
    const list = Array.isArray(channels) ? channels : [];
    if (!list.length) {
      envYtChannelList.innerHTML = '<div style="opacity:.6;">연결된 채널이 없습니다. [채널 추가 연결]을 눌러주세요.</div>';
      return;
    }

    envYtChannelList.innerHTML = list.map((ch) => {
      const active = ch.active || ch.id === activeId;
      const border = active ? 'rgba(52,211,153,.5)' : 'var(--border-color)';
      const bg = active ? 'rgba(52,211,153,.08)' : 'transparent';
      const thumb = ch.thumbnail
        ? `<img src="${escapeHtml(ch.thumbnail)}" alt="" style="width:24px;height:24px;border-radius:50%;flex:none;">`
        : '';
      const rightBtn = active
        ? '<span class="badge badge-success" style="font-size:10px;">사용 중</span>'
        : `<button type="button" class="btn btn-xs btn-outline js-yt-select" data-id="${escapeHtml(ch.id)}">이 채널 사용</button>`;
      return `
        <div style="display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:6px;border:1px solid ${border};background:${bg};">
          ${thumb}
          <div style="flex:1;min-width:0;">
            <div style="color:#fff;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(ch.title || ch.id)}</div>
            <div style="font-size:.72rem;opacity:.6;">${escapeHtml(ch.custom_url || ch.id)}</div>
          </div>
          ${rightBtn}
          <button type="button" class="btn btn-xs btn-outline js-yt-remove" data-id="${escapeHtml(ch.id)}" title="이 채널만 연결 해제" style="color:#f43f5e;">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>`;
    }).join('');

    envYtChannelList.querySelectorAll('.js-yt-select').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        btn.disabled = true;
        try {
          const res = await fetch(`/api/youtube/channels/select?channel_id=${encodeURIComponent(id)}`, { method: 'POST' });
          const d = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(d.detail || '채널 전환에 실패했습니다.');
          showAlert('업로드에 사용할 채널을 전환했습니다.', 'success');
          loadEnvSettings();
        } catch (err) {
          showAlert('채널 전환 오류: ' + err.message, 'error');
          btn.disabled = false;
        }
      });
    });

    envYtChannelList.querySelectorAll('.js-yt-remove').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        if (!confirm('이 채널의 연결만 해제하시겠습니까? (다른 채널 연결은 유지됩니다)')) return;
        btn.disabled = true;
        try {
          const res = await fetch(`/api/youtube/auth/disconnect?channel_id=${encodeURIComponent(id)}`, { method: 'POST' });
          const d = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(d.detail || '연결 해제에 실패했습니다.');
          showAlert('채널 연결이 해제되었습니다.', 'success');
          loadEnvSettings();
        } catch (err) {
          showAlert('연결 해제 오류: ' + err.message, 'error');
          btn.disabled = false;
        }
      });
    });
  }

  // 채널 추가 연결 (이미 연결된 채널이 있어도 새 채널을 추가로 연결)
  if (btnConnectYoutube) {
    btnConnectYoutube.addEventListener('click', async () => {
      const orig = btnConnectYoutube.innerHTML;
      btnConnectYoutube.disabled = true;
      btnConnectYoutube.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 브라우저에서 인증 중...';
      showAlert('브라우저에 열린 구글 동의 화면에서 연결할 채널을 선택해주세요.', 'success');
      try {
        const res = await fetch('/api/youtube/auth/login?force=true');
        const d = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(d.detail || '연결에 실패했습니다.');
        showAlert(d.message || '채널이 연결되었습니다.', 'success');
        loadEnvSettings();
      } catch (err) {
        showAlert('유튜브 연결 오류: ' + err.message, 'error');
      } finally {
        btnConnectYoutube.disabled = false;
        btnConnectYoutube.innerHTML = orig;
      }
    });
  }

  if (btnOpenEnvSettingsModal && envSettingsModal) {
    btnOpenEnvSettingsModal.addEventListener('click', () => {
      envSettingsModal.style.display = 'flex';
      loadEnvSettings();
    });
  }

  if (btnCloseEnvSettingsModal && envSettingsModal) {
    btnCloseEnvSettingsModal.addEventListener('click', () => {
      envSettingsModal.style.display = 'none';
    });
  }

  // 키 표시/숨김 토글
  if (btnToggleGeminiKeyVisibility && envGeminiKeyInput) {
    btnToggleGeminiKeyVisibility.addEventListener('click', () => {
      const isPwd = envGeminiKeyInput.type === 'password';
      envGeminiKeyInput.type = isPwd ? 'text' : 'password';
      btnToggleGeminiKeyVisibility.innerHTML = isPwd ? '<i class="fa-solid fa-eye-slash"></i>' : '<i class="fa-solid fa-eye"></i>';
    });
  }

  // 키 저장 버튼
  if (btnSaveGeminiKey && envGeminiKeyInput) {
    btnSaveGeminiKey.addEventListener('click', async () => {
      const keyVal = envGeminiKeyInput.value.trim();
      if (!keyVal) {
        showAlert('Gemini API 키를 입력해주세요.', 'error');
        return;
      }

      btnSaveGeminiKey.disabled = true;
      btnSaveGeminiKey.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> 저장 중...';

      try {
        const res = await fetch('/api/settings/env', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ gemini_api_key: keyVal })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || '저장 실패');
        }

        envGeminiKeyInput.value = '';
        showAlert('Gemini API 키가 .env 파일에 안전하게 저장되었습니다!', 'success');
        loadEnvSettings();
      } catch (err) {
        showAlert('API 키 저장 실패: ' + err.message, 'error');
      } finally {
        btnSaveGeminiKey.disabled = false;
        btnSaveGeminiKey.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> .env 저장';
      }
    });
  }

  // 기존 루나 키 자동 가져오기
  if (btnImportLunaKeys) {
    btnImportLunaKeys.addEventListener('click', async () => {
      btnImportLunaKeys.disabled = true;
      btnImportLunaKeys.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> 연동 중...';

      try {
        const res = await fetch('/api/settings/import-luna-keys', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '연동 실패');

        showAlert(`기존 루나 키와 인증 파일이 성공적으로 동기화되었습니다!\n(${data.imported.join(', ')})`, 'success');
        loadEnvSettings();
      } catch (err) {
        showAlert('루나 키 연동 실패: ' + err.message, 'error');
      } finally {
        btnImportLunaKeys.disabled = false;
        btnImportLunaKeys.innerHTML = '<i class="fa-solid fa-bolt"></i> 기존 루나 키 자동 가져오기';
      }
    });
  }

  // 유튜브 연결 해제
  if (btnDisconnectYoutube) {
    btnDisconnectYoutube.addEventListener('click', async () => {
      if (!confirm('연결된 모든 유튜브 채널의 연결을 해제하시겠습니까?')) return;
      try {
        await fetch('/api/youtube/auth/disconnect', { method: 'POST' });
        showAlert('모든 유튜브 채널 연결이 해제되었습니다.', 'success');
        loadEnvSettings();
      } catch (err) {
        showAlert('연결 해제 오류: ' + err.message, 'error');
      }
    });
  }

  // ==============================================================
  // 19. [Phase 8] Meta Threads API 연동 & 실시간 타래 자동 발행
  // ==============================================================
  const envThreadsBadge = document.getElementById('envThreadsBadge');
  const envThreadsTokenInput = document.getElementById('envThreadsTokenInput');
  const envThreadsUserIdInput = document.getElementById('envThreadsUserIdInput');
  const btnSaveThreadsToken = document.getElementById('btnSaveThreadsToken');
  const envThreadsAccountInfo = document.getElementById('envThreadsAccountInfo');
  const btnDisconnectThreads = document.getElementById('btnDisconnectThreads');

  const marketingThreadsStatusBadge = document.getElementById('marketingThreadsStatusBadge');
  const btnPublishThreadsLive = document.getElementById('btnPublishThreadsLive');
  const threadsPublishResultBox = document.getElementById('threadsPublishResultBox');

  async function loadThreadsStatus() {
    try {
      const res = await fetch('/api/threads/status');
      if (!res.ok) return;
      const data = await res.json();

      const isConn = data.connected;
      const uname = data.username ? `@${data.username}` : '';

      // 1. 설정 모달 배지
      if (envThreadsBadge) {
        if (isConn) {
          envThreadsBadge.className = 'badge badge-success';
          envThreadsBadge.innerHTML = `<i class="fa-brands fa-threads"></i> 연결됨 (${escapeHtml(uname)})`;
        } else {
          envThreadsBadge.className = 'badge badge-subtle';
          envThreadsBadge.innerHTML = '미등록';
        }
      }

      if (envThreadsAccountInfo) {
        envThreadsAccountInfo.textContent = isConn 
          ? `✅ 연결된 계정: ${uname} (토큰: ${data.masked_token || '***'})` 
          : '연결된 계정 없음 (토큰 입력 필요)';
      }

      // 2. 마케팅 탭 배지
      if (marketingThreadsStatusBadge) {
        if (isConn) {
          marketingThreadsStatusBadge.className = 'badge badge-success';
          marketingThreadsStatusBadge.innerHTML = `<i class="fa-solid fa-circle-check"></i> ${escapeHtml(uname)} 계정 준비됨`;
        } else {
          marketingThreadsStatusBadge.className = 'badge badge-subtle';
          marketingThreadsStatusBadge.innerHTML = '키 미설정 (설정 모달에서 등록)';
        }
      }
    } catch (err) {
      console.warn('Threads 상태 조회 실패:', err);
    }
  }

  // Threads 토큰 저장
  if (btnSaveThreadsToken) {
    btnSaveThreadsToken.addEventListener('click', async () => {
      const token = envThreadsTokenInput ? envThreadsTokenInput.value.trim() : '';
      const uid = envThreadsUserIdInput ? envThreadsUserIdInput.value.trim() : '';

      if (!token) {
        showAlert('Threads User Access Token을 입력해주세요.', 'error');
        return;
      }

      btnSaveThreadsToken.disabled = true;
      btnSaveThreadsToken.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> 저장 중...';

      try {
        const res = await fetch('/api/threads/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ access_token: token, user_id: uid })
        });

        const data = await res.json();
        if (data.connected) {
          showAlert(`Threads @${data.username} 계정에 성공적으로 연결되었습니다!`, 'success');
        } else {
          showAlert(data.message || '토큰이 저장되었으나 인증을 확인해주세요.', 'error');
        }
        if (envThreadsTokenInput) envThreadsTokenInput.value = '';
        loadThreadsStatus();
      } catch (err) {
        showAlert('Threads 설정 저장 실패: ' + err.message, 'error');
      } finally {
        btnSaveThreadsToken.disabled = false;
        btnSaveThreadsToken.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> 저장';
      }
    });
  }

  // Threads 연결 해제
  if (btnDisconnectThreads) {
    btnDisconnectThreads.addEventListener('click', async () => {
      if (!confirm('Threads 계정 연결을 해제하시겠습니까?')) return;
      try {
        await fetch('/api/threads/auth/disconnect', { method: 'POST' });
        showAlert('Threads 계정 연결이 해제되었습니다.', 'success');
        loadThreadsStatus();
      } catch (err) {
        showAlert('연결 해제 오류: ' + err.message, 'error');
      }
    });
  }

  // Threads에 5개 타래 즉시 자동 연쇄 발행
  if (btnPublishThreadsLive) {
    btnPublishThreadsLive.addEventListener('click', async () => {
      // 현재 생성된 스레드 텍스트 추출
      let posts = [];
      if (currentMarketingResult && currentMarketingResult.threads && currentMarketingResult.threads.posts) {
        posts = currentMarketingResult.threads.posts;
      } else {
        // DOM에서 텍스트 수집
        const postBoxes = document.querySelectorAll('#threadsPostList .market-content-box');
        postBoxes.forEach(box => {
          const t = box.textContent.trim();
          if (t) posts.push(t);
        });
      }

      if (!posts || posts.length === 0) {
        showAlert('먼저 좌측에서 마케팅 자산(스레드 타래)을 생성해주세요.', 'error');
        return;
      }

      if (!confirm(`총 ${posts.length}개의 스레드 타래를 실제 Threads 계정에 순차 연쇄 발행하시겠습니까?`)) {
        return;
      }

      btnPublishThreadsLive.disabled = true;
      btnPublishThreadsLive.querySelector('.btn-text').style.display = 'none';
      btnPublishThreadsLive.querySelector('.spinner').style.display = 'inline-block';
      if (threadsPublishResultBox) threadsPublishResultBox.style.display = 'none';

      try {
        const res = await fetch('/api/threads/publish', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ posts: posts, delay_seconds: 2.0 })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || 'Threads 자동 발행 실패');
        }

        const data = await res.json();
        showAlert(`🎉 ${data.total_published}개 스레드 타래가 실제 Threads에 성공적으로 연쇄 발행되었습니다!`, 'success');

        if (threadsPublishResultBox) {
          threadsPublishResultBox.style.display = 'block';
          threadsPublishResultBox.innerHTML = `
            <div style="background: rgba(34, 197, 94, 0.1); border: 1px solid rgba(34, 197, 94, 0.3); border-radius: 8px; padding: 12px 16px; display: flex; justify-content: space-between; align-items: center;">
              <div>
                <strong style="color: #4ade80; font-size: 0.9rem;"><i class="fa-solid fa-circle-check"></i> ${data.total_published}개 타래 발행 완료!</strong>
                <div style="color: var(--text-secondary); font-size: 0.8rem; margin-top: 2px;">모든 답글이 정상적으로 체이닝되어 Threads 피드에 등록되었습니다.</div>
              </div>
              ${data.thread_url ? `
                <a href="${data.thread_url}" target="_blank" class="btn btn-xs btn-primary" style="background: #000; border: 1px solid #fff; color: #fff; text-decoration: none;">
                  <i class="fa-brands fa-threads"></i> 실시간 스레드 보기 <i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 10px;"></i>
                </a>
              ` : ''}
            </div>
          `;
        }
      } catch (err) {
        showAlert('Threads 자동 발행 오류: ' + err.message + '\n(API 설정 모달에서 토큰 연결 상태를 확인해주세요)', 'error');
      } finally {
        btnPublishThreadsLive.disabled = false;
        btnPublishThreadsLive.querySelector('.btn-text').style.display = 'inline-block';
        btnPublishThreadsLive.querySelector('.spinner').style.display = 'none';
      }
    });
  }

  // ==============================================================
  // 20. [Phase 10] 캡컷(CapCut) 타임라인 조립 & 렌더링 모드 양자택일
  // ==============================================================
  const btnModeCapCut = document.getElementById('btnModeCapCut');
  const btnModeFfmpeg = document.getElementById('btnModeFfmpeg');
  const panelRenderCapCut = document.getElementById('panelRenderCapCut');
  const panelRenderFfmpeg = document.getElementById('panelRenderFfmpeg');
  const producerBgmSelect = document.getElementById('producerBgmSelect');

  const capcutAppBadge = document.getElementById('capcutAppBadge');
  const capcutTransitionSelect = document.getElementById('capcutTransitionSelect');
  const capcutRatioSelect = document.getElementById('capcutRatioSelect');
  const btnExportToCapCut = document.getElementById('btnExportToCapCut');
  const btnLaunchCapCutApp = document.getElementById('btnLaunchCapCutApp');
  const capcutExportResultBox = document.getElementById('capcutExportResultBox');

  if (btnModeCapCut && btnModeFfmpeg) {
    btnModeCapCut.addEventListener('click', () => {
      btnModeCapCut.className = 'btn btn-sm btn-primary';
      btnModeCapCut.style.background = 'linear-gradient(135deg, #0284c7, #06b6d4)';
      btnModeCapCut.style.border = 'none';
      btnModeFfmpeg.className = 'btn btn-sm btn-outline';
      btnModeFfmpeg.style.background = 'transparent';
      if (panelRenderCapCut) panelRenderCapCut.style.display = 'block';
      if (panelRenderFfmpeg) panelRenderFfmpeg.style.display = 'none';
    });

    btnModeFfmpeg.addEventListener('click', () => {
      btnModeFfmpeg.className = 'btn btn-sm btn-primary';
      btnModeFfmpeg.style.background = 'var(--primary-color)';
      btnModeFfmpeg.style.border = 'none';
      btnModeCapCut.className = 'btn btn-sm btn-outline';
      btnModeCapCut.style.background = 'transparent';
      if (panelRenderCapCut) panelRenderCapCut.style.display = 'none';
      if (panelRenderFfmpeg) panelRenderFfmpeg.style.display = 'block';
    });
  }

  // 루나(Luna) 스튜디오 발매 음원 BGM 목록 동적 연동
  async function loadLunaBgmOptions() {
    if (!producerBgmSelect) return;
    try {
      const res = await fetch('/api/luna/history');
      if (!res.ok) return;
      const data = await res.json();
      const tracks = data.tracks || [];

      producerBgmSelect.innerHTML = `
        <option value="">배경음악 없음 (대사 나레이션만)</option>
        <option value="__default_lofi__">기본 잔잔한 앰비언트 로파이 (432Hz Soundscape)</option>
      `;

      if (tracks.length > 0) {
        const group = document.createElement('optgroup');
        group.label = '🎵 에이전트 루나 발매 음원 (스튜디오)';
        tracks.forEach(t => {
          if (t.audio_url) {
            const opt = document.createElement('option');
            opt.value = t.audio_url;
            opt.textContent = `🎵 ${t.title} [${t.genre || 'Ambient'}] (${Math.round(t.duration_seconds || 180)}초)`;
            group.appendChild(opt);
          }
        });
        producerBgmSelect.appendChild(group);
      }
    } catch (err) {
      console.warn('루나 BGM 목록 로드 실패:', err);
    }
  }

  async function loadCapcutStatus() {
    try {
      const res = await fetch('/api/capcut/status');
      if (!res.ok) return;
      const data = await res.json();

      if (capcutAppBadge) {
        if (data.app_installed) {
          capcutAppBadge.className = 'badge badge-success';
          capcutAppBadge.innerHTML = '<i class="fa-solid fa-check"></i> CapCut 설치됨';
        } else {
          capcutAppBadge.className = 'badge badge-subtle';
          capcutAppBadge.innerHTML = 'CapCut 미설치';
        }
      }
    } catch (err) {
      console.warn('CapCut 상태 조회 실패:', err);
    }
  }

  // 캡컷 프로젝트 자동 조립 실행
  if (btnExportToCapCut) {
    btnExportToCapCut.addEventListener('click', async () => {
      const planId = producerPlanSelect ? producerPlanSelect.value : '';
      if (!planId) {
        showAlert('먼저 상단에서 캡컷으로 내보낼 [영상 기획서]를 선택해주세요.', 'error');
        return;
      }

      btnExportToCapCut.disabled = true;
      btnExportToCapCut.querySelector('.btn-text').style.display = 'none';
      btnExportToCapCut.querySelector('.spinner').style.display = 'inline-block';
      if (capcutExportResultBox) capcutExportResultBox.style.display = 'none';

      const trans = capcutTransitionSelect ? capcutTransitionSelect.value : 'dissolve';
      const ratio = capcutRatioSelect ? capcutRatioSelect.value : '16:9';
      let bgmPath = producerBgmSelect ? producerBgmSelect.value : '';
      if (bgmPath.startsWith('/data/')) {
        bgmPath = bgmPath.substring(1); // 'data/...'
      }

      try {
        const res = await fetch('/api/capcut/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            plan_id: planId,
            transition_type: trans,
            aspect_ratio: ratio,
            bgm_path: bgmPath
          })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || '캡컷 프로젝트 생성 실패');
        }

        const data = await res.json();
        showAlert(`🎉 캡컷 프로젝트 '${data.project_name}' 생성이 완료되었습니다!`, 'success');

        if (capcutExportResultBox) {
          capcutExportResultBox.style.display = 'block';
          capcutExportResultBox.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <div>
                <strong style="color: #38bdf8;"><i class="fa-solid fa-circle-check"></i> 캡컷 타임라인 조립 완료!</strong>
                <div style="color: var(--text-secondary); margin-top: 2px;">
                  • <strong>${data.total_scenes}개 씬</strong> 클립 + 대사 나레이션 싱크<br>
                  • <strong>전환 이펙트</strong>: ${data.transition_applied} (${data.total_duration_seconds}초 영상)
                </div>
              </div>
              <button type="button" class="btn btn-sm btn-primary btn-open-capcut-now" style="background: #38bdf8; border: none; color: #000; font-weight: 700;">
                <i class="fa-solid fa-play"></i> CapCut 지금 열기
              </button>
            </div>
          `;

          capcutExportResultBox.querySelector('.btn-open-capcut-now')?.addEventListener('click', async () => {
            try {
              await fetch('/api/capcut/open', { method: 'POST' });
              showAlert('CapCut 앱을 실행했습니다.', 'success');
            } catch (err) {
              showAlert('CapCut 실행 실패: ' + err.message, 'error');
            }
          });
        }
      } catch (err) {
        showAlert('캡컷 조립 실패: ' + err.message, 'error');
      } finally {
        btnExportToCapCut.disabled = false;
        btnExportToCapCut.querySelector('.btn-text').style.display = 'inline-block';
        btnExportToCapCut.querySelector('.spinner').style.display = 'none';
      }
    });
  }

  // 캡컷 앱 열기 버튼
  if (btnLaunchCapCutApp) {
    btnLaunchCapCutApp.addEventListener('click', async () => {
      try {
        await fetch('/api/capcut/open', { method: 'POST' });
        showAlert('CapCut 앱을 실행했습니다.', 'success');
      } catch (err) {
        showAlert('CapCut 실행 오류: ' + err.message, 'error');
      }
    });
  }

  // 초기 데이터 로드
  loadHistory();
  loadTrends();
  loadEnvSettings();
  loadThreadsStatus();
  loadCapcutStatus();
  loadLunaBgmOptions();
});




