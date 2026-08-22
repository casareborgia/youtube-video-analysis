document.addEventListener('DOMContentLoaded', () => {
  // DOM 요소
  const analyzeForm = document.getElementById('analyzeForm');
  const videoUrlInput = document.getElementById('videoUrl');
  const chkSubtitles = document.getElementById('chkSubtitles');
  const chkComments = document.getElementById('chkComments');
  const chkAutoAiReport = document.getElementById('chkAutoAiReport');
  const commentLimit = document.getElementById('commentLimit');
  const playlistLimit = document.getElementById('playlistLimit');
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

  let historyData = [];

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
      ? `<i class="fa-solid fa-triangle-exclamation"></i> <span>${message}</span>`
      : `<i class="fa-solid fa-circle-check"></i> <span>${message}</span>`;
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
          auto_generate_ai_report: chkAutoAiReport.checked,
          max_playlist_items: parseInt(playlistLimit.value, 10)
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
      
      const tagHtml = (item.tags || []).slice(0, 4).map(t => `<span class="tag-chip">#${t}</span>`).join('');
      const commentsCount = item.comments_count_extracted || (item.comments ? item.comments.length : 0);

      card.innerHTML = `
        <div class="card-thumbnail-wrap">
          <img src="${item.thumbnail || 'https://via.placeholder.com/320x180?text=No+Thumbnail'}" alt="썸네일" loading="lazy">
          <span class="follower-pill"><i class="fa-solid fa-users"></i> 구독자 ${formatFollowers(item.channel_follower_count)}</span>
          <span class="duration-pill"><i class="fa-regular fa-clock"></i> ${item.duration_string || item.duration_formatted}</span>
        </div>
        <div class="card-content">
          <a href="javascript:void(0)" class="card-title btn-open-detail" data-id="${item.id}" title="${item.title}">${item.title}</a>
          <div class="card-channel">
            <i class="fa-regular fa-user"></i>
            <span>${item.channel}</span>
            <span style="margin-left: auto; font-size: 11px; color: var(--text-muted);">${item.upload_date}</span>
          </div>

          <div class="stats-bar">
            <div class="stat-item">
              <span class="stat-label"><i class="fa-regular fa-eye"></i> 조회수</span>
              <span class="stat-value">${formatNumber(item.view_count)}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label"><i class="fa-regular fa-thumbs-up"></i> 좋아요</span>
              <span class="stat-value">${formatNumber(item.like_count)}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label"><i class="fa-regular fa-comments"></i> 총댓글</span>
              <span class="stat-value">${formatNumber(item.comment_count)}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label"><i class="fa-solid fa-list-ol"></i> 챕터</span>
              <span class="stat-value">${item.chapters ? item.chapters.length : 0}개</span>
            </div>
          </div>

          ${tagHtml ? `<div class="tag-cloud">${tagHtml}</div>` : ''}

          <div class="card-actions">
            <button class="btn btn-sm btn-primary btn-open-detail" data-id="${item.id}" data-tab="tabOverview" style="flex:1;">
              <i class="fa-solid fa-chart-pie"></i> 메타데이터 확인
            </button>
            <button class="btn btn-sm btn-outline btn-open-detail" data-id="${item.id}" data-tab="tabComments" style="padding: 6px 10px;" title="댓글 여론">
              <i class="fa-solid fa-comments"></i> ${commentsCount}
            </button>
            <button class="btn btn-sm btn-ai btn-open-detail" data-id="${item.id}" data-tab="tabAiReport" style="padding: 6px 10px;" title="AI 리포트">
              <i class="fa-solid fa-robot"></i>
            </button>
            <a href="${item.url}" target="_blank" class="btn btn-sm btn-outline" style="padding: 6px 10px;" title="유튜브로 열기">
              <i class="fa-solid fa-arrow-up-right-from-square"></i>
            </a>
          </div>
        </div>
      `;

      recentResultsContainer.appendChild(card);
    });

    recentResultSection.style.display = 'block';
    recentResultSection.scrollIntoView({ behavior: 'smooth' });
  }

  // 5. 히스토리 로드
  async function loadHistory() {
    try {
      const res = await fetch('/api/history');
      const data = await res.json();
      if (data.status === 'success') {
        historyData = data.data;
        renderHistoryTable(historyData);
        if (typeof updatePromptVideoSelect === 'function') {
          updatePromptVideoSelect();
        }
      }
    } catch (e) {
      console.error('히스토리 로드 실패:', e);
    }
  }

  function renderHistoryTable(items) {
    totalHistoryCount.textContent = `${items.length}개 영상`;

    if (items.length === 0) {
      historyTableBody.innerHTML = `
        <tr>
          <td colspan="9" class="text-center py-4 text-muted">
            수집된 데이터가 없습니다. 상단에서 URL을 입력해 분석을 시작하세요.
          </td>
        </tr>
      `;
      return;
    }

    historyTableBody.innerHTML = items.map(item => `
      <tr class="history-row" data-id="${item.id}" style="cursor: pointer;">
        <td>
          <img src="${item.thumbnail || 'https://via.placeholder.com/60x34'}" class="table-thumb" alt="썸네일">
        </td>
        <td>
          <div class="table-title-cell">
            <span class="table-title font-weight-bold">${escapeHtml(item.title)}</span>
            <span class="table-channel">${escapeHtml(item.channel)} (${formatFollowers(item.channel_follower_count)})</span>
          </div>
        </td>
        <td><code>${item.duration_string || item.duration_formatted}</code></td>
        <td><strong>${formatNumber(item.view_count)}</strong></td>
        <td>${formatNumber(item.like_count)}</td>
        <td>${formatNumber(item.comment_count)} <span style="font-size:11px; color:#10b981;">(${item.comments_extracted || 0})</span></td>
        <td>
          ${item.has_ai_report 
            ? '<span class="badge badge-ai"><i class="fa-solid fa-check"></i> 생성됨</span>' 
            : '<span class="badge" style="opacity:0.6;">미생성</span>'}
        </td>
        <td>${item.upload_date || '-'}</td>
        <td>
          <div class="table-actions">
            <button class="btn-table-action btn-open-detail" data-id="${item.id}" data-tab="tabOverview" title="메타데이터 확인">
              <i class="fa-solid fa-chart-pie" style="color:var(--primary-color)"></i> 상세
            </button>
            <button class="btn-table-action btn-open-prompt-studio" data-id="${item.id}" title="AI 프롬프트 생성기 열기" style="color:#60a5fa; border-color:rgba(96,165,250,0.4);">
              <i class="fa-solid fa-wand-magic-sparkles"></i> 프롬프트
            </button>
            <button class="btn-table-action delete btn-delete" data-id="${item.id}" title="삭제">
              <i class="fa-solid fa-trash-can"></i>
            </button>
          </div>
        </td>
      </tr>
    `).join('');
  }

  historySearch.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    const filtered = historyData.filter(item => 
      (item.title && item.title.toLowerCase().includes(q)) ||
      (item.channel && item.channel.toLowerCase().includes(q))
    );
    renderHistoryTable(filtered);
  });

  btnRefreshHistory.addEventListener('click', loadHistory);

  // 6. 모달 탭 전환
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      switchTab(btn.dataset.tab);
    });
  });

  function switchTab(tabId) {
    tabBtns.forEach(b => {
      b.classList.toggle('active', b.dataset.tab === tabId);
    });
    tabPanes.forEach(p => {
      p.classList.toggle('active', p.id === tabId);
    });
  }

  // 7. 클릭 이벤트 핸들링
  document.addEventListener('click', async (e) => {
    // 1) 상세/메타데이터/AI 버튼 클릭 시
    const detailBtn = e.target.closest('.btn-open-detail');
    if (detailBtn) {
      e.stopPropagation();
      const videoId = detailBtn.dataset.id;
      const targetTab = detailBtn.dataset.tab || 'tabOverview';
      openDetailModal(videoId, targetTab);
      return;
    }

    // 2) 삭제 버튼 클릭 시
    const deleteBtn = e.target.closest('.btn-delete');
    if (deleteBtn) {
      e.stopPropagation();
      const videoId = deleteBtn.dataset.id;
      if (confirm('해당 영상의 모든 메타데이터, 댓글, AI 리포트를 삭제하시겠습니까?')) {
        await deleteVideo(videoId);
      }
      return;
    }

    // 3) 테이블 행(Row) 클릭 시
    const historyRow = e.target.closest('.history-row');
    if (historyRow && !e.target.closest('.table-actions')) {
      const videoId = historyRow.dataset.id;
      openDetailModal(videoId, 'tabOverview');
      return;
    }
  });

  // 상세 모달 열기 및 데이터 렌더링
  async function openDetailModal(videoId, defaultTab = 'tabOverview') {
    try {
      const res = await fetch(`/api/metadata/${videoId}`);
      const result = await res.json();
      if (!res.ok) throw new Error(result.detail || '상세 정보 조회 실패');

      const data = result.data;

      modalTitle.innerHTML = `<i class="fa-brands fa-youtube" style="color:var(--accent-color);"></i> ${escapeHtml(data.title)}`;
      modalChapterCount.textContent = (data.chapters || []).length;
      modalCommentCount.textContent = (data.comments || []).length;

      // 탭 전환 (기본: tabOverview)
      switchTab(defaultTab);

      // 1) 탭 1: 기본 메타데이터 요약 렌더링
      renderOverviewTab(data);

      // 2) 탭 2: 댓글 여론 렌더링
      renderCommentsTab(data);

      // 3) 탭 3: 자막 전문 렌더링
      renderTranscriptTab(data);

      // 4) 탭 4: AI 분석 리포트 렌더링
      renderAiReportTab(data);

      // 5) 탭 5: 챕터 목록 렌더링
      renderChaptersTab(data);

      // 6) 탭 6: 원본 JSON 탭
      document.getElementById('tabRawJson').innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span class="text-muted" style="font-size:12px;">파일: <code>data/${data.id}_metadata.json</code> & <code>data/${data.id}_c.info.json</code></span>
          <button class="btn btn-sm btn-outline" id="btnCopyJson"><i class="fa-regular fa-copy"></i> JSON 복사</button>
        </div>
        <pre class="json-viewer">${JSON.stringify(data, null, 2)}</pre>
      `;

      document.getElementById('btnCopyJson').addEventListener('click', () => {
        navigator.clipboard.writeText(JSON.stringify(data, null, 2));
        alert('JSON 메타데이터가 클립보드에 복사되었습니다.');
      });

      detailModal.style.display = 'flex';
    } catch (e) {
      alert(e.message);
    }
  }

  // [탭 1: 기본 메타데이터 요약] 상세 렌더링 함수
  function renderOverviewTab(data) {
    const resTags = (data.resolutions || []).map(r => `<span class="badge badge-accent" style="font-size:11px;">${r}</span>`).join(' ');
    const tagsHtml = (data.tags || []).map(t => `<span class="tag-chip">#${escapeHtml(t)}</span>`).join(' ');
    const categoriesHtml = (data.categories || []).map(c => `<span class="badge">${escapeHtml(c)}</span>`).join(' ');

    const manualSubs = (data.subtitles && data.subtitles.manual_languages) || [];
    const autoSubs = (data.subtitles && data.subtitles.automatic_languages) || [];

    const engagementRate = data.view_count > 0 ? ((data.like_count / data.view_count) * 100).toFixed(2) : '0';

    document.getElementById('tabOverview').innerHTML = `
      <!-- 상단 주요 지표 카드 그리드 -->
      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px;">
        <div style="background:var(--bg-input); padding:12px; border-radius:8px; border:1px solid var(--border-color); text-align:center;">
          <div style="font-size:11px; color:var(--text-muted);"><i class="fa-regular fa-eye"></i> 총 조회수</div>
          <div style="font-size:16px; font-weight:800; color:var(--text-primary); margin-top:4px;">${formatNumber(data.view_count)}회</div>
        </div>
        <div style="background:var(--bg-input); padding:12px; border-radius:8px; border:1px solid var(--border-color); text-align:center;">
          <div style="font-size:11px; color:var(--text-muted);"><i class="fa-regular fa-thumbs-up"></i> 좋아요 수</div>
          <div style="font-size:16px; font-weight:800; color:#10b981; margin-top:4px;">${formatNumber(data.like_count)}개</div>
        </div>
        <div style="background:var(--bg-input); padding:12px; border-radius:8px; border:1px solid var(--border-color); text-align:center;">
          <div style="font-size:11px; color:var(--text-muted);"><i class="fa-regular fa-comments"></i> 총 댓글 수</div>
          <div style="font-size:16px; font-weight:800; color:#3b82f6; margin-top:4px;">${formatNumber(data.comment_count)}개</div>
        </div>
        <div style="background:var(--bg-input); padding:12px; border-radius:8px; border:1px solid var(--border-color); text-align:center;">
          <div style="font-size:11px; color:var(--text-muted);"><i class="fa-solid fa-fire"></i> 반응 참여율</div>
          <div style="font-size:16px; font-weight:800; color:#f59e0b; margin-top:4px;">${engagementRate}%</div>
        </div>
        <div style="background:var(--bg-input); padding:12px; border-radius:8px; border:1px solid var(--border-color); text-align:center;">
          <div style="font-size:11px; color:var(--text-muted);"><i class="fa-regular fa-clock"></i> 재생 시간</div>
          <div style="font-size:16px; font-weight:800; color:var(--text-primary); margin-top:4px;">${data.duration_string || data.duration_formatted}</div>
        </div>
      </div>

      <!-- 상세 메타데이터 정보 박스 -->
      <div style="display:flex; gap:18px; align-items:flex-start; flex-wrap:wrap; background:var(--bg-card); padding:16px; border-radius:10px; border:1px solid var(--border-color);">
        <img src="${data.thumbnail}" style="width:240px; border-radius:8px; object-fit:cover;" alt="썸네일">
        <div style="flex:1; display:flex; flex-direction:column; gap:10px; min-width:280px;">
          <div>
            <span style="font-size:11px; color:var(--text-muted);">채널명</span>
            <div style="font-size:15px; font-weight:700; margin-top:2px;">
              <a href="${data.channel_url}" target="_blank" style="color:var(--primary-color); text-decoration:none;">
                ${escapeHtml(data.channel)} <i class="fa-solid fa-arrow-up-right-from-square" style="font-size:12px;"></i>
              </a>
              <span class="badge" style="margin-left:8px; background:rgba(245, 158, 11, 0.15); color:#f59e0b;">
                <i class="fa-solid fa-users"></i> 구독자 ${formatFollowers(data.channel_follower_count)}
              </span>
            </div>
          </div>

          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
            <div>
              <span style="font-size:11px; color:var(--text-muted);">업로드 일자</span>
              <div style="font-size:13px; font-weight:600;">${data.upload_date || '-'}</div>
            </div>
            <div>
              <span style="font-size:11px; color:var(--text-muted);">분석 일시</span>
              <div style="font-size:13px; font-weight:600;">${data.analyzed_at || '-'}</div>
            </div>
          </div>

          <div>
            <span style="font-size:11px; color:var(--text-muted);">카테고리 & 태그</span>
            <div style="margin-top:4px; display:flex; flex-wrap:wrap; gap:4px;">
              ${categoriesHtml || '<span class="text-muted" style="font-size:12px;">없음</span>'}
              ${tagsHtml}
            </div>
          </div>

          <div>
            <span style="font-size:11px; color:var(--text-muted);">자막 정보</span>
            <div style="font-size:12px; margin-top:2px;">
              수동 자막: ${manualSubs.length > 0 ? manualSubs.map(s => `<span class="badge badge-accent">${s}</span>`).join(' ') : '<span class="text-muted">없음</span>'}
              <span style="margin-left:8px;">자동 생성 자막: <strong>${autoSubs.length}개 언어</strong></span>
            </div>
          </div>

          <div>
            <span style="font-size:11px; color:var(--text-muted);">가용 해상도</span>
            <div style="margin-top:4px; display:flex; flex-wrap:wrap; gap:4px;">
              ${resTags || '정보 없음'}
            </div>
          </div>
        </div>
      </div>

      <!-- 영상 설명란 -->
      <div>
        <h4 style="font-size:14px; margin-bottom:6px;"><i class="fa-solid fa-align-left"></i> 영상 설명 전문 (Description)</h4>
        <textarea style="width:100%; height:130px; background:var(--bg-input); border:1px solid var(--border-color); color:var(--text-secondary); border-radius:6px; padding:10px; font-size:12px; resize:none;" readonly>${escapeHtml(data.description || '설명 없음')}</textarea>
      </div>
    `;
  }

  // [탭 2: 댓글 여론 분석]
  function renderCommentsTab(data) {
    const comments = data.comments || [];
    const tab = document.getElementById('tabComments');

    if (comments.length === 0) {
      tab.innerHTML = `
        <div class="text-center py-4 text-muted">
          <i class="fa-regular fa-comment-dots" style="font-size:24px; margin-bottom:8px; display:block;"></i>
          수집된 댓글이 없습니다.
        </div>
      `;
      return;
    }

    tab.innerHTML = `
      <div class="comments-header-bar">
        <span><strong>수집된 댓글: ${comments.length}개</strong> (좋아요 순 정렬됨)</span>
        <button class="btn btn-sm btn-outline" id="btnDownloadCommentsCsv">
          <i class="fa-solid fa-file-arrow-down"></i> 댓글 CSV 다운로드
        </button>
      </div>
      <div class="comments-list">
        ${comments.map((c, idx) => `
          <div class="comment-card">
            <div class="comment-top">
              <span class="badge" style="background:#3b82f6; color:#fff; font-size:11px;">#${idx + 1}</span>
              <span class="comment-author-name">${escapeHtml(c.author)}</span>
              <span class="comment-like-badge"><i class="fa-regular fa-thumbs-up"></i> ${formatNumber(c.like_count)}</span>
              <span class="comment-date">${c.date}</span>
            </div>
            <div class="comment-text">${escapeHtml(c.text)}</div>
          </div>
        `).join('')}
      </div>
    `;

    document.getElementById('btnDownloadCommentsCsv').addEventListener('click', () => {
      window.open(`/api/comments/${data.id}/csv`, '_blank');
    });
  }

  // [탭 3: 자막 전문 (Transcript)]
  function renderTranscriptTab(data) {
    const tab = document.getElementById('tabTranscript');
    const transcript = data.transcript || '(자막 없음 또는 아직 추출되지 않음)';

    tab.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span><i class="fa-solid fa-closed-captioning"></i> <strong>한국어 자막 정제 텍스트</strong> (중복 타임라인 제거됨)</span>
        <button class="btn btn-sm btn-outline" id="btnCopyTranscript"><i class="fa-regular fa-copy"></i> 자막 복사</button>
      </div>
      <textarea style="width:100%; height:380px; background:var(--bg-input); border:1px solid var(--border-color); color:var(--text-primary); border-radius:8px; padding:14px; font-size:13px; line-height:1.7; resize:none;" readonly>${escapeHtml(transcript)}</textarea>
    `;

    document.getElementById('btnCopyTranscript').addEventListener('click', () => {
      navigator.clipboard.writeText(transcript);
      alert('자막 전문이 클립보드에 복사되었습니다.');
    });
  }

  // [탭 4: AI 분석 리포트]
  function renderAiReportTab(data) {
    const aiTab = document.getElementById('tabAiReport');

    if (data.ai_report && data.has_ai_report) {
      aiTab.innerHTML = `
        <div class="ai-report-header">
          <div class="ai-report-model-info">
            <i class="fa-solid fa-brain"></i>
            <span>LM Studio 로컬 AI 리포트 (google/gemma-4-e4b)</span>
          </div>
          <div style="display:flex; gap:8px;">
            <button class="btn btn-sm btn-outline" id="btnCopyAiReport"><i class="fa-regular fa-copy"></i> 복사</button>
            <a href="/api/ai-report/${data.id}/download" class="btn btn-sm btn-outline" target="_blank"><i class="fa-solid fa-file-arrow-down"></i> _리포트.txt 다운로드</a>
            <button class="btn btn-sm btn-ai" id="btnRegenerateAiReport"><i class="fa-solid fa-rotate"></i> AI 재분석</button>
          </div>
        </div>
        <div class="ai-report-content">${escapeHtml(data.ai_report)}</div>
      `;

      document.getElementById('btnCopyAiReport').addEventListener('click', () => {
        navigator.clipboard.writeText(data.ai_report);
        alert('AI 리포트 전문이 클립보드에 복사되었습니다.');
      });

      document.getElementById('btnRegenerateAiReport').addEventListener('click', () => {
        triggerAiAnalysis(data.id);
      });
    } else {
      aiTab.innerHTML = `
        <div class="ai-empty-state">
          <div class="ai-empty-icon"><i class="fa-solid fa-wand-magic-sparkles"></i></div>
          <h4 style="font-size:16px; font-weight:700;">아직 AI 종합 분석 리포트가 생성되지 않았습니다</h4>
          <p style="font-size:13px; color:var(--text-secondary); max-width:540px;">
            LM Studio(Gemma 4)와 연동하여 <strong>제목·훅 구조, 전개 방식, 핵심 메시지, 댓글 여론 특징, 내 채널 적용점</strong> 5가지를 0원으로 자동 분석합니다.
          </p>
          <button class="btn btn-ai" id="btnGenerateAiReport" style="padding:10px 24px; font-size:15px; margin-top:8px;">
            <span class="btn-text"><i class="fa-solid fa-robot"></i> 0원 로컬 AI 분석 리포트 생성</span>
            <span class="spinner" style="display:none;"><i class="fa-solid fa-circle-notch fa-spin"></i> Gemma 4 AI 분석 중...</span>
          </button>
        </div>
      `;

      document.getElementById('btnGenerateAiReport').addEventListener('click', () => {
        triggerAiAnalysis(data.id);
      });
    }
  }

  async function triggerAiAnalysis(videoId) {
    const aiTab = document.getElementById('tabAiReport');
    aiTab.innerHTML = `
      <div class="ai-empty-state" style="padding:60px 20px;">
        <i class="fa-solid fa-circle-notch fa-spin text-ai" style="font-size:42px; margin-bottom:12px;"></i>
        <h4 style="font-size:16px; font-weight:700;">LM Studio (Gemma 4) AI가 영상을 분석 중입니다...</h4>
        <p style="font-size:13px; color:var(--text-secondary);">
          메타데이터, 한국어 자막(SRT), 상위 댓글 여론을 조합하여 5대 핵심 분석 리포트를 작성하고 있습니다. (약 5~15초 소요)
        </p>
      </div>
    `;

    try {
      const res = await fetch(`/api/ai-analyze/${videoId}`, { method: 'POST' });
      const result = await res.json();
      if (!res.ok) throw new Error(result.detail || 'AI 분석 실패');

      openDetailModal(videoId, 'tabAiReport');
      loadHistory();
      showAlert('AI 심층 분석 리포트 생성이 완료되었습니다!', 'success');
    } catch (err) {
      alert('AI 분석 실패: ' + err.message);
      openDetailModal(videoId, 'tabAiReport');
    }
  }

  function renderChaptersTab(data) {
    const chapters = data.chapters || [];
    const tab = document.getElementById('tabChapters');

    if (chapters.length === 0) {
      tab.innerHTML = `
        <div class="text-center py-4 text-muted">
          <i class="fa-solid fa-list-ul" style="font-size:24px; margin-bottom:8px; display:block;"></i>
          등록된 챕터 정보가 없습니다.
        </div>
      `;
      return;
    }

    tab.innerHTML = `
      <div class="chapter-list">
        ${chapters.map(c => `
          <div class="chapter-item">
            <span class="chapter-time">${c.start_time_formatted} ~ ${c.end_time_formatted}</span>
            <span class="chapter-title">${escapeHtml(c.title)}</span>
          </div>
        `).join('')}
      </div>
    `;
  }

  function escapeHtml(text) {
    if (!text) return '';
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // 모달 닫기
  btnCloseModal.addEventListener('click', () => {
    detailModal.style.display = 'none';
  });

  detailModal.addEventListener('click', (e) => {
    if (e.target === detailModal) detailModal.style.display = 'none';
  });

  // 8. 삭제
  async function deleteVideo(videoId) {
    try {
      const res = await fetch(`/api/metadata/${videoId}`, { method: 'DELETE' });
      if (res.ok) {
        showAlert('관련 모든 데이터가 삭제되었습니다.', 'success');
        loadHistory();
      }
    } catch (e) {
      showAlert('삭제 중 오류 발생', 'error');
    }
  }

  // 9. Mac Finder 열기
  btnOpenFolder.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/open-folder', { method: 'POST' });
      const data = await res.json();
      if (res.ok) showAlert(data.message, 'success');
    } catch (e) {
      showAlert('폴더 열기 요청 실패', 'error');
    }
  });

  // 10. 전체 CSV 내보내기
  btnExportCsv.addEventListener('click', () => {
    window.open('/api/export/csv', '_blank');
  });

  // ==============================================================
  // 11. AI 프롬프트 스튜디오 (AutoFlow-Pro 연동) 로직
  // ==============================================================
  const navTabAnalysis = document.getElementById('navTabAnalysis');
  const navTabPromptStudio = document.getElementById('navTabPromptStudio');
  const viewAnalysis = document.getElementById('viewAnalysis');
  const viewPromptStudio = document.getElementById('viewPromptStudio');

  const promptVideoSelect = document.getElementById('promptVideoSelect');
  const promptTargetModel = document.getElementById('promptTargetModel');
  const promptSceneCount = document.getElementById('promptSceneCount');
  const promptAspectRatio = document.getElementById('promptAspectRatio');
  const promptCameraAngle = document.getElementById('promptCameraAngle');
  const promptLighting = document.getElementById('promptLighting');
  const promptStyle = document.getElementById('promptStyle');
  const promptCustomSubject = document.getElementById('promptCustomSubject');
  const btnGeneratePrompts = document.getElementById('btnGeneratePrompts');

  const studioVideoTitle = document.getElementById('studioVideoTitle');
  const studioSceneBadge = document.getElementById('studioSceneBadge');
  const studioScenesContainer = document.getElementById('studioScenesContainer');

  const btnCopyAllPrompts = document.getElementById('btnCopyAllPrompts');
  const btnExportAutoFlowTxt = document.getElementById('btnExportAutoFlowTxt');
  const btnExportCsvPrompts = document.getElementById('btnExportCsvPrompts');
  const btnExportJsonPrompts = document.getElementById('btnExportJsonPrompts');

  let currentGeneratedBatch = null;

  // 메인 네비게이션 탭 전환
  function switchMainView(viewName) {
    if (viewName === 'promptStudio') {
      navTabPromptStudio.classList.add('active');
      navTabAnalysis.classList.remove('active');
      viewPromptStudio.style.display = 'block';
      viewAnalysis.style.display = 'none';
      updatePromptVideoSelect();
    } else {
      navTabAnalysis.classList.add('active');
      navTabPromptStudio.classList.remove('active');
      viewAnalysis.style.display = 'block';
      viewPromptStudio.style.display = 'none';
    }
  }

  navTabAnalysis.addEventListener('click', () => switchMainView('analysis'));
  navTabPromptStudio.addEventListener('click', () => switchMainView('promptStudio'));

  // 프롬프트 스튜디오 영상 선택 셀렉트박스 갱신
  function updatePromptVideoSelect() {
    if (!promptVideoSelect) return;
    const prevVal = promptVideoSelect.value;
    promptVideoSelect.innerHTML = '<option value="">-- 분석된 영상 선택 --</option>';
    
    historyData.forEach(item => {
      const opt = document.createElement('option');
      opt.value = item.id;
      opt.textContent = `[${item.id}] ${item.title || '제목 없음'}`;
      if (item.id === prevVal) opt.selected = true;
      promptVideoSelect.appendChild(opt);
    });
  }

  // 외부에서 특정 영상으로 프롬프트 스튜디오 열기
  window.openPromptStudioForVideo = function(videoId) {
    switchMainView('promptStudio');
    if (promptVideoSelect) {
      promptVideoSelect.value = videoId;
      triggerPromptGeneration();
    }
  };

  // 프롬프트 생성 요청 함수
  async function triggerPromptGeneration() {
    const videoId = promptVideoSelect.value;
    if (!videoId) {
      alert('분석된 영상을 선택해주세요.');
      return;
    }

    btnGeneratePrompts.disabled = true;
    btnGeneratePrompts.querySelector('.btn-text').style.display = 'none';
    btnGeneratePrompts.querySelector('.spinner').style.display = 'inline-block';

    try {
      const res = await fetch('/api/prompt/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_id: videoId,
          model: promptTargetModel.value,
          scene_count: parseInt(promptSceneCount.value, 10),
          angle_key: promptCameraAngle.value,
          lighting_key: promptLighting.value,
          style_key: promptStyle.value,
          aspect_ratio: promptAspectRatio.value,
          custom_subject: promptCustomSubject.value.trim()
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '프롬프트 생성 실패');
      }

      currentGeneratedBatch = await res.json();
      renderStudioScenes(currentGeneratedBatch);
    } catch (err) {
      alert('프롬프트 생성 오류: ' + err.message);
    } finally {
      btnGeneratePrompts.disabled = false;
      btnGeneratePrompts.querySelector('.btn-text').style.display = 'inline-block';
      btnGeneratePrompts.querySelector('.spinner').style.display = 'none';
    }
  }

  btnGeneratePrompts.addEventListener('click', triggerPromptGeneration);

  // 씬 카드 렌더링
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

    studioVideoTitle.innerHTML = `<i class="fa-solid fa-clapperboard"></i> ${escapeHtml(batchData.title)}`;
    studioSceneBadge.textContent = `총 ${batchData.scenes.length}개 씬 분할 완료 (${batchData.model})`;

    studioScenesContainer.innerHTML = batchData.scenes.map((scene, idx) => `
      <div class="scene-card" data-index="${idx}">
        <div class="scene-card-header">
          <div class="scene-badge-group">
            <span class="scene-num-badge">Scene #${scene.scene_index}</span>
            <span class="scene-time-badge"><i class="fa-regular fa-clock"></i> ${scene.time_range}</span>
          </div>
          <div class="scene-tag-chips">
            ${(scene.keywords || []).map(kw => `<span class="tag-chip">#${escapeHtml(kw)}</span>`).join('')}
          </div>
        </div>

        <div class="scene-narration-box">
          <strong><i class="fa-solid fa-quote-left"></i> 자막/대본:</strong> ${escapeHtml(scene.narration)}
        </div>

        <div class="scene-prompt-editor-area">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <label><i class="fa-solid fa-sparkles"></i> AI 생성 프롬프트 (수정 가능):</label>
            <button class="btn btn-sm btn-outline btn-copy-single" data-index="${idx}" style="padding:2px 8px; font-size:11px;">
              <i class="fa-solid fa-copy"></i> 복사
            </button>
          </div>
          <textarea class="prompt-textarea" data-index="${idx}">${escapeHtml(scene.prompt)}</textarea>
        </div>

        <div class="scene-card-footer">
          <div class="scene-modifiers-info">
            <span><i class="fa-solid fa-camera"></i> ${scene.angle}</span>
            <span><i class="fa-solid fa-sun"></i> ${scene.lighting}</span>
            <span><i class="fa-solid fa-palette"></i> ${scene.style}</span>
            <span><i class="fa-solid fa-crop"></i> ${scene.aspect_ratio}</span>
          </div>
        </div>
      </div>
    `).join('');

    // 개별 프롬프트 수정 이벤트 바인딩
    const textareas = studioScenesContainer.querySelectorAll('.prompt-textarea');
    textareas.forEach(ta => {
      ta.addEventListener('input', (e) => {
        const index = parseInt(e.target.dataset.index, 10);
        if (currentGeneratedBatch && currentGeneratedBatch.scenes[index]) {
          currentGeneratedBatch.scenes[index].prompt = e.target.value;
        }
      });
    });

    // 개별 복사 버튼
    const copyBtns = studioScenesContainer.querySelectorAll('.btn-copy-single');
    copyBtns.forEach(btn => {
      btn.addEventListener('click', (e) => {
        const index = parseInt(btn.dataset.index, 10);
        const promptText = currentGeneratedBatch.scenes[index].prompt;
        navigator.clipboard.writeText(promptText).then(() => {
          const original = btn.innerHTML;
          btn.innerHTML = '<i class="fa-solid fa-check text-success"></i> 복사됨';
          setTimeout(() => btn.innerHTML = original, 1500);
        });
      });
    });
  }

  // 전체 프롬프트 복사
  btnCopyAllPrompts.addEventListener('click', () => {
    if (!currentGeneratedBatch || !currentGeneratedBatch.scenes) {
      alert('먼저 프롬프트를 생성해주세요.');
      return;
    }
    const allText = currentGeneratedBatch.scenes.map(s => s.prompt).join('\n\n');
    navigator.clipboard.writeText(allText).then(() => {
      const original = btnCopyAllPrompts.innerHTML;
      btnCopyAllPrompts.innerHTML = '<i class="fa-solid fa-check text-success"></i> 전체 복사됨!';
      setTimeout(() => btnCopyAllPrompts.innerHTML = original, 1500);
    });
  });

  // 내보내기 헬퍼 함수
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
          video_title: currentGeneratedBatch.title || 'prompt_batch'
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
  btnExportJsonPrompts.addEventListener('click', () => exportPromptBatch('json'));

  // 테이블 내 프롬프트 생성 바로가기 이벤트 연동
  document.addEventListener('click', (e) => {
    const promptBtn = e.target.closest('.btn-open-prompt-studio');
    if (promptBtn) {
      const videoId = promptBtn.dataset.id;
      window.openPromptStudioForVideo(videoId);
    }
  });

  // 초기 히스토리 로드
  loadHistory();
});

