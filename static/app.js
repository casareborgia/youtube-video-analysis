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

      // 백엔드별 그룹핑 (Google Gemini 최우선 정렬)
      const order = ['Google Gemini (클라우드)', 'LM Studio', 'Ollama'];
      const grouped = {};
      models.forEach(m => {
        const label = m.backend_label || '기타 AI';
        if (!grouped[label]) grouped[label] = [];
        grouped[label].push(m);
      });

      // 정렬된 라벨 순서
      const sortedLabels = Object.keys(grouped).sort((a, b) => {
        const ia = order.indexOf(a);
        const ib = order.indexOf(b);
        return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
      });

      let html = '';
      for (const label of sortedLabels) {
        const items = grouped[label];
        const isGemini = label.includes('Gemini');
        const headerColor = isGemini ? '#38bdf8' : '#8b5cf6';
        const headerIcon = isGemini ? '<i class="fa-solid fa-cloud" style="margin-right:6px;"></i>' : '<i class="fa-solid fa-microchip" style="margin-right:6px;"></i>';
        const tagHtml = isGemini ? '<span style="font-size:0.68rem;background:rgba(56,189,248,0.15);color:#38bdf8;padding:2px 8px;border-radius:12px;font-weight:600;margin-left:6px;">구독/API 연동</span>' : '';

        html += `<div style="font-size:0.75rem;font-weight:700;color:${headerColor};text-transform:uppercase;
          letter-spacing:0.08em;margin:12px 0 6px;padding-left:4px;display:flex;align-items:center;">
          ${headerIcon} ${label} ${tagHtml}
        </div>`;

        items.forEach(m => {
          const isActive = m.id === selectedModel;
          const activeBorder = isGemini ? '#38bdf8' : '#8b5cf6';
          const activeBg = isGemini ? 'rgba(56,189,248,0.18)' : 'rgba(139,92,246,0.18)';
          const activeColor = isGemini ? '#38bdf8' : '#8b5cf6';
          const itemIcon = isGemini ? 'fa-solid fa-bolt' : (isActive ? 'fa-solid fa-circle-check' : 'fa-regular fa-circle');

          html += `
            <button class="llm-model-item" data-model="${escapeHtml(m.id)}" style="
              display:flex; align-items:center; gap:12px; width:100%;
              padding:11px 14px; border-radius:10px; border:1px solid ${isActive ? activeBorder : 'rgba(255,255,255,0.08)'};
              background:${isActive ? activeBg : 'rgba(255,255,255,0.03)'};
              color:var(--text,#e0e0e0); cursor:pointer; text-align:left;
              transition:all 0.15s; font-size:0.88rem; margin-bottom:5px;
            "
            onmouseover="this.style.background='${isGemini ? 'rgba(56,189,248,0.12)' : 'rgba(139,92,246,0.12)'}';this.style.borderColor='${activeBorder}'"
            onmouseout="this.style.background='${isActive ? activeBg : 'rgba(255,255,255,0.03)'}';this.style.borderColor='${isActive ? activeBorder : 'rgba(255,255,255,0.08)'}'"
            >
              <i class="${itemIcon}" style="color:${isActive ? activeColor : '#64748b'};font-size:0.95rem;flex-shrink:0;"></i>
              <div style="flex:1;display:flex;flex-direction:column;gap:2px;">
                <span style="font-weight:${isActive ? '700' : '500'};word-break:break-all;">${escapeHtml(m.id)}</span>
                ${isGemini ? '<span style="font-size:0.73rem;color:#94a3b8;">Google DeepMind 초고속 클라우드 추론</span>' : ''}
              </div>
              ${isActive ? `<span style="font-size:0.72rem;background:${activeColor};color:#fff;font-weight:700;padding:3px 9px;border-radius:20px;flex-shrink:0;">활성 사용 중</span>` : ''}
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
          showAlert(`AI 모델이 [${modelId}]로 전환되었습니다.`, 'success');
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

        if (data.active.backend_type === 'gemini') {
          llmBackendName.innerHTML = `<i class="fa-solid fa-cloud" style="color:#38bdf8;margin-right:4px;"></i>Google Gemini`;
          llmStatusBadge.title = `Google Gemini 클라우드 (${displayModel}) 연동 중 • 클릭하여 모델 변경`;
        } else {
          llmBackendName.textContent = data.active.name;
          llmStatusBadge.title = `로컬 AI (${displayModel}) • 클릭하여 모델 변경`;
        }
        llmModelBadge.textContent = displayModel;
        llmModelBadge.style.display = 'inline-block';
      } else {
        dot.className = 'status-dot offline';
        llmBackendName.textContent = 'AI 연결 없음';
        llmModelBadge.textContent = 'API 키 등록 또는 로컬 AI 실행 필요';
        llmModelBadge.style.display = 'inline-block';
        llmStatusBadge.title = '우측 상단 ⚙️ 설정에서 Gemini API 키를 등록해주세요.';
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
  const navTabSocial = document.getElementById('navTabSocial');

  const viewAnalysis = document.getElementById('viewAnalysis');
  const viewChannel = document.getElementById('viewChannel');
  const viewPromptStudio = document.getElementById('viewPromptStudio');
  const viewProducer = document.getElementById('viewProducer');
  const viewMarketing = document.getElementById('viewMarketing');
  const viewMusic = document.getElementById('viewMusic');
  const viewSocial = document.getElementById('viewSocial');

  const allNavTabs = [
    { tab: navTabAnalysis, view: viewAnalysis, id: 'analysis' },
    { tab: navTabChannel, view: viewChannel, id: 'channel' },
    { tab: navTabPromptStudio, view: viewPromptStudio, id: 'promptStudio' },
    { tab: navTabProducer, view: viewProducer, id: 'producer' },
    { tab: navTabMarketing, view: viewMarketing, id: 'marketing' },
    { tab: navTabMusic, view: viewMusic, id: 'music' },
    { tab: navTabSocial, view: viewSocial, id: 'social' }
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
      const briefList = document.getElementById('leoBriefList');
      const fetchBtn = document.getElementById('btnFetchMusicTrends');
      if (briefList && !briefList.children.length && fetchBtn) {
        fetchBtn.click();
      }
    } else if (targetId === 'social') {
      if (typeof loadSocialDashboard === 'function') {
        loadSocialDashboard();
      }
    }
  }

  if (navTabAnalysis) navTabAnalysis.addEventListener('click', () => switchMainView('analysis'));
  if (navTabChannel) navTabChannel.addEventListener('click', () => switchMainView('channel'));
  if (navTabPromptStudio) navTabPromptStudio.addEventListener('click', () => switchMainView('promptStudio'));
  if (navTabProducer) navTabProducer.addEventListener('click', () => switchMainView('producer'));
  if (navTabMarketing) navTabMarketing.addEventListener('click', () => switchMainView('marketing'));
  if (navTabMusic) navTabMusic.addEventListener('click', () => switchMainView('music'));
  if (navTabSocial) navTabSocial.addEventListener('click', () => switchMainView('social'));

  const promptTopicInput = document.getElementById('promptTopicInput');
  const promptConcept = document.getElementById('promptConcept');
  const promptConceptDesc = document.getElementById('promptConceptDesc');

  // 컨셉 팩 목록 — 서사 골격·이미지 레이어 구성·렌더 톤이 한 세트로 바뀐다
  async function loadConceptPacks() {
    if (!promptConcept) return;
    try {
      const res = await fetch('/api/prompt/concepts');
      const d = await res.json();
      const packs = (d && d.data) || [];
      promptConcept.innerHTML = '';
      packs.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.key;
        opt.textContent = p.name;
        opt.dataset.desc = p.description || '';
        if (p.key === d.default) opt.selected = true;
        promptConcept.appendChild(opt);
      });
      updateConceptDesc();
    } catch (err) {
      console.warn('컨셉 목록 로드 실패:', err);
      promptConcept.innerHTML = '<option value="">기본 컨셉</option>';
    }
  }

  function updateConceptDesc() {
    if (!promptConcept || !promptConceptDesc) return;
    const opt = promptConcept.selectedOptions[0];
    promptConceptDesc.textContent = opt ? (opt.dataset.desc || '') : '';
  }

  if (promptConcept) promptConcept.addEventListener('change', updateConceptDesc);
  loadConceptPacks();

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

  window.openPromptStudioForTopic = function(topicText, angleText, conceptKey) {
    switchMainView('promptStudio');
    if (promptTopicInput) {
      promptTopicInput.value = topicText;
      pendingTopicAngle = (angleText || '').trim();
      // 트렌드 분석이 제안한 컨셉이 있으면 드롭다운을 맞춘다 (사용자가 바꿀 수 있음)
      if (conceptKey && promptConcept && [...promptConcept.options].some(o => o.value === conceptKey)) {
        promptConcept.value = conceptKey;
        updateConceptDesc();
      }
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
          concept_key: promptConcept ? promptConcept.value : '',
          language: promptLanguageSelect ? promptLanguageSelect.value : 'korean'
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '기획 생성 실패');
      }

      currentGeneratedBatch = await res.json();
      // 파싱 실패로 템플릿 대사가 나갔으면 조용히 넘어가지 않고 알린다
      if (currentGeneratedBatch.is_fallback) {
        showAlert(currentGeneratedBatch.fallback_note || 'AI 응답 해석에 실패해 기본 템플릿 대사로 대체됐습니다. 씬 개수를 줄이거나 다시 생성해주세요.', 'error');
      }
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
    btnGoToProducer.addEventListener('click', async () => {
      if (!currentGeneratedBatch || !(currentGeneratedBatch.scenes || []).length) {
        showAlert('먼저 씬을 기획해주세요.', 'error');
        return;
      }
      const orig = btnGoToProducer.innerHTML;
      btnGoToProducer.disabled = true;
      btnGoToProducer.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 기획서 저장 중...';
      try {
        // 씬 데이터를 영상 합성이 읽을 수 있는 기획서로 저장한 뒤 넘어간다
        const res = await fetch('/api/scenes/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ batch: currentGeneratedBatch })
        });
        const d = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(d.detail || '기획서 저장에 실패했습니다.');
        switchMainView('producer');
        await loadProducerPlans(d.plan_id);
        const audioNote = d.audio_count ? ` (음성 ${d.audio_count}개 포함)` : ' (음성 미포함 — 3단계에서 먼저 합성하면 나레이션이 들어갑니다)';
        showAlert(`씬 ${d.scene_count}개를 기획서로 저장했습니다${audioNote}`, 'success');
      } catch (err) {
        showAlert('이동 실패: ' + err.message, 'error');
      } finally {
        btnGoToProducer.disabled = false;
        btnGoToProducer.innerHTML = orig;
      }
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

  // 썸네일이 없거나 불러오지 못한 트렌드 카드용 대체 이미지.
  // CSP(img-src 'self' data: ...)가 허용하는 내장 SVG 를 쓴다. 외부 이미지로 대체하면 CSP 에 막혀
  // onerror 가 같은 주소를 다시 넣으며 무한 반복되므로, onerror 는 한 번만 동작하게 한다.
  const TREND_THUMB_PLACEHOLDER = 'data:image/svg+xml,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">' +
    '<rect width="320" height="180" fill="#1f2937"/>' +
    '<circle cx="160" cy="90" r="30" fill="#374151"/>' +
    '<path d="M150 75 L175 90 L150 105 Z" fill="#9ca3af"/>' +
    '</svg>'
  );

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
          <img src="${escapeHtml(item.thumbnail || TREND_THUMB_PLACEHOLDER)}" alt="" loading="lazy" onerror="this.onerror=null; this.src='${TREND_THUMB_PLACEHOLDER}'">
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
                ${t.concept_name ? `<div style="font-size:0.72rem; opacity:.75; margin-top:2px;"><i class="fa-solid fa-layer-group"></i> 추천 컨셉: ${escapeHtml(t.concept_name)}</div>` : ''}
              </div>
              <button type="button" class="btn btn-xs btn-accent js-plan-topic"
                      data-topic="${escapeHtml(t.topic || '')}" data-angle="${escapeHtml(t.angle || '')}"
                      data-concept="${escapeHtml(t.concept || '')}"
                      style="flex:none; white-space:nowrap;"
                      title="이 주제·앵글·컨셉으로 8초 씬 기획을 바로 시작합니다">
                <i class="fa-solid fa-wand-magic-sparkles"></i> 이 주제로 기획
              </button>
            </div>`).join('');

          trendRecommendedTopics.querySelectorAll('.js-plan-topic').forEach((btn) => {
            btn.addEventListener('click', () => {
              window.openPromptStudioForTopic(btn.dataset.topic, btn.dataset.angle, btn.dataset.concept);
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
  const producerAutoImages = document.getElementById('producerAutoImages');
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

  async function loadProducerPlans(selectId) {
    if (!producerPlanSelect) return;
    producerPlanSelect.innerHTML = '<option value="">기획서를 선택하세요...</option>';

    // 씬 기획서 — 영상 합성이 실제로 소비할 수 있는 유일한 형식
    try {
      const res = await fetch('/api/scenes/list');
      const d = await res.json();
      const plans = (d && d.data) || [];
      if (plans.length) {
        const g = document.createElement('optgroup');
        g.label = '씬 기획서 (합성 가능)';
        plans.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.id;
          const audio = p.audio_count ? ` · 음성 ${p.audio_count}` : '';
          opt.textContent = `${p.title || p.topic} — 씬 ${p.scene_count}${audio}`;
          g.appendChild(opt);
        });
        producerPlanSelect.appendChild(g);
      }
    } catch (err) {
      console.warn('씬 기획서 목록 로드 실패:', err);
    }

    // 채널 기획서 — 씬 데이터가 없어 합성은 불가. 참고용으로만 노출한다.
    try {
      const res = await fetch('/api/channel/history');
      const list = await res.json();
      if (Array.isArray(list) && list.length) {
        const g = document.createElement('optgroup');
        g.label = '채널 기획서 (씬 없음 — 합성 불가)';
        list.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.id;
          opt.textContent = p.topic || '채널 기획서';
          g.appendChild(opt);
        });
        producerPlanSelect.appendChild(g);
      }
    } catch (err) {
      console.warn('채널 기획서 목록 로드 실패:', err);
    }

    if (selectId) producerPlanSelect.value = selectId;
  }

  if (producerPlanSelect) {
    producerPlanSelect.addEventListener('change', () => {
      const selectedOpt = producerPlanSelect.options[producerPlanSelect.selectedIndex];
      if (selectedOpt && selectedOpt.value) {
        const planTitle = selectedOpt.text.split('—')[0].trim();
        if (ytUploadTitle && !ytUploadTitle.value) ytUploadTitle.value = planTitle;
        if (ytUploadDesc && !ytUploadDesc.value) {
          ytUploadDesc.value = `${planTitle}\n\nAI 프로듀서 레오가 기획·제작한 쇼츠 영상입니다.\n\n#Shorts #AI영상 #트렌드`;
        }
        if (ytUploadPinnedComment && !ytUploadPinnedComment.value) {
          ytUploadPinnedComment.value = '영상 재미있게 시청하셨나요? 여러분의 소중한 생각을 댓글로 남겨주시면 레오가 직접 답글을 남겨드립니다! ✨';
        }
      }
    });
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
            transition: producerTransitionSelect ? producerTransitionSelect.value : 'fade',
            generate_images: producerAutoImages ? producerAutoImages.checked : true
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
          if (ytUploadTitle && !ytUploadTitle.value) {
            const selectedOpt = producerPlanSelect?.options[producerPlanSelect.selectedIndex];
            const planTitle = selectedOpt ? selectedOpt.text.split('—')[0].trim() : 'AI 쇼츠 비디오';
            ytUploadTitle.value = planTitle || 'AI 쇼츠 비디오';
          }
          if (ytUploadDesc && !ytUploadDesc.value) {
            ytUploadDesc.value = 'AI로 자동 제작된 유튜브 쇼츠 영상입니다. #Shorts #AI영상';
          }
          if (ytUploadPinnedComment && !ytUploadPinnedComment.value) {
            ytUploadPinnedComment.value = '영상 재미있게 시청하셨나요? 여러분의 소중한 생각을 댓글로 남겨주시면 레오가 직접 답글을 남겨드립니다! ✨';
          }

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

  // ---------------------------------------------------------------
  // 📅 예약 공개 날짜/시간 공통 유틸 함수
  // ---------------------------------------------------------------
  function formatKoreanScheduleTime(val) {
    if (!val) return '';
    const d = new Date(val);
    if (isNaN(d.getTime())) return '';
    const days = ['일', '월', '화', '수', '목', '금', '토'];
    const yyyy = d.getFullYear();
    const mm = d.getMonth() + 1;
    const dd = d.getDate();
    const day = days[d.getDay()];
    const hh = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `📅 ${yyyy}년 ${mm}월 ${dd}일(${day}) ${hh}:${min} (한국 표준시 KST)에 자동 공개 예정`;
  }

  function toIsoPublishAt(val) {
    if (!val) return null;
    const d = new Date(val);
    if (isNaN(d.getTime())) return null;
    const now = new Date();
    // 현재 시각보다 최소 1분 이상 미래인지 체크
    if (d.getTime() <= now.getTime() + 60000) {
      throw new Error('예약 공개 일시는 현재 시각보다 최소 몇 분 이후여야 합니다.');
    }
    return d.toISOString();
  }

  function calculatePresetDate(presetType) {
    const now = new Date();
    let target = new Date(now.getTime());

    if (presetType === 'plus2h') {
      target.setHours(target.getHours() + 2);
    } else if (presetType === 'today8pm' || presetType === 'today20') {
      target.setHours(20, 0, 0, 0);
      if (target <= now) {
        target.setDate(target.getDate() + 1); // 이미 20시 지난 경우 내일 20시
      }
    } else if (presetType === 'tomorrow9am' || presetType === 'tomorrow09') {
      target.setDate(target.getDate() + 1);
      target.setHours(9, 0, 0, 0);
    } else if (presetType === 'tomorrow8pm' || presetType === 'tomorrow20') {
      target.setDate(target.getDate() + 1);
      target.setHours(20, 0, 0, 0);
    }

    const pad = (n) => String(n).padStart(2, '0');
    const yyyy = target.getFullYear();
    const mm = pad(target.getMonth() + 1);
    const dd = pad(target.getDate());
    const hh = pad(target.getHours());
    const min = pad(target.getMinutes());
    return `${yyyy}-${mm}-${dd}T${hh}:${min}`;
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

      const privacy = ytUploadPrivacy ? ytUploadPrivacy.value : 'unlisted';
      let publishAt = null;
      let effectivePrivacy = privacy;
      if (privacy === 'scheduled') {
        const schedTime = document.getElementById('ytUploadScheduleTime')?.value;
        if (!schedTime) {
          showAlert('예약 공개할 일시를 선택해주세요.', 'error');
          return;
        }
        try {
          publishAt = toIsoPublishAt(schedTime);
        } catch (err) {
          showAlert(err.message, 'error');
          return;
        }
        if (!publishAt) {
          showAlert('올바른 예약 공개 일시를 입력해주세요.', 'error');
          return;
        }
        effectivePrivacy = 'private';
      }
      const playlistId = document.getElementById('ytUploadPlaylist')?.value || null;

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
            privacy_status: effectivePrivacy,
            publish_at: publishAt,
            playlist_id: playlistId,
            category_id: ytUploadCategory ? ytUploadCategory.value : '28',
            pinned_comment: ytUploadPinnedComment ? ytUploadPinnedComment.value : ''
          })
        });
        const data = await res.json();
        if (data.status === 'success') {
          const schedNotice = publishAt ? ` (예약: ${publishAt})` : '';
          showAlert(`유튜브 업로드가 성공적으로 완료되었습니다!${schedNotice}`, 'success');
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
  const lunaVocalSelect = document.getElementById('lunaVocalSelect');
  const btnRunLunaGen = document.getElementById('btnRunLunaGen');

  const lunaEmptyState = document.getElementById('lunaEmptyState');
  const lunaActiveView = document.getElementById('lunaActiveView');
  const lunaStatusBadge = document.getElementById('lunaStatusBadge');

  const lunaCoverImg = document.getElementById('lunaCoverImg');
  const lunaGenreBadge = document.getElementById('lunaGenreBadge');
  const lunaHasLyricsBadge = document.getElementById('lunaHasLyricsBadge');
  const lunaTrackTitle = document.getElementById('lunaTrackTitle');
  const lunaTrackStory = document.getElementById('lunaTrackStory');
  const lunaAudioPlayer = document.getElementById('lunaAudioPlayer');

  // 사운드 엔지니어 베가 (마스터링) 패널 요소
  const vegaPanel = document.getElementById('vegaPanel');
  const vegaStatusBadge = document.getElementById('vegaStatusBadge');
  const vegaMetrics = document.getElementById('vegaMetrics');
  const vegaReasoning = document.getElementById('vegaReasoning');
  const vegaStaleNotice = document.getElementById('vegaStaleNotice');
  const vegaPromptInput = document.getElementById('vegaPromptInput');
  const btnVegaAbRaw = document.getElementById('btnVegaAbRaw');
  const btnVegaAbMaster = document.getElementById('btnVegaAbMaster');
  const btnVegaRemaster = document.getElementById('btnVegaRemaster');
  let vegaAbMode = 'master'; // 'raw' | 'master'

  // 가사 & 보컬 뷰어 요소
  const lunaLyricsBox = document.getElementById('lunaLyricsBox');
  const lunaLyricsToggle = document.getElementById('lunaLyricsToggle');
  const lunaLyricsContent = document.getElementById('lunaLyricsContent');
  const lunaVocalStyleBadge = document.getElementById('lunaVocalStyleBadge');
  const btnCopyLunaLyrics = document.getElementById('btnCopyLunaLyrics');
  const lunaLyricsChevron = document.getElementById('lunaLyricsChevron');

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

  // 레오 트렌드 브리프 연동 요소
  const btnFetchMusicTrends = document.getElementById('btnFetchMusicTrends');
  const leoMusicBriefBox = document.getElementById('leoMusicBriefBox');
  const leoChartInsights = document.getElementById('leoChartInsights');
  const leoBriefList = document.getElementById('leoBriefList');
  const lunaPinnedCommentPreview = document.getElementById('lunaPinnedCommentPreview');
  const btnCopyLunaPinnedComment = document.getElementById('btnCopyLunaPinnedComment');

  let currentLunaTrack = null;
  let currentLeoBrief = null;

  // 1단계: 레오의 실시간 음악 트렌드 브리프 가져오기
  if (btnFetchMusicTrends) {
    btnFetchMusicTrends.addEventListener('click', async () => {
      btnFetchMusicTrends.disabled = true;
      const textSpan = btnFetchMusicTrends.querySelector('.btn-text');
      const spinnerSpan = btnFetchMusicTrends.querySelector('.spinner');
      if (textSpan) textSpan.style.display = 'none';
      if (spinnerSpan) spinnerSpan.style.display = 'inline-block';

      if (leoChartInsights) {
        leoChartInsights.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="color:#38bdf8;"></i> 유튜브 실시간 음악 인기 급상승 차트를 수집하고 Gemini 3.6 Flash로 분석 중입니다...';
      }

      try {
        const res = await fetch('/api/trends/music-for-luna?region=KR');
        if (!res.ok) {
          throw new Error('음악 트렌드 수집 실패');
        }
        const data = await res.json();
        const analysis = data.analysis || {};
        const briefs = analysis.luna_briefs || [];

        if (leoMusicBriefBox) leoMusicBriefBox.style.display = 'block';
        if (leoChartInsights) {
          leoChartInsights.innerHTML = `<strong><i class="fa-solid fa-lightbulb" style="color:#38bdf8;"></i> 레오의 실시간 차트 인사이트:</strong> ${analysis.chart_insights || ''} <span style="color:#a78bfa; margin-left:6px;">#${(analysis.top_keywords || []).join(' #')}</span>`;
        }

        if (leoBriefList) {
          leoBriefList.innerHTML = briefs.map((b, idx) => `
            <div class="leo-brief-card" data-idx="${idx}" style="background: rgba(255,255,255,0.02); border: 1.5px solid rgba(56, 189, 248, 0.3); border-radius: 8px; padding: 14px; transition: all 0.25s; display: flex; flex-direction: column; justify-content: space-between;">
              <div>
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                  <span class="badge" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; font-size: 11px; font-weight: 700;">추천 브리프 ${b.brief_id || (idx+1)}</span>
                  <span class="badge badge-accent" style="font-size: 11px;">${b.genre_name || b.genre}</span>
                </div>
                <h4 style="margin: 0 0 6px 0; font-size: 0.95rem; color: #fff; font-weight: 600;">${b.title_concept || '트렌드 기획 ' + (idx+1)}</h4>
                <div style="font-size: 0.78rem; color: var(--text-secondary); line-height: 1.4; margin-bottom: 8px;">${b.topic}</div>
                <div style="font-size: 0.74rem; color: #38bdf8; background: rgba(56, 189, 248, 0.08); padding: 6px 8px; border-radius: 4px; margin-bottom: 8px;">
                  <i class="fa-solid fa-user-tag"></i> <strong>타깃:</strong> ${b.target_audience || '감성 리스너'}
                </div>
                <div style="font-size: 0.74rem; color: #c084fc; background: rgba(192, 132, 252, 0.08); padding: 6px 8px; border-radius: 4px; margin-bottom: 12px;">
                  <i class="fa-solid fa-bolt"></i> <strong>30초 후킹:</strong> ${b.angle}
                </div>
              </div>
              <div style="display: flex; flex-direction: column; gap: 6px;">
                <button type="button" class="btn btn-xs btn-primary btn-auto-generate" data-idx="${idx}" style="background: linear-gradient(135deg, #a855f7 0%, #6366f1 100%); border: none; width: 100%; padding: 7px 0; font-weight: 600;">
                  <i class="fa-solid fa-wand-magic-sparkles"></i> 이 브리프로 바로 작곡 시작 🎵
                </button>
                <button type="button" class="btn btn-xs btn-outline btn-select-brief" data-idx="${idx}" style="border-color: #38bdf8; color: #38bdf8; width: 100%; padding: 5px 0;">
                  <i class="fa-solid fa-arrow-down"></i> 폼에 브리프 세팅만 하기
                </button>
              </div>
            </div>
          `).join('');

          // 폼에 세팅하는 헬퍼 함수
          const applyBriefToForm = (selectedBrief, cardEl) => {
            currentLeoBrief = selectedBrief;
            if (lunaGenreSelect && selectedBrief.genre) lunaGenreSelect.value = selectedBrief.genre;
            if (lunaMoodSelect && selectedBrief.mood) lunaMoodSelect.value = selectedBrief.mood;
            if (lunaTopicInput) lunaTopicInput.value = selectedBrief.topic || selectedBrief.title_concept;

            const noticeBox = document.getElementById('lunaActiveBriefNotice');
            const titleEl = document.getElementById('lunaActiveBriefTitle');
            const angleEl = document.getElementById('lunaActiveBriefAngle');
            if (noticeBox && titleEl && angleEl) {
              noticeBox.style.display = 'block';
              titleEl.textContent = `${selectedBrief.title_concept || selectedBrief.topic || '트렌드 추천곡'}`;
              angleEl.textContent = `🎯 30초 후킹 앵글: ${selectedBrief.angle || '트렌드 사운드 반영'} | 타깃: ${selectedBrief.target_audience || '감성 리스너'}`;
            }

            leoBriefList.querySelectorAll('.leo-brief-card').forEach(el => {
              el.style.borderColor = 'rgba(56, 189, 248, 0.3)';
              el.style.background = 'rgba(255,255,255,0.02)';
              el.style.boxShadow = 'none';
            });
            if (cardEl) {
              cardEl.style.borderColor = '#c084fc';
              cardEl.style.background = 'rgba(192, 132, 252, 0.08)';
              cardEl.style.boxShadow = '0 0 15px rgba(192, 132, 252, 0.2)';
            }
          };

          // 첫 번째 추천 브리프를 기본적으로 루나 작업대에 자동 세팅
          if (briefs.length > 0) {
            const firstCard = leoBriefList.querySelector('.leo-brief-card');
            applyBriefToForm(briefs[0], firstCard);
          }

          // 트렌드 브리프 해제 버튼 이벤트
          const btnCancelActiveBrief = document.getElementById('btnCancelActiveBrief');
          if (btnCancelActiveBrief) {
            btnCancelActiveBrief.onclick = () => {
              currentLeoBrief = null;
              const noticeBox = document.getElementById('lunaActiveBriefNotice');
              if (noticeBox) noticeBox.style.display = 'none';
              leoBriefList.querySelectorAll('.leo-brief-card').forEach(el => {
                el.style.borderColor = 'rgba(56, 189, 248, 0.3)';
                el.style.background = 'rgba(255,255,255,0.02)';
                el.style.boxShadow = 'none';
              });
              showAlert('트렌드 브리프 연동이 해제되었습니다. 기본 장르 모드로 작곡합니다.', 'info');
            };
          }

          // 각 버튼 이벤트 바인딩
          leoBriefList.querySelectorAll('.btn-select-brief').forEach(btn => {
            btn.addEventListener('click', (e) => {
              e.stopPropagation();
              const idx = parseInt(btn.getAttribute('data-idx'), 10);
              const card = btn.closest('.leo-brief-card');
              const selectedBrief = briefs[idx];
              if (!selectedBrief) return;
              applyBriefToForm(selectedBrief, card);
              if (lunaMusicForm) {
                lunaMusicForm.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
              }
              showAlert(`[1단계 ➔ 2단계] 레오의 트렌드 브리프 '${selectedBrief.title_concept}'가 루나 작업대에 설정되었습니다!`, 'success');
            });
          });

          leoBriefList.querySelectorAll('.btn-auto-generate').forEach(btn => {
            btn.addEventListener('click', (e) => {
              e.stopPropagation();
              const idx = parseInt(btn.getAttribute('data-idx'), 10);
              const card = btn.closest('.leo-brief-card');
              const selectedBrief = briefs[idx];
              if (!selectedBrief) return;
              applyBriefToForm(selectedBrief, card);
              if (lunaMusicForm) {
                lunaMusicForm.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                // 폼 서브밋 트리거로 루나 곡 생성 즉시 시작
                lunaMusicForm.dispatchEvent(new Event('submit', { cancelable: true }));
              }
            });
          });
        }
      } catch (err) {
        showAlert('레오 음악 트렌드 분석 오류: ' + err.message, 'error');
      } finally {
        btnFetchMusicTrends.disabled = false;
        if (textSpan) textSpan.style.display = 'inline-block';
        if (spinnerSpan) spinnerSpan.style.display = 'none';
      }
    });
  }

  // 고정 댓글 복사 기능
  if (btnCopyLunaPinnedComment) {
    btnCopyLunaPinnedComment.addEventListener('click', () => {
      const inputEl = document.getElementById('lunaPinnedCommentInput');
      const text = (inputEl ? inputEl.value : '') || (lunaPinnedCommentPreview ? lunaPinnedCommentPreview.textContent : '') || '';
      if (!text) return;
      navigator.clipboard.writeText(text).then(() => {
        showAlert('레오의 고정 댓글이 클립보드에 복사되었습니다!', 'success');
      }).catch(() => {
        showAlert('복사에 실패했습니다.', 'error');
      });
    });
  }

  if (lunaMusicForm) {
    lunaMusicForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const genre = lunaGenreSelect ? lunaGenreSelect.value : 'lofi';
      const mood = lunaMoodSelect ? lunaMoodSelect.value : 'dawn';
      const customTopic = lunaTopicInput ? lunaTopicInput.value.trim() : '';
      const duration = lunaDurationSelect ? parseInt(lunaDurationSelect.value, 10) : 180;
      const vocalMode = lunaVocalSelect ? lunaVocalSelect.value : 'auto';

      btnRunLunaGen.disabled = true;
      btnRunLunaGen.querySelector('.btn-text').style.display = 'none';
      btnRunLunaGen.querySelector('.spinner').style.display = 'inline-block';
      if (lunaStatusBadge) {
        lunaStatusBadge.className = 'badge badge-accent';
        lunaStatusBadge.textContent = 'Gemini 기획 & Lyria 작곡 & 베가 마스터링 중...';
      }

      try {
        const res = await fetch('/api/luna/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            genre: genre,
            mood: mood,
            custom_topic: customTopic,
            duration_seconds: duration,
            leo_brief: currentLeoBrief,
            vocal_mode: vocalMode
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
        if (track.is_ai_generated) {
          const lyricsNotice = (track.has_lyrics || track.lyrics) ? ' (🎤 감성 가사 포함)' : '';
          showAlert(`🎵 '${track.title}' Lyria 3 Pro 고품질 AI 완곡 작곡 및 앨범아트가 완성되었습니다! (${track.ai_model || 'Lyria 3.5'})${lyricsNotice}`, 'success');
        } else {
          showAlert(`⚠️ '${track.title}' 백업 음원으로 준비되었습니다. (${track.fallback_reason || '네트워크 지연'})`, 'warning');
        }
      } catch (err) {
        const msg = err.message || '';
        if (msg.includes('429') || msg.includes('지출 한도') || msg.includes('spending cap') || msg.includes('RESOURCE_EXHAUSTED')) {
          showAlert(`🚨 Google AI 지출 한도 초과: AI Studio(https://ai.studio/spend)에서 월간 한도를 상향해주세요.`, 'error');
        } else {
          showAlert('루나 음원 생성 실패: ' + msg, 'error');
        }
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

  // ── 사운드 엔지니어 베가: 마스터링 결과 패널 / A-B 비교 / 재마스터 ─────────────
  function fmtDb(v, unit) {
    if (v === undefined || v === null || !isFinite(v)) return '—';
    return `${Number(v).toFixed(1)} ${unit}`;
  }

  function renderVegaPanel(track) {
    if (!vegaPanel) return;
    const m = track && track.mastering;
    if (!m) { vegaPanel.style.display = 'none'; return; }
    vegaPanel.style.display = 'block';

    const hasMaster = m.status === 'done' && Boolean(track.audio_raw_url);
    if (vegaAbGroupVisible()) {
      btnVegaAbRaw.style.display = hasMaster ? 'inline-block' : 'none';
      btnVegaAbMaster.style.display = hasMaster ? 'inline-block' : 'none';
    }
    updateVegaAbButtons();

    if (vegaStatusBadge) {
      if (m.status === 'done') {
        const src = m.decision_source === 'llm'
          ? `AI 결정${m.decision_model ? ' · ' + m.decision_model : ''}`
          : '장르 프리셋';
        vegaStatusBadge.className = 'badge badge-success';
        vegaStatusBadge.textContent = `마스터링 완료 · ${src}`;
      } else if (m.status === 'skipped') {
        vegaStatusBadge.className = 'badge badge-subtle';
        vegaStatusBadge.textContent = '건너뜀 (의존성 미설치)';
      } else {
        vegaStatusBadge.className = 'badge badge-subtle';
        vegaStatusBadge.textContent = '실패 · 원본 사용';
      }
    }

    if (vegaMetrics) {
      if (m.status === 'done' && m.before && m.after) {
        const b = m.before, a = m.after;
        vegaMetrics.innerHTML =
          `<span style="color:#67e8f9;">음량</span> ${fmtDb(b.integrated_lufs, 'LUFS')} → <strong style="color:#fff;">${fmtDb(a.integrated_lufs, 'LUFS')}</strong> (목표 ${fmtDb(m.target_lufs, 'LUFS')}) &nbsp;·&nbsp; ` +
          `<span style="color:#67e8f9;">트루피크</span> ${fmtDb(b.true_peak_dbtp, 'dBTP')} → <strong style="color:#fff;">${fmtDb(a.true_peak_dbtp, 'dBTP')}</strong> &nbsp;·&nbsp; ` +
          `<span style="color:#67e8f9;">다이내믹</span> ${fmtDb(b.crest_factor_db, 'dB')} → ${fmtDb(a.crest_factor_db, 'dB')} &nbsp;·&nbsp; ` +
          `<span style="color:#67e8f9;">스테레오 폭</span> ${Number(b.stereo_width || 0).toFixed(2)} → ${Number(a.stereo_width || 0).toFixed(2)}` +
          (m.elapsed_seconds ? ` <span style="color:var(--text-muted);">(${m.elapsed_seconds}s)</span>` : '');
      } else {
        vegaMetrics.textContent = m.reason || m.note || '';
      }
    }
    if (vegaReasoning) {
      const note = m.note ? ` (${m.note})` : '';
      vegaReasoning.textContent = m.status === 'done' ? `“${m.reasoning || ''}”${note}` : '';
    }
    if (vegaStaleNotice) vegaStaleNotice.style.display = track.video_stale ? 'block' : 'none';
    if (vegaPromptInput && m.prompt) vegaPromptInput.value = m.prompt;
  }

  function vegaAbGroupVisible() { return Boolean(btnVegaAbRaw && btnVegaAbMaster); }

  function updateVegaAbButtons() {
    if (!vegaAbGroupVisible()) return;
    const on = 'rgba(34,211,238,0.25)';
    btnVegaAbRaw.style.background = vegaAbMode === 'raw' ? on : '';
    btnVegaAbMaster.style.background = vegaAbMode === 'master' ? on : '';
  }

  function switchVegaAb(mode) {
    if (!currentLunaTrack || !lunaAudioPlayer) return;
    const url = mode === 'raw' ? currentLunaTrack.audio_raw_url : currentLunaTrack.audio_url;
    if (!url) return;
    const wasPlaying = !lunaAudioPlayer.paused;
    const pos = lunaAudioPlayer.currentTime || 0;
    vegaAbMode = mode;
    lunaAudioPlayer.src = url;
    lunaAudioPlayer.load();
    lunaAudioPlayer.addEventListener('loadedmetadata', () => {
      try { lunaAudioPlayer.currentTime = Math.min(pos, lunaAudioPlayer.duration || pos); } catch (_) {}
      if (wasPlaying) lunaAudioPlayer.play().catch(() => {});
    }, { once: true });
    updateVegaAbButtons();
  }

  if (btnVegaAbRaw) btnVegaAbRaw.addEventListener('click', () => switchVegaAb('raw'));
  if (btnVegaAbMaster) btnVegaAbMaster.addEventListener('click', () => switchVegaAb('master'));

  if (btnVegaRemaster) {
    btnVegaRemaster.addEventListener('click', async () => {
      if (!currentLunaTrack || !currentLunaTrack.track_id) {
        showAlert('먼저 트랙을 선택하거나 생성해주세요.', 'error');
        return;
      }
      btnVegaRemaster.disabled = true;
      btnVegaRemaster.querySelector('.btn-text').style.display = 'none';
      btnVegaRemaster.querySelector('.spinner').style.display = 'inline-block';
      if (lunaStatusBadge) {
        lunaStatusBadge.className = 'badge badge-accent';
        lunaStatusBadge.textContent = '베가 마스터링 중...';
      }
      try {
        const res = await fetch('/api/luna/master', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            track_id: currentLunaTrack.track_id,
            prompt: vegaPromptInput ? vegaPromptInput.value.trim() : '',
            use_llm: true
          })
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || '마스터링 실패');
        }
        const updated = await res.json();
        currentLunaTrack = updated;
        renderLunaTrackView(updated);
        loadLunaHistory();
        const m = updated.mastering || {};
        if (m.status === 'done') {
          showAlert(`🎚️ 베가 마스터링 완료: ${fmtDb(m.after && m.after.integrated_lufs, 'LUFS')} / ${fmtDb(m.after && m.after.true_peak_dbtp, 'dBTP')}`, 'success');
        } else {
          showAlert(`⚠️ 베가 마스터링을 적용하지 못했습니다: ${m.reason || '알 수 없는 오류'}`, 'warning');
        }
      } catch (err) {
        showAlert('베가 마스터링 오류: ' + err.message, 'error');
      } finally {
        btnVegaRemaster.disabled = false;
        btnVegaRemaster.querySelector('.btn-text').style.display = 'inline-block';
        btnVegaRemaster.querySelector('.spinner').style.display = 'none';
      }
    });
  }

  function renderLunaTrackView(track) {
    if (!track) return;
    if (lunaEmptyState) lunaEmptyState.style.display = 'none';
    if (lunaActiveView) lunaActiveView.style.display = 'block';

    if (lunaCoverImg) lunaCoverImg.src = track.cover_url || '';
    if (lunaGenreBadge) {
      const aiTag = track.is_ai_generated ? ` • 🤖 ${track.ai_model || 'Lyria 3'}` : ``;
      const trendTag = track.trend_brief_applied ? ` • 🔥 트렌드 반영` : ``;
      lunaGenreBadge.textContent = `${track.genre} • ${track.mood}${aiTag}${trendTag}`;
    }

    const hasLyrics = Boolean(track.has_lyrics || track.lyrics);
    if (lunaHasLyricsBadge) {
      if (hasLyrics) {
        let langLabel = '';
        if (track.vocal_language === 'en') langLabel = ' (EN)';
        else if (track.vocal_language === 'ja') langLabel = ' (JA)';
        else if (track.vocal_language === 'ko') langLabel = ' (KR)';
        lunaHasLyricsBadge.textContent = `📝 가사 포함${langLabel}`;
        lunaHasLyricsBadge.style.display = 'inline-block';
      } else {
        lunaHasLyricsBadge.style.display = 'none';
      }
    }

    if (lunaTrackTitle) lunaTrackTitle.textContent = track.title || 'Untitled Track';
    if (lunaTrackStory) lunaTrackStory.textContent = track.story || '';
    if (lunaAudioPlayer) {
      lunaAudioPlayer.src = track.audio_url || '';
      lunaAudioPlayer.load();
    }
    vegaAbMode = 'master';
    renderVegaPanel(track);

    // 감성 가사(Lyrics) 뷰어 렌더링
    if (lunaLyricsBox) {
      if (hasLyrics && track.lyrics) {
        lunaLyricsBox.style.display = 'block';
        if (lunaLyricsContent) {
          lunaLyricsContent.textContent = track.lyrics;
          lunaLyricsContent.style.display = 'none'; // 기본 접힘 상태
        }
        if (lunaVocalStyleBadge) {
          const langPrefix = track.vocal_language === 'en' ? '[EN] ' : (track.vocal_language === 'ja' ? '[JA] ' : '');
          lunaVocalStyleBadge.textContent = track.vocal_style ? `🎤 ${langPrefix}${track.vocal_style}` : (track.vocal_language === 'en' ? '🎤 English Vocal' : '🎤 감성 보컬');
          lunaVocalStyleBadge.style.display = 'inline-block';
        }
        if (lunaLyricsChevron) {
          lunaLyricsChevron.style.transform = 'rotate(0deg)';
        }
      } else {
        lunaLyricsBox.style.display = 'none';
      }
    }

    const meta = track.metadata || {};
    if (lunaYtTitlePreview) lunaYtTitlePreview.textContent = meta.youtube_title || track.title;
    if (lunaYtTagsPreview) lunaYtTagsPreview.textContent = (meta.youtube_tags || []).slice(0, 5).join(', ') + '...';
    const commentVal = meta.pinned_comment || track.pinned_comment || '';
    if (lunaPinnedCommentPreview) {
      lunaPinnedCommentPreview.textContent = commentVal;
    }
    const lunaPinnedCommentInput = document.getElementById('lunaPinnedCommentInput');
    if (lunaPinnedCommentInput) {
      lunaPinnedCommentInput.value = commentVal;
    }

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
        const schedBadge = track.publish_at 
          ? `<span class="badge" style="background:rgba(244,63,94,0.15); color:#f43f5e; border:1px solid rgba(244,63,94,0.3); font-size:11px; margin-left:6px;"><i class="fa-solid fa-clock"></i> 📅 ${new Date(track.publish_at).toLocaleString('ko-KR')} 공개 예약</span>` 
          : '';
        const plBadge = track.playlist_id
          ? `<span class="badge" style="background:rgba(56,189,248,0.15); color:#38bdf8; border:1px solid rgba(56,189,248,0.3); font-size:11px; margin-left:6px;"><i class="fa-solid fa-list-ul"></i> 재생목록 배정됨</span>`
          : '';
        const studioCommentUrl = track.studio_comment_url || `https://studio.youtube.com/video/${track.uploaded_video_id}/comments`;
        const commentBadge = `
          <div style="margin-top: 8px; font-size: 0.78rem; color: #cbd5e1; background: rgba(168, 85, 247, 0.12); border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 6px; padding: 8px 12px; display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;">
            <span><i class="fa-solid fa-thumbtack" style="color: #c084fc;"></i> <strong>고정 댓글:</strong> 등록 완료 (유튜브 정책상 상단 고정은 스튜디오에서 [고정] 1회 클릭 필요)</span>
            <a href="${studioCommentUrl}" target="_blank" class="btn btn-xs btn-outline" style="border-color: #c084fc; color: #e9d5ff; text-decoration: none; padding: 3px 8px; font-weight: 600;">
              <i class="fa-solid fa-arrow-up-right-from-square"></i> 스튜디오에서 댓글 고정하기 📌
            </a>
          </div>
        `;
        lunaUploadResultBadge.innerHTML = `
          <div style="display:flex; justify-content:center; align-items:center; flex-wrap:wrap; gap:6px;">
            <a href="https://youtu.be/${track.uploaded_video_id}" target="_blank" class="badge badge-success" style="font-size:12px; padding:6px 12px; text-decoration:none;">
              <i class="fa-brands fa-youtube"></i> 유튜브 업로드 완료 (youtu.be/${track.uploaded_video_id})
            </a>
            ${schedBadge}
            ${plBadge}
          </div>
          ${commentBadge}
        `;
      } else {
        lunaUploadResultBadge.style.display = 'none';
      }
    }

    // AI 플레이리스트 추천 업데이트
    updateLunaPlaylistRecommendation(track);
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

  // 3. 루나 채널 유튜브 업로드 (즉시/예약 공개 & 재생목록 자동 배정)
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

      const privacy = lunaPrivacySelect ? lunaPrivacySelect.value : 'public';
      let publishAt = null;
      let effectivePrivacy = privacy;

      if (privacy === 'scheduled') {
        const schedTime = document.getElementById('lunaScheduleTime')?.value;
        if (!schedTime) {
          showAlert('예약 공개할 일시를 선택해주세요.', 'error');
          return;
        }
        try {
          publishAt = toIsoPublishAt(schedTime);
        } catch (err) {
          showAlert(err.message, 'error');
          return;
        }
        if (!publishAt) {
          showAlert('올바른 예약 공개 일시를 입력해주세요.', 'error');
          return;
        }
        effectivePrivacy = 'private'; // 유튜브 정책: 예약 공개는 최초 private 상태로 대기
      }

      const playlistSelect = document.getElementById('lunaPlaylistSelect');
      const playlistId = playlistSelect ? playlistSelect.value : null;

      const pinnedInput = document.getElementById('lunaPinnedCommentInput');
      const customPinnedComment = pinnedInput ? pinnedInput.value.trim() : '';

      btnUploadLunaYt.disabled = true;
      btnUploadLunaYt.querySelector('.btn-text').style.display = 'none';
      btnUploadLunaYt.querySelector('.spinner').style.display = 'inline-block';
      if (lunaStatusBadge) {
        lunaStatusBadge.className = 'badge badge-accent';
        lunaStatusBadge.textContent = publishAt ? '유튜브 예약 업로드 중...' : '유튜브 채널 업로드 중...';
      }

      try {
        const res = await fetch('/api/luna/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            track_id: currentLunaTrack.track_id,
            privacy_status: effectivePrivacy,
            publish_at: publishAt,
            playlist_id: playlistId || null,
            pinned_comment: customPinnedComment || null
          })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || '유튜브 업로드 실패');
        }

        const data = await res.json();
        const schedMsg = publishAt ? ` (예약 공개 일시: ${new Date(publishAt).toLocaleString('ko-KR')})` : '';
        const plMsg = data.playlist_added ? ' & 재생목록 추가 완료' : '';
        const commentMsg = data.comment_posted 
          ? '\n💬 레오의 고정 댓글이 등록되었습니다! (유튜브 정책상 상단 고정은 스튜디오에서 [고정] 1회 클릭 필요)' 
          : '';
        showAlert(`루나 유튜브 채널에 성공적으로 업로드되었습니다!${schedMsg}${plMsg}${commentMsg}`, 'success');
        if (currentLunaTrack) {
          currentLunaTrack.uploaded_video_id = data.video_id;
          currentLunaTrack.uploaded_url = data.url;
          currentLunaTrack.publish_at = data.publish_at;
          currentLunaTrack.playlist_id = data.playlist_id;
          currentLunaTrack.playlist_added = data.playlist_added;
          currentLunaTrack.comment_posted = data.comment_posted;
          currentLunaTrack.studio_comment_url = data.studio_comment_url;
        }
        renderLunaTrackView(currentLunaTrack);
        loadLunaHistory();
        loadYoutubePlaylists(); // 플레이리스트 곡 수 갱신
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
        const hasLyrics = Boolean(t.has_lyrics || t.lyrics);
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
              ${hasLyrics ? '<span class="badge" style="font-size:10px; background:rgba(168,85,247,0.18); color:#d8b4fe; border:1px solid rgba(168,85,247,0.3);"><i class="fa-solid fa-microphone-lines"></i> 가사</span>' : ''}
              ${isUploaded ? '<span class="badge badge-success" style="font-size:10px;"><i class="fa-brands fa-youtube"></i> 업로드됨</span>' : ''}
              ${isRendered ? '<span class="badge badge-accent" style="font-size:10px;"><i class="fa-solid fa-film"></i> 영상완료</span>' : '<span class="badge badge-subtle" style="font-size:10px;">음원만</span>'}
              <button class="btn btn-xs btn-outline btn-load-luna-track" data-id="${escapeHtml(t.track_id)}"><i class="fa-solid fa-play"></i></button>
            </div>
          </div>
        `;
      }).join('');

      // 최초 로드 시 또는 새로고침 시 가장 최근 트랙을 자동으로 선택하여 작업대에 로드
      if (!currentLunaTrack && tracks.length > 0) {
        currentLunaTrack = tracks[0];
        renderLunaTrackView(tracks[0]);
      }

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

  // 가사(Lyrics) 펼치기/접기 및 복사 이벤트 리스너 바인딩
  if (lunaLyricsToggle) {
    lunaLyricsToggle.addEventListener('click', (e) => {
      if (e.target.closest('#btnCopyLunaLyrics')) return; // 복사 버튼 클릭 시 접힘 방지
      if (!lunaLyricsContent) return;
      const isHidden = lunaLyricsContent.style.display === 'none';
      lunaLyricsContent.style.display = isHidden ? 'block' : 'none';
      if (lunaLyricsChevron) {
        lunaLyricsChevron.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
      }
    });
  }

  if (btnCopyLunaLyrics) {
    btnCopyLunaLyrics.addEventListener('click', (e) => {
      e.stopPropagation();
      const lyricsText = (currentLunaTrack && currentLunaTrack.lyrics) || (lunaLyricsContent ? lunaLyricsContent.textContent : '');
      if (!lyricsText || !lyricsText.trim()) {
        showAlert('복사할 가사가 없습니다.', 'warning');
        return;
      }
      navigator.clipboard.writeText(lyricsText.trim()).then(() => {
        showAlert('🎵 감성 가사가 클립보드에 복사되었습니다!', 'success');
      }).catch(() => {
        showAlert('가사 복사에 실패했습니다.', 'error');
      });
    });
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
  const engagementPlatform = document.getElementById('engagementPlatform');
  const engagementAccountId = document.getElementById('engagementAccountId');
  const engagementPostId = document.getElementById('engagementPostId');
  const engagementProfileUrl = document.getElementById('engagementProfileUrl');
  const engagementPostUrl = document.getElementById('engagementPostUrl');
  const engagementUseWeb = document.getElementById('engagementUseWeb');
  const btnPreviewEngagement = document.getElementById('btnPreviewEngagement');
  const btnRunEngagement = document.getElementById('btnRunEngagement');
  const engagementResultBox = document.getElementById('engagementResultBox');

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

  // ==============================================================
  // 19-1. [설정 모달] X (Twitter) API & OAuth 2.0 PKCE 설정
  // ==============================================================
  const envXBadge = document.getElementById('envXBadge');
  const btnConnectX = document.getElementById('btnConnectX');
  const envXTokenInput = document.getElementById('envXTokenInput');
  const envXUserIdInput = document.getElementById('envXUserIdInput');
  const btnSaveXToken = document.getElementById('btnSaveXToken');
  const envXAccountInfo = document.getElementById('envXAccountInfo');
  const btnDisconnectX = document.getElementById('btnDisconnectX');

  async function loadXEnvStatus() {
    try {
      const res = await fetch('/api/x/status');
      if (!res.ok) return;
      const data = await res.json();

      const isConn = data.connected;
      const uname = data.username ? `@${data.username}` : (data.account_id ? `ID: ${data.account_id}` : '');

      if (envXBadge) {
        if (isConn) {
          envXBadge.className = 'badge badge-success';
          envXBadge.textContent = '연결됨';
        } else {
          envXBadge.className = 'badge badge-subtle';
          envXBadge.textContent = '미연결';
        }
      }

      if (envXAccountInfo) {
        envXAccountInfo.textContent = isConn
          ? `✅ 연결된 계정: ${uname} (OAuth 2.0 활성)`
          : '연결된 계정 없음 (OAuth 연결 또는 토큰 등록 필요)';
      }
    } catch (err) {
      console.warn('X 상태 조회 실패:', err);
    }
  }

  // X OAuth 2.0 PKCE 로그인 시작
  if (btnConnectX) {
    btnConnectX.addEventListener('click', () => {
      window.location.href = '/api/x/auth/login';
    });
  }

  // X 토큰 직접 저장
  if (btnSaveXToken) {
    btnSaveXToken.addEventListener('click', async () => {
      const token = envXTokenInput ? envXTokenInput.value.trim() : '';
      const uid = envXUserIdInput ? envXUserIdInput.value.trim() : '';

      if (!token) {
        showAlert('X OAuth 2.0 User Access Token을 입력해주세요.', 'error');
        return;
      }

      btnSaveXToken.disabled = true;
      btnSaveXToken.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> 저장 중...';

      try {
        const res = await fetch('/api/x/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ access_token: token, user_id: uid })
        });

        const data = await res.json();
        if (data.connected) {
          showAlert(`X @${data.username || uid} 계정에 성공적으로 연결되었습니다!`, 'success');
        } else {
          showAlert(data.message || '토큰이 저장되었습니다.', 'info');
        }
        if (envXTokenInput) envXTokenInput.value = '';
        loadXEnvStatus();
        if (typeof loadSocialAccountsStatus === 'function') loadSocialAccountsStatus();
      } catch (err) {
        showAlert('X 설정 저장 실패: ' + err.message, 'error');
      } finally {
        btnSaveXToken.disabled = false;
        btnSaveXToken.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> 저장';
      }
    });
  }

  // X 연결 해제
  if (btnDisconnectX) {
    btnDisconnectX.addEventListener('click', async () => {
      if (!confirm('X 계정 연결을 해제하시겠습니까?')) return;
      try {
        await fetch('/api/x/auth/disconnect', { method: 'POST' });
        showAlert('X 계정 연결이 해제되었습니다.', 'success');
        loadXEnvStatus();
        if (typeof loadSocialAccountsStatus === 'function') loadSocialAccountsStatus();
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

  function selectedEngagementActions() {
    return [
      ['engagementActionFollow', 'follow'],
      ['engagementActionLike', 'like'],
      ['engagementActionRepost', 'repost']
    ].filter(([id]) => document.getElementById(id)?.checked).map(([, action]) => action);
  }

  function renderEngagementResults(data) {
    if (!engagementResultBox) return;
    const labels = {
      dry_run: '검토 완료', success: '실행 완료', already_done: '이미 완료',
      skipped_duplicate: '중복 건너뜀', web_required: '웹 방식 필요',
      blocked_quota: '일일 한도 초과', failed: '실패'
    };
    const skippedItems = data.skipped_details || data.skipped_existing_relationships || [];
    const skipRows = skippedItems.map(s => {
      const targetLabel = s.target?.label || s.target?.account_id || '대상 계정';
      return `<div style="padding: 5px 0; color: #fca5a5; border-bottom: 1px solid var(--border-color);">
        🛡️ <strong>${escapeHtml(targetLabel)}</strong> — 기존 관계 감지로 자동 건너뜀 (${escapeHtml(s.detail || s.reason || '기존 상호작용/팔로워')})
      </div>`;
    }).join('');

    const rows = (data.results || []).map(item => {
      const detail = item.detail ? ` · ${escapeHtml(String(item.detail))}` : '';
      return `<div style="padding: 5px 0; border-bottom: 1px solid var(--border-color);">
        <strong>${escapeHtml(item.action)}</strong> — ${escapeHtml(labels[item.status] || item.status)}${detail}
      </div>`;
    }).join('');
    engagementResultBox.style.display = 'block';
    engagementResultBox.innerHTML = `<div style="background: rgba(15,23,42,0.65); border: 1px solid var(--border-color); border-radius: 7px; padding: 9px 12px; font-size: 0.8rem;">${skipRows}${rows || (skipRows ? '' : '결과가 없습니다.')}</div>`;
  }

  async function runEngagement(dryRun) {
    const platform = engagementPlatform?.value || 'threads';
    const accountId = engagementAccountId?.value.trim() || '';
    const postId = engagementPostId?.value.trim() || '';
    const actions = selectedEngagementActions();
    const useWeb = Boolean(engagementUseWeb?.checked);
    if (!accountId || !postId) {
      showAlert('대상 계정 ID와 게시물 ID를 입력해주세요.', 'error');
      return;
    }
    if (actions.length === 0) {
      showAlert('실행할 동작을 하나 이상 선택해주세요.', 'error');
      return;
    }
    if (useWeb && (!engagementProfileUrl?.value.trim() || !engagementPostUrl?.value.trim())) {
      showAlert('전용 브라우저 사용 시 프로필 URL과 게시물 URL이 모두 필요합니다.', 'error');
      return;
    }
    if (!dryRun && !confirm(`${platform === 'threads' ? 'Threads' : 'X'}에서 ${actions.join(', ')} 동작을 실제 실행하시겠습니까?`)) return;

    const activeButton = dryRun ? btnPreviewEngagement : btnRunEngagement;
    if (activeButton) activeButton.disabled = true;
    try {
      const response = await fetch('/api/engagement/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          targets: [{
            platform,
            account_id: accountId,
            post_id: postId,
            profile_url: engagementProfileUrl?.value.trim() || '',
            post_url: engagementPostUrl?.value.trim() || ''
          }],
          actions,
          dry_run: dryRun,
          use_web_fallback: useWeb,
          confirm_live: !dryRun,
          exclude_existing_relationships: true
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '참여 자동화 요청에 실패했습니다.');
      renderEngagementResults(data);
      showAlert(dryRun ? '드라이런 검토가 완료되었습니다.' : '참여 자동화 실행이 완료되었습니다.', 'success');
    } catch (err) {
      showAlert('참여 자동화 오류: ' + err.message, 'error');
    } finally {
      if (activeButton) activeButton.disabled = false;
    }
  }

  if (btnPreviewEngagement) btnPreviewEngagement.addEventListener('click', () => runEngagement(true));
  if (btnRunEngagement) btnRunEngagement.addEventListener('click', () => runEngagement(false));

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

  // ==============================================================
  // 21. [Phase 11] 예약 공개 & YouTube 플레이리스트 스마트 매니저
  // ==============================================================
  let cachedPlaylists = [];

  // 1. 4단계(Producer) 예약 공개 이벤트 바인딩
  const ytUploadScheduleBox = document.getElementById('ytUploadScheduleBox');
  const ytUploadScheduleTime = document.getElementById('ytUploadScheduleTime');
  const ytUploadSchedulePreview = document.getElementById('ytUploadSchedulePreview');

  function updateYtSchedulePreview() {
    if (!ytUploadSchedulePreview || !ytUploadScheduleTime) return;
    const v = ytUploadScheduleTime.value;
    if (v) {
      ytUploadSchedulePreview.innerHTML = `<span style="color:#4ade80;">✔</span> ${formatKoreanScheduleTime(v)}`;
    } else {
      ytUploadSchedulePreview.textContent = '⏰ 날짜와 시간을 선택하거나 위 골든타임 버튼을 클릭하세요.';
    }
  }

  if (ytUploadPrivacy && ytUploadScheduleBox) {
    ytUploadPrivacy.addEventListener('change', () => {
      if (ytUploadPrivacy.value === 'scheduled') {
        ytUploadScheduleBox.style.display = 'block';
        if (ytUploadScheduleTime && !ytUploadScheduleTime.value) {
          ytUploadScheduleTime.value = calculatePresetDate('plus2h');
        }
        updateYtSchedulePreview();
      } else {
        ytUploadScheduleBox.style.display = 'none';
      }
    });

    if (ytUploadScheduleTime) {
      ytUploadScheduleTime.addEventListener('input', updateYtSchedulePreview);
      ytUploadScheduleTime.addEventListener('change', updateYtSchedulePreview);
    }

    ytUploadScheduleBox.querySelectorAll('.btn-yt-schedule-preset').forEach((btn) => {
      btn.addEventListener('click', () => {
        const p = btn.dataset.preset;
        if (ytUploadScheduleTime) {
          ytUploadScheduleTime.value = calculatePresetDate(p);
          updateYtSchedulePreview();
        }
      });
    });
  }

  // 2. 6단계(Luna) 예약 공개 이벤트 바인딩
  const lunaScheduleBox = document.getElementById('lunaScheduleBox');
  const lunaScheduleTime = document.getElementById('lunaScheduleTime');
  const lunaSchedulePreview = document.getElementById('lunaSchedulePreview');

  function updateLunaSchedulePreview() {
    if (!lunaSchedulePreview || !lunaScheduleTime) return;
    const v = lunaScheduleTime.value;
    if (v) {
      lunaSchedulePreview.innerHTML = `<span style="color:#4ade80;">✔</span> ${formatKoreanScheduleTime(v)}`;
    } else {
      lunaSchedulePreview.textContent = '⏰ 날짜와 시간을 선택하거나 위 골든타임 버튼을 클릭하세요.';
    }
  }

  if (lunaPrivacySelect && lunaScheduleBox) {
    lunaPrivacySelect.addEventListener('change', () => {
      if (lunaPrivacySelect.value === 'scheduled') {
        lunaScheduleBox.style.display = 'block';
        if (lunaScheduleTime && !lunaScheduleTime.value) {
          lunaScheduleTime.value = calculatePresetDate('plus2h');
        }
        updateLunaSchedulePreview();
      } else {
        lunaScheduleBox.style.display = 'none';
      }
    });

    if (lunaScheduleTime) {
      lunaScheduleTime.addEventListener('input', updateLunaSchedulePreview);
      lunaScheduleTime.addEventListener('change', updateLunaSchedulePreview);
    }

    lunaScheduleBox.querySelectorAll('.btn-luna-schedule-preset').forEach((btn) => {
      btn.addEventListener('click', () => {
        const p = btn.dataset.preset;
        if (lunaScheduleTime) {
          lunaScheduleTime.value = calculatePresetDate(p);
          updateLunaSchedulePreview();
        }
      });
    });
  }

  // 3. 유튜브 플레이리스트 목록 조회 및 드롭다운 채우기
  async function loadYoutubePlaylists() {
    try {
      const res = await fetch('/api/youtube/playlists');
      if (!res.ok) return;
      const data = await res.json();
      cachedPlaylists = data.playlists || [];

      // 4단계 업로드 셀렉트 채우기
      const ytUploadPlaylist = document.getElementById('ytUploadPlaylist');
      if (ytUploadPlaylist) {
        const curVal = ytUploadPlaylist.value;
        let html = '<option value="">플레이리스트에 추가 안 함</option>';
        cachedPlaylists.forEach((pl) => {
          html += `<option value="${escapeHtml(pl.id)}">${escapeHtml(pl.title)} (${pl.item_count}곡)</option>`;
        });
        ytUploadPlaylist.innerHTML = html;
        if (curVal) ytUploadPlaylist.value = curVal;
      }

      // 6단계(루나) 업로드 셀렉트 채우기
      const lunaPlaylistSelect = document.getElementById('lunaPlaylistSelect');
      if (lunaPlaylistSelect) {
        const curVal = lunaPlaylistSelect.value;
        let html = '<option value="">(선택 안 함 - 플레이리스트 미지정)</option>';
        cachedPlaylists.forEach((pl) => {
          html += `<option value="${escapeHtml(pl.id)}">${escapeHtml(pl.title)} (${pl.item_count}곡)</option>`;
        });
        lunaPlaylistSelect.innerHTML = html;
        if (curVal) lunaPlaylistSelect.value = curVal;
      }
    } catch (err) {
      console.warn('플레이리스트 목록 로드 실패:', err);
    }
  }

  // 4. 루나 트랙 최적 플레이리스트 AI 자동 추천
  async function updateLunaPlaylistRecommendation(track) {
    const lunaAiPlaylistBadge = document.getElementById('lunaAiPlaylistBadge');
    const lunaPlaylistSelect = document.getElementById('lunaPlaylistSelect');
    if (!lunaAiPlaylistBadge || !track) return;

    // 만약 이미 업로드되어 플레이리스트가 배정된 경우
    if (track.playlist_id) {
      if (lunaPlaylistSelect) lunaPlaylistSelect.value = track.playlist_id;
      const plObj = cachedPlaylists.find((p) => p.id === track.playlist_id);
      const plTitle = plObj ? plObj.title : track.playlist_id;
      lunaAiPlaylistBadge.className = 'badge badge-success';
      lunaAiPlaylistBadge.innerHTML = `<i class="fa-solid fa-list-check"></i> 배정됨: ${escapeHtml(plTitle)}`;
      return;
    }

    lunaAiPlaylistBadge.className = 'badge badge-accent';
    lunaAiPlaylistBadge.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> ✨ AI 플레이리스트 추천 중...';

    try {
      const q = new URLSearchParams({
        title: track.title || '',
        genre: track.genre || '',
        mood: track.mood || ''
      });
      const res = await fetch(`/api/luna/playlist-recommendation?${q.toString()}`);
      if (!res.ok) throw new Error('추천 실패');
      const data = await res.json();

      if (data.recommended_playlist_id) {
        if (lunaPlaylistSelect) {
          lunaPlaylistSelect.value = data.recommended_playlist_id;
        }
        lunaAiPlaylistBadge.className = 'badge badge-accent';
        const confPercent = Math.round((data.confidence || 0.9) * 100);
        lunaAiPlaylistBadge.innerHTML = `✨ AI 추천: ${escapeHtml(data.recommended_playlist_title)} (${confPercent}%)`;
        lunaAiPlaylistBadge.title = data.reasoning || '';
      } else {
        lunaAiPlaylistBadge.className = 'badge badge-subtle';
        lunaAiPlaylistBadge.innerHTML = '✨ AI 추천: 미분류 (기존 목록 없음)';
      }
    } catch (err) {
      console.warn('AI 플레이리스트 추천 오류:', err);
      lunaAiPlaylistBadge.className = 'badge badge-subtle';
      lunaAiPlaylistBadge.innerHTML = '✨ 플레이리스트 선택 가능';
    }
  }

  // 5. 새 플레이리스트 인라인 생성 핸들러
  const btnToggleCreatePlaylist = document.getElementById('btnToggleCreatePlaylist');
  const lunaCreatePlaylistInline = document.getElementById('lunaCreatePlaylistInline');
  const btnCancelCreatePlaylist = document.getElementById('btnCancelCreatePlaylist');
  const btnSubmitCreatePlaylist = document.getElementById('btnSubmitCreatePlaylist');
  const newPlaylistTitle = document.getElementById('newPlaylistTitle');
  const newPlaylistDesc = document.getElementById('newPlaylistDesc');
  const newPlaylistPrivacy = document.getElementById('newPlaylistPrivacy');

  if (btnToggleCreatePlaylist && lunaCreatePlaylistInline) {
    btnToggleCreatePlaylist.addEventListener('click', () => {
      const isHidden = lunaCreatePlaylistInline.style.display === 'none';
      lunaCreatePlaylistInline.style.display = isHidden ? 'block' : 'none';
      if (isHidden && newPlaylistTitle) newPlaylistTitle.focus();
    });
  }

  if (btnCancelCreatePlaylist && lunaCreatePlaylistInline) {
    btnCancelCreatePlaylist.addEventListener('click', () => {
      lunaCreatePlaylistInline.style.display = 'none';
    });
  }

  if (btnSubmitCreatePlaylist) {
    btnSubmitCreatePlaylist.addEventListener('click', async () => {
      const title = newPlaylistTitle ? newPlaylistTitle.value.trim() : '';
      if (!title) {
        showAlert('새 재생목록 제목을 입력해주세요.', 'error');
        return;
      }
      const desc = newPlaylistDesc ? newPlaylistDesc.value.trim() : '';
      const privacy = newPlaylistPrivacy ? newPlaylistPrivacy.value : 'public';

      btnSubmitCreatePlaylist.disabled = true;
      btnSubmitCreatePlaylist.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 생성 중...';

      try {
        const res = await fetch('/api/youtube/playlists', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: title,
            description: desc,
            privacy_status: privacy
          })
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || '플레이리스트 생성에 실패했습니다.');
        }

        const data = await res.json();
        showAlert(`새 플레이리스트 '${title}'이 생성되었습니다!`, 'success');

        // 목록 새로고침 및 새로 생성된 항목 자동 선택
        await loadYoutubePlaylists();
        const lunaPlaylistSelect = document.getElementById('lunaPlaylistSelect');
        if (lunaPlaylistSelect && data.playlist_id) {
          lunaPlaylistSelect.value = data.playlist_id;
        }

        // 인라인 폼 리셋 및 닫기
        if (newPlaylistTitle) newPlaylistTitle.value = '';
        if (newPlaylistDesc) newPlaylistDesc.value = '';
        if (lunaCreatePlaylistInline) lunaCreatePlaylistInline.style.display = 'none';
      } catch (err) {
        showAlert('플레이리스트 생성 오류: ' + err.message, 'error');
      } finally {
        btnSubmitCreatePlaylist.disabled = false;
        btnSubmitCreatePlaylist.innerHTML = '<i class="fa-solid fa-plus"></i> 생성';
      }
    });
  }

  // 6. [🗂️ 플레이리스트 스마트 매니저] 모달 로직
  const btnOpenPlaylistManagerModal = document.getElementById('btnOpenPlaylistManagerModal');
  const playlistManagerModal = document.getElementById('playlistManagerModal');
  const btnClosePlaylistManagerModal = document.getElementById('btnClosePlaylistManagerModal');
  const btnCancelPlaylistManagerModal = document.getElementById('btnCancelPlaylistManagerModal');
  const btnBatchAssignPlaylists = document.getElementById('btnBatchAssignPlaylists');
  const unassignedPlaylistList = document.getElementById('unassignedPlaylistList');
  const unassignedCountBadge = document.getElementById('unassignedCountBadge');

  async function loadUnassignedPlaylistTracks() {
    if (!unassignedPlaylistList) return;
    unassignedPlaylistList.innerHTML = `
      <div style="text-align:center;padding:40px;color:var(--text-secondary);">
        <i class="fa-solid fa-spinner fa-spin fa-2x" style="color:#38bdf8;"></i>
        <div style="margin-top:12px;font-size:0.9rem;">채널 내 미배정 영상 및 AI 최적 플레이리스트 매칭 분석 중...</div>
      </div>
    `;

    if (btnBatchAssignPlaylists) btnBatchAssignPlaylists.disabled = true;

    try {
      const res = await fetch('/api/luna/unassigned-playlist-tracks');
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || '미배정 트랙 조회 실패');
      }

      const data = await res.json();
      const tracks = data.unassigned_tracks || [];
      const playlists = data.playlists || cachedPlaylists;
      cachedPlaylists = playlists;

      if (unassignedCountBadge) {
        unassignedCountBadge.textContent = `미배정 ${tracks.length}곡 탐지됨`;
      }

      if (tracks.length === 0) {
        unassignedPlaylistList.innerHTML = `
          <div style="text-align:center;padding:50px 20px;">
            <i class="fa-solid fa-circle-check fa-3x" style="color:#34d399;margin-bottom:16px;"></i>
            <h4 style="color:#fff;font-size:1.1rem;margin-bottom:8px;">모든 유튜브 영상이 플레이리스트에 배정되어 있습니다!</h4>
            <p style="color:var(--text-secondary);font-size:0.85rem;">미배정된 업로드 트랙이 없습니다. 앞으로 업로드할 트랙도 AI가 자동 배정합니다.</p>
          </div>
        `;
        if (btnBatchAssignPlaylists) btnBatchAssignPlaylists.disabled = true;
        return;
      }

      // 트랙 카드 리스트 렌더링
      let html = '<div style="display:flex;flex-direction:column;gap:10px;">';

      tracks.forEach((t) => {
        const rec = t.ai_recommendation || {};
        const recommendedId = rec.recommended_playlist_id || t.ai_recommended_playlist_id || '';
        const confidence = rec.confidence !== undefined ? rec.confidence : (t.ai_confidence ?? 0.9);
        const reasoning = rec.reasoning || t.ai_recommendation_reason || '장르 일치';
        const confPercent = Math.round(confidence * 100);

        const thumbUrl = t.cover_url || t.thumbnail_url || (t.video_id ? `https://i.ytimg.com/vi/${t.video_id}/mqdefault.jpg` : '');

        // 셀렉트 박스 옵션 생성
        let optionsHtml = '<option value="">(선택 안 함 - 배정 제외)</option>';
        playlists.forEach((p) => {
          const isSelected = p.id === recommendedId ? 'selected' : '';
          optionsHtml += `<option value="${escapeHtml(p.id)}" ${isSelected}>${escapeHtml(p.title)} (${p.item_count}곡)</option>`;
        });

        html += `
          <div class="unassigned-track-card" data-track-id="${escapeHtml(t.track_id)}" data-video-id="${escapeHtml(t.video_id)}" style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:12px;display:flex;gap:14px;align-items:center;">
            <div style="width:96px;height:54px;border-radius:6px;overflow:hidden;background:#000;flex-shrink:0;position:relative;">
              ${thumbUrl ? `<img src="${escapeHtml(thumbUrl)}" alt="" style="width:100%;height:100%;object-fit:cover;">` : '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#666;"><i class="fa-solid fa-music"></i></div>'}
              <span style="position:absolute;bottom:2px;right:2px;background:rgba(0,0,0,0.8);color:#fff;font-size:9px;padding:1px 4px;border-radius:2px;">
                ${escapeHtml(t.video_id || '')}
              </span>
            </div>
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                <h5 style="color:#fff;margin:0;font-size:0.92rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(t.title)}">
                  ${escapeHtml(t.title)}
                </h5>
                <span class="badge badge-subtle" style="font-size:0.7rem;flex-shrink:0;">${escapeHtml(t.genre || '음악')}</span>
              </div>
              <div style="font-size:0.75rem;color:var(--text-secondary);display:flex;align-items:center;gap:6px;">
                <i class="fa-solid fa-robot" style="color:var(--primary-color);"></i>
                <span>추천 근거: <strong>${escapeHtml(reasoning)}</strong> (${confPercent}% 일치)</span>
              </div>
            </div>
            <div style="width:240px;flex-shrink:0;">
              <label style="display:block;font-size:0.72rem;color:var(--text-muted);margin-bottom:3px;">배정할 플레이리스트</label>
              <select class="form-control form-control-sm unassigned-track-select" style="font-size:0.8rem;background:#111;color:#fff;border-color:rgba(99,102,241,0.4);">
                ${optionsHtml}
              </select>
            </div>
          </div>
        `;
      });

      html += '</div>';
      unassignedPlaylistList.innerHTML = html;
      if (btnBatchAssignPlaylists) btnBatchAssignPlaylists.disabled = false;
    } catch (err) {
      unassignedPlaylistList.innerHTML = `
        <div style="text-align:center;padding:30px;color:#f43f5e;">
          <i class="fa-solid fa-triangle-exclamation fa-2x"></i>
          <div style="margin-top:10px;">미배정 트랙 로드 실패: ${escapeHtml(err.message)}</div>
          <button type="button" class="btn btn-sm btn-outline" style="margin-top:12px;" onclick="loadUnassignedPlaylistTracks()">다시 시도</button>
        </div>
      `;
      if (btnBatchAssignPlaylists) btnBatchAssignPlaylists.disabled = true;
    }
  }

  if (btnOpenPlaylistManagerModal && playlistManagerModal) {
    btnOpenPlaylistManagerModal.addEventListener('click', () => {
      playlistManagerModal.style.display = 'flex';
      loadUnassignedPlaylistTracks();
    });
  }

  if (btnClosePlaylistManagerModal && playlistManagerModal) {
    btnClosePlaylistManagerModal.addEventListener('click', () => {
      playlistManagerModal.style.display = 'none';
    });
  }

  if (btnCancelPlaylistManagerModal && playlistManagerModal) {
    btnCancelPlaylistManagerModal.addEventListener('click', () => {
      playlistManagerModal.style.display = 'none';
    });
  }

  // 일괄 배정 실행
  if (btnBatchAssignPlaylists) {
    btnBatchAssignPlaylists.addEventListener('click', async () => {
      const cards = unassignedPlaylistList.querySelectorAll('.unassigned-track-card');
      const assignments = [];

      cards.forEach((card) => {
        const trackId = card.dataset.trackId;
        const videoId = card.dataset.videoId;
        const select = card.querySelector('.unassigned-track-select');
        const playlistId = select ? select.value : '';

        if (playlistId) {
          assignments.push({
            track_id: trackId,
            video_id: videoId,
            playlist_id: playlistId
          });
        }
      });

      if (assignments.length === 0) {
        showAlert('배정할 플레이리스트가 선택된 트랙이 없습니다.', 'error');
        return;
      }

      btnBatchAssignPlaylists.disabled = true;
      btnBatchAssignPlaylists.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 플레이리스트 일괄 배정 중...';

      try {
        const res = await fetch('/api/luna/batch-assign-playlists', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ assignments: assignments })
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || '일괄 배정 요청 실패');
        }

        const data = await res.json();
        showAlert(`🎉 총 ${data.success_count}곡이 유튜브 플레이리스트에 성공적으로 배정되었습니다!`, 'success');

        // 히스토리 및 플레이리스트 데이터 새로고침
        await loadYoutubePlaylists();
        await loadLunaHistory();

        // 모달 닫기
        if (playlistManagerModal) playlistManagerModal.style.display = 'none';
      } catch (err) {
        showAlert('플레이리스트 일괄 배정 오류: ' + err.message, 'error');
      } finally {
        btnBatchAssignPlaylists.disabled = false;
        btnBatchAssignPlaylists.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> AI 추천대로 전체 일괄 배정하기';
      }
    });
  }

  // =================================================================
  // Phase 8: Threads ✕ X 소셜 통합 자동화 대시보드 컨트롤러
  // =================================================================
  let socialDraftItems = [
    { text: '🧵 첫 번째 도입부: 사람들의 시선을 사로잡는 핵심 후킹 메시지' },
    { text: '2/3 본론: 구체적인 핵심 원리와 실용적인 인사이트 설명' },
    { text: '3/3 결론: 핵심 요약 및 팔로우/리포스트 CTA 유도' }
  ];
  let socialPendingConfirmAction = null;

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // 1. 소셜 대시보드 전체 초기화 및 상태 로드
  async function loadSocialDashboard() {
    initSocialTabNavigation();
    initSocialConfirmModal();
    initAutonomousOperatorUI();
    renderSocialDraftItems();
    await Promise.allSettled([
      loadAutonomousDashboard(),
      loadSocialAccountsStatus(),
      loadSocialSchedulerStatus(),
      loadPublishDrafts(),
      loadSocialHistory(),
      loadQueueJobs()
    ]);
  }

  // 2. 서브탭 네비게이션
  function initSocialTabNavigation() {
    const tabBtns = document.querySelectorAll('#viewSocial [data-social-tab]');
    tabBtns.forEach(btn => {
      btn.onclick = () => {
        const targetTabId = btn.getAttribute('data-social-tab');
        tabBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        document.querySelectorAll('#socialTabContent .social-tab-pane').forEach(pane => {
          pane.style.display = 'none';
          pane.classList.remove('active');
        });

        const targetPane = document.getElementById(targetTabId);
        if (targetPane) {
          targetPane.style.display = 'block';
          targetPane.classList.add('active');
        }

        // 탭 전환 시 자동 데이터 갱신
        if (targetTabId === 'socialTabAutonomous') loadAutonomousDashboard();
        else if (targetTabId === 'socialTabPublish') loadPublishDrafts();
        else if (targetTabId === 'socialTabQueue') loadQueueJobs();
        else if (targetTabId === 'socialTabHistory') loadSocialHistory();
      };
    });

    const btnRefresh = document.getElementById('btnRefreshSocialDashboard');
    if (btnRefresh) {
      btnRefresh.onclick = () => loadSocialDashboard();
    }
  }

  // 3. 계정 및 스케줄러 상태 로드
  async function loadSocialAccountsStatus() {
    try {
      const res = await fetch('/api/social/accounts');
      if (!res.ok) return;
      const data = await res.json();
      const accounts = data.accounts || [];

      const threadsAcc = accounts.find(a => a.platform === 'threads');
      const dashThreadsBadge = document.getElementById('dashThreadsBadge');
      const dashThreadsUsername = document.getElementById('dashThreadsUsername');
      const dashThreadsExpiry = document.getElementById('dashThreadsExpiry');

      if (threadsAcc && (threadsAcc.status === 'active' || threadsAcc.status === 'connected')) {
        if (dashThreadsBadge) {
          dashThreadsBadge.className = 'badge badge-success';
          dashThreadsBadge.textContent = '연결됨';
        }
        if (dashThreadsUsername) dashThreadsUsername.textContent = '@' + (threadsAcc.username || threadsAcc.account_id);
        if (dashThreadsExpiry) dashThreadsExpiry.textContent = '토큰 정상 작동 중';
      } else {
        if (dashThreadsBadge) {
          dashThreadsBadge.className = 'badge badge-subtle';
          dashThreadsBadge.textContent = '미연결';
        }
        if (dashThreadsUsername) dashThreadsUsername.textContent = '미연결';
        if (dashThreadsExpiry) dashThreadsExpiry.textContent = '토큰 등록 필요';
      }

      const xAcc = accounts.find(a => a.platform === 'x');
      const dashXBadge = document.getElementById('dashXBadge');
      const dashXUsername = document.getElementById('dashXUsername');
      const dashXScopes = document.getElementById('dashXScopes');

      if (xAcc && (xAcc.status === 'active' || xAcc.status === 'connected')) {
        if (dashXBadge) {
          dashXBadge.className = 'badge badge-success';
          dashXBadge.textContent = '연결됨';
        }
        if (dashXUsername) dashXUsername.textContent = '@' + (xAcc.username || xAcc.account_id);
        if (dashXScopes) dashXScopes.textContent = 'OAuth 2.0 PKCE 활성';
      } else {
        if (dashXBadge) {
          dashXBadge.className = 'badge badge-subtle';
          dashXBadge.textContent = '미연결';
        }
        if (dashXUsername) dashXUsername.textContent = '미연결';
        if (dashXScopes) dashXScopes.textContent = '토큰 등록 필요';
      }
    } catch (err) {
      console.error('loadSocialAccountsStatus error:', err);
    }
  }

  async function loadSocialSchedulerStatus() {
    try {
      const res = await fetch('/api/social/scheduler/status');
      if (!res.ok) return;
      const data = await res.json();
      const sched = data.scheduler || {};
      const stats = sched.stats || {};

      const dashSchedulerBadge = document.getElementById('dashSchedulerBadge');
      const dashSchedulerWorker = document.getElementById('dashSchedulerWorker');
      const dashSchedulerStats = document.getElementById('dashSchedulerStats');

      if (dashSchedulerBadge) {
        if (sched.status === 'running') {
          dashSchedulerBadge.className = 'badge badge-success';
          dashSchedulerBadge.textContent = '정상 가동 중';
        } else {
          dashSchedulerBadge.className = 'badge badge-subtle';
          dashSchedulerBadge.textContent = '대기 중';
        }
      }
      if (dashSchedulerWorker) {
        dashSchedulerWorker.textContent = 'worker: ' + (sched.worker_id || '-');
      }
      if (dashSchedulerStats) {
        dashSchedulerStats.textContent = `실행: ${stats.jobs_executed || 0} | 성공: ${stats.jobs_succeeded || 0} | 재시도: ${stats.jobs_retried || 0}`;
      }

      const btnTick = document.getElementById('btnManualSchedulerTick');
      if (btnTick) {
        btnTick.onclick = async () => {
          btnTick.disabled = true;
          try {
            const tickRes = await fetch('/api/social/scheduler/tick', { method: 'POST' });
            const tickData = await tickRes.json();
            showAlert('스케줄러 1회 실행 완료: ' + (tickData.result ? tickData.result.job_id : '대기 작업 없음'), 'info');
            loadSocialSchedulerStatus();
            loadQueueJobs();
          } catch (e) {
            showAlert('스케줄러 실행 오류: ' + e.message, 'error');
          } finally {
            btnTick.disabled = false;
          }
        };
      }
    } catch (err) {
      console.error('loadSocialSchedulerStatus error:', err);
    }
  }

  // 4. 초안 작성 및 타래 편집
  function renderSocialDraftItems() {
    const container = document.getElementById('socialDraftItemsContainer');
    const badge = document.getElementById('socialDraftSummaryBadge');
    if (!container) return;

    const platform = document.getElementById('socialDraftPlatform')?.value || 'threads';
    const limit = platform === 'threads' ? 500 : 280;

    container.innerHTML = '';
    socialDraftItems.forEach((item, idx) => {
      const charCount = (item.text || '').length;
      const isOver = charCount > limit;

      const itemCard = document.createElement('div');
      itemCard.style.cssText = 'background: rgba(0,0,0,0.25); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px;';
      itemCard.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <strong style="font-size: 0.82rem; color: #38bdf8;">타래 #${idx + 1}</strong>
          <div style="display: flex; gap: 8px; align-items: center;">
            <span style="font-size: 0.75rem; color: ${isOver ? '#f43f5e' : 'var(--text-secondary)'};">
              ${charCount} / ${limit}자 ${isOver ? '(글자 수 초과)' : ''}
            </span>
            ${socialDraftItems.length > 1 ? `<button type="button" class="btn btn-xs btn-outline" data-del-draft="${idx}" style="color: #f43f5e;">삭제</button>` : ''}
          </div>
        </div>
        <textarea class="form-control" rows="3" data-draft-idx="${idx}" style="resize: vertical; font-size: 0.85rem; line-height: 1.5;">${escapeHtml(item.text)}</textarea>
      `;
      container.appendChild(itemCard);
    });

    if (badge) badge.textContent = `총 ${socialDraftItems.length}개 타래 항목 (${limit}자 기준)`;

    // 입력 및 삭제 이벤트 바인딩
    container.querySelectorAll('textarea[data-draft-idx]').forEach(ta => {
      ta.oninput = (e) => {
        const i = parseInt(e.target.getAttribute('data-draft-idx'), 10);
        socialDraftItems[i].text = e.target.value;
        const cSpan = e.target.parentElement.querySelector('span');
        const c = e.target.value.length;
        if (cSpan) {
          cSpan.textContent = `${c} / ${limit}자 ${c > limit ? '(글자 수 초과)' : ''}`;
          cSpan.style.color = c > limit ? '#f43f5e' : 'var(--text-secondary)';
        }
      };
    });

    container.querySelectorAll('button[data-del-draft]').forEach(btn => {
      btn.onclick = () => {
        const i = parseInt(btn.getAttribute('data-del-draft'), 10);
        socialDraftItems.splice(i, 1);
        renderSocialDraftItems();
      };
    });
  }

  // 타래 추가 버튼
  const btnAddDraftItem = document.getElementById('btnAddDraftThreadItem');
  if (btnAddDraftItem) {
    btnAddDraftItem.onclick = () => {
      if (socialDraftItems.length >= 10) {
        showAlert('타래는 한 번에 최대 10개까지만 구성 가능합니다.', 'warning');
        return;
      }
      socialDraftItems.push({ text: `${socialDraftItems.length + 1}/${socialDraftItems.length + 1} 추가 타래 내용...` });
      renderSocialDraftItems();
    };
  }

  // 마케팅 결과 불러오기
  const btnImportMarketing = document.getElementById('btnImportFromMarketing');
  if (btnImportMarketing) {
    btnImportMarketing.onclick = async () => {
      try {
        const res = await fetch('/api/marketing/history');
        if (!res.ok) throw new Error('마케팅 이력 조회 실패');
        const list = await res.json();
        if (!list || !list.length) {
          showAlert('불러올 수 있는 마케팅 생성물이 없습니다. 먼저 5번 마케팅 탭에서 생성을 실행하세요.', 'info');
          return;
        }
        const latest = list[0];
        const threadsText = latest.threads || '';
        const lines = threadsText.split(/\n\n+/).filter(l => l.trim());
        if (lines.length > 0) {
          socialDraftItems = lines.map(line => ({ text: line.trim() }));
          renderSocialDraftItems();
          showAlert(`마케팅 생성물에서 총 ${socialDraftItems.length}개 타래 항목을 성공적으로 불러왔습니다!`, 'success');
        } else {
          showAlert('마케팅 생성물 내에 스레드 텍스트가 없습니다.', 'warning');
        }
      } catch (e) {
        showAlert('불러오기 오류: ' + e.message, 'error');
      }
    };
  }

  // 초안 저장 버튼
  const btnSavePublishDraft = document.getElementById('btnSaveAsPublishDraft');
  if (btnSavePublishDraft) {
    btnSavePublishDraft.onclick = async () => {
      const platform = document.getElementById('socialDraftPlatform')?.value || 'threads';
      const items = socialDraftItems.filter(it => it.text.trim());
      if (!items.length) {
        showAlert('초안 내용이 비어 있습니다.', 'warning');
        return;
      }

      btnSavePublishDraft.disabled = true;
      try {
        const payload = {
          platform: platform,
          actor_account_id: 'default',
          items: items.map((it, idx) => ({ item_index: idx, content: it.text })),
          dry_run: true
        };
        const res = await fetch('/api/social/drafts/manual', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error('초안 저장 실패');
        const data = await res.json();
        const savedJobId = data.job_id || data.draft?.job_id || '';
        showAlert(`발행 초안이 성공적으로 등록되었습니다 (Job ID: ${savedJobId})!`, 'success');
        loadPublishDrafts();
      } catch (e) {
        showAlert('초안 저장 오류: ' + e.message, 'error');
      } finally {
        btnSavePublishDraft.disabled = false;
      }
    };
  }

  // 5. 발행 탭 (Publish)
  async function loadPublishDrafts() {
    const listContainer = document.getElementById('socialPublishDraftList');
    if (!listContainer) return;
    try {
      const res = await fetch('/api/social/jobs?job_type=publish&limit=20');
      if (!res.ok) return;
      const data = await res.json();
      const jobs = (data.jobs || []).filter(j => ['draft', 'approved', 'partial', 'scheduled'].includes(j.status));

      if (!jobs.length) {
        listContainer.innerHTML = '<div class="empty-state-box" style="padding: 24px;"><p>대기 중인 발행 초안이 없습니다. 1번 탭에서 초안을 등록하세요.</p></div>';
        return;
      }

      listContainer.innerHTML = '';
      jobs.forEach(job => {
        const card = document.createElement('div');
        card.style.cssText = 'background: rgba(0,0,0,0.25); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px;';
        card.innerHTML = `
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="badge ${job.platform === 'threads' ? 'badge-primary' : 'badge-subtle'}">${job.platform.toUpperCase()}</span>
              <strong style="color: #fff; font-size: 0.88rem;">${job.job_id}</strong>
              <span class="badge badge-subtle">${job.status}</span>
            </div>
            <div style="font-size: 0.75rem; color: var(--text-secondary);">
              생성: ${new Date(job.created_at * 1000).toLocaleString('ko-KR')}
            </div>
          </div>
          <div style="font-size: 0.82rem; color: #cbd5e1; margin-bottom: 12px; line-height: 1.5; background: rgba(0,0,0,0.3); padding: 8px 10px; border-radius: 6px;">
            ${escapeHtml(JSON.stringify(job.content_payload || {}).slice(0, 150))}...
          </div>
          <div style="display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap;">
            <button class="btn btn-xs btn-outline" data-pub-dryrun="${job.job_id}"><i class="fa-solid fa-flask"></i> 드라이런 미리보기</button>
            <button class="btn btn-xs btn-primary" data-pub-live="${job.job_id}"><i class="fa-solid fa-paper-plane"></i> 승인 후 즉시 발행</button>
          </div>
          <div id="pubResultBox_${job.job_id}" style="display: none; margin-top: 10px;"></div>
        `;
        listContainer.appendChild(card);
      });

      // 발행 이벤트 바인딩
      listContainer.querySelectorAll('button[data-pub-dryrun]').forEach(btn => {
        btn.onclick = async () => {
          const jid = btn.getAttribute('data-pub-dryrun');
          const box = document.getElementById(`pubResultBox_${jid}`);
          btn.disabled = true;
          try {
            const res = await fetch(`/api/social/publish/${jid}?dry_run=true`, { method: 'POST' });
            const data = await res.json();
            if (box) {
              box.style.display = 'block';
              box.innerHTML = `<div class="alert alert-info" style="font-size: 0.8rem; margin: 0;"><strong>[드라이런 통과]</strong> ${data.results?.length || 0}개 항목 정상 검증 완료</div>`;
            }
          } catch (e) {
            showAlert('드라이런 오류: ' + e.message, 'error');
          } finally {
            btn.disabled = false;
          }
        };
      });

      listContainer.querySelectorAll('button[data-pub-live]').forEach(btn => {
        btn.onclick = () => {
          const jid = btn.getAttribute('data-pub-live');
          const job = jobs.find(j => j.job_id === jid);
          showSocialConfirmModal(
            {
              platform: job ? job.platform : 'threads',
              jobType: '게시물 발행 (Publish)',
              itemCount: '전체 타래 항목'
            },
            async () => {
              btn.disabled = true;
              try {
                const res = await fetch(`/api/social/publish/${jid}?dry_run=false`, { method: 'POST' });
                const data = await res.json();
                showAlert(`🎉 소셜 게시물이 성공적으로 발행되었습니다!`, 'success');
                loadPublishDrafts();
                loadSocialHistory();
              } catch (e) {
                showAlert('발행 실패: ' + e.message, 'error');
              } finally {
                btn.disabled = false;
              }
            }
          );
        };
      });
    } catch (err) {
      console.error('loadPublishDrafts error:', err);
    }
  }

  // 6. 댓글·답글 자동화
  let fetchedComments = [];
  const btnFetchComments = document.getElementById('btnFetchPostComments');
  if (btnFetchComments) {
    btnFetchComments.onclick = async () => {
      const platform = document.getElementById('replyFetchPlatform')?.value || 'threads';
      const postId = document.getElementById('replyFetchPostId')?.value.trim();
      const container = document.getElementById('replyCommentsContainer');

      const origBtnHtml = btnFetchComments.innerHTML;
      btnFetchComments.disabled = true;
      btnFetchComments.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 조회 중...';
      try {
        const fetchUrl = postId 
          ? `/api/social/comments/${platform}/${encodeURIComponent(postId)}`
          : `/api/social/comments/${platform}`;
        const res = await fetch(fetchUrl);
        const data = await res.json();
        fetchedComments = data.comments || data.replies || [];

        if (!fetchedComments.length) {
          container.innerHTML = '<div class="empty-state-box" style="padding: 24px;"><p>조회된 최근 댓글·답글이 없습니다.</p></div>';
          showAlert('조회된 최근 댓글이 없습니다.', 'info');
          return;
        }

        showAlert(`최근 댓글 ${fetchedComments.length}건을 성공적으로 불러왔습니다.`, 'success');

        const repliedCount = fetchedComments.filter(c => c.has_replied).length;
        const pendingCount = fetchedComments.length - repliedCount;

        container.innerHTML = `
          <div style="display: flex; gap: 14px; align-items: center; background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 0.82rem; flex-wrap: wrap;">
            <span>총 댓글: <strong>${fetchedComments.length}</strong>건</span>
            <span style="color: #34d399;"><i class="fa-solid fa-circle-check"></i> 답글 완료: <strong>${repliedCount}</strong>건</span>
            <span style="color: #fbbf24;"><i class="fa-regular fa-clock"></i> 답글 대기: <strong>${pendingCount}</strong>건</span>
          </div>
        `;

        fetchedComments.forEach((c, idx) => {
          const cCard = document.createElement('div');
          cCard.id = `commentCard_${idx}`;
          cCard.style.cssText = `background: rgba(0,0,0,0.25); border: 1px solid ${c.has_replied ? '#059669' : 'var(--border-color)'}; border-radius: 8px; padding: 14px; margin-bottom: 10px;`;

          const postBadge = c.post_snippet ? `<span style="font-size:0.72rem;background:rgba(56,189,248,0.12);color:#38bdf8;padding:2px 6px;border-radius:4px;margin-left:6px;"><i class="fa-solid fa-link"></i> 원글: ${escapeHtml(c.post_snippet)}</span>` : '';
          const ownBadge = c.is_own_comment ? `<span style="font-size:0.72rem;background:rgba(168,85,247,0.15);color:#c084fc;padding:2px 6px;border-radius:4px;margin-left:6px;"><i class="fa-solid fa-user-check"></i> 내 계정 작성</span>` : '';
          const statusBadge = c.has_replied
            ? `<span id="statusBadge_${idx}" style="font-size:0.74rem;background:#065f46;color:#34d399;padding:3px 8px;border-radius:4px;font-weight:600;"><i class="fa-solid fa-circle-check"></i> 답글 완료</span>`
            : `<span id="statusBadge_${idx}" style="font-size:0.74rem;background:rgba(245,158,11,0.15);color:#fbbf24;padding:3px 8px;border-radius:4px;"><i class="fa-regular fa-clock"></i> 답글 대기 중</span>`;

          let myReplyBoxHtml = '';
          if (c.has_replied && c.my_reply) {
            const replyUrlLink = c.my_reply.url ? `<a href="${escapeHtml(c.my_reply.url)}" target="_blank" rel="noopener noreferrer" style="color: #38bdf8; text-decoration: none; font-size: 0.74rem;"><i class="fa-solid fa-arrow-up-right-from-square"></i> 답글 보기 ↗</a>` : '';
            myReplyBoxHtml = `
              <div id="existingReplyBox_${idx}" style="background: rgba(16,185,129,0.08); border-left: 3px solid #10b981; border-radius: 4px; padding: 8px 12px; margin-bottom: 10px; font-size: 0.82rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                  <strong style="color: #34d399;"><i class="fa-solid fa-reply"></i> 등록된 내 답글</strong>
                  ${replyUrlLink}
                </div>
                <div style="color: #f1f5f9; line-height: 1.4;">${escapeHtml(c.my_reply.text || '(답글 내용 없음)')}</div>
              </div>
            `;
          }

          cCard.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; flex-wrap: wrap; gap: 6px;">
              <div>
                <strong style="font-size: 0.88rem; color: #fff;">@${escapeHtml(c.username || c.author_id || '익명')}</strong>
                ${ownBadge}
                ${postBadge}
              </div>
              <div style="display: flex; align-items: center; gap: 8px;">
                ${statusBadge}
                <span style="font-size: 0.72rem; color: var(--text-secondary);">${c.created_at ? escapeHtml(String(c.created_at)) : (c.timestamp ? new Date(c.timestamp * 1000).toLocaleString('ko-KR') : '')}</span>
              </div>
            </div>
            <div style="font-size: 0.9rem; color: #e2e8f0; margin-bottom: 10px; line-height: 1.45;">${escapeHtml(c.text)}</div>
            ${myReplyBoxHtml}
            <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
              <select class="form-control" data-tone-idx="${idx}" style="width: auto; font-size: 0.78rem; padding: 4px 8px;">
                <option value="friendly">친근한 톤</option>
                <option value="informative">정보 제공형</option>
                <option value="grateful">감사 인사형</option>
                <option value="question">질문 유도형</option>
                <option value="concise">간결형</option>
              </select>
              <button class="btn btn-xs btn-outline" data-gen-reply="${idx}"><i class="fa-solid fa-wand-magic-sparkles"></i> AI 답글 생성</button>
            </div>
            <div id="replyDraftBox_${idx}" style="margin-top: 10px; display: none;">
              <textarea class="form-control" rows="2" style="font-size: 0.84rem; resize: vertical;" id="replyDraftText_${idx}" placeholder="생성된 답글 초안을 검토하거나 직접 수정하세요."></textarea>
              <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; flex-wrap: wrap; gap: 6px;">
                <label style="font-size: 0.8rem; color: #34d399; cursor: pointer; display: flex; align-items: center; gap: 4px;">
                  <input type="checkbox" data-approve-reply="${idx}"> 이 답글 일괄 승인에 포함
                </label>
                <button class="btn btn-xs btn-primary" data-publish-single="${idx}">
                  <i class="fa-solid fa-paper-plane"></i> 이 답글 즉시 발행 🚀
                </button>
              </div>
            </div>
          `;
          container.appendChild(cCard);
        });

        // 답글 생성 이벤트
        container.querySelectorAll('button[data-gen-reply]').forEach(btn => {
          btn.onclick = async () => {
            const idx = parseInt(btn.getAttribute('data-gen-reply'), 10);
            const comment = fetchedComments[idx];
            const tone = container.querySelector(`select[data-tone-idx="${idx}"]`)?.value || 'friendly';
            const draftBox = document.getElementById(`replyDraftBox_${idx}`);
            const draftText = document.getElementById(`replyDraftText_${idx}`);

            const origHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 생성 중...';
            try {
              const res = await fetch('/api/social/reply/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  platform: platform,
                  original_post: comment.text,
                  comment_text: comment.text,
                  author_name: comment.username || '',
                  tone: tone
                })
              });
              const data = await res.json();
              if (res.ok) {
                const draft = data.reply_draft || (data.reply && data.reply.reply) || data.reply || '';
                if (draftText) draftText.value = draft;
                if (draftBox) draftBox.style.display = 'block';
                showAlert('AI 답글 초안이 생성되었습니다. 검토 후 즉시 발행하거나 일괄 승인하세요.', 'success');
              } else {
                showAlert('답글 생성 실패: ' + (data.detail || data.message || '오류 발생'), 'error');
              }
            } catch (e) {
              showAlert('답글 생성 오류: ' + e.message, 'error');
            } finally {
              btn.disabled = false;
              btn.innerHTML = origHtml;
            }
          };
        });

        // 단일 답글 즉시 발행 이벤트
        container.querySelectorAll('button[data-publish-single]').forEach(btn => {
          btn.onclick = async () => {
            const idx = parseInt(btn.getAttribute('data-publish-single'), 10);
            const comment = fetchedComments[idx];
            const draftText = document.getElementById(`replyDraftText_${idx}`);
            const replyContent = (draftText ? draftText.value : '').trim();
            if (!replyContent) {
              showAlert('발행할 답글 내용이 비어 있습니다.', 'warning');
              return;
            }

            const origHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 발행 중...';
            try {
              const res = await fetch('/api/social/replies/publish-single', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  platform: platform,
                  target_comment_id: comment.id,
                  reply_text: replyContent,
                  dry_run: false
                })
              });
              const data = await res.json();
              if (res.ok && data.status === 'success') {
                const result = data.result || {};
                showAlert('답글이 성공적으로 발행되었습니다!', 'success');

                // 해당 카드를 즉시 답글 완료 상태로 갱신
                comment.has_replied = true;
                comment.my_reply = {
                  text: replyContent,
                  url: result.url || '',
                  post_id: result.reply_post_id || '',
                  status: 'published'
                };

                const card = document.getElementById(`commentCard_${idx}`);
                if (card) {
                  card.style.borderColor = '#059669';
                }
                const badge = document.getElementById(`statusBadge_${idx}`);
                if (badge) {
                  badge.style.background = '#065f46';
                  badge.style.color = '#34d399';
                  badge.style.fontWeight = '600';
                  badge.innerHTML = '<i class="fa-solid fa-circle-check"></i> 답글 완료';
                }

                // 기존 등록된 내 답글 박스 삽입 또는 업데이트
                let replyBox = document.getElementById(`existingReplyBox_${idx}`);
                const urlLink = result.url ? `<a href="${escapeHtml(result.url)}" target="_blank" rel="noopener noreferrer" style="color: #38bdf8; text-decoration: none; font-size: 0.74rem;"><i class="fa-solid fa-arrow-up-right-from-square"></i> 답글 보기 ↗</a>` : '';
                if (!replyBox) {
                  replyBox = document.createElement('div');
                  replyBox.id = `existingReplyBox_${idx}`;
                  replyBox.style.cssText = 'background: rgba(16,185,129,0.08); border-left: 3px solid #10b981; border-radius: 4px; padding: 8px 12px; margin-bottom: 10px; font-size: 0.82rem;';
                  const draftBox = document.getElementById(`replyDraftBox_${idx}`);
                  if (draftBox) {
                    draftBox.parentNode.insertBefore(replyBox, draftBox);
                  }
                }
                replyBox.innerHTML = `
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                    <strong style="color: #34d399;"><i class="fa-solid fa-reply"></i> 방금 등록된 내 답글</strong>
                    ${urlLink}
                  </div>
                  <div style="color: #f1f5f9; line-height: 1.4;">${escapeHtml(replyContent)}</div>
                `;
              } else {
                showAlert('답글 발행 실패: ' + (data.detail || data.error || '오류 발생'), 'error');
              }
            } catch (e) {
              showAlert('답글 발행 중 오류: ' + e.message, 'error');
            } finally {
              btn.disabled = false;
              btn.innerHTML = origHtml;
            }
          };
        });

        // 승인 체크박스 토글
        container.querySelectorAll('input[data-approve-reply]').forEach(chk => {
          chk.onchange = () => {
            const approvedCount = container.querySelectorAll('input[data-approve-reply]:checked').length;
            const badge = document.getElementById('replySelectedCount');
            const btnExec = document.getElementById('btnExecuteBatchReplies');
            if (badge) badge.textContent = `선택된 승인 답글: ${approvedCount}개`;
            if (btnExec) btnExec.disabled = approvedCount === 0;
          };
        });
      } catch (err) {
        showAlert('댓글 조회 실패: ' + err.message, 'error');
      } finally {
        btnFetchComments.disabled = false;
        btnFetchComments.innerHTML = origBtnHtml || '<i class="fa-solid fa-comments"></i> 댓글 조회';
      }
    };
  }

  // 승인된 답글 일괄 실행
  const btnExecBatchReplies = document.getElementById('btnExecuteBatchReplies');
  if (btnExecBatchReplies) {
    btnExecBatchReplies.onclick = () => {
      const container = document.getElementById('replyCommentsContainer');
      const approvedCheckboxes = container.querySelectorAll('input[data-approve-reply]:checked');
      if (!approvedCheckboxes.length) return;

      const itemsToPublish = [];
      approvedCheckboxes.forEach(chk => {
        const idx = parseInt(chk.getAttribute('data-approve-reply'), 10);
        const comment = fetchedComments[idx];
        const draftText = document.getElementById(`replyDraftText_${idx}`);
        const text = draftText ? draftText.value.trim() : '';
        if (comment && text) {
          itemsToPublish.push({
            comment_id: comment.id,
            reply_text: text,
            idx: idx
          });
        }
      });

      if (!itemsToPublish.length) {
        showAlert('승인된 답글 중 내용이 입력된 항목이 없습니다.', 'warning');
        return;
      }

      showSocialConfirmModal(
        {
          platform: document.getElementById('replyFetchPlatform')?.value || 'threads',
          jobType: '댓글 답글 일괄 발행',
          itemCount: `${itemsToPublish.length}건`
        },
        async () => {
          showAlert(`총 ${itemsToPublish.length}건의 승인된 답글을 실시간 발행합니다...`, 'info');
          btnExecBatchReplies.disabled = true;

          try {
            const res = await fetch('/api/social/replies/batch-publish', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                platform: document.getElementById('replyFetchPlatform')?.value || 'threads',
                items: itemsToPublish.map(it => ({ comment_id: it.comment_id, reply_text: it.reply_text })),
                dry_run: false
              })
            });
            const data = await res.json();
            if (res.ok && data.status === 'success') {
              const results = data.results || [];
              let successCount = 0;
              results.forEach((r, rIdx) => {
                if (r.status === 'success') {
                  successCount++;
                  const origItem = itemsToPublish[rIdx];
                  if (origItem) {
                    const idx = origItem.idx;
                    const card = document.getElementById(`commentCard_${idx}`);
                    if (card) card.style.borderColor = '#059669';
                    const badge = document.getElementById(`statusBadge_${idx}`);
                    if (badge) {
                      badge.style.background = '#065f46';
                      badge.style.color = '#34d399';
                      badge.style.fontWeight = '600';
                      badge.innerHTML = '<i class="fa-solid fa-circle-check"></i> 답글 완료';
                    }
                  }
                }
              });
              showAlert(`총 ${successCount}건의 답글이 성공적으로 발행되었습니다!`, 'success');
              loadSocialHistory();
            } else {
              showAlert('일괄 발행 실패: ' + (data.detail || '오류 발생'), 'error');
            }
          } catch (e) {
            showAlert('일괄 발행 중 통신 오류: ' + e.message, 'error');
          } finally {
            btnExecBatchReplies.disabled = false;
          }
        }
      );
    };
  }

  // 7. 스하리 탭 (불특정 다수 실시간 탐색형 스하리)
  let discoveredEngTargets = [];
  const btnDiscoverTargets = document.getElementById('btnDiscoverTargets');
  const btnSelectAllTargets = document.getElementById('btnSelectAllTargets');
  const btnDeselectAllTargets = document.getElementById('btnDeselectAllTargets');
  const btnTabEngDryRun = document.getElementById('btnTabEngDryRun');
  const btnTabEngLive = document.getElementById('btnTabEngLive');

  // 1단계: 신규 발굴 모드 토글 안내문 이벤트
  const chkExcludeExisting = document.getElementById('chkExcludeExistingRelationships');
  const engExistingNotice = document.getElementById('engExistingNotice');
  if (chkExcludeExisting && engExistingNotice) {
    chkExcludeExisting.onchange = () => {
      engExistingNotice.style.display = chkExcludeExisting.checked ? 'none' : 'block';
    };
  }

  // 1단계: 기존 맞팔/팔로워 수동 등록 모달
  const btnOpenBatchModal = document.getElementById('btnOpenBatchFollowersModal');
  const batchFollowersModal = document.getElementById('batchFollowersModal');
  const btnCloseBatchModal = document.getElementById('btnCloseBatchFollowersModal');
  const btnCancelBatchModal = document.getElementById('btnCancelBatchFollowersModal');
  const btnSubmitBatchFollowers = document.getElementById('btnSubmitBatchFollowers');
  const txtBatchFollowers = document.getElementById('txtBatchFollowerUsernames');

  if (btnOpenBatchModal && batchFollowersModal) {
    btnOpenBatchModal.onclick = () => {
      if (txtBatchFollowers) txtBatchFollowers.value = '';
      batchFollowersModal.style.display = 'flex';
    };
    const closeModal = () => { batchFollowersModal.style.display = 'none'; };
    if (btnCloseBatchModal) btnCloseBatchModal.onclick = closeModal;
    if (btnCancelBatchModal) btnCancelBatchModal.onclick = closeModal;

    if (btnSubmitBatchFollowers) {
      btnSubmitBatchFollowers.onclick = async () => {
        const rawText = txtBatchFollowers?.value || '';
        const lines = rawText.split(/[\n,]+/).map(s => s.trim().replace(/^@/, '')).filter(Boolean);
        if (!lines.length) {
          showAlert('등록할 사용자명을 1개 이상 입력해주세요.', 'warning');
          return;
        }

        const platform = document.getElementById('tabEngPlatform')?.value || 'threads';
        btnSubmitBatchFollowers.disabled = true;
        try {
          const res = await fetch('/api/engagement/relationships/batch-register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              platform: platform,
              usernames: lines,
              expires_in_days: null
            })
          });
          const data = await res.json();
          if (res.ok && data.status === 'success') {
            showAlert(`총 ${data.registered_count}명의 팔로워가 영구 제외 목록에 등록되었습니다!`, 'success');
            closeModal();
            if (btnDiscoverTargets) btnDiscoverTargets.click();
          } else {
            showAlert('등록 실패: ' + (data.detail || '오류 발생'), 'error');
          }
        } catch (e) {
          showAlert('통신 오류: ' + e.message, 'error');
        } finally {
          btnSubmitBatchFollowers.disabled = false;
        }
      };
    }
  }

  // 1단계: 실시간 활성 스레더 자동 탐색
  if (btnDiscoverTargets) {
    btnDiscoverTargets.onclick = async () => {
      const platform = document.getElementById('tabEngPlatform')?.value || 'threads';
      const topic = document.getElementById('tabEngTopic')?.value || '스하리';
      const limit = document.getElementById('tabEngLimit')?.value || '10';
      const excludeExisting = document.getElementById('chkExcludeExistingRelationships')?.checked ?? true;
      const container = document.getElementById('engTargetsContainer');
      const countBadge = document.getElementById('engTargetCount');
      const summaryBar = document.getElementById('engDiscoverySummaryBar');
      const summaryText = document.getElementById('engSummaryText');
      const summaryBadges = document.getElementById('engSummaryBadges');

      const origHtml = btnDiscoverTargets.innerHTML;
      btnDiscoverTargets.disabled = true;
      btnDiscoverTargets.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 실시간 탐색 중...';

      try {
        const queryParams = new URLSearchParams({
          platform: platform,
          topic: topic,
          limit: limit,
          exclude_existing_relationships: excludeExisting ? 'true' : 'false'
        });
        const res = await fetch(`/api/engagement/discover?${queryParams.toString()}`);
        const data = await res.json();
        discoveredEngTargets = data.targets || [];
        const summary = data.summary || {};

        if (countBadge) countBadge.textContent = discoveredEngTargets.length;

        // 요약 바 렌더링
        if (summaryBar && summaryText && summaryBadges) {
          summaryBar.style.display = 'flex';
          const scanned = summary.scanned || discoveredEngTargets.length;
          const excluded = summary.excluded || 0;
          const included = summary.included || discoveredEngTargets.length;
          summaryText.innerHTML = `<strong><i class="fa-solid fa-filter"></i> 탐색 요약:</strong> 총 ${scanned}명 스캔 · <span style="color: #f87171;">${excluded}명 제외</span> · <span style="color: #34d399;">신규 후보 ${included}명</span>`;

          // 사유별 배지 생성
          summaryBadges.innerHTML = '';
          const reasons = summary.excluded_by_reason || {};
          const reasonLabels = {
            self_account: '본인',
            duplicate_candidate: '중복',
            engaged_before: '기존 상호작용',
            commented_on_my_content: '댓글 작성자',
            replied_by_me: '답글 발송 상대',
            known_follower: '팔로워',
            followed_or_following: '맞팔/팔로우',
            suppressed: '차단/제외',
            action_already_done: '액션 중복'
          };

          for (const [rCode, count] of Object.entries(reasons)) {
            if (count > 0) {
              const label = reasonLabels[rCode] || rCode;
              const badge = document.createElement('span');
              badge.style.cssText = 'background: rgba(239, 68, 68, 0.15); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3); padding: 1px 6px; border-radius: 4px; font-size: 0.72rem;';
              badge.textContent = `${label} ${count}`;
              summaryBadges.appendChild(badge);
            }
          }
        }

        if (!discoveredEngTargets.length) {
          container.innerHTML = `
            <div class="empty-state-box" style="padding: 24px;">
              <p style="margin: 0; color: var(--text-secondary);">현재 조건에서 새로운 활성 스레더를 찾지 못했습니다. 주제를 변경해보세요.</p>
            </div>
          `;
          showAlert('탐색된 새로운 활성 스레더가 없습니다.', 'info');
          return;
        }

        container.innerHTML = '';
        discoveredEngTargets.forEach((t, idx) => {
          const card = document.createElement('div');
          card.id = `engTargetCard_${idx}`;
          card.style.cssText = 'background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; display: flex; gap: 12px; align-items: flex-start;';

          const postLink = t.post_url ? `<a href="${escapeHtml(t.post_url)}" target="_blank" rel="noopener noreferrer" style="color: #38bdf8; text-decoration: none; font-size: 0.74rem;"><i class="fa-solid fa-arrow-up-right-from-square"></i> 원문 보기 ↗</a>` : '';
          const viaBadge = t.discovered_via ? `<span style="font-size: 0.7rem; background: rgba(56,189,248,0.12); color: #38bdf8; padding: 2px 6px; border-radius: 4px; margin-left: 6px;"><i class="fa-solid fa-satellite-dish"></i> ${escapeHtml(t.discovered_via)}</span>` : '';
          const newBadge = t.is_new_candidate ? `<span style="font-size: 0.7rem; background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3); padding: 2px 6px; border-radius: 4px; margin-left: 4px;"><i class="fa-solid fa-sparkles"></i> 신규 후보</span>` : '';

          card.innerHTML = `
            <input type="checkbox" data-eng-target-chk="${idx}" checked style="margin-top: 4px; cursor: pointer; width: 16px; height: 16px;">
            <div style="flex: 1; min-width: 0;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; flex-wrap: wrap; gap: 4px;">
                <div>
                  <strong style="font-size: 0.88rem; color: #fff;">@${escapeHtml(t.username || t.account_id)}</strong>
                  ${newBadge}
                  ${viaBadge}
                </div>
                ${postLink}
              </div>
              <div style="font-size: 0.84rem; color: #cbd5e1; line-height: 1.4; margin-bottom: 4px;">${escapeHtml(t.post_text || '(텍스트 없음)')}</div>
            </div>
          `;
          container.appendChild(card);
        });

        showAlert(`실시간 활동 중인 불특정 다수 ${discoveredEngTargets.length}명을 성공적으로 발굴했습니다!`, 'success');
      } catch (e) {
        showAlert('타겟 탐색 실패: ' + e.message, 'error');
      } finally {
        btnDiscoverTargets.disabled = false;
        btnDiscoverTargets.innerHTML = origHtml;
      }
    };
  }

  // 전체 선택 / 해제
  if (btnSelectAllTargets) {
    btnSelectAllTargets.onclick = () => {
      document.querySelectorAll('input[data-eng-target-chk]').forEach(c => c.checked = true);
    };
  }
  if (btnDeselectAllTargets) {
    btnDeselectAllTargets.onclick = () => {
      document.querySelectorAll('input[data-eng-target-chk]').forEach(c => c.checked = false);
    };
  }

  // 선택된 타겟 수집 헬퍼
  function getSelectedEngagementTargets() {
    const platform = document.getElementById('tabEngPlatform')?.value || 'threads';
    const checkedBoxes = document.querySelectorAll('input[data-eng-target-chk]:checked');
    const selected = [];

    checkedBoxes.forEach(chk => {
      const idx = parseInt(chk.getAttribute('data-eng-target-chk'), 10);
      const t = discoveredEngTargets[idx];
      if (t) selected.push(t);
    });

    // 만약 발굴 목록이 비어있고 수동 입력값이 있으면 수동 입력값 사용
    if (!selected.length) {
      const manualAccount = document.getElementById('tabEngAccountId')?.value.trim();
      const manualPost = document.getElementById('tabEngPostId')?.value.trim();
      if (manualAccount && manualPost) {
        selected.push({
          platform: platform,
          account_id: manualAccount,
          username: manualAccount,
          post_id: manualPost,
          profile_url: document.getElementById('tabEngProfileUrl')?.value.trim(),
          post_url: document.getElementById('tabEngPostUrl')?.value.trim(),
          discovered_via: '수동 입력'
        });
      }
    }

    return selected;
  }

  function getSelectedEngagementActions() {
    const actions = [];
    if (document.getElementById('tabEngActionLike')?.checked) actions.push('like');
    if (document.getElementById('tabEngActionRepost')?.checked) actions.push('repost');
    if (document.getElementById('tabEngActionFollow')?.checked) actions.push('follow');
    return actions;
  }

  // 3단계: 모의 시뮬레이션 (드라이런)
  if (btnTabEngDryRun) {
    btnTabEngDryRun.onclick = async () => {
      const targets = getSelectedEngagementTargets();
      const actions = getSelectedEngagementActions();
      const useWeb = document.getElementById('tabEngUseWeb')?.checked || false;
      const excludeExisting = document.getElementById('chkExcludeExistingRelationships')?.checked ?? true;
      const box = document.getElementById('tabEngResultBox');

      if (!targets.length) {
        showAlert('스하리를 실행할 대상을 1명 이상 선택하거나 발굴해주세요.', 'warning');
        return;
      }
      if (!actions.length) {
        showAlert('적어도 1개 이상의 스하리 동작(좋아요/리포스트/팔로우)을 선택하세요.', 'warning');
        return;
      }

      const origHtml = btnTabEngDryRun.innerHTML;
      btnTabEngDryRun.disabled = true;
      btnTabEngDryRun.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 시뮬레이션 중...';

      try {
        const res = await fetch('/api/engagement/auto-run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            platform: document.getElementById('tabEngPlatform')?.value || 'threads',
            targets: targets,
            actions: actions,
            dry_run: true,
            confirm_live: false,
            use_web_fallback: useWeb,
            exclude_existing_relationships: excludeExisting
          })
        });
        const data = await res.json();
        if (box) {
          box.style.display = 'block';
          const skippedInfo = (data.skipped && data.skipped > 0)
            ? `<div style="margin-top: 6px; color: #fca5a5;">⚠️ 기존 관계 계정 ${data.skipped}명은 실행 직전 자동 제외되었습니다.</div>`
            : '';
          box.innerHTML = `
            <div style="background: rgba(56,189,248,0.1); border: 1px solid #38bdf8; border-radius: 8px; padding: 14px; font-size: 0.84rem;">
              <strong style="color: #38bdf8;"><i class="fa-solid fa-flask"></i> [시뮬레이션 완료] 총 ${targets.length}명 대상 검증</strong>
              <div style="color: #cbd5e1; margin-top: 6px;">동작: ${actions.join(', ')} | 일일 한도 슬롯 정상 확인됨 | 계정 제재 없는 3~5초 인간 모사 딜레이 준비 완료</div>
              ${skippedInfo}
            </div>
          `;
        }
        showAlert(`총 ${targets.length}명에 대한 모의 시뮬레이션 검증이 완료되었습니다.`, 'success');
      } catch (e) {
        showAlert('시뮬레이션 실패: ' + e.message, 'error');
      } finally {
        btnTabEngDryRun.disabled = false;
        btnTabEngDryRun.innerHTML = origHtml;
      }
    };
  }

  // 3단계: 실제 일괄 스하리 실행
  if (btnTabEngLive) {
    btnTabEngLive.onclick = () => {
      const targets = getSelectedEngagementTargets();
      const actions = getSelectedEngagementActions();
      const useWeb = document.getElementById('tabEngUseWeb')?.checked || false;
      const excludeExisting = document.getElementById('chkExcludeExistingRelationships')?.checked ?? true;
      const box = document.getElementById('tabEngResultBox');

      if (!targets.length) {
        showAlert('스하리를 실행할 대상을 1명 이상 선택하거나 발굴해주세요.', 'warning');
        return;
      }
      if (!actions.length) {
        showAlert('적어도 1개 이상의 스하리 동작(좋아요/리포스트/팔로우)을 선택하세요.', 'warning');
        return;
      }

      const noticeExtra = !excludeExisting ? '<br><span style="color: #f87171;">⚠️ 신규 발굴 모드가 꺼져있어 기존 관계 계정이 포함될 수 있습니다.</span>' : '';

      showSocialConfirmModal(
        {
          platform: document.getElementById('tabEngPlatform')?.value || 'threads',
          jobType: `불특정 다수 스하리 (${actions.join(', ')})`,
          itemCount: `불특정 다수 ${targets.length}명 ${noticeExtra}`
        },
        async () => {
          showAlert(`불특정 다수 ${targets.length}명에게 3~5초 안전 딜레이를 적용하며 순차 스하리를 시작합니다...`, 'info');
          btnTabEngLive.disabled = true;
          const origHtml = btnTabEngLive.innerHTML;
          btnTabEngLive.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 순차 스하리 진행 중...';

          try {
            const res = await fetch('/api/engagement/auto-run', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                platform: document.getElementById('tabEngPlatform')?.value || 'threads',
                targets: targets,
                actions: actions,
                dry_run: false,
                confirm_live: true,
                use_web_fallback: useWeb,
                exclude_existing_relationships: excludeExisting
              })
            });
            const data = await res.json();
            if (res.ok && data.status === 'success') {
              showAlert(`🎉 스하리 작업이 안전하게 완료되었습니다!`, 'success');
              if (box) {
                box.style.display = 'block';
                const skippedCount = data.skipped || (data.result && data.result.skipped_existing_relationships ? data.result.skipped_existing_relationships.length : 0);
                const skippedHtml = skippedCount > 0
                  ? `<div style="margin-top: 6px; color: #fca5a5;">🛡️ 실행 직전 기존 관계 계정 ${skippedCount}명이 자동 안전 제외(스킵)되었습니다.</div>`
                  : '';
                box.innerHTML = `
                  <div style="background: rgba(16,185,129,0.1); border: 1px solid #10b981; border-radius: 8px; padding: 14px; font-size: 0.84rem;">
                    <strong style="color: #34d399;"><i class="fa-solid fa-circle-check"></i> [실제 스하리 실행 완료]</strong>
                    <div style="color: #f1f5f9; margin-top: 6px;">
                      대상: <strong>${targets.length}명</strong> (${actions.join(', ')})<br>
                      상태: 성공적으로 완료되었으며 감사 로그에 기록되었습니다.
                      ${skippedHtml}
                    </div>
                  </div>
                `;
              }
              loadSocialHistory();
            } else {
              showAlert('스하리 실행 실패: ' + (data.detail || '오류 발생'), 'error');
            }
          } catch (e) {
            showAlert('스하리 실행 중 통신 오류: ' + e.message, 'error');
          } finally {
            btnTabEngLive.disabled = false;
            btnTabEngLive.innerHTML = origHtml;
          }
        }
      );
    };
  }

  // 8. 예약 대기열 탭 (Queue)
  async function loadQueueJobs() {
    const tbody = document.getElementById('socialQueueTableBody');
    if (!tbody) return;
    try {
      const res = await fetch('/api/social/jobs?status=scheduled&limit=50');
      if (!res.ok) return;
      const data = await res.json();
      const jobs = data.jobs || [];

      if (!jobs.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 20px;">대기 중인 예약 작업이 없습니다.</td></tr>';
        return;
      }

      tbody.innerHTML = '';
      jobs.forEach(job => {
        const tr = document.createElement('tr');
        const schedStr = job.scheduled_at > 0 ? new Date(job.scheduled_at * 1000).toLocaleString('ko-KR') : '즉시';
        tr.innerHTML = `
          <td style="font-family: 'JetBrains Mono', monospace;">${escapeHtml(job.job_id)}</td>
          <td><span class="badge ${job.platform === 'threads' ? 'badge-primary' : 'badge-subtle'}">${job.platform}</span></td>
          <td>${job.job_type}</td>
          <td style="color: #38bdf8;">${schedStr}</td>
          <td><span class="badge badge-warning">${job.status}</span></td>
          <td>${job.retry_count} / ${job.max_retries}</td>
          <td>
            <div style="display: flex; gap: 4px;">
              <button class="btn btn-xs btn-outline" data-queue-retry="${job.job_id}"><i class="fa-solid fa-play"></i> 즉시 실행</button>
              <button class="btn btn-xs btn-outline" data-queue-cancel="${job.job_id}" style="color: #f43f5e;"><i class="fa-solid fa-ban"></i> 취소</button>
            </div>
          </td>
        `;
        tbody.appendChild(tr);
      });

      tbody.querySelectorAll('button[data-queue-retry]').forEach(btn => {
        btn.onclick = async () => {
          const jid = btn.getAttribute('data-queue-retry');
          try {
            await fetch(`/api/social/jobs/${jid}/retry?run_immediately=true`, { method: 'POST' });
            showAlert('작업을 즉시 재실행했습니다.', 'success');
            loadQueueJobs();
            loadSocialHistory();
          } catch (e) {
            showAlert('재실행 실패: ' + e.message, 'error');
          }
        };
      });

      tbody.querySelectorAll('button[data-queue-cancel]').forEach(btn => {
        btn.onclick = async () => {
          const jid = btn.getAttribute('data-queue-cancel');
          try {
            await fetch(`/api/social/jobs/${jid}/cancel`, { method: 'POST' });
            showAlert('예약 작업이 취소되었습니다.', 'info');
            loadQueueJobs();
          } catch (e) {
            showAlert('취소 실패: ' + e.message, 'error');
          }
        };
      });
    } catch (err) {
      console.error('loadQueueJobs error:', err);
    }
  }

  // 9. 통합 실행 이력 탭 (History)
  async function loadSocialHistory() {
    const tbody = document.getElementById('socialHistoryTableBody');
    if (!tbody) return;

    const statusFilter = document.getElementById('socialHistoryStatusFilter')?.value || '';
    const platformFilter = document.getElementById('socialHistoryPlatformFilter')?.value || '';

    let url = '/api/social/history?limit=100';
    if (statusFilter) url += `&status=${encodeURIComponent(statusFilter)}`;
    if (platformFilter) url += `&platform=${encodeURIComponent(platformFilter)}`;

    try {
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      const jobs = data.jobs || [];

      if (!jobs.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 20px;">표시할 이력이 없습니다.</td></tr>';
        return;
      }

      tbody.innerHTML = '';
      jobs.forEach(job => {
        const tr = document.createElement('tr');
        const dateStr = new Date(job.created_at * 1000).toLocaleString('ko-KR');
        let statusBadge = 'badge-subtle';
        if (job.status === 'succeeded') statusBadge = 'badge-success';
        else if (job.status === 'partially_failed' || job.status === 'partial') statusBadge = 'badge-warning';
        else if (job.status === 'failed') statusBadge = 'badge-danger';

        const resultInfo = job.last_error_message
          ? `<span style="color: #f43f5e;">${escapeHtml(job.last_error_message.slice(0, 40))}...</span>`
          : (job.result_payload?.results_count ? `완료 항목: ${job.result_payload.results_count}건` : '-');

        tr.innerHTML = `
          <td style="font-size: 0.75rem; color: var(--text-secondary); white-space: nowrap;">${dateStr}</td>
          <td style="font-family: 'JetBrains Mono', monospace; font-size: 0.78rem;">${escapeHtml(job.job_id)}</td>
          <td><span class="badge ${job.platform === 'threads' ? 'badge-primary' : 'badge-subtle'}">${job.platform}</span></td>
          <td>${job.job_type}</td>
          <td><span class="badge ${statusBadge}">${job.status}</span></td>
          <td style="font-size: 0.78rem;">${resultInfo}</td>
          <td>
            <button class="btn btn-xs btn-outline" data-history-detail="${job.job_id}">상세</button>
          </td>
        `;
        tbody.appendChild(tr);
      });

      tbody.querySelectorAll('button[data-history-detail]').forEach(btn => {
        btn.onclick = () => {
          const jid = btn.getAttribute('data-history-detail');
          const job = jobs.find(j => j.job_id === jid);
          if (job) {
            showAlert(`[작업 상세] ID: ${job.job_id}\n플랫폼: ${job.platform} | 종류: ${job.job_type} | 상태: ${job.status}\n생성시각: ${new Date(job.created_at * 1000).toLocaleString('ko-KR')}\n오류: ${job.last_error_message || '없음'}`, 'info');
          }
        };
      });
    } catch (err) {
      console.error('loadSocialHistory error:', err);
    }
  }

  // 필터 변경 시 이력 자동 새로고침
  const histStatusFilter = document.getElementById('socialHistoryStatusFilter');
  if (histStatusFilter) histStatusFilter.onchange = () => loadSocialHistory();
  const histPlatFilter = document.getElementById('socialHistoryPlatformFilter');
  if (histPlatFilter) histPlatFilter.onchange = () => loadSocialHistory();
  const btnRefreshSocialHistory = document.getElementById('btnRefreshSocialHistory');
  if (btnRefreshSocialHistory) btnRefreshSocialHistory.onclick = () => loadSocialHistory();

  // 10. 확인 대화상자 모달
  function initSocialConfirmModal() {
    const modal = document.getElementById('socialConfirmModal');
    const btnClose = document.getElementById('btnCloseSocialConfirmModal');
    const btnCancel = document.getElementById('btnCancelSocialConfirm');
    const btnProceed = document.getElementById('btnProceedSocialConfirm');

    if (btnClose) btnClose.onclick = () => closeSocialConfirmModal();
    if (btnCancel) btnCancel.onclick = () => closeSocialConfirmModal();
    if (btnProceed) {
      btnProceed.onclick = () => {
        closeSocialConfirmModal();
        if (typeof socialPendingConfirmAction === 'function') {
          socialPendingConfirmAction();
        }
      };
    }
  }

  function showSocialConfirmModal({ platform, jobType, itemCount }, onConfirm) {
    const modal = document.getElementById('socialConfirmModal');
    const platEl = document.getElementById('confirmModalPlatform');
    const typeEl = document.getElementById('confirmModalJobType');
    const countEl = document.getElementById('confirmModalItemCount');

    if (platEl) platEl.textContent = (platform || '-').toUpperCase();
    if (typeEl) typeEl.textContent = jobType || '-';
    if (countEl) countEl.textContent = itemCount || '1개';

    socialPendingConfirmAction = onConfirm;
    if (modal) modal.style.display = 'flex';
  }

  function closeSocialConfirmModal() {
    const modal = document.getElementById('socialConfirmModal');
    if (modal) modal.style.display = 'none';
    socialPendingConfirmAction = null;
  }

  // 11. 계정 설정 이벤트 (7번 서브탭)
  const btnSaveTabThreadsToken = document.getElementById('btnSaveTabThreadsToken');
  if (btnSaveTabThreadsToken) {
    btnSaveTabThreadsToken.onclick = async () => {
      const token = document.getElementById('tabThreadsTokenInput')?.value.trim();
      const userId = document.getElementById('tabThreadsUserIdInput')?.value.trim();
      if (!token) {
        showAlert('Threads Access Token을 입력하세요.', 'warning');
        return;
      }
      try {
        const res = await fetch('/api/threads/auth/token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ access_token: token, user_id: userId })
        });
        if (!res.ok) throw new Error('토큰 저장 실패');
        showAlert('Threads 계정 토큰이 성공적으로 저장되었습니다!', 'success');
        loadSocialAccountsStatus();
      } catch (e) {
        showAlert('토큰 저장 오류: ' + e.message, 'error');
      }
    };
  }

  const btnDisconnectTabThreads = document.getElementById('btnDisconnectTabThreads');
  if (btnDisconnectTabThreads) {
    btnDisconnectTabThreads.onclick = async () => {
      if (!confirm('정말 Threads 계정 연결을 해제하시겠습니까?')) return;
      try {
        await fetch('/api/threads/disconnect', { method: 'POST' });
        showAlert('Threads 계정 연결이 해제되었습니다.', 'info');
        loadSocialAccountsStatus();
      } catch (e) {
        showAlert('해제 실패: ' + e.message, 'error');
      }
    };
  }

  const btnSaveTabXToken = document.getElementById('btnSaveTabXToken');
  if (btnSaveTabXToken) {
    btnSaveTabXToken.onclick = async () => {
      const token = document.getElementById('tabXTokenInput')?.value.trim();
      const userId = document.getElementById('tabXUserIdInput')?.value.trim();
      if (!token) {
        showAlert('X Access Token을 입력하세요.', 'warning');
        return;
      }
      try {
        const res = await fetch('/api/x/auth/token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ access_token: token, user_id: userId })
        });
        if (!res.ok) throw new Error('토큰 저장 실패');
        showAlert('X (Twitter) 계정 토큰이 성공적으로 저장되었습니다!', 'success');
        loadSocialAccountsStatus();
      } catch (e) {
        showAlert('토큰 저장 오류: ' + e.message, 'error');
      }
    };
  }

  const btnDisconnectTabX = document.getElementById('btnDisconnectTabX');
  if (btnDisconnectTabX) {
    btnDisconnectTabX.onclick = async () => {
      if (!confirm('정말 X 계정 연결을 해제하시겠습니까?')) return;
      try {
        await fetch('/api/x/auth/disconnect', { method: 'POST' });
        showAlert('X 계정 연결이 해제되었습니다.', 'info');
        loadSocialAccountsStatus();
      } catch (e) {
        showAlert('해제 실패: ' + e.message, 'error');
      }
    };
  }

  // ==========================================
  // 🤖 자율 소셜 오퍼레이터 (어사이드 4대 루틴) 프론트엔드 컨트롤러
  // ==========================================
  let cachedRoutines = [];

  function initAutonomousOperatorUI() {
    const btnRefresh = document.getElementById('btnRefreshAutonomous');
    if (btnRefresh) {
      btnRefresh.onclick = () => loadAutonomousDashboard();
    }

    const btnTriggerAll = document.getElementById('btnTriggerAllAutonomous');
    if (btnTriggerAll) {
      btnTriggerAll.onclick = async () => {
        showAlert('활성 루틴 일괄 점검 및 초안 생성을 시작합니다...', 'info');
        for (const r of cachedRoutines) {
          if (r.enabled) {
            try {
              await fetch(`/api/routines/${r.code}/run?limit=1`, { method: 'POST' });
            } catch (e) {
              console.error(e);
            }
          }
        }
        showAlert('활성 루틴 점검이 완료되었습니다. Outbox를 확인하세요.', 'success');
        loadAutonomousDashboard();
      };
    }

    // 출처 추가 모달 이벤트
    const btnOpenAddSource = document.getElementById('btnOpenAddSourceModal');
    const modalAddSource = document.getElementById('modalAddSource');
    const btnCloseAddSource = document.getElementById('btnCloseAddSourceModal');
    const btnCancelAddSource = document.getElementById('btnCancelAddSourceModal');
    const btnTestSource = document.getElementById('btnTestSourceUrl');
    const btnSaveAddSource = document.getElementById('btnSaveAddSourceModal');

    if (btnOpenAddSource && modalAddSource) {
      btnOpenAddSource.onclick = () => {
        const select = document.getElementById('modalSourceRoutineSelect');
        if (select) {
          select.innerHTML = cachedRoutines.map(r => `<option value="${r.id}">${escapeHtml(r.name)} (${r.code})</option>`).join('');
        }
        document.getElementById('modalSourceName').value = '';
        document.getElementById('modalSourceUrl').value = '';
        const resBox = document.getElementById('sourceTestResultBox');
        if (resBox) {
          resBox.style.display = 'none';
          resBox.innerHTML = '';
        }
        modalAddSource.style.display = 'flex';
      };
    }

    const closeAddSource = () => { if (modalAddSource) modalAddSource.style.display = 'none'; };
    if (btnCloseAddSource) btnCloseAddSource.onclick = closeAddSource;
    if (btnCancelAddSource) btnCancelAddSource.onclick = closeAddSource;

    if (btnTestSource) {
      btnTestSource.onclick = async () => {
        const url = (document.getElementById('modalSourceUrl').value || '').trim();
        const kind = document.getElementById('modalSourceKind').value;
        const resBox = document.getElementById('sourceTestResultBox');
        if (!url) {
          showAlert('URL을 입력해주세요.', 'warning');
          return;
        }

        btnTestSource.disabled = true;
        btnTestSource.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 검증 중...';
        if (resBox) {
          resBox.style.display = 'block';
          resBox.style.background = 'rgba(56,189,248,0.1)';
          resBox.style.color = '#38bdf8';
          resBox.innerHTML = 'SSRF 및 보안 대역 검증, 통신 테스트 진행 중...';
        }

        try {
          const resp = await fetch('/api/sources/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, kind })
          });
          const data = await resp.json();
          if (data.success) {
            resBox.style.background = 'rgba(16,185,129,0.15)';
            resBox.style.color = '#34d399';
            resBox.innerHTML = `<strong>✅ 안전성 통과</strong> | 제목: ${escapeHtml(data.sample_title || '확인됨')} (수집 가능 항목: ${data.items_count}건)`;
          } else {
            resBox.style.background = 'rgba(239,68,68,0.15)';
            resBox.style.color = '#f87171';
            resBox.innerHTML = `<strong>❌ 검증 실패</strong>: ${escapeHtml(data.error || '알 수 없는 오류')}`;
          }
        } catch (e) {
          if (resBox) {
            resBox.style.background = 'rgba(239,68,68,0.15)';
            resBox.style.color = '#f87171';
            resBox.innerHTML = `<strong>❌ 통신 오류</strong>: ${escapeHtml(e.message)}`;
          }
        } finally {
          btnTestSource.disabled = false;
          btnTestSource.innerHTML = '<i class="fa-solid fa-shield-check"></i> 검증 테스트';
        }
      };
    }

    if (btnSaveAddSource) {
      btnSaveAddSource.onclick = async () => {
        const routineId = parseInt(document.getElementById('modalSourceRoutineSelect').value);
        const name = (document.getElementById('modalSourceName').value || '').trim();
        const kind = document.getElementById('modalSourceKind').value;
        const url = (document.getElementById('modalSourceUrl').value || '').trim();

        if (!name || !url) {
          showAlert('출처 이름과 URL을 모두 입력해주세요.', 'warning');
          return;
        }

        try {
          const resp = await fetch('/api/sources', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ routine_id: routineId, name, kind, url, enabled: true })
          });
          if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || '출처 등록 실패');
          }
          showAlert('새 출처가 안전하게 등록되었습니다!', 'success');
          closeAddSource();
          loadAutonomousDashboard();
        } catch (e) {
          showAlert('출처 등록 오류: ' + e.message, 'error');
        }
      };
    }

    // 스케줄 편집 모달 이벤트
    const modalSchedule = document.getElementById('modalScheduleEdit');
    const btnCloseSchedule = document.getElementById('btnCloseScheduleModal');
    const btnCancelSchedule = document.getElementById('btnCancelScheduleModal');
    const btnAddScheduleTime = document.getElementById('btnAddScheduleTimeRow');
    const btnSaveSchedule = document.getElementById('btnSaveScheduleModal');

    const closeSchedule = () => { if (modalSchedule) modalSchedule.style.display = 'none'; };
    if (btnCloseSchedule) btnCloseSchedule.onclick = closeSchedule;
    if (btnCancelSchedule) btnCancelSchedule.onclick = closeSchedule;

    if (btnAddScheduleTime) {
      btnAddScheduleTime.onclick = () => {
        addScheduleTimeInputRow('12:00');
      };
    }

    if (btnSaveSchedule) {
      btnSaveSchedule.onclick = async () => {
        const code = document.getElementById('modalScheduleRoutineCode').value;
        const maxPosts = parseInt(document.getElementById('modalScheduleMaxPosts').value) || 3;

        // 선택된 요일 수집
        const days = [];
        document.querySelectorAll('#modalScheduleDaysContainer input:checked').forEach(cb => {
          days.push(cb.value);
        });
        if (days.length === 0) {
          showAlert('적어도 1개 이상의 실행 요일을 선택해주세요.', 'warning');
          return;
        }

        // 입력된 시각들 수집
        const timeInputs = document.querySelectorAll('.schedule-time-input');
        const schedules = [];
        timeInputs.forEach(inp => {
          const val = inp.value.trim();
          if (/^\d{2}:\d{2}$/.test(val)) {
            schedules.push({
              local_time: val,
              days_of_week: days,
              enabled: true
            });
          }
        });

        if (schedules.length === 0) {
          showAlert('올바른 시각(HH:mm)을 최소 1개 이상 입력해주세요.', 'warning');
          return;
        }

        try {
          const resp = await fetch(`/api/routines/${code}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              schedules: schedules,
              max_posts_per_day: maxPosts
            })
          });
          if (!resp.ok) throw new Error('스케줄 저장 실패');
          showAlert(`${code} 루틴 스케줄이 성공적으로 저장되었습니다!`, 'success');
          closeSchedule();
          loadAutonomousDashboard();
        } catch (e) {
          showAlert('스케줄 저장 오류: ' + e.message, 'error');
        }
      };
    }

    // Outbox 새로고침 & 필터
    const btnRefreshOutbox = document.getElementById('btnRefreshOutbox');
    if (btnRefreshOutbox) {
      btnRefreshOutbox.onclick = () => loadAutonomousOutbox();
    }
    const filterOutbox = document.getElementById('autoOutboxStatusFilter');
    if (filterOutbox) {
      filterOutbox.onchange = () => loadAutonomousOutbox();
    }
  }

  function addScheduleTimeInputRow(val = '09:00') {
    const container = document.getElementById('modalScheduleTimesContainer');
    if (!container) return;
    const div = document.createElement('div');
    div.style.cssText = 'display: flex; gap: 8px; align-items: center;';
    div.innerHTML = `
      <input type="time" class="form-control schedule-time-input" value="${val}" style="width: 130px;">
      <button type="button" class="btn btn-xs btn-outline btn-del-time" style="color: #f87171; border-color: rgba(248,113,113,0.3);">
        <i class="fa-solid fa-trash"></i>
      </button>
    `;
    div.querySelector('.btn-del-time').onclick = () => div.remove();
    container.appendChild(div);
  }

  function openScheduleModal(routine) {
    const modal = document.getElementById('modalScheduleEdit');
    if (!modal) return;
    document.getElementById('modalScheduleRoutineCode').value = routine.code;
    document.getElementById('modalScheduleRoutineName').textContent = `${routine.name} (${routine.code}) 스케줄`;
    document.getElementById('modalScheduleMaxPosts').value = routine.max_posts_per_day || 3;

    // 시각 컨테이너 채우기
    const timesContainer = document.getElementById('modalScheduleTimesContainer');
    timesContainer.innerHTML = '';
    const schedList = routine.schedules || [];
    if (schedList.length > 0) {
      schedList.forEach(s => addScheduleTimeInputRow(s.local_time));
    } else {
      addScheduleTimeInputRow('09:00');
    }

    // 요일 체크박스 동기화
    const firstSched = schedList[0];
    const targetDays = firstSched ? firstSched.days_of_week : ["MON", "TUE", "WED", "THU", "FRI"];
    document.querySelectorAll('#modalScheduleDaysContainer input').forEach(cb => {
      cb.checked = targetDays.includes(cb.value);
    });

    modal.style.display = 'flex';
  }

  // 자율 오퍼레이터 대시보드 데이터 로드
  async function loadAutonomousDashboard() {
    try {
      const [pilotRes, routinesRes, sourcesRes, anglesRes] = await Promise.all([
        fetch('/api/pilot/status').then(r => r.json()),
        fetch('/api/routines').then(r => r.json()),
        fetch('/api/sources').then(r => r.json()),
        fetch('/api/routines/MAUM_PROMO/angles').then(r => r.json())
      ]);

      cachedRoutines = routinesRes || [];

      // 1. 헤더 배지 업데이트
      const badge = document.getElementById('autoPilotBadge');
      if (badge && pilotRes) {
        badge.textContent = `${pilotRes.status} (${pilotRes.active_routines}/${pilotRes.total_routines} 루틴 활성)`;
      }

      // 2. 4대 루틴 카드 렌더링
      renderAutonomousRoutines(cachedRoutines);

      // 3. 출처 목록 렌더링
      renderAutonomousSources(sourcesRes || []);

      // 4. 마음지기 8대 앵글 렌더링
      renderMaumAngles(anglesRes || []);

      // 5. Outbox 작업 렌더링
      await loadAutonomousOutbox();

    } catch (e) {
      console.error('자율 오퍼레이터 대시보드 로드 오류:', e);
    }
  }

  function renderAutonomousRoutines(routines) {
    const container = document.getElementById('autonomousRoutinesContainer');
    if (!container) return;

    if (!routines || routines.length === 0) {
      container.innerHTML = '<div style="color: var(--text-secondary); font-size: 0.85rem;">등록된 루틴이 없습니다.</div>';
      return;
    }

    container.innerHTML = routines.map(r => {
      const isEnabled = r.enabled;
      const schedCount = (r.schedules || []).length;
      const schedTimes = (r.schedules || []).map(s => s.local_time).join(', ') || '설정 없음';
      const sourceCount = (r.sources || []).length;

      return `
        <div class="card" style="padding: 16px; border: 1px solid ${isEnabled ? 'rgba(56,189,248,0.35)' : 'var(--border-color)'}; background: rgba(15,23,42,0.4); position: relative;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
            <div>
              <span class="badge ${isEnabled ? 'badge-success' : 'badge-subtle'}" style="font-size: 0.7rem; margin-bottom: 4px;">
                ${isEnabled ? '가동 중 (ON)' : '일시정지 (OFF)'}
              </span>
              <h4 style="margin: 0; font-size: 0.96rem; font-weight: 700; color: #fff;">${escapeHtml(r.name)}</h4>
              <div style="font-size: 0.75rem; color: #38bdf8; font-family: 'JetBrains Mono', monospace;">${escapeHtml(r.code)}</div>
            </div>
            <!-- 활성화 토글 -->
            <label class="switch" style="cursor: pointer;" title="루틴 활성화/비활성화">
              <input type="checkbox" ${isEnabled ? 'checked' : ''} onchange="toggleRoutineActive('${r.code}', this.checked)">
              <span class="slider round"></span>
            </label>
          </div>

          <div style="font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 12px; line-height: 1.4;">
            ${escapeHtml(r.description || '')}
          </div>

          <!-- 설정 옵션 행 -->
          <div style="background: rgba(0,0,0,0.25); border-radius: 6px; padding: 10px; font-size: 0.8rem; display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span style="color: var(--text-secondary);">발행 모드:</span>
              <select class="form-control" style="width: auto; font-size: 0.75rem; padding: 2px 6px;" onchange="changeRoutineMode('${r.code}', this.value)">
                <option value="AUTO" ${r.mode === 'AUTO' ? 'selected' : ''}>⚡ 완전 자동 (AUTO)</option>
                <option value="REVIEW" ${r.mode === 'REVIEW' ? 'selected' : ''}>🔍 초안 검토 후 발행 (REVIEW)</option>
                <option value="DRY_RUN" ${r.mode === 'DRY_RUN' ? 'selected' : ''}>🧪 모의 실행 (DRY_RUN)</option>
              </select>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span style="color: var(--text-secondary);">스케줄 (${schedCount}회):</span>
              <span style="color: #f1f5f9; font-weight: 600;">${escapeHtml(schedTimes)}</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span style="color: var(--text-secondary);">연결 출처:</span>
              <span style="color: #94a3b8;">${sourceCount}개 출처</span>
            </div>
          </div>

          <!-- 조작 액션 버튼 -->
          <div style="display: flex; gap: 6px;">
            <button class="btn btn-xs btn-outline" style="flex: 1;" onclick="onScheduleEditClick('${r.code}')">
              <i class="fa-solid fa-calendar-days"></i> 스케줄 설정
            </button>
            <button class="btn btn-xs btn-primary" style="flex: 1; background: #0284c7; border-color: #0284c7;" onclick="triggerRoutineNow('${r.code}')">
              <i class="fa-solid fa-play"></i> 지금 1회 실행
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  // 글로벌 바인딩 (HTML 인라인 이벤트용)
  window.toggleRoutineActive = async (code, enabled) => {
    try {
      const resp = await fetch(`/api/routines/${code}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled })
      });
      if (!resp.ok) throw new Error('상태 변경 실패');
      showAlert(`${code} 루틴이 ${enabled ? '활성화' : '비활성화'}되었습니다.`, 'info');
      loadAutonomousDashboard();
    } catch (e) {
      showAlert('변경 실패: ' + e.message, 'error');
    }
  };

  window.changeRoutineMode = async (code, mode) => {
    try {
      const resp = await fetch(`/api/routines/${code}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode })
      });
      if (!resp.ok) throw new Error('모드 변경 실패');
      showAlert(`${code} 루틴 발행 모드가 [${mode}]로 변경되었습니다.`, 'success');
      loadAutonomousDashboard();
    } catch (e) {
      showAlert('변경 실패: ' + e.message, 'error');
    }
  };

  window.onScheduleEditClick = (code) => {
    const routine = cachedRoutines.find(r => r.code === code);
    if (routine) openScheduleModal(routine);
  };

  window.triggerRoutineNow = async (code) => {
    showAlert(`${code} 루틴 파이프라인 수집 및 생성을 시작합니다...`, 'info');
    try {
      const resp = await fetch(`/api/routines/${code}/run?limit=1`, { method: 'POST' });
      if (!resp.ok) throw new Error('실행 실패');
      const data = await resp.json();
      showAlert(`✅ ${code} 루틴 실행 완료! (${data.executed_items_count}건 생성됨)`, 'success');
      loadAutonomousDashboard();
    } catch (e) {
      showAlert('실행 오류: ' + e.message, 'error');
    }
  };

  function renderAutonomousSources(sources) {
    const container = document.getElementById('sourcesListContainer');
    if (!container) return;

    if (!sources || sources.length === 0) {
      container.innerHTML = '<div style="color: var(--text-secondary); font-size: 0.8rem;">등록된 출처가 없습니다.</div>';
      return;
    }

    container.innerHTML = sources.map(s => {
      return `
        <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.25); padding: 8px 10px; border-radius: 6px; font-size: 0.78rem;">
          <div style="flex: 1; min-width: 0; margin-right: 8px;">
            <div style="display: flex; align-items: center; gap: 6px;">
              <span class="badge badge-subtle" style="font-size: 0.68rem;">${s.kind}</span>
              <strong style="color: #f1f5f9; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(s.name)}</strong>
            </div>
            <div style="color: var(--text-secondary); font-size: 0.72rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              ${escapeHtml(s.url)}
            </div>
          </div>
          <div style="display: flex; gap: 6px; align-items: center;">
            <button class="btn btn-xs btn-outline" style="color: #f87171; border-color: rgba(248,113,113,0.3);" onclick="deleteAutonomousSource(${s.id})" title="출처 삭제">
              <i class="fa-solid fa-trash"></i>
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  window.deleteAutonomousSource = async (sourceId) => {
    if (!confirm('이 출처를 삭제하시겠습니까?')) return;
    try {
      const resp = await fetch(`/api/sources/${sourceId}`, { method: 'DELETE' });
      if (!resp.ok) throw new Error('삭제 실패');
      showAlert('출처가 성공적으로 삭제되었습니다.', 'info');
      loadAutonomousDashboard();
    } catch (e) {
      showAlert('삭제 실패: ' + e.message, 'error');
    }
  };

  function renderMaumAngles(angles) {
    const container = document.getElementById('maumAnglesListContainer');
    if (!container) return;

    if (!angles || angles.length === 0) {
      container.innerHTML = '<div style="color: var(--text-secondary); font-size: 0.8rem;">등록된 앵글이 없습니다.</div>';
      return;
    }

    container.innerHTML = angles.map(a => {
      const lastUsed = a.last_used_at ? new Date(a.last_used_at * 1000).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '미사용';
      return `
        <div style="background: rgba(0,0,0,0.25); padding: 8px 10px; border-radius: 6px; font-size: 0.78rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
            <strong style="color: #f472b6;">[#${a.angle_index}] ${escapeHtml(a.title)}</strong>
            <span style="color: var(--text-secondary); font-size: 0.7rem;">최근 순환: ${lastUsed}</span>
          </div>
          <div style="color: var(--text-secondary); font-size: 0.72rem; line-height: 1.3;">
            ${escapeHtml(a.hook_template)}
          </div>
        </div>
      `;
    }).join('');
  }

  async function loadAutonomousOutbox() {
    const container = document.getElementById('outboxJobsContainer');
    const filter = document.getElementById('autoOutboxStatusFilter');
    if (!container) return;

    const statusParam = filter && filter.value ? `?status=${filter.value}` : '';
    try {
      const resp = await fetch(`/api/outbox/jobs${statusParam}`);
      const jobs = await resp.json();

      if (!jobs || jobs.length === 0) {
        container.innerHTML = '<div style="color: var(--text-secondary); font-size: 0.85rem; padding: 20px 0; text-align: center;">대기 중인 Outbox 작업이 없습니다.</div>';
        return;
      }

      container.innerHTML = jobs.map(j => {
        const steps = j.steps || [];
        const parentStep = steps.find(s => s.step_type === 'PARENT') || {};
        const replyStep = steps.find(s => s.step_type === 'FIRST_REPLY') || {};
        const isSucceeded = j.status === 'SUCCEEDED';
        const isFailed = j.status === 'FAILED';

        return `
          <div style="background: rgba(0,0,0,0.3); border: 1px solid ${isSucceeded ? 'rgba(16,185,129,0.3)' : (isFailed ? 'rgba(239,68,68,0.3)' : 'var(--border-color)')}; border-radius: 8px; padding: 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; gap: 8px;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span class="badge ${isSucceeded ? 'badge-success' : (isFailed ? 'badge-error' : 'badge-subtle')}">
                  ${j.status}
                </span>
                <strong style="color: #fff; font-size: 0.88rem;">${escapeHtml(j.topic_key)}</strong>
                <span style="font-size: 0.75rem; color: #94a3b8;">(플랫폼: ${(j.platforms || []).join(', ')})</span>
              </div>
              <div style="display: flex; gap: 6px;">
                ${!isSucceeded ? `
                  <button class="btn btn-xs btn-outline" style="border-color: #10b981; color: #10b981;" onclick="approveOutboxJob(${j.id}, false)">
                    <i class="fa-solid fa-paper-plane"></i> 승인 및 즉시 발행
                  </button>
                  <button class="btn btn-xs btn-outline" style="border-color: #38bdf8; color: #38bdf8;" onclick="approveOutboxJob(${j.id}, true)">
                    <i class="fa-solid fa-flask"></i> 모의 발행 (Dry-run)
                  </button>
                ` : '<span style="color: #34d399; font-size: 0.8rem;"><i class="fa-solid fa-circle-check"></i> 발행 완료</span>'}
              </div>
            </div>

            <!-- 2-Step 체인 카드 내용 -->
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 0.8rem;">
              <!-- Step 1: 본문 (링크 없음) -->
              <div style="background: rgba(15,23,42,0.6); padding: 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.06);">
                <div style="font-weight: 600; color: #38bdf8; margin-bottom: 4px;">
                  <i class="fa-solid fa-paragraph"></i> Step 1: 본문 (Zero-Penalty, 링크 0개)
                </div>
                <div style="color: #e2e8f0; white-space: pre-wrap; font-size: 0.78rem; line-height: 1.4;">${escapeHtml(parentStep.content || '')}</div>
                ${parentStep.remote_id ? `<div style="font-size: 0.7rem; color: #94a3b8; margin-top: 6px;">ID: ${escapeHtml(parentStep.remote_id)}</div>` : ''}
              </div>

              <!-- Step 2: 첫 답글 (원문 링크 체인) -->
              <div style="background: rgba(15,23,42,0.6); padding: 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.06);">
                <div style="font-weight: 600; color: #34d399; margin-bottom: 4px;">
                  <i class="fa-solid fa-reply"></i> Step 2: 첫 번째 셀프 답글 (원문/서비스 링크)
                </div>
                <div style="color: #e2e8f0; white-space: pre-wrap; font-size: 0.78rem; line-height: 1.4;">${escapeHtml(replyStep.content || '')}</div>
                ${replyStep.remote_id ? `<div style="font-size: 0.7rem; color: #94a3b8; margin-top: 6px;">ID: ${escapeHtml(replyStep.remote_id)}</div>` : ''}
              </div>
            </div>
          </div>
        `;
      }).join('');
    } catch (e) {
      console.error('Outbox 로드 오류:', e);
    }
  }

  window.approveOutboxJob = async (jobId, dryRun = false) => {
    showAlert(dryRun ? '모의 발행을 실행합니다...' : '소셜 플랫폼에 실제 발행을 진행합니다...', 'info');
    try {
      const resp = await fetch(`/api/outbox/jobs/${jobId}/approve?dry_run=${dryRun}`, { method: 'POST' });
      if (!resp.ok) throw new Error('발행 실패');
      const data = await resp.json();
      showAlert(`작업(${jobId})이 ${dryRun ? '모의' : '실제'} 발행되었습니다! (상태: ${data.result.status})`, 'success');
      loadAutonomousDashboard();
    } catch (e) {
      showAlert('발행 오류: ' + e.message, 'error');
    }
  };

  // 초기 데이터 로드
  loadHistory();
  loadTrends();
  loadEnvSettings();
  loadThreadsStatus();
  loadXEnvStatus();
  loadCapcutStatus();
  loadLunaBgmOptions();
  loadYoutubePlaylists();

  // X OAuth 콜백 후 리다이렉트 감지
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get('x_connected') === '1') {
    showAlert('🎉 X (Twitter) 계정이 OAuth 2.0 PKCE로 성공적으로 연결되었습니다!', 'success');
    window.history.replaceState({}, document.title, window.location.pathname);
  }
});



