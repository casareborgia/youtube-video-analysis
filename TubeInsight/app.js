// TubeInsight — 화면 로직 (① 분석 · ② 기획/나레이션 · ③ 제작/업로드)
'use strict';

const state = {
  status: null, analysis: null, plan: null, history: { analyses: [], plans: [] },
  producePlan: null, media: {}, render: null, youtube: null, env: null,
  fullAudio: null, llmPreference: 'auto', mode: 'analyze',
  marketing: { currentData: null, source: 'custom' },
  channel: { currentData: null, history: [] },
};
const FEATURES = { producer: true };  // ③ 제작·업로드 탭 활성화
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── 공용 유틸 ──────────────────────────────────────────────────────────

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* 빈 응답 */ }
  if (!res.ok || data.error) throw new Error(data.error || `서버 오류 (${res.status})`);
  return data;
}

// 백그라운드 작업 폴링: {status:'queued', job_id} 이면 완료까지 기다리고 결과를 돌려줌
async function runJob(resp, onProgress) {
  if (resp.status === 'success') return resp.data;
  if (resp.status !== 'queued') throw new Error(resp.error || '알 수 없는 응답');
  for (;;) {
    await sleep(900);
    const { job } = await api(`/api/jobs/${resp.job_id}`);
    if (onProgress) onProgress(job);
    if (job.status === 'done') return job.result;
    if (job.status === 'error') throw new Error(job.error || '작업 실패');
  }
}

function setProgress(prefix, job) {
  const box = $(`${prefix}ProgressBox`), fill = $(`${prefix}ProgressFill`), msg = $(`${prefix}ProgressMsg`);
  if (!box) return;
  box.style.display = 'block';
  fill.style.width = `${Math.max(2, job.progress || 0)}%`;
  msg.textContent = job.message || '';
  const steps = [...box.querySelectorAll('.step-item')];
  let currentIdx = steps.findIndex((s) => (s.dataset.steps || '').split(',').includes(job.step));
  if (job.status === 'done') currentIdx = steps.length;
  steps.forEach((s, i) => {
    s.classList.toggle('done', i < currentIdx);
    s.classList.toggle('active', i === currentIdx);
  });
}
function hideProgress(prefix) { const b = $(`${prefix}ProgressBox`); if (b) b.style.display = 'none'; }

function escapeHtml(str) {
  return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}
function md(text) {
  const html = window.marked ? window.marked.parse(text || '') : escapeHtml(text || '');
  return window.DOMPurify ? window.DOMPurify.sanitize(html, { ADD_ATTR: ['target'] }) : html;
}
function icons() { if (window.lucide) window.lucide.createIcons(); }

function showToast(msg, isError = false) {
  const t = $('toast'); $('toastMsg').textContent = msg;
  t.classList.toggle('error', isError);
  $('toastIcon').setAttribute('data-lucide', isError ? 'alert-circle' : 'check-circle'); icons();
  t.classList.add('show'); clearTimeout(showToast._t);
  showToast._t = setTimeout(() => t.classList.remove('show'), isError ? 5000 : 2800);
}
function copyText(text, okMsg = '복사했습니다.') {
  if (!text) { showToast('복사할 내용이 없습니다.', true); return; }
  navigator.clipboard.writeText(text).then(() => showToast(okMsg)).catch(() => showToast('복사 실패 — 브라우저 권한을 확인하세요.', true));
}
function downloadText(filename, content) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }));
  a.download = filename; document.body.appendChild(a); a.click(); a.remove();
}
function fmtNum(n) {
  if (n == null) return '—';
  if (n >= 1e8) return (n / 1e8).toFixed(1) + '억';
  if (n >= 1e4) return (n / 1e4).toFixed(1) + '만';
  return Number(n).toLocaleString();
}
function fmtDate(s) { return s && s.length === 8 ? `${s.slice(0, 4)}.${s.slice(4, 6)}.${s.slice(6, 8)}` : (s || ''); }
function fmtTs(ts) { if (!ts) return ''; const d = new Date(ts * 1000); return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; }
function setBusy(btn, busy, labelHtml) {
  if (!btn) return;
  btn.disabled = busy;
  if (busy) { btn.dataset.orig = btn.innerHTML; btn.innerHTML = `<i data-lucide="loader-2" class="spin w-4 h-4"></i><span>${labelHtml}</span>`; }
  else if (btn.dataset.orig) { btn.innerHTML = btn.dataset.orig; }
  icons();
}
function fileToDataUrl(file) {
  return new Promise((resolve, reject) => { const r = new FileReader(); r.onloadend = () => resolve(r.result); r.onerror = reject; r.readAsDataURL(file); });
}

// ── 초기화 ────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  icons();
  if (!FEATURES.producer) { $('btnModeProduce').style.display = 'none'; $('btnGoProduce').style.display = 'none'; }
  bindHeader(); bindAnalyzer(); bindGenerator(); bindVoiceModal(); bindProducer(); bindMarketing(); bindChannelStudio();
  await refreshStatus(); setInterval(refreshStatus, 15000);
  await Promise.all([loadHistory(), loadVoiceProfiles(), loadChannelHistory()]);
  const first = state.history.analyses.find((a) => a.id === 'ws1Clj0vOAM') || state.history.analyses[0];
  if (first) loadVideoData(first.id, first.id === 'ws1Clj0vOAM');
  const qp = new URLSearchParams(location.search).get('q');
  if (qp) { $('urlInput').value = qp; searchBenchmarks(qp); }
  const hashMode = (location.hash || '').replace('#', '');
  if (['channel', 'generate', 'produce', 'marketing'].includes(hashMode)) setMode(hashMode);
});

// ── 상단: 모드 전환 · 백엔드 상태 · 환경 진단 ──────────────────────────

function setMode(mode) {
  if (mode === 'produce' && !FEATURES.producer) mode = 'generate';
  state.mode = mode;
  const map = { channel: 'channelSection', analyze: 'analyzerSection', generate: 'generatorSection', produce: 'producerSection', marketing: 'marketingSection' };
  Object.entries(map).forEach(([m, id]) => { 
    const el = $(id);
    if (el) el.style.display = m === mode ? 'block' : 'none'; 
  });
  document.querySelectorAll('.mode-btn').forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
  if (mode === 'channel') {
    loadChannelHistory(); checkChannelYtStatus();
  }
  if (mode === 'generate') {
    loadVoiceProfiles(); fillReferenceSelect(); loadStyleGuides();
    if (!state.plan && state.history.plans.length) {  // 처음 들어오면 가장 최근 기획서를 보여줌
      api(`/api/plan?id=${encodeURIComponent(state.history.plans[0].plan_id)}`).then((r) => renderPlan(r.data)).catch(() => {});
    }
  }
  history.replaceState(null, '', mode === 'analyze' ? location.pathname : `#${mode}`);
  if (mode === 'produce') { fillProducePlanSelect(); if (!state.producePlan && $('producePlanSelect').value) loadProducePlan($('producePlanSelect').value); }
  if (mode === 'marketing') { syncMarketingWithCurrentState(); }
  window.scrollTo({ top: 0, behavior: 'smooth' }); icons();
}

function bindHeader() {
  document.querySelectorAll('.mode-btn').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));
  $('lmsPill').addEventListener('click', () => selectBackend('lmstudio'));
  $('ollamaPill').addEventListener('click', () => selectBackend('ollama'));
  $('btnEnv').addEventListener('click', openEnvModal);
  $('btnCloseEnv').addEventListener('click', () => $('envModal').classList.remove('open'));
  $('envModal').addEventListener('click', (e) => { if (e.target === $('envModal')) $('envModal').classList.remove('open'); });
}

async function refreshStatus() {
  const pills = { lmstudio: { pill: $('lmsPill'), label: $('lmsLabel'), name: 'LM Studio' }, ollama: { pill: $('ollamaPill'), label: $('ollamaLabel'), name: 'Ollama' } };
  try {
    const st = await api('/api/status');
    state.status = st; state.llmPreference = st.llm.preference || 'auto';
    $('appVersion').textContent = `v${st.version}`;
    for (const key of ['lmstudio', 'ollama']) {
      const p = pills[key], b = st.backends[key] || {}, active = st.llm.active === key, chosen = state.llmPreference === key;
      p.pill.className = 'pill' + (b.online ? ' online' : '') + (active ? ' active' : '') + (b.online && !b.model ? ' nomodel' : '') + (chosen && !b.online ? ' chosen-offline' : '');
      let text = p.name;
      if (active && (st.llm.model || b.model)) text += ' · ' + String(st.llm.model || b.model).split('/').pop().replace(/\.gguf$/i, '').slice(0, 28);
      else if (chosen && !b.online) text += ' · 꺼짐';
      else if (b.online && !b.model) text += ' · 모델 없음';
      p.label.textContent = text;
      p.pill.title = !b.online
        ? (chosen ? `${p.name}을(를) 선택했지만 꺼져 있습니다. 실행하거나 다시 클릭해 자동 모드로 돌아가세요.` : `${p.name} 꺼짐 · 클릭하면 이 백엔드를 사용합니다`)
        : active ? `${p.name} 사용 중 (${state.llmPreference === 'auto' ? '자동 감지' : '수동 선택'} · ${b.model || '모델 없음'})${chosen ? ' — 다시 클릭하면 자동 모드' : ''}`
        : b.model ? `${p.name} 실행 중 (대기) · 클릭하면 이 백엔드를 사용합니다` : `${p.name} 실행 중 — 모델 설치 필요 (ollama pull gemma3)`;
    }
  } catch (e) {
    for (const key of ['lmstudio', 'ollama']) { pills[key].pill.className = 'pill'; pills[key].label.textContent = pills[key].name; pills[key].pill.title = '서버 연결 대기 중'; }
  }
}

async function selectBackend(key) {
  const next = state.llmPreference === key ? 'auto' : key;
  try {
    await api('/api/llm/select', { backend: next });
    showToast(next === 'auto' ? '자동 감지 모드 (LM Studio 우선)' : `${key === 'lmstudio' ? 'LM Studio' : 'Ollama'}를 사용합니다.`);
  } catch (e) { showToast(e.message, true); }
  refreshStatus();
}

function openEnvModal() {
  const st = state.status; const body = $('envModalBody');
  if (!st) { body.innerHTML = '<p>서버 상태를 불러오지 못했습니다.</p>'; }
  else {
    const row = (label, ok, detail, hint) => `
      <div class="flex items-start justify-between gap-3 py-1.5 border-b border-neutral-100">
        <div><div class="font-semibold text-neutral-800">${label}</div>${detail ? `<div class="text-[11px] text-neutral-500">${escapeHtml(detail)}</div>` : ''}${!ok && hint ? `<div class="text-[11px] text-amber-700 mt-0.5">${escapeHtml(hint)}</div>` : ''}</div>
        <span class="badge ${ok ? 'badge-ok' : 'badge-warn'} shrink-0">${ok ? '정상' : '확인 필요'}</span></div>`;
    const lms = st.backends.lmstudio, oll = st.backends.ollama;
    body.innerHTML = [
      row('TubeInsight', true, `v${st.version} · Python ${st.python}`),
      row('yt-dlp (유튜브 수집)', !!st.yt_dlp, st.yt_dlp ? `버전 ${st.yt_dlp}` : '설치되지 않음', 'pip3 install -r requirements.txt'),
      row('LM Studio', lms.online && !!lms.model, lms.online ? '' : '꺼짐 (포트 1234)', 'LM Studio → Developer → Local Server 시작 후 모델 로드') + modelPicker('lmstudio', lms),
      row('Ollama', oll.online && !!oll.model, oll.online ? '' : '꺼짐 (포트 11434)', oll.online ? 'ollama pull gemma3' : 'Ollama 앱 실행') + modelPicker('ollama', oll),
      row('현재 AI 백엔드', st.llm.online, st.llm.online ? `${st.llm.backend} · ${st.llm.model}` : '사용 가능한 로컬 AI 없음', 'LM Studio 또는 Ollama 중 하나를 켜세요'),
      row('나레이션 (Edge-TTS)', true, '무료 · 인터넷 필요'),
      row('보이스 클로닝 (선택)', st.tts.clone_available, st.tts.clone_available ? 'torch + qwen-tts 설치됨' : '미설치 — 내 목소리 등록 시 기본 음성으로 대체', 'pip3 install torch qwen-tts (용량 큼)'),
      row('ffmpeg (영상 합성)', st.render.ffmpeg, st.render.ffmpeg ? '사용 가능' : '없음', 'pip3 install imageio-ffmpeg'),
      row('한글 자막 폰트', !!st.render.font, st.render.font || '없음 — 자막 굽기 비활성', '나눔고딕 등 한글 TTF 설치'),
      row('Gemini API 키 (이미지 생성, 선택)', st.render.gemini_key_set, st.render.gemini_key_set ? '저장됨' : '없음 — 이미지를 직접 넣어 사용', '③ 탭 환경 카드에서 저장'),
      row('YouTube 업로드 (선택)', st.youtube.libs && st.youtube.client_secret, st.youtube.libs ? (st.youtube.client_secret ? (st.youtube.authorized ? '계정 연결됨' : 'client_secret.json 있음 · 계정 미연결') : 'client_secret.json 없음') : '구글 API 패키지 미설치', st.youtube.libs ? 'data/youtube/client_secret.json 저장 후 ③ 탭에서 연결' : 'pip3 install google-api-python-client google-auth-oauthlib'),
    ].join('');
  }
  body.querySelectorAll('[data-model-backend]').forEach((sel) => sel.addEventListener('change', async () => {
    try { await api('/api/llm/select', { backend: sel.dataset.modelBackend, model: sel.value }); showToast(`사용할 모델을 '${sel.value.split('/').pop()}'(으)로 바꿨습니다.`); await refreshStatus(); openEnvModal(); }
    catch (e) { showToast(e.message, true); }
  }));
  $('envModal').classList.add('open'); icons();
}

// 백엔드에 모델이 여러 개면 어떤 모델을 쓸지 고르는 드롭다운
function modelPicker(key, b) {
  if (!b.online || !b.models || b.models.length === 0) return '';
  const active = state.status?.llm?.active === key ? state.status.llm.model : b.model;
  if (b.models.length === 1) return `<div class="text-[11px] text-neutral-500 -mt-1 mb-1.5 pl-0.5">모델: ${escapeHtml(b.models[0])}</div>`;
  return `<div class="flex items-center gap-2 -mt-1 mb-1.5 pl-0.5"><span class="text-[11px] text-neutral-500 shrink-0">사용할 모델</span>
    <select data-model-backend="${key}" class="input px-2 py-1 text-[11px] flex-1">${b.models.map((m) => `<option value="${escapeHtml(m)}" ${m === active ? 'selected' : ''}>${escapeHtml(m)}</option>`).join('')}</select></div>`;
}

// ── 이력 ──────────────────────────────────────────────────────────────

async function loadHistory() {
  try {
    const h = await api('/api/history');
    state.history = { analyses: h.analyses || [], plans: h.plans || [] };
  } catch (e) { /* 무시 */ }
  const aSel = $('analysisHistorySelect');
  aSel.innerHTML = '<option value="">불러오기…</option>' + state.history.analyses.map((a) =>
    `<option value="${a.id}">${escapeHtml((a.title || a.id).slice(0, 40))} · ${fmtNum(a.view_count)}회</option>`).join('');
  fillReferenceSelect(); fillPlanSelect($('planHistorySelect'), true); fillProducePlanSelect();
}
function fillReferenceSelect() {
  const sel = $('referenceSelect'); const cur = sel.value || (state.analysis && state.analysis.id);
  const list = state.history.analyses.filter((a) => a.ai_ok !== false);
  sel.innerHTML = list.map((a) => `<option value="${a.id}">${escapeHtml((a.title || a.id).slice(0, 34))}</option>`).join('') || '<option value="">분석된 영상 없음 (기본 공식 사용)</option>';
  if (cur && list.some((a) => a.id === cur)) sel.value = cur;
}
function fillPlanSelect(sel, withPlaceholder) {
  const cur = sel.value;
  sel.innerHTML = (withPlaceholder ? '<option value="">불러오기…</option>' : '') + state.history.plans.map((p) =>
    `<option value="${escapeHtml(p.plan_id)}">${escapeHtml((p.topic || p.plan_id).slice(0, 30))} · ${p.num_scenes}씬 ${p.aspect_ratio || ''}${p.has_audio ? ' · 🔊' : ''} · ${fmtTs(p.created_at)}</option>`).join('');
  if (cur) sel.value = cur;
}
function fillProducePlanSelect() {
  const sel = $('producePlanSelect'); fillPlanSelect(sel, false);
  let remembered = null; try { remembered = localStorage.getItem('ti_last_plan'); } catch (e) {}
  if (state.producePlan && state.history.plans.some((p) => p.plan_id === state.producePlan.plan_id)) sel.value = state.producePlan.plan_id;
  else if (state.plan && state.history.plans.some((p) => p.plan_id === state.plan.plan_id)) sel.value = state.plan.plan_id;
  else if (remembered && state.history.plans.some((p) => p.plan_id === remembered)) sel.value = remembered;
  if (!state.history.plans.length) sel.innerHTML = '<option value="">기획서가 없습니다 — ② 탭에서 먼저 만들어주세요</option>';
}

// ══════════════════════════ ① 영상 분석 ══════════════════════════

function bindAnalyzer() {
  $('btnClear').addEventListener('click', () => { $('urlInput').value = ''; $('urlInput').focus(); });
  $('urlInput').addEventListener('keypress', (e) => { if (e.key === 'Enter') $('btnAnalyze').click(); });
  $('btnAnalyze').addEventListener('click', () => {
    const q = $('urlInput').value.trim();
    if (!q) { showToast('유튜브 링크나 검색 키워드를 입력해주세요.', true); return; }
    const isUrl = /(?:v=|youtu\.be\/|shorts\/|embed\/|live\/)[A-Za-z0-9_-]{11}/.test(q) || /^[A-Za-z0-9_-]{11}$/.test(q);
    if (isUrl) startAnalysis(q.length === 11 ? `https://youtu.be/${q}` : q, $('forceReanalyze').checked);
    else searchBenchmarks(q);
  });
  $('btnCloseSearch')?.addEventListener('click', () => { $('searchResultsBox').style.display = 'none'; });
  $('btnRetryAnalysis').addEventListener('click', () => { if (state.analysis) startAnalysis(state.analysis.url || `https://youtu.be/${state.analysis.id}`, true); });
  document.querySelectorAll('.sample-btn').forEach((b) => b.addEventListener('click', () => {
    document.querySelectorAll('.sample-btn').forEach((x) => x.classList.remove('active')); b.classList.add('active'); loadVideoData(b.dataset.id, true);
  }));
  $('analysisHistorySelect').addEventListener('change', (e) => { if (e.target.value) loadVideoData(e.target.value, false); });
  document.querySelectorAll('.tab-btn').forEach((tab) => tab.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach((p) => p.classList.remove('active'));
    tab.classList.add('active'); $(tab.dataset.target).classList.add('active');
  }));
  $('btnCopyReport').addEventListener('click', () => copyText(state.analysis && state.analysis.report, '리포트를 복사했습니다.'));
  $('btnDownloadReport').addEventListener('click', () => { if (state.analysis) downloadText(`${state.analysis.id}_분석리포트.md`, state.analysis.report || ''); });
  $('btnCopyTranscript').addEventListener('click', () => copyText(state.analysis && state.analysis.transcript, '자막 전체를 복사했습니다.'));
  $('transcriptSearchInput').addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase();
    document.querySelectorAll('.transcript-row').forEach((row) => {
      const hit = !q || (row.dataset.text || '').includes(q);
      row.style.display = hit ? 'flex' : 'none'; row.classList.toggle('highlight', hit && !!q);
    });
  });
  $('btnGoGenerate').addEventListener('click', () => {
    setMode('generate');
    if (state.analysis) { fillReferenceSelect(); $('referenceSelect').value = state.analysis.id; }
  });
  $('btnGoMarketingFromAnalysis')?.addEventListener('click', () => {
    setMode('marketing');
    syncMarketingWithCurrentState();
  });
  $('btnGoChannelFromAnalysis')?.addEventListener('click', () => {
    transferBenchToChannel();
  });
  $('btnBenchToChannel')?.addEventListener('click', () => {
    transferBenchToChannel();
  });
}

function transferBenchToChannel() {
  if (!state.analysis) {
    showToast('먼저 분석된 영상 데이터가 필요합니다.', true);
    return;
  }
  const vis = state.analysis.visual || {};
  const cs = vis.channel_strategy || {};
  const info = state.analysis.info || {};
  const topic = cs.recommended_new_channel_topic || `${info.channel || '유튜브'} 벤치마킹 채널 기획`;
  
  if ($('channelTopicInput')) $('channelTopicInput').value = topic + (cs.differentiation_point ? ` — 차별화: ${cs.differentiation_point}` : '');
  if ($('channelAudienceInput') && cs.positioning) $('channelAudienceInput').value = cs.positioning;
  const toneSel = $('channelToneSelect');
  if (toneSel && cs.core_tone) {
    if (![...toneSel.options].some((o) => o.value === cs.core_tone)) {
      const opt = document.createElement('option'); opt.value = cs.core_tone; opt.textContent = `벤치마크: ${cs.core_tone.slice(0, 30)}`; toneSel.appendChild(opt);
    }
    toneSel.value = cs.core_tone;
  }
  setMode('channel');
  showToast('벤치마킹 정보 반영: 추천 주제 + 차별화 포인트 + 타겟 + 톤앤매너');
}

async function searchBenchmarks(query) {
  const btn = $('btnAnalyze'); setBusy(btn, true, '유튜브에서 찾는 중…');
  try {
    const r = await api(`/api/search?q=${encodeURIComponent(query)}`);
    const list = r.results || [];
    $('searchResultsCount').textContent = `— "${query}" ${list.length}건 (조회수 순)`;
    $('searchResultsList').innerHTML = list.length ? list.map((v) => `
      <button class="subtle-box p-2 flex gap-2.5 items-center text-left hover:border-black transition-all search-pick" data-id="${v.id}">
        <div class="relative shrink-0"><img src="${v.thumbnail}" alt="" class="w-[104px] h-[58px] object-cover rounded-md bg-neutral-100">
          ${v.duration_string ? `<span class="absolute bottom-1 right-1 px-1 bg-black/80 text-white rounded text-[9px] font-mono">${v.duration_string}</span>` : ''}</div>
        <div class="min-w-0 flex-1">
          <div class="text-xs font-bold text-black leading-snug" style="display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${escapeHtml(v.title)}</div>
          <div class="text-[10px] text-neutral-500 mt-0.5 truncate">${escapeHtml(v.channel)} · 조회수 ${fmtNum(v.view_count)}회${v.analyzed ? ' · <b class="text-emerald-700">분석됨</b>' : ''}</div>
        </div>
        <i data-lucide="sparkles" class="w-3.5 h-3.5 text-neutral-300 shrink-0"></i>
      </button>`).join('') : '<p class="text-xs text-neutral-400 col-span-full">검색 결과가 없습니다. 키워드를 바꿔보세요.</p>';
    $('searchResultsList').querySelectorAll('.search-pick').forEach((b) => b.addEventListener('click', () => {
      const url = `https://youtu.be/${b.dataset.id}`;
      $('urlInput').value = url; $('searchResultsBox').style.display = 'none';
      startAnalysis(url, false);
    }));
    $('searchResultsBox').style.display = 'block'; icons();
  } catch (e) { showToast(e.message, true); }
  finally { setBusy(btn, false); }
}

async function loadVideoData(vid, isSample) {
  try {
    const r = await api(`/api/report?id=${encodeURIComponent(vid)}`);
    renderDashboard(r.data, isSample);
    $('urlInput').value = r.data.url || `https://youtu.be/${vid}`;
  } catch (e) { showToast(e.message, true); }
}

async function startAnalysis(url, force) {
  const btn = $('btnAnalyze'); setBusy(btn, true, '분석 중…');
  $('aiFailNotice').style.display = 'none';
  setProgress('analysis', { progress: 2, message: '서버에 요청 중...', step: 'metadata' });
  try {
    const resp = await api('/api/analyze', { url, force });
    if (resp.cached) { hideProgress('analysis'); renderDashboard(resp.data, false); showToast('저장된 분석 결과를 불러왔습니다. 새로 분석하려면 "캐시 무시"를 켜세요.'); return; }
    const data = await runJob(resp, (job) => setProgress('analysis', job));
    setProgress('analysis', { progress: 100, message: '완료', status: 'done' });
    await sleep(500); hideProgress('analysis');
    renderDashboard(data, false); document.querySelectorAll('.sample-btn').forEach((x) => x.classList.remove('active'));
    showToast(data.ai_ok ? '분석이 완료되었습니다.' : '데이터는 모았지만 AI 분석은 실행되지 않았습니다.', !data.ai_ok);
    loadHistory();
  } catch (e) {
    setProgress('analysis', { progress: 100, message: `❌ ${e.message}`, step: null }); showToast(e.message, true);
  } finally { setBusy(btn, false); $('forceReanalyze').checked = false; }
}

function renderDashboard(data, isSample) {
  state.analysis = data;
  const info = data.info || {}, visual = data.visual || null, report = data.report || '';
  $('videoTitle').textContent = info.title || '제목 없음';
  $('channelName').textContent = info.channel || '채널명 미상';
  $('channelSubs').textContent = info.channel_follower_count ? `구독자 ${fmtNum(info.channel_follower_count)}명` : '구독자 비공개';
  $('videoDuration').textContent = info.duration_string || '';
  $('uploadDate').textContent = info.upload_date ? `${fmtDate(info.upload_date)} 게시` : '';
  $('videoThumb').src = info.thumbnail || `https://i.ytimg.com/vi/${data.id}/hqdefault.jpg`;
  $('videoLink').href = `https://youtu.be/${data.id}`;
  $('sampleDataBadge').style.display = isSample ? 'inline-flex' : 'none';

  const views = info.view_count || 0, likes = info.like_count || 0, comments = info.comment_count || 0;
  $('viewCount').textContent = views ? views.toLocaleString() : '—';
  $('likeCount').textContent = likes ? likes.toLocaleString() : '—';
  $('commentCount').textContent = comments ? comments.toLocaleString() : '—';
  $('engagementRate').textContent = views > 0 && (likes || comments) ? `${(((likes + comments) / views) * 100).toFixed(2)}%` : '—';

  const meta = [];
  if (data.ai_ok === false) meta.push('<span class="badge badge-warn">AI 분석 없음</span>');
  else if (data.llm) meta.push(`<span class="badge badge-ok" title="${escapeHtml(data.llm.model || '')}">AI · ${escapeHtml(data.llm.backend)}</span>`);
  if (data.analyzed_at) meta.push(`<span class="badge badge-mono">${fmtTs(data.analyzed_at)}</span>`);
  if (data.transcript_source) meta.push(`<span class="badge">자막 ${escapeHtml(data.transcript_source)}</span>`);
  else if ((data.transcript || '').trim() === '(자막 없음)') meta.push('<span class="badge badge-warn">자막 없음</span>');
  if (data.cached) meta.push('<span class="badge">저장된 결과</span>');
  $('analysisMeta').innerHTML = meta.join('');

  $('aiFailNotice').style.display = data.ai_ok === false ? 'flex' : 'none';
  $('aiFailText').textContent = data.ai_error || '';

  // 01 훅
  const title = info.title || '';
  const hookA = visual?.hook?.part_a || title.slice(0, Math.ceil(title.length / 2));
  const hookB = visual?.hook?.part_b || title.slice(Math.ceil(title.length / 2));
  $('hookPart1').textContent = hookA ? `"${hookA}"` : '—';
  $('hookPart2').textContent = hookB ? `"${hookB}"` : '—';
  const hookSec = sectionOf(report, 1);
  $('hookAnalysisText').textContent = visual?.hook?.mechanism || (hookSec ? plainSnippet(hookSec, 220) : (data.ai_ok === false ? 'AI 분석이 없어 훅 구조를 정리하지 못했습니다.' : '—'));

  // 02 타임라인
  const stages = visual?.stages?.length ? visual.stages : ['도입', '갈등', '난제', '반전', '여운'].map((n) => ({ name: n, time_range: '', summary: '' }));
  $('storyTimelineGrid').innerHTML = stages.map((s, i) => `
    <div class="subtle-box p-2.5 text-center">
      <span class="text-[10px] font-mono font-bold text-black uppercase">${i + 1}. ${escapeHtml(s.name)}</span>
      <p class="text-[10px] text-neutral-400 my-1 font-mono">${escapeHtml(s.time_range || '—')}</p>
      <p class="text-xs text-neutral-800 font-medium leading-snug">${escapeHtml(s.summary || '—')}</p>
    </div>`).join('');

  // 03 핵심 메시지
  const coreSec = sectionOf(report, 3);
  $('coreMessageText').textContent = visual?.core_message ? `"${visual.core_message}"` : (coreSec ? `"${plainSnippet(coreSec, 160)}"` : '—');
  const kws = visual?.keywords?.length ? visual.keywords : (info.tags || []).slice(0, 4).map((t) => '#' + t);
  $('keywordChips').innerHTML = kws.map((k) => `<span class="badge badge-mono">${escapeHtml(k)}</span>`).join('');

  // 04 댓글 여론
  const sent = visual?.sentiment || {};
  $('sentimentSummary').textContent = sent.summary || (sectionOf(report, 4) ? plainSnippet(sectionOf(report, 4), 160) : '');
  const hasNums = [sent.positive, sent.neutral, sent.negative].every((v) => typeof v === 'number');
  $('sentimentBar').style.display = hasNums ? 'flex' : 'none'; $('sentimentLegend').style.display = hasNums ? 'flex' : 'none';
  if (hasNums) {
    const total = Math.max(1, sent.positive + sent.neutral + sent.negative);
    $('sentimentBar').innerHTML = `<span style="width:${(sent.positive / total) * 100}%;background:#059669"></span><span style="width:${(sent.neutral / total) * 100}%;background:#9CA3AF"></span><span style="width:${(sent.negative / total) * 100}%;background:#DC2626"></span>`;
    $('sentimentLegend').innerHTML = `<span>긍정 ${sent.positive}%</span><span>중립 ${sent.neutral}%</span><span>부정 ${sent.negative}%</span>`;
  }
  renderTopComments(data.comments || []);

  // 05 플레이북
  const playSec = sectionOf(report, 5);
  const tips = visual?.tips?.length ? visual.tips : [];
  $('playbookTips').innerHTML = tips.length ? tips.map((t, i) => `
    <div class="subtle-box p-2.5"><div class="text-xs font-bold text-black">📌 ${i + 1}. ${escapeHtml(t.title)}</div><div class="text-[11px] text-neutral-600 mt-0.5">${escapeHtml(t.summary || '')}</div></div>`).join('')
    : `<p class="text-xs text-neutral-400">${playSec ? '아래 전문을 확인하세요.' : (data.ai_ok === false ? 'AI 분석이 없어 플레이북이 없습니다.' : '—')}</p>`;
  $('playbookContent').innerHTML = playSec ? md(playSec) : '<p class="text-neutral-400">—</p>';

  // 06 채널 브랜딩 & 전략
  const cs = visual?.channel_strategy || {};
  const channelPos = cs.positioning || `${info.channel || '이 채널'}의 전문 지식 기반 콘텐츠`;
  const channelTone = cs.core_tone || '전문적이고 몰입감 있는 톤';
  const channelDiff = cs.differentiation_point || '쇼츠와 8초 씬 구성을 결합한 빠른 템포의 시각화';
  const recTopic = cs.recommended_new_channel_topic || `${(title.split(' ')[0] || info.channel)} 관련 1인 미디어 채널`;
  
  if ($('channelStrategyPos')) $('channelStrategyPos').textContent = channelPos;
  if ($('channelStrategyTone')) $('channelStrategyTone').textContent = channelTone;
  if ($('channelStrategyDiff')) $('channelStrategyDiff').textContent = channelDiff;
  if ($('channelStrategyRecTopic')) $('channelStrategyRecTopic').textContent = recTopic;

  $('markdownReportContent').innerHTML = md(report || '(리포트 없음)');
  renderTranscript(data.transcript || '', data.id);
  $('transcriptSourceBadge').textContent = data.transcript_source || '';
  $('dashboardSection').style.display = 'grid';
  fillReferenceSelect(); $('referenceSelect').value = data.id;
  icons();
}

// 리포트에서 "N." 섹션 본문 추출 (##, ###, #### 모두 허용)
function sectionOf(report, n) {
  const m = (report || '').match(new RegExp(`#{2,4}\\s*${n}[.)]\\s*[^\\n]*\\n([\\s\\S]*?)(?=\\n#{2,4}\\s*${n + 1}[.)]|\\n---|$)`));
  return m ? m[1].trim() : '';
}
function plainSnippet(text, max) {
  const t = (text || '').replace(/[#*_`>|]/g, '').replace(/\s+/g, ' ').trim();
  return t.length > max ? t.slice(0, max) + '…' : t;
}

function renderTopComments(comments) {
  const list = $('topCommentsList');
  if (!comments.length) { list.innerHTML = '<p class="text-xs text-neutral-400">댓글이 없거나 비활성화된 영상입니다.</p>'; return; }
  list.innerHTML = comments.slice(0, 4).map((c) => `
    <div class="subtle-box p-3">
      <div class="flex justify-between items-center mb-1"><span class="text-xs font-bold text-black">${escapeHtml(c.author || '시청자')}</span>
        <span class="text-[11px] text-neutral-400 font-mono flex items-center gap-1"><i data-lucide="thumbs-up" class="w-3 h-3"></i> ${(c.like_count || 0).toLocaleString()}</span></div>
      <p class="text-xs text-neutral-600 leading-relaxed">${escapeHtml(c.text || '')}</p>
    </div>`).join('');
}

function renderTranscript(text, vid) {
  const c = $('transcriptContainer');
  if (!text || text.trim() === '(자막 없음)') { c.innerHTML = '<div class="transcript-row"><span class="transcript-text text-neutral-400">자막이 제공되지 않는 영상입니다.</span></div>'; return; }
  c.innerHTML = text.split('\n').filter((l) => l.trim()).map((line) => {
    const m = line.match(/^\[(\d{2}:\d{2})\]\s*(.*)$/);
    if (!m) return `<div class="transcript-row" data-text="${escapeHtml(line.toLowerCase())}"><span class="time-badge">자막</span><span class="transcript-text">${escapeHtml(line)}</span></div>`;
    const [mm, ss] = m[1].split(':').map(Number);
    return `<div class="transcript-row" data-text="${escapeHtml(m[2].toLowerCase())}">
      <a href="https://youtu.be/${vid}?t=${mm * 60 + ss}" target="_blank" rel="noopener" class="time-badge" title="유튜브 해당 시점으로"><i data-lucide="play-circle"></i> ${m[1]}</a>
      <span class="transcript-text">${escapeHtml(m[2])}</span></div>`;
  }).join('');
  icons();
}

// ══════════════════════════ ② 기획 · 나레이션 ══════════════════════════

function bindGenerator() {
  $('topicInput').addEventListener('keypress', (e) => { if (e.key === 'Enter') $('btnGenerate').click(); });
  $('btnGenerate').addEventListener('click', () => {
    const topic = $('topicInput').value.trim();
    if (!topic) { showToast('영상 주제를 입력해주세요.', true); return; }
    if ($('fullAutoToggle')?.checked) startFullAuto(topic); else startGeneration(topic);
  });
  $('fullAutoToggle')?.addEventListener('change', () => {
    $('fullAutoOptions').style.display = $('fullAutoToggle').checked ? 'flex' : 'none';
    const span = $('btnGenerate').querySelector('span'); if (span) span.textContent = $('fullAutoToggle').checked ? '⚡ 풀 오토 시작' : '기획 시작';
  });
  $('btnFullGoProduce')?.addEventListener('click', async () => {
    if (!state.plan) return; setMode('produce'); await loadHistory();
    $('producePlanSelect').value = state.plan.plan_id; loadProducePlan(state.plan.plan_id);
  });
  $('btnFullGoMarketing')?.addEventListener('click', () => setMode('marketing'));
  document.querySelectorAll('.topic-chip').forEach((c) => c.addEventListener('click', () => { $('topicInput').value = c.dataset.topic; }));
  $('planHistorySelect').addEventListener('change', async (e) => {
    if (!e.target.value) return;
    try { const r = await api(`/api/plan?id=${encodeURIComponent(e.target.value)}`); renderPlan(r.data); showToast('기획서를 불러왔습니다.'); }
    catch (err) { showToast(err.message, true); }
  });

  $('btnPlayFullAudio').addEventListener('click', toggleFullAudio);
  $('btnDownloadAudioZip').addEventListener('click', () => {
    const url = state.plan?.audio_data?.zip_download_url;
    if (!url) { showToast('나레이션 오디오가 없습니다. "나레이션 다시 만들기"를 눌러주세요.', true); return; }
    const a = document.createElement('a'); a.href = url; a.download = `${state.plan.topic}_나레이션.zip`; document.body.appendChild(a); a.click(); a.remove();
  });
  $('btnRegenerateAudios').addEventListener('click', regenerateAudio);
  $('btnDownloadPlan').addEventListener('click', () => { if (state.plan) downloadText(`${state.plan.topic}_기획서.md`, state.plan.full_document || ''); });
  $('btnGoProduce').addEventListener('click', async () => { if (!state.plan) return; setMode('produce'); await loadHistory(); $('producePlanSelect').value = state.plan.plan_id; loadProducePlan(state.plan.plan_id); });

  $('btnCopyMeta').addEventListener('click', () => copyText(state.plan && `${state.plan.meta_text}`, '제목·설명란을 복사했습니다.'));
  $('btnCopyDescription').addEventListener('click', () => copyText(state.plan && state.plan.description_plain, '설명란을 복사했습니다.'));
  $('btnCopyFullScript').addEventListener('click', () => copyText(state.plan && (state.plan.structured_scenes || []).map((s) => `[씬 ${s.scene_num}] ${s.time_range}\n${s.subtitle}`).join('\n\n'), '전체 대본을 복사했습니다.'));
  $('btnCopyAllPrompts').addEventListener('click', () => copyText(state.plan && (state.plan.structured_scenes || []).map((s) => `// 씬 ${s.scene_num} (${s.time_range})\n${s.prompt_en}`).join('\n\n'), '전체 영상 프롬프트를 복사했습니다.'));
  $('btnCopyThumbnailPrompt').addEventListener('click', () => copyText(state.plan && state.plan.thumbnail_prompt_raw, '썸네일 프롬프트를 복사했습니다.'));
  $('btnCopyAllImagePrompts').addEventListener('click', () => {
    if (!state.plan) return;
    const parts = [`/* 썸네일 (${state.plan.aspect_ratio}) */\n${state.plan.thumbnail_prompt_raw}`];
    (state.plan.structured_scenes || []).forEach((s) => parts.push(`/* 씬 ${s.scene_num} 첫 프레임 (${s.time_range}) */\n${s.image_prompt_raw || ''}`));
    copyText(parts.join('\n\n'), '썸네일과 씬별 이미지 프롬프트를 모두 복사했습니다.');
  });
}

async function startFullAuto(topic) {
  if (state.generating) { showToast('이미 작업이 진행 중입니다.'); return; }
  const { scenes, seconds: sceneSeconds } = lengthPreset();
  const includeVideos = $('fullIncludeVideos')?.checked !== false;
  const quality = $('fullVideoQuality')?.value || '360p';
  const doMarketing = $('fullMarketing')?.checked !== false;
  const imgUsd = (scenes + 1) * IMAGE_USD;
  const vc = includeVideos ? videoCostKrw(scenes, quality) : { usd: 0, krw: 0 };
  const lines = [`⚡ 풀 오토: "${topic}"`, '',
    `1. 기획 + 대본 교정 + 나레이션(${$('voiceSelect').selectedOptions[0]?.textContent || ''}) — 무료`,
    `2. 이미지 ${scenes + 1}개 (썸네일 포함) — 약 $${imgUsd.toFixed(2)}`,
    includeVideos ? `3. AI 영상 ${scenes}개 · ${quality} — 약 $${vc.usd.toFixed(2)} (${vc.krw.toLocaleString()}원)` : '3. AI 영상 건너뜀 (이미지 켄번즈 합성)',
    `4. 자막·전환 합성 — 무료`,
    doMarketing ? '5. 스레드·블로그·뉴스레터 — 무료' : '5. 마케팅 건너뜀', '',
    `예상 소요: ${includeVideos ? '15~30분' : '5~10분'} · 예상 비용 합계: 약 $${(imgUsd + vc.usd).toFixed(2)}`, '', '시작할까요?'];
  if (!confirm(lines.join('\n'))) return;

  state.generating = true;
  const btn = $('btnGenerate'); setBusy(btn, true, '풀 오토 진행 중…');
  $('genResultsSection').style.display = 'none'; $('fullDoneCard').style.display = 'none'; hideProgress('gen');
  setProgress('full', { progress: 2, message: '시작 중...', step: 'meta' });
  try {
    const resp = await api('/api/pipeline/full', {
      topic, scenes, scene_seconds: sceneSeconds, aspect_ratio: $('aspectRatioSelect').value, voice_id: $('voiceSelect').value,
      reference_id: $('referenceSelect').value || null, style_guide: $('styleGuideSelect')?.value || null,
      include_videos: includeVideos, video_quality: quality, marketing: doMarketing,
    });
    const r = await runJob(resp, (job) => setProgress('full', job));
    setProgress('full', { progress: 100, message: '완료', status: 'done' });
    await sleep(500); hideProgress('full');

    renderPlan(r.plan); state.render = r.render || null;
    if (r.marketing) {
      state.marketing.currentData = r.marketing;
      if (r.marketing.threads_x) renderThreadsOutput(r.marketing.threads_x);
      if (r.marketing.seo_blog) renderBlogOutput(r.marketing.seo_blog);
      if (r.marketing.newsletter) renderNewsletterOutput(r.marketing.newsletter);
      $('marketingTopicInput').value = topic;
    }
    const ss = (r.plan.structured_scenes || []).length;
    const nv = Object.values(await api(`/api/render/status?plan_id=${encodeURIComponent(r.plan.plan_id)}`).then((x) => { state.media = x.media || {}; state.env = x.env; state.youtube = x.youtube; return x.media || {}; })).filter((m) => m.type === 'video').length;
    $('fullDoneMeta').textContent = `${ss}씬 · AI 영상 ${nv}/${ss} · ${r.render?.duration ? Math.round(r.render.duration) + '초' : ''} · ${r.marketing ? '마케팅 3종 포함' : '마케팅 없음'}`;
    $('fullDoneWarnings').innerHTML = (r.warnings || []).map((w) => `<div class="text-[11px] text-amber-700">• ${escapeHtml(w)}</div>`).join('');
    $('fullDoneCard').style.display = 'block'; $('fullDoneCard').scrollIntoView({ behavior: 'smooth' });
    showToast(r.warnings?.length ? `풀 오토 완료 — 경고 ${r.warnings.length}건 확인` : '⚡ 풀 오토 완성! 기획·영상·마케팅이 모두 준비됐습니다.', !!r.warnings?.length);
    loadHistory();
  } catch (e) {
    setProgress('full', { progress: 100, message: `❌ ${e.message}`, step: null }); showToast(e.message, true);
  } finally { setBusy(btn, false); state.generating = false; icons(); }
}

function lengthPreset() {
  const [n, s] = ($('sceneCountSelect')?.value || '10x8').split('x').map(Number);
  return { scenes: n || 10, seconds: s || 8 };
}

async function startGeneration(topic) {
  if (state.generating) { showToast('이미 기획서를 만드는 중입니다. 잠시만요.'); return; }
  state.generating = true;
  const btn = $('btnGenerate'); setBusy(btn, true, '기획 중…');
  $('genResultsSection').style.display = 'none';
  setProgress('gen', { progress: 2, message: '서버에 요청 중...', step: 'meta' });
  try {
    const resp = await api('/api/generate', {
      topic, scenes: lengthPreset().scenes, scene_seconds: lengthPreset().seconds, voice_id: $('voiceSelect').value || 'ko-KR-InJoonNeural',
      aspect_ratio: $('aspectRatioSelect').value, reference_id: $('referenceSelect').value || null, generate_audio: true,
      style_guide: $('styleGuideSelect')?.value || null,
    });
    const plan = await runJob(resp, (job) => setProgress('gen', job));
    setProgress('gen', { progress: 100, message: '완료', status: 'done' });
    await sleep(500); hideProgress('gen');
    renderPlan(plan); $('genResultsSection').scrollIntoView({ behavior: 'smooth' });
    showToast(`'${topic}' 기획서가 완성되었습니다.`); loadHistory();
  } catch (e) {
    setProgress('gen', { progress: 100, message: `❌ ${e.message}`, step: null }); showToast(e.message, true);
  } finally { setBusy(btn, false); state.generating = false; }
}

function renderPlan(plan) {
  state.plan = plan; stopFullAudio();
  const scenes = plan.structured_scenes || [], n = scenes.length, q = plan.quality || {};
  $('genTopicBadge').textContent = `주제: ${plan.topic}`;
  $('genRefBadge').textContent = plan.reference ? `벤치마크: ${plan.reference.title.slice(0, 28)}` : '벤치마크: 기본 공식';
  const allOk = q.scenes_parsed === n && q.prompts_parsed === n && q.images_parsed === n;
  $('genQualityBadge').textContent = `대본 ${q.scenes_parsed ?? '?'}/${n} · 영상 프롬프트 ${q.prompts_parsed ?? '?'}/${n} · 이미지 프롬프트 ${q.images_parsed ?? '?'}/${n}`;
  $('genQualityBadge').className = 'badge badge-mono ' + (allOk ? 'badge-ok' : 'badge-warn');
  $('genMainTitle').textContent = plan.meta?.recommended?.title || plan.topic;
  $('badgeAspectRatio').textContent = `${plan.aspect_ratio} · 2K`;
  const psec = plan.scene_seconds || 8;
  $('totalDurationBadge').textContent = `${n}씬 × ${psec}초 · 총 ${Math.floor(n * psec / 60)}분 ${(n * psec) % 60}초`;

  $('titlesList').innerHTML = (plan.meta?.titles || []).map((t) => {
    const rec = t.title === plan.meta?.recommended?.title;
    return `<div class="subtle-box p-2.5 ${rec ? 'border-black' : ''}">
      <div class="flex items-start justify-between gap-2">
        <div><span class="badge ${rec ? 'badge-ok' : ''} mb-1">${rec ? '✓ 추천 · ' : ''}${escapeHtml(t.type)}</span><div class="text-xs font-bold text-black">${escapeHtml(t.title)}</div>
          <div class="text-[11px] text-neutral-500 mt-0.5">${escapeHtml(t.reason)}</div></div>
        <button class="btn btn-ghost !py-0.5 !px-2 shrink-0" data-copy="${escapeHtml(t.title)}"><i data-lucide="copy" class="w-3 h-3"></i></button></div></div>`;
  }).join('') + (plan.meta?.recommended?.reason ? `<p class="text-[11px] text-neutral-500 mt-1">${escapeHtml(plan.meta.recommended.reason)}</p>` : '');
  $('titlesList').querySelectorAll('[data-copy]').forEach((b) => b.addEventListener('click', () => copyText(b.dataset.copy, '제목을 복사했습니다.')));
  $('descriptionText').textContent = plan.description_plain || '';
  $('thumbnailPromptJsonDisplay').textContent = plan.thumbnail_prompt_raw || '';

  renderAudioNotice(plan);
  const audioMap = {};
  (plan.audio_data?.scenes_audio || []).forEach((a) => { audioMap[a.scene_num] = a; });

  $('scenesGrid').innerHTML = scenes.map((sc) => {
    const a = audioMap[sc.scene_num] || {};
    const len = (sc.subtitle || '').length;
    const lenBadge = sc.parse_ok ? `<span class="badge ${sc.length_warning ? 'badge-warn' : ''} badge-mono" title="8초 기준 30~45자 권장">${len}자</span>` : '';
    const durBadge = a.duration ? `<span class="badge ${a.over_limit ? 'badge-warn' : 'badge-ok'} badge-mono" title="${a.over_limit ? '8초를 넘습니다 — 대본을 줄이거나 ③ 탭의 \'나레이션 길이에 맞춤\'을 사용하세요' : '8초 이내'}">${a.duration}s${a.over_limit ? ' ⚠' : ''}</span>` : '';
    return `
    <div class="card p-5 border-l-2 border-l-black flex flex-col gap-3">
      <div class="flex justify-between items-center flex-wrap gap-1">
        <div class="flex items-center gap-2"><span class="badge badge-mono !bg-black !text-white !border-black">SCENE ${String(sc.scene_num).padStart(2, '0')}</span><span class="badge">${escapeHtml(sc.stage || '')}</span></div>
        <span class="text-[11px] font-mono text-neutral-500 flex items-center gap-1"><i data-lucide="clock" class="w-3 h-3"></i> ${escapeHtml(sc.time_range)}</span>
      </div>
      <div class="subtle-box p-3 space-y-1.5">
        <div class="flex items-center justify-between"><span class="card-title flex items-center gap-1"><i data-lucide="mic" class="w-3 h-3"></i> 나레이션</span><div class="flex gap-1">${lenBadge}${durBadge}</div></div>
        ${sc.parse_ok ? `<p class="text-xs text-neutral-900 font-medium leading-relaxed narration-text" data-scene="${sc.scene_num}">"${escapeHtml(sc.subtitle)}"</p>` : '<p class="text-xs text-amber-700">AI 응답에서 이 씬의 대본을 읽지 못했습니다. 아래 "수정"으로 직접 입력할 수 있습니다.</p>'}
        <div class="narration-edit hidden" data-scene="${sc.scene_num}">
          <textarea class="w-full input px-2 py-1.5 text-xs" rows="2" maxlength="120">${escapeHtml(sc.subtitle || '')}</textarea>
          <div class="flex gap-1.5 mt-1.5">
            <button class="btn btn-primary !py-1 narration-save" data-scene="${sc.scene_num}"><i data-lucide="check" class="w-3 h-3"></i> 저장하고 나레이션 다시 만들기</button>
            <button class="btn btn-ghost !py-1 narration-cancel" data-scene="${sc.scene_num}">취소</button>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button class="text-[11px] text-neutral-500 hover:text-black underline narration-edit-btn" data-scene="${sc.scene_num}">✏️ 나레이션 수정</button>
          ${sc.proofread ? `<span class="badge badge-ok" title="원문: ${escapeHtml(sc.original_subtitle || '')}">교정됨</span>` : ''}${sc.edited ? '<span class="badge">직접 수정</span>' : ''}
        </div>
        ${sc.direction ? `<p class="text-[11px] text-neutral-500">연출: ${escapeHtml(sc.direction)}</p>` : ''}
        ${a.audio_url ? `<audio controls src="${a.audio_url}" class="w-full h-7 mt-1" preload="none"></audio>${a.fallback ? `<p class="text-[11px] text-amber-700 mt-0.5">⚠ ${escapeHtml(a.fallback)}</p>` : ''}` : `<p class="text-[11px] text-neutral-400">${a.error ? '오디오: ' + escapeHtml(a.error) : '나레이션 오디오 없음'}</p>`}
      </div>
      <div class="subtle-box p-3 space-y-2">
        <div class="flex justify-between items-center">
          <span class="card-title flex items-center gap-1"><i data-lucide="video" class="w-3 h-3"></i> 영상 프롬프트 ${sc.prompt_ok === false ? '<span class="badge badge-warn">기본값</span>' : ''}</span>
          <button class="btn btn-ghost !py-0.5 !px-2" data-copy="${escapeHtml(sc.prompt_en || '')}" data-msg="영상 프롬프트를 복사했습니다."><i data-lucide="copy" class="w-3 h-3"></i> 복사</button>
        </div>
        <p class="font-mono text-[11px] text-neutral-800 bg-white p-2.5 rounded border border-neutral-200 leading-relaxed">${escapeHtml(sc.prompt_en || '')}</p>
        ${sc.guide_ko ? `<p class="text-[11px] text-neutral-500">${escapeHtml(sc.guide_ko)}</p>` : ''}
      </div>
      <details class="bg-red-50/40 rounded-lg p-3 border border-red-200/60">
        <summary class="cursor-pointer card-title text-red-700 flex items-center justify-between">
          <span>첫 프레임 이미지 프롬프트 (JSON)</span>
          <button class="btn btn-ghost !py-0.5 !px-2 text-red-700" data-copy="${escapeHtml(sc.image_prompt_raw || '')}" data-msg="이미지 프롬프트를 복사했습니다."><i data-lucide="copy" class="w-3 h-3"></i> 복사</button>
        </summary>
        <pre class="code-box light mt-2 max-h-[200px] text-[11px]">${escapeHtml(sc.image_prompt_raw || '')}</pre>
      </details>
    </div>`;
  }).join('');
  $('scenesGrid').querySelectorAll('[data-copy]').forEach((b) => b.addEventListener('click', (e) => { e.preventDefault(); copyText(b.dataset.copy, b.dataset.msg); }));
  $('scenesGrid').querySelectorAll('.narration-edit-btn').forEach((b) => b.addEventListener('click', () => {
    const box = $('scenesGrid').querySelector(`.narration-edit[data-scene="${b.dataset.scene}"]`); box.classList.toggle('hidden');
    if (!box.classList.contains('hidden')) box.querySelector('textarea').focus();
  }));
  $('scenesGrid').querySelectorAll('.narration-cancel').forEach((b) => b.addEventListener('click', () => {
    $('scenesGrid').querySelector(`.narration-edit[data-scene="${b.dataset.scene}"]`).classList.add('hidden');
  }));
  $('scenesGrid').querySelectorAll('.narration-save').forEach((b) => b.addEventListener('click', () => saveNarration(b)));
  $('genResultsSection').style.display = 'block';
  fillPlanSelect($('planHistorySelect'), true); $('planHistorySelect').value = plan.plan_id;
  icons();
}

async function saveNarration(btn) {
  const sceneNum = parseInt(btn.dataset.scene, 10);
  const box = $('scenesGrid').querySelector(`.narration-edit[data-scene="${sceneNum}"]`);
  const text = box.querySelector('textarea').value.trim();
  if (!text) { showToast('나레이션을 입력해주세요.', true); return; }
  setBusy(btn, true, '재합성 중…');
  try {
    const resp = await api('/api/plan/scene', { plan_id: state.plan.plan_id, scene_num: sceneNum, subtitle: text, voice_id: $('voiceSelect').value });
    const plan = await runJob(resp, (job) => { const s = btn.querySelector('span'); if (s) s.textContent = job.message || '재합성 중…'; });
    renderPlan(plan); showToast(`씬 ${sceneNum} 나레이션을 수정하고 오디오를 다시 만들었습니다.`);
    if (state.producePlan?.plan_id === plan.plan_id) state.producePlan = plan;
  } catch (e) { showToast(e.message, true); setBusy(btn, false); }
}

function renderAudioNotice(plan) {
  const box = $('audioNotice'); const a = plan.audio_data; const items = [];
  if (plan.audio_error) items.push(`<div class="notice notice-bad"><i data-lucide="alert-circle" class="w-4 h-4 shrink-0"></i><span>나레이션 합성 실패: ${escapeHtml(plan.audio_error)} — Edge-TTS는 인터넷 연결이 필요합니다.</span></div>`);
  if (a?.engine_note) items.push(`<div class="notice notice-warn"><i data-lucide="alert-triangle" class="w-4 h-4 shrink-0"></i><span>${escapeHtml(a.engine_note)}</span></div>`);
  if (a?.failed_scenes?.length) items.push(`<div class="notice notice-warn"><i data-lucide="alert-triangle" class="w-4 h-4 shrink-0"></i><span>씬 ${a.failed_scenes.join(', ')}의 오디오 합성이 실패했습니다. "나레이션 다시 만들기"를 눌러보세요.</span></div>`);
  if (a?.over_limit_scenes?.length) items.push(`<div class="notice notice-info"><i data-lucide="timer" class="w-4 h-4 shrink-0"></i><span>씬 ${a.over_limit_scenes.join(', ')}의 나레이션이 8초를 넘습니다. 영상 제작 시 '나레이션 길이에 맞춤'이 켜져 있으면 해당 씬이 자동으로 길어집니다.</span></div>`);
  if (plan.quality && plan.quality.scenes_parsed < (plan.structured_scenes || []).length) items.push(`<div class="notice notice-warn"><i data-lucide="alert-triangle" class="w-4 h-4 shrink-0"></i><span>일부 씬의 대본을 AI 응답에서 읽지 못했습니다. 더 큰 모델을 쓰거나 다시 생성하면 개선됩니다.</span></div>`);
  box.innerHTML = items.join(''); box.className = items.length ? 'space-y-2' : ''; icons();
}

function toggleFullAudio() {
  const url = state.plan?.audio_data?.full_audio_url;
  if (!url) { showToast('전체 나레이션 오디오가 없습니다.', true); return; }
  if (state.fullAudio) { stopFullAudio(); return; }
  state.fullAudio = new Audio(url); state.fullAudio.play();
  $('btnPlayFullAudio').innerHTML = '<i data-lucide="square" class="w-3.5 h-3.5"></i> 정지'; icons();
  state.fullAudio.onended = stopFullAudio;
}
function stopFullAudio() {
  if (state.fullAudio) { state.fullAudio.pause(); state.fullAudio = null; }
  $('btnPlayFullAudio').innerHTML = '<i data-lucide="play" class="w-3.5 h-3.5"></i> 전체 나레이션'; icons();
}

async function regenerateAudio() {
  if (!state.plan) return;
  const btn = $('btnRegenerateAudios'); setBusy(btn, true, '합성 중…');
  try {
    const resp = await api('/api/tts/generate-scenes', { plan_id: state.plan.plan_id, voice_id: $('voiceSelect').value });
    const audio = await runJob(resp, (job) => { btn.querySelector('span').textContent = job.message || '합성 중…'; });
    state.plan.audio_data = audio; delete state.plan.audio_error; renderPlan(state.plan);
    showToast(audio.failed_scenes?.length ? `일부 씬(${audio.failed_scenes.join(', ')}) 합성에 실패했습니다.` : '나레이션을 다시 만들었습니다.', !!audio.failed_scenes?.length);
  } catch (e) { showToast(e.message, true); } finally { setBusy(btn, false); }
}

// ── 내 목소리 등록 ────────────────────────────────────────────────────

const rec = { recorder: null, chunks: [], base64: null, active: false };

async function loadStyleGuides() {
  const sel = $('styleGuideSelect'); if (!sel) return;
  const cur = sel.value;
  try {
    const r = await api('/api/knowledge');
    sel.innerHTML = '<option value="">기본 (내장 레드라인 규칙)</option>' +
      (r.guides || []).map((g) => `<option value="${escapeHtml(g.name)}">${escapeHtml(g.name.replace(/\.(md|txt)$/i, ''))}</option>`).join('');
    if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
    else if ([...sel.options].some((o) => o.value === '레드라인.md')) sel.value = '레드라인.md';
  } catch (e) { /* 무시 */ }
}

async function loadVoiceProfiles() {
  const sel = $('voiceSelect'); const cur = sel.value;
  try {
    const d = await api('/api/voice/profiles');
    sel.innerHTML = d.voices.map((v) => `<option value="${escapeHtml(v.id)}" title="${escapeHtml(v.style || '')}">${escapeHtml(v.name)}</option>`).join('');
    if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
    $('cloneAvailabilityNote').innerHTML = d.clone_available
      ? '<i data-lucide="check-circle" class="w-3.5 h-3.5 shrink-0"></i><span>보이스 클로닝(Qwen3-TTS)이 설치되어 있습니다. 등록한 목소리로 나레이션을 합성합니다.</span>'
      : '<i data-lucide="info" class="w-3.5 h-3.5 shrink-0"></i><span>보이스 클로닝 패키지가 설치되어 있지 않습니다. 지금 등록해도 나레이션은 기본 음성(인준)으로 만들어집니다. 사용하려면 <code>pip3 install torch qwen-tts</code> (용량 큼) 후 서버를 재시작하세요.</span>';
    icons();
  } catch (e) { /* 무시 */ }
}

function bindVoiceModal() {
  const panel = $('voiceClonePanel');
  $('btnOpenVoiceModal').addEventListener('click', () => { panel.classList.add('open'); icons(); });
  $('btnCloseVoicePanel').addEventListener('click', () => panel.classList.remove('open'));
  panel.addEventListener('click', (e) => { if (e.target === panel) panel.classList.remove('open'); });

  $('btnRecordVoice').addEventListener('click', async () => {
    const btn = $('btnRecordVoice');
    if (!rec.active) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        rec.chunks = []; rec.recorder = new MediaRecorder(stream);
        rec.recorder.ondataavailable = (e) => { if (e.data.size > 0) rec.chunks.push(e.data); };
        rec.recorder.onstop = async () => {
          const blob = new Blob(rec.chunks, { type: rec.recorder.mimeType || 'audio/webm' });
          $('recordedAudioPreview').src = URL.createObjectURL(blob); $('recordedAudioPreview').style.display = 'block';
          rec.base64 = await fileToDataUrl(blob);
          stream.getTracks().forEach((t) => t.stop());
        };
        rec.recorder.start(); rec.active = true; btn.classList.add('recording-red'); $('recordBtnText').textContent = '녹음 중… (끝나면 클릭)';
      } catch (e) { showToast('마이크 권한이 필요합니다.', true); }
    } else {
      if (rec.recorder && rec.recorder.state !== 'inactive') rec.recorder.stop();
      rec.active = false; btn.classList.remove('recording-red'); $('recordBtnText').textContent = '다시 녹음';
    }
  });
  $('voiceFileInput').addEventListener('change', async (e) => {
    const f = e.target.files[0]; if (!f) return;
    rec.base64 = await fileToDataUrl(f); $('recordedAudioPreview').src = URL.createObjectURL(f); $('recordedAudioPreview').style.display = 'block';
    showToast(`'${f.name}' 첨부됨`);
  });
  $('btnSaveVoiceProfile').addEventListener('click', async () => {
    if (!rec.base64) { showToast('먼저 녹음하거나 음성 파일을 첨부해주세요.', true); return; }
    const btn = $('btnSaveVoiceProfile'); setBusy(btn, true, '저장 중…');
    try {
      const r = await api('/api/voice/upload', { name: $('voiceProfileName').value.trim() || '내 목소리', ref_text: $('voiceRefText').value.trim(), audio_base64: rec.base64 });
      showToast(r.clone_available ? '목소리 프로필을 저장했습니다.' : '프로필을 저장했습니다 (클로닝 패키지가 없어 기본 음성으로 합성됩니다).', !r.clone_available);
      panel.classList.remove('open'); await loadVoiceProfiles(); $('voiceSelect').value = `custom:${r.profile.id}`;
    } catch (e) { showToast(e.message, true); } finally { setBusy(btn, false); }
  });
}

// ══════════════════════════ ③ 제작 · 업로드 ══════════════════════════

function bindProducer() {
  $('producePlanSelect').addEventListener('change', (e) => { if (e.target.value) loadProducePlan(e.target.value); });
  $('btnSaveGeminiKey').addEventListener('click', async () => {
    try {
      const r = await api('/api/settings', { gemini_api_key: $('geminiKeyInput').value.trim() });
      state.env = r.env;
      $('geminiKeyInput').value = '';
      renderEnvRow();
      if (r.key_valid === true) showToast('✓ API 키 저장 — 인증 확인됨');
      else if (r.key_valid === false) showToast(`키를 저장했지만 인증에 실패했습니다: ${r.key_message}. 키를 다시 확인하세요.`, true);
      else showToast(r.env.gemini_key_set ? 'API 키를 저장했습니다.' : 'API 키를 지웠습니다.');
    } catch (e) { showToast(e.message, true); }
  });
  $('btnGenerateImages').addEventListener('click', generateImages);
  $('btnGenerateVideos').addEventListener('click', () => generateVideos(null));  // 이벤트 객체가 slots 로 넘어가지 않도록
  $('btnAutoProduce').addEventListener('click', autoProduce);
  $('btnReviewContinue')?.addEventListener('click', () => { $('reviewBar').style.display = 'none'; autoProduce(); });
  $('btnReviewStop')?.addEventListener('click', () => { $('reviewBar').style.display = 'none'; showToast('중단했습니다. 이미지는 저장돼 있으니 언제든 "▶ 완성 영상 만들기"로 이어서 진행하세요.'); });
  $('btnBuildVideo').addEventListener('click', buildVideo);
  $('videoQualitySelect').addEventListener('change', updateCostEstimate);
  $('btnYtConnect').addEventListener('click', connectYoutube);
  $('ytSecretFile')?.addEventListener('change', async (e) => {
    const f = e.target.files[0]; if (!f) return;
    try {
      const r = await api('/api/youtube/secret', { data_base64: await fileToDataUrl(f) });
      state.youtube = r.youtube; renderYoutube();
      showToast('client_secret.json 저장 완료 — 이제 "유튜브 계정 연결"을 누르세요.');
    } catch (err) { showToast(err.message, true); }
    e.target.value = '';
  });
  $('btnYtDisconnect').addEventListener('click', async () => {
    try {
      const r = await api('/api/youtube/disconnect', {});
      state.youtube = r.youtube;
      renderYoutube();
      showToast('연결을 해제했습니다.');
    } catch (e) { showToast(e.message, true); }
  });
  $('btnYtUpload').addEventListener('click', uploadYoutube);
}

async function loadProducePlan(planId) {
  try {
    const r = await api(`/api/plan?id=${encodeURIComponent(planId)}`);
    state.producePlan = r.data;
    try { localStorage.setItem('ti_last_plan', r.data.plan_id); } catch (e) {}
    const p = r.data;
    const sceneCount = (p.structured_scenes || []).length;
    $('producePlanSummary').textContent = `${sceneCount}씬 · ${p.aspect_ratio} · ${p.audio_data?.full_audio_url ? '나레이션 있음' : '나레이션 없음'}`;
    $('ytTitle').value = p.meta?.recommended?.title || p.topic || '';
    $('ytDescription').value = p.description_plain || '';
    $('ytTags').value = (p.meta?.description?.hashtags || []).map((h) => h.replace(/^#/, '')).join(', ');
    await refreshProduceStatus();
    updateCostEstimate();
  } catch (e) { showToast(e.message, true); }
}

function updateCostEstimate() {
  const p = state.producePlan;
  const numScenes = (p?.structured_scenes || []).length || 10;
  const quality = $('videoQualitySelect')?.value || '360p';
  const secPerScene = 10;
  const usdPerSec = 0.10;
  const ratio = { '360p': 1 / 3, '720p': 1.0, '1080p': 1.0 }[quality] || (1 / 3);
  const usd = numScenes * secPerScene * usdPerSec * ratio;
  const krw = Math.round(usd * 1400 / 10) * 10;
  const badge = $('videoCostEstimateBadge');
  if (badge) {
    badge.textContent = `💰 ${numScenes}장면 예상: 약 $${usd.toFixed(2)} (${krw.toLocaleString()}원)`;
  }
}

async function refreshProduceStatus() {
  const planId = state.producePlan?.plan_id;
  try {
    const r = await api(`/api/render/status?plan_id=${encodeURIComponent(planId || '')}`);
    state.env = r.env;
    state.youtube = r.youtube;
    state.media = r.media || {};
    state.render = r.render;
    renderEnvRow();
    renderMediaGrid();
    renderRenderResult();
    renderYoutube();
  } catch (e) { showToast(e.message, true); }
}

function renderEnvRow() {
  const env = state.env || {};
  const set = (id, ok, okText, badText) => {
    const el = $(id);
    if (!el) return;
    el.textContent = ok ? okText : badText;
    el.className = 'badge ' + (ok ? 'badge-ok' : 'badge-warn');
  };
  set('envFfmpeg', env.ffmpeg, '사용 가능', '없음 — pip3 install imageio-ffmpeg');
  set('envFont', !!env.font, (env.font || '').split('/').pop(), '없음 — 자막 굽기 불가');
  set('envGemini', env.gemini_key_set, '저장됨', '미설정');
  set('envFile', env.has_env_file, '.env 연동됨', '.env 없음');

  const hasKey = !!env.gemini_key_set;
  if ($('btnGenerateImages')) {
    $('btnGenerateImages').disabled = !hasKey;
    $('btnGenerateImages').title = hasKey ? '' : 'Gemini API 키를 먼저 저장하세요';
  }
  if ($('btnGenerateVideos')) {
    $('btnGenerateVideos').disabled = !hasKey;
    $('btnGenerateVideos').title = hasKey ? '' : 'Gemini API 키를 먼저 저장하세요';
  }
  if ($('btnAutoProduce')) {
    $('btnAutoProduce').disabled = false;
    $('btnAutoProduce').title = hasKey ? '' : 'Gemini API 키가 없으면 이미지·영상 생성은 건너뛰고, 넣어 둔 미디어와 나레이션만으로 합성합니다';
  }
}

function renderMediaGrid() {
  const grid = $('mediaGrid');
  const p = state.producePlan;
  if (!p) {
    grid.innerHTML = '<p class="text-xs text-neutral-400 col-span-full">기획서를 선택하세요.</p>';
    return;
  }
  const slots = [
    ...(p.structured_scenes || []).map((s) => ({
      slot: String(s.scene_num),
      label: `씬 ${String(s.scene_num).padStart(2, '0')}`,
      sub: s.subtitle,
    })),
    { slot: 'thumbnail', label: '썸네일', sub: '유튜브 썸네일 (이미지)' },
  ];

  grid.innerHTML = slots
    .map(({ slot, label, sub }) => {
      const m = state.media[slot];
      let tagBadge = '';
      if (m) {
        if (m.source === 'omni' || (m.type === 'video' && m.source !== 'upload')) {
          tagBadge = `<span class="badge media-tag badge-purple">AI 영상 (Omni)</span>`;
        } else if (m.source === 'gemini' || m.source === 'nanobanana') {
          tagBadge = `<span class="badge media-tag badge-red">AI 이미지</span>`;
        } else {
          tagBadge = `<span class="badge media-tag">${m.type === 'video' ? '영상 클립' : '이미지'}</span>`;
        }
      }

      return `<div class="space-y-1">
      <div class="dropzone" data-slot="${slot}" title="클릭하거나 파일을 끌어다 놓으세요">
        ${
          m
            ? m.type === 'video'
              ? `<video src="${m.url}${m.trim_start ? '#t=' + (Number(m.trim_start) + 0.5) : ''}" muted preload="metadata" playsinline></video>`
              : `<img src="${m.url}?t=${Date.now()}" alt="">`
            : `<i data-lucide="${slot === 'thumbnail' ? 'image' : 'image-plus'}" class="w-6 h-6"></i><span>${
                slot === 'thumbnail' ? '썸네일 이미지' : '이미지 / AI 영상'
              }</span>`
        }
        ${tagBadge}
        ${
          m
            ? `<button class="btn btn-danger !py-0.5 !px-1.5 media-remove" data-remove="${slot}" title="${m && m.type === 'video' ? '영상 제거 (첫 프레임 이미지로 되돌아감)' : '제거'}"><i data-lucide="x" class="w-3 h-3"></i></button>`
            : ''
        }
      </div>
      <div class="flex items-center justify-between gap-1">
        <div class="text-[11px] font-bold text-neutral-700">${label}</div>
        ${slot !== 'thumbnail' ? `<button class="text-[10px] text-purple-700 hover:underline scene-video-btn" data-slot="${slot}" title="이 씬만 AI 영상 생성 (현재 화질 설정 적용, 첫 프레임 이미지는 유지)">${m && m.type === 'video' ? '🎬 이 씬만 다시' : '🎬 이 씬만 AI 영상'}</button>` : ''}
      </div>
      <div class="text-[10px] text-neutral-400 truncate" title="${escapeHtml(sub || '')}">${escapeHtml(sub || '')}</div>
    </div>`;
    })
    .join('');

  grid.querySelectorAll('.dropzone').forEach((z) => {
    z.addEventListener('click', (e) => {
      if (e.target.closest('[data-remove]')) return;
      pickMedia(z.dataset.slot);
    });
    z.addEventListener('dragover', (e) => {
      e.preventDefault();
      z.classList.add('over');
    });
    z.addEventListener('dragleave', () => z.classList.remove('over'));
    z.addEventListener('drop', (e) => {
      e.preventDefault();
      z.classList.remove('over');
      const f = e.dataTransfer.files[0];
      if (f) uploadMedia(z.dataset.slot, f);
    });
  });

  grid.querySelectorAll('.scene-video-btn').forEach((b) => b.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!state.env?.gemini_key_set) { showToast('Gemini API 키를 먼저 저장하세요.', true); return; }
    generateVideos([b.dataset.slot]);
  }));
  grid.querySelectorAll('[data-remove]').forEach((b) =>
    b.addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        const r = await api('/api/render/media/delete', {
          plan_id: state.producePlan.plan_id,
          slot: b.dataset.remove,
        });
        state.media = r.media;
        renderMediaGrid();
      } catch (err) {
        showToast(err.message, true);
      }
    })
  );
  const sceneSlots = (p.structured_scenes || []).map((s) => String(s.scene_num));
  const nVideo = sceneSlots.filter((s) => state.media[s]?.type === 'video').length;
  const nImage = sceneSlots.filter((s) => state.media[s]?.type === 'image').length;
  const nEmpty = sceneSlots.length - nVideo - nImage;
  const gi = $('btnGenerateImages'); if (gi && !gi.disabled) gi.innerHTML = `<i data-lucide="wand-2" class="w-3.5 h-3.5"></i> ${nImage + nVideo + (state.media['thumbnail'] ? 1 : 0) === sceneSlots.length + 1 ? '이미지 모두 준비됨' : '비어 있는 ' + (sceneSlots.length - nImage - nVideo + (state.media['thumbnail'] ? 0 : 1)) + '칸 이미지 생성'}`;
  const gv = $('btnGenerateVideos'); if (gv && !gv.disabled) gv.innerHTML = `<i data-lucide="video" class="w-3.5 h-3.5"></i> ${nVideo === sceneSlots.length ? '모든 씬 AI 영상 있음' : 'AI 영상 없는 ' + (sceneSlots.length - nVideo) + '씬 생성'}`;
  renderNextStepGuide(sceneSlots.length, nVideo, nImage, nEmpty);
  icons();
}

// ③ 상단: 현재 상태를 보고 "지금 눌러야 할 버튼"을 한 줄로 안내
function renderNextStepGuide(total, nVideo, nImage, nEmpty) {
  const box = $('nextStepGuide'); if (!box) return;
  const p = state.producePlan; if (!p) { box.innerHTML = ''; return; }
  const audioOk = (p.audio_data?.scenes_audio || []).filter((s) => s.audio_url).length;
  const voice = p.audio_data?.voice_id || '';
  const voiceName = voice.startsWith('custom:') ? '내 목소리(Qwen)' : ({ 'ko-KR-InJoonNeural': '인준', 'ko-KR-SunHiNeural': '선희', 'ko-KR-HyunsuNeural': '현수' }[voice] || voice || '없음');
  const hasRender = !!state.render;
  const steps = [
    { name: '이미지', done: nEmpty === 0, detail: `${nImage + nVideo}/${total}` },
    { name: 'AI 영상', done: nVideo === total, detail: `${nVideo}/${total}` },
    { name: '나레이션', done: audioOk === total, detail: `${audioOk}/${total} · ${voiceName}` },
    { name: '합성', done: hasRender, detail: hasRender ? `${Math.round(state.render.duration || 0)}초` : '' },
    { name: '업로드', done: false, detail: state.youtube?.authorized ? '연결됨' : '나중에' },
  ];
  let next, tone = 'info';
  const vidCost = videoCostKrw(total - nVideo, $('videoQualitySelect')?.value || '360p');
  if (audioOk < total) next = `②탭에서 이 기획서를 불러와 <b>"나레이션 다시 만들기"</b>를 누르세요 (무료). 씬 ${total - audioOk}개에 나레이션이 없습니다.`;
  else if (nEmpty > 0) next = `1번 카드의 <b>"비어 있는 ${nEmpty + (state.media['thumbnail'] ? 0 : 1)}칸 이미지 생성"</b> (이미 있는 이미지는 다시 만들지 않음)`;
  else if (!hasRender) next = `3번 카드의 <b>"지금 재료로 합성하기"</b>를 누르면 영상이 완성됩니다 (무료 — 이미지는 켄번즈로 움직임).${nVideo < total ? ` 씬을 <b>진짜 움직이는 AI 영상</b>으로 만들고 싶으면 그 전에 2번 (약 $${vidCost.usd.toFixed(2)}, 선택).` : ''}`;
  else if (nVideo < total) { tone = 'ok'; next = `<b>✅ 영상 완성!</b> (이미지 켄번즈 기반) — 이대로 저장·업로드해도 됩니다.<br><span class="text-neutral-600">선택 업그레이드: 정지 이미지를 진짜 움직이는 영상으로 바꾸려면 2번 "AI 영상 없는 ${total - nVideo}씬 생성"(약 $${vidCost.usd.toFixed(2)}) → 3번 다시 합성.</span>`; }
  else { tone = 'ok'; next = `<b>✅ AI 영상 기반 완성!</b> 3번에서 미리보기·<b>mp4 저장</b>. 마음에 안 드는 씬은 "이 씬만 다시" 후 재합성. 업로드는 4번.`; }
  box.innerHTML = `
    <div class="flex items-center gap-1 flex-wrap text-[11px] mb-2">${steps.map((s, i) => `<span class="badge ${s.done ? 'badge-ok' : ''}">${s.done ? '✓' : (i + 1)} ${s.name}${s.detail ? ' ' + s.detail : ''}</span>${i < steps.length - 1 ? '<span class="text-neutral-300">→</span>' : ''}`).join('')}</div>
    <div class="notice notice-${tone}"><i data-lucide="${tone === 'ok' ? 'check-circle' : 'arrow-right-circle'}" class="w-4 h-4 shrink-0 mt-0.5"></i><div>${tone === 'ok' ? '' : '<b>다음 할 일:</b> '}${next}</div></div>`;
  icons();
}

function pickMedia(slot) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = slot === 'thumbnail' ? 'image/*' : 'image/*,video/mp4,video/quicktime,video/webm';
  input.onchange = () => {
    if (input.files[0]) uploadMedia(slot, input.files[0]);
  };
  input.click();
}

async function uploadMedia(slot, file) {
  if (file.size > 35 * 1024 * 1024) {
    showToast('35MB 이하 파일만 넣을 수 있습니다.', true);
    return;
  }
  try {
    showToast(`'${file.name}' 업로드 중…`);
    const r = await api('/api/render/media', {
      plan_id: state.producePlan.plan_id,
      slot,
      filename: file.name,
      data_base64: await fileToDataUrl(file),
    });
    state.media = r.media;
    renderMediaGrid();
    showToast(`${slot === 'thumbnail' ? '썸네일' : '씬 ' + slot}에 넣었습니다.`);
  } catch (e) {
    showToast(e.message, true);
  }
}

async function generateImages() {
  if (!state.producePlan) return;
  const mc = mediaCounts();
  if (mc.imagesMissing === 0) { showToast('이미지가 모두 준비되어 있습니다. 바꾸려면 해당 칸의 ✕로 지운 뒤 다시 생성하세요.'); return; }
  if (!confirm(`비어 있는 ${mc.imagesMissing}칸(씬 ${mc.noImage.length}개${!state.media['thumbnail'] ? ' + 썸네일' : ''})의 이미지를 생성합니다.\n이미 있는 이미지는 다시 만들지 않습니다.\n예상 비용: 약 $${(mc.imagesMissing * IMAGE_USD).toFixed(2)} — Gemini API에 과금됩니다.\n\n진행할까요?`)) return;
  const btn = $('btnGenerateImages');
  setBusy(btn, true, '이미지 생성 중…');
  $('imagesNotice').innerHTML = '';
  try {
    const resp = await api('/api/render/images', { plan_id: state.producePlan.plan_id });
    const r = await runJob(resp, (job) => {
      if (btn.querySelector('span')) btn.querySelector('span').textContent = job.message;
    });
    state.media = r.media;
    renderMediaGrid();
    if (r.errors?.length) {
      $('imagesNotice').innerHTML = `<div class="notice notice-warn mb-3"><i data-lucide="alert-triangle" class="w-4 h-4 shrink-0"></i><div>${r.errors
        .map((e) => `<div>${escapeHtml(e.slot === 'thumbnail' ? '썸네일' : '씬 ' + e.slot)}: ${escapeHtml(e.error)}</div>`)
        .join('')}</div></div>`;
    }
    showToast(
      `이미지 ${r.generated.length}개 생성${r.errors?.length ? `, ${r.errors.length}개 실패` : ''}`,
      !!r.errors?.length
    );
    icons();
  } catch (e) {
    showToast(e.message, true);
  } finally {
    setBusy(btn, false);
  }
}

const IMAGE_USD = 0.13;  // 나노바나나 프로 이미지 1장 대략 (실제 청구는 구글 요금표 기준)
function mediaCounts() {
  const ss = (state.producePlan?.structured_scenes || []).map((s) => String(s.scene_num));
  const noVideo = ss.filter((s) => state.media[s]?.type !== 'video');
  const noImage = ss.filter((s) => !state.media[s]);
  const thumbMissing = !state.media['thumbnail'];
  return { scenes: ss, noVideo, noImage, imagesMissing: noImage.length + (thumbMissing ? 1 : 0), hasVideo: ss.length - noVideo.length };
}
function videoCostKrw(numScenes, quality) {
  const ratio = { '360p': 1 / 3, '720p': 1.0, '1080p': 1.0 }[quality] || (1 / 3);
  const usd = numScenes * 10 * 0.10 * ratio;
  return { usd, krw: Math.round(usd * 1400 / 10) * 10 };
}

async function generateVideos(slots = null) {
  if (!Array.isArray(slots)) slots = null;
  if (!state.producePlan) return;
  const mc = mediaCounts();
  const count = slots ? slots.length : mc.noVideo.length;
  if (!slots && count === 0) { showToast('모든 씬에 이미 AI 영상이 있습니다. 특정 씬을 다시 만들려면 씬 카드의 "이 씬만 다시"를 누르세요.'); return; }
  const q = $('videoQualitySelect')?.value || '360p';
  const cost = videoCostKrw(count, q);
  const skipNote = !slots && mc.hasVideo ? `\n(이미 AI 영상이 있는 ${mc.hasVideo}개 씬은 다시 만들지 않습니다)` : '';
  if (!confirm(`AI 영상 ${count}개 (${q}) 를 생성합니다.${skipNote}\n예상 비용: 약 $${cost.usd.toFixed(2)} (${cost.krw.toLocaleString()}원) — Gemini API에 과금됩니다.\n\n진행할까요?`)) return;
  const btn = $('btnGenerateVideos');
  setBusy(btn, true, 'Omni 영상 생성 중…');
  const pBox = $('videosProgressBox');
  const pFill = $('videosProgressFill');
  const pMsg = $('videosProgressMsg');
  if (pBox) pBox.style.display = 'block';
  if ($('videosNotice')) $('videosNotice').innerHTML = '';

  try {
    const quality = $('videoQualitySelect')?.value || '360p';
    const resp = await api('/api/render/videos', {
      plan_id: state.producePlan.plan_id,
      quality,
      chain: $('videoChain')?.checked !== false,
      slots: slots || undefined,
      skip_existing: true,
    });
    const r = await runJob(resp, (job) => {
      if (pFill) pFill.style.width = `${job.progress || 10}%`;
      if (pMsg) pMsg.textContent = job.message || '영상 생성 중...';
    });
    state.media = r.media;
    renderMediaGrid();
    if (r.errors?.length && $('videosNotice')) {
      $('videosNotice').innerHTML = `<div class="notice notice-warn mb-3"><i data-lucide="alert-triangle" class="w-4 h-4 shrink-0"></i><div>${r.errors
        .map((e) => `<div>씬 ${escapeHtml(e.slot)}: ${escapeHtml(e.error)}</div>`)
        .join('')}</div></div>`;
    }
    showToast(`AI 영상 ${r.generated.length}개 생성 완료${r.skipped?.length ? ` (이미 있던 ${r.skipped.length}개는 유지)` : ''}`, !!r.errors?.length);
    icons();
  } catch (e) {
    showToast(e.message, true);
    if (pMsg) pMsg.textContent = `❌ ${e.message}`;
  } finally {
    setBusy(btn, false);
    if (pBox) setTimeout(() => { pBox.style.display = 'none'; }, 3000);
  }
}

async function autoProduce() {
  if (!state.producePlan) {
    showToast('기획서를 먼저 선택하세요.', true);
    return;
  }
  const mcPre = mediaCounts();
  const wantVideos = $('autoIncludeVideos')?.checked || false;
  // 검수 모드: 유료 영상 생성 전에 이미지를 먼저 만들어 보여주고 멈춤 (이미지가 이미 다 있으면 건너뜀)
  if (wantVideos && $('reviewImages')?.checked !== false && mcPre.imagesMissing > 0) {
    if (!confirm(`1단계: 비어 있는 이미지 ${mcPre.imagesMissing}개를 먼저 생성합니다 (약 $${(mcPre.imagesMissing * IMAGE_USD).toFixed(2)}).\n생성 후 이미지를 확인하고 나서 AI 영상(유료)으로 진행합니다.\n\n시작할까요?`)) return;
    const btn0 = $('btnAutoProduce'); setBusy(btn0, true, '1단계: 이미지 생성 중…');
    try {
      const resp = await api('/api/render/images', { plan_id: state.producePlan.plan_id });
      const r = await runJob(resp);
      state.media = r.media; renderMediaGrid();
      if (r.errors?.length) showToast(`이미지 ${r.errors.length}개 실패 — 목록을 확인하세요.`, true);
      const ms = $('manualSteps'); if (ms) ms.open = true;
      $('reviewBar').style.display = 'block'; icons();
      $('reviewBar').scrollIntoView({ behavior: 'smooth' });
    } catch (e) { showToast(e.message, true); }
    finally { setBusy(btn0, false); }
    return;  // 사용자가 검수 후 [계속]을 누르면 autoProduceContinue()가 이어감
  }
  const btn = $('btnAutoProduce');
  setBusy(btn, true, '전체 자동 제작 중…');
  const pBox = $('autoProgressBox');
  const pFill = $('autoProgressFill');
  const pMsg = $('autoProgressMsg');
  if (pBox) pBox.style.display = 'block';
  $('renderResult').style.display = 'none';

  try {
    const includeVideos = $('autoIncludeVideos')?.checked || false;
    const quality = $('videoQualitySelect')?.value || '360p';
    {
      const mc = mediaCounts();
      const nVid = includeVideos ? mc.noVideo.length : 0;
      const vc = videoCostKrw(nVid, quality);
      const imgUsd = mc.imagesMissing * IMAGE_USD;
      const lines = [`이미 있는 이미지·AI 영상은 다시 만들지 않습니다.`, ``,
        `• 이미지 생성: ${mc.imagesMissing}개 (약 $${imgUsd.toFixed(2)})`,
        includeVideos ? `• AI 영상 생성: ${nVid}개 · ${quality} (약 $${vc.usd.toFixed(2)}, ${vc.krw.toLocaleString()}원)` : `• AI 영상: 생성 안 함 (이미지 켄번즈로 합성)`,
        `• 나레이션·자막 합성: 무료`, ``,
        (mc.imagesMissing + nVid) === 0 ? `과금 없이 합성만 진행합니다. 진행할까요?` : `진행할까요?`];
      if (!confirm(lines.join('\n'))) { setBusy(btn, false); if (pBox) pBox.style.display = 'none'; return; }
    }
    const resolution = $('renderResolution')?.value || '1080p';
    const burnSubtitles = $('burnSubtitles')?.checked !== false;
    const fitNarration = $('fitNarration')?.checked !== false;

    const resp = await api('/api/render/auto', {
      plan_id: state.producePlan.plan_id,
      include_videos: includeVideos,
      quality,
      resolution,
      burn_subtitles: burnSubtitles,
      fit_narration: fitNarration,
      chain: $('videoChain')?.checked !== false,
      subtitle_style: $('subtitleStyleSelect')?.value || 'outline',
      transition: $('transitionSelect')?.value || 'fade',
    });

    state.render = await runJob(resp, (job) => {
      if (pFill) pFill.style.width = `${job.progress || 10}%`;
      if (pMsg) pMsg.textContent = job.message || '진행 중...';
    });

    await refreshProduceStatus();
    renderRenderResult();
    showToast(state.render?.warnings?.length ? `영상은 완성됐지만 경고 ${state.render.warnings.length}건이 있습니다 — 아래 목록을 확인하세요.` : '원클릭 영상 제작이 완료되었습니다!', !!state.render?.warnings?.length);
    loadHistory();
  } catch (e) {
    showToast(e.message, true);
    if (pMsg) pMsg.textContent = `❌ ${e.message}`;
  } finally {
    setBusy(btn, false);
    if (pBox) setTimeout(() => { pBox.style.display = 'none'; }, 4000);
  }
}

async function buildVideo() {
  if (!state.producePlan) {
    showToast('기획서를 먼저 선택하세요.', true);
    return;
  }
  const btn = $('btnBuildVideo');
  setBusy(btn, true, '합성 중…');
  $('renderResult').style.display = 'none';
  setProgress('render', { progress: 2, message: '준비 중...' });
  try {
    const resp = await api('/api/render/build', {
      plan_id: state.producePlan.plan_id,
      resolution: $('renderResolution').value,
      burn_subtitles: $('burnSubtitles').checked,
      fit_narration: $('fitNarration').checked,
      subtitle_style: $('subtitleStyleSelect')?.value || 'outline',
      transition: $('transitionSelect')?.value || 'fade',
    });
    state.render = await runJob(resp, (job) => setProgress('render', job));
    hideProgress('render');
    renderRenderResult();
    showToast('영상이 완성되었습니다.');
    loadHistory();
  } catch (e) {
    setProgress('render', { progress: 100, message: `❌ ${e.message}` });
    showToast(e.message, true);
  } finally {
    setBusy(btn, false);
  }
}

function renderRenderResult() {
  const r = state.render;
  const box = $('renderResult');
  if (state.producePlan) { const ss = (state.producePlan.structured_scenes || []).map((s) => String(s.scene_num)); renderNextStepGuide(ss.length, ss.filter((s) => state.media[s]?.type === 'video').length, ss.filter((s) => state.media[s]?.type === 'image').length, ss.filter((s) => !state.media[s]).length); }
  if (!r) {
    box.style.display = 'none';
    return;
  }
  box.style.display = 'block';
  const v = $('renderVideo');
  v.src = `${r.video_url}?t=${Date.now()}`;
  $('btnDownloadVideo').href = r.video_url;
  $('btnDownloadVideo').download = `${state.producePlan?.topic || 'video'}.mp4`;
  $('renderInfo').innerHTML = [
    `<span class="badge badge-ok">완성</span>`,
    `<span class="badge badge-mono">${r.resolution}</span>`,
    `<span class="badge badge-mono">${r.duration ? Math.round(r.duration) + '초' : ''}</span>`,
    `<span class="badge">${r.scenes}씬</span>`,
    (() => { const ss = (state.producePlan?.structured_scenes || []).map((s) => String(s.scene_num)); const nv = ss.filter((s) => state.media[s]?.type === 'video').length; return `<span class="badge ${nv === ss.length ? 'badge-ok' : 'badge-warn'}">AI 영상 ${nv}/${ss.length} · 이미지 ${ss.length - nv}</span>`; })(),
    r.subtitles_burned ? '<span class="badge">자막 포함</span>' : '<span class="badge badge-warn">자막 없음</span>',
    r.thumbnail_url ? '<span class="badge">썸네일 준비됨</span>' : '<span class="badge badge-warn">썸네일 없음</span>',
  ].join('');
  $('renderWarnings').innerHTML = (r.warnings || []).map((w) => `<div class="text-[11px] text-amber-700">• ${escapeHtml(w)}</div>`).join('');
  icons();
}

function renderYoutube() {
  const y = state.youtube || {};
  const badge = $('ytStatusBadge');
  const ready = y.libs && y.client_secret;
  if (y.authorized) {
    badge.textContent = y.channel ? `연결됨 · ${y.channel.title}` : '연결됨';
    badge.className = 'badge badge-ok';
  } else if (ready) {
    badge.textContent = '계정 미연결';
    badge.className = 'badge badge-warn';
  } else {
    badge.textContent = '설정 필요';
    badge.className = 'badge badge-warn';
  }
  $('ytStatusText').innerHTML = y.authorized
    ? `<b>${escapeHtml(y.channel?.title || '내 채널')}</b>${y.channel?.subscribers ? ` · 구독자 ${fmtNum(+y.channel.subscribers)}명` : ''} 계정으로 업로드합니다.`
    : !y.libs
    ? '구글 API 패키지가 없습니다: <code>pip3 install google-api-python-client google-auth-oauthlib</code>'
    : !y.client_secret
    ? '<code>data/youtube/client_secret.json</code> 파일이 없습니다. 아래 안내를 따라 준비해주세요.'
    : '준비가 끝났습니다. 연결 버튼을 누르면 브라우저에서 구글 로그인 창이 열립니다.';
  if (y.error) $('ytStatusText').innerHTML += `<div class="text-amber-700 mt-1">${escapeHtml(y.error)}</div>`;
  $('btnYtConnect').style.display = y.authorized ? 'none' : '';
  $('btnYtConnect').disabled = !ready;
  $('btnYtDisconnect').style.display = y.authorized ? '' : 'none';
  $('ytSetupHelp').open = !ready;
  $('btnYtUpload').disabled = !y.authorized;
}

async function connectYoutube() {
  const btn = $('btnYtConnect');
  setBusy(btn, true, '브라우저에서 로그인 중…');
  try {
    const resp = await api('/api/youtube/auth', {});
    showToast('브라우저 창에서 구글 로그인과 권한 허용을 진행해주세요.');
    const r = await runJob(resp);
    await refreshProduceStatus();
    showToast(`'${r.channel?.title || '채널'}' 연결 완료`);
  } catch (e) {
    showToast(e.message, true);
  } finally {
    setBusy(btn, false);
    renderYoutube();
  }
}

async function uploadYoutube() {
  if (!state.render) {
    showToast('먼저 영상을 만들어주세요.', true);
    return;
  }
  const privacy = $('ytPrivacy').value;
  const publishLocal = $('ytPublishAt').value;
  const publish_at = publishLocal ? new Date(publishLocal).toISOString() : null;
  if (
    !confirm(
      `'${$('ytTitle').value}'\n\n공개 상태: ${{ private: '비공개', unlisted: '일부 공개', public: '공개' }[privacy]}${
        publish_at ? `\n예약 공개: ${publishLocal.replace('T', ' ')}` : ''
      }\n\n유튜브에 업로드할까요?`
    )
  )
    return;
  const btn = $('btnYtUpload');
  setBusy(btn, true, '업로드 중…');
  $('uploadResult').innerHTML = '';
  setProgress('upload', { progress: 2, message: '준비 중...' });
  try {
    const resp = await api('/api/youtube/upload', {
      plan_id: state.producePlan.plan_id,
      title: $('ytTitle').value.trim(),
      description: $('ytDescription').value,
      tags: $('ytTags').value,
      privacy,
      publish_at,
    });
    const r = await runJob(resp, (job) => setProgress('upload', job));
    hideProgress('upload');
    $('uploadResult').innerHTML = `<div class="notice notice-ok"><i data-lucide="check-circle" class="w-4 h-4 shrink-0"></i><div><b>업로드 완료</b> · <a href="${
      r.url
    }" target="_blank" rel="noopener" class="underline">${r.url}</a><div class="text-[11px] mt-1">공개 상태: ${r.privacy}${
      r.publish_at ? ' · 예약됨' : ''
    }${r.thumbnail_set ? ' · 썸네일 설정됨' : ''}</div>${(r.warnings || [])
      .map((w) => `<div class="text-[11px] text-amber-700 mt-1">• ${escapeHtml(w)}</div>`)
      .join('')}</div></div>`;
    showToast('유튜브 업로드가 완료되었습니다.');
    icons();
  } catch (e) {
    setProgress('upload', { progress: 100, message: `❌ ${e.message}` });
    showToast(e.message, true);
  } finally {
    setBusy(btn, false);
  }
}


// ── 4단계: ✍️ 멀티채널 마케팅 & SNS 스튜디오 로직 ───────────────────────

function bindMarketing() {
  // 소스 전환 버튼
  $('btnSyncFromAnalysis')?.addEventListener('click', () => syncMarketingWithCurrentState('analysis'));
  $('btnSyncFromPlan')?.addEventListener('click', () => syncMarketingWithCurrentState('plan'));
  $('btnSyncCustom')?.addEventListener('click', () => syncMarketingWithCurrentState('custom'));

  // 컨텍스트 펼치기/접기
  $('btnToggleContext')?.addEventListener('click', () => {
    const wrap = $('marketingContextWrapper');
    if (wrap) wrap.style.display = wrap.style.display === 'none' ? 'block' : 'none';
  });

  // 분석 / 기획 화면의 바로가기 버튼 연동
  $('btnGoMarketingFromAnalysis')?.addEventListener('click', () => {
    syncMarketingWithCurrentState('analysis');
    setMode('marketing');
  });
  $('btnGoMarketingFromPlan')?.addEventListener('click', () => {
    syncMarketingWithCurrentState('plan');
    setMode('marketing');
  });

  // 3대 탭 전환
  document.querySelectorAll('.marketing-tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.marketing-tab-btn').forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('.marketing-pane').forEach((p) => p.style.display = 'none');
      btn.classList.add('active');
      const target = $(btn.dataset.target);
      if (target) target.style.display = 'block';
      icons();
    });
  });

  // 1. 올인원 일괄 생성
  $('btnRunMarketingAll')?.addEventListener('click', () => executeMarketingGeneration('all'));

  // 2. 개별 채널 생성
  $('btnRunThreadX')?.addEventListener('click', () => executeMarketingGeneration('threads'));
  $('btnRunBlog')?.addEventListener('click', () => executeMarketingGeneration('blog'));
  $('btnRunNewsletter')?.addEventListener('click', () => executeMarketingGeneration('newsletter'));

  // 블로그 뷰어 모드 토글 (렌더링 vs 마크다운 원본)
  $('btnBlogViewRendered')?.addEventListener('click', () => {
    $('btnBlogViewRendered').className = 'px-2.5 py-1 rounded-md bg-white shadow-sm text-black';
    $('btnBlogViewRaw').className = 'px-2.5 py-1 rounded-md text-neutral-500';
    $('blogRenderedViewer').style.display = 'block';
    $('blogRawTextarea').style.display = 'none';
  });
  $('btnBlogViewRaw')?.addEventListener('click', () => {
    $('btnBlogViewRaw').className = 'px-2.5 py-1 rounded-md bg-white shadow-sm text-black';
    $('btnBlogViewRendered').className = 'px-2.5 py-1 rounded-md text-neutral-500';
    $('blogRenderedViewer').style.display = 'none';
    $('blogRawTextarea').style.display = 'block';
  });

  // 뉴스레터 뷰어 모드 토글 (PC 640px vs 모바일 375px vs 텍스트)
  $('btnNewsViewDesktop')?.addEventListener('click', () => {
    $('btnNewsViewDesktop').className = 'px-2.5 py-1 rounded-md bg-white shadow-sm text-black flex items-center gap-1';
    $('btnNewsViewMobile').className = 'px-2.5 py-1 rounded-md text-neutral-500 flex items-center gap-1';
    $('btnNewsViewPlain').className = 'px-2.5 py-1 rounded-md text-neutral-500 flex items-center gap-1';
    $('newsPreviewFrameContainer').style.display = 'flex';
    $('newsIframePreview').style.maxWidth = '640px';
    $('newsPlainViewer').style.display = 'none';
  });
  $('btnNewsViewMobile')?.addEventListener('click', () => {
    $('btnNewsViewMobile').className = 'px-2.5 py-1 rounded-md bg-white shadow-sm text-black flex items-center gap-1';
    $('btnNewsViewDesktop').className = 'px-2.5 py-1 rounded-md text-neutral-500 flex items-center gap-1';
    $('btnNewsViewPlain').className = 'px-2.5 py-1 rounded-md text-neutral-500 flex items-center gap-1';
    $('newsPreviewFrameContainer').style.display = 'flex';
    $('newsIframePreview').style.maxWidth = '375px';
    $('newsPlainViewer').style.display = 'none';
  });
  $('btnNewsViewPlain')?.addEventListener('click', () => {
    $('btnNewsViewPlain').className = 'px-2.5 py-1 rounded-md bg-white shadow-sm text-black flex items-center gap-1';
    $('btnNewsViewDesktop').className = 'px-2.5 py-1 rounded-md text-neutral-500 flex items-center gap-1';
    $('btnNewsViewMobile').className = 'px-2.5 py-1 rounded-md text-neutral-500 flex items-center gap-1';
    $('newsPreviewFrameContainer').style.display = 'none';
    $('newsPlainViewer').style.display = 'block';
  });

  // 보관함 버튼
  $('btnMarketingHistory')?.addEventListener('click', openMarketingHistoryModal);
  $('btnCloseMarketingHistory')?.addEventListener('click', () => $('marketingHistoryModal').classList.remove('open'));
  $('marketingHistoryModal')?.addEventListener('click', (e) => { if (e.target === $('marketingHistoryModal')) $('marketingHistoryModal').classList.remove('open'); });
}

async function syncMarketingWithCurrentState(forceSource) {
  // 아직 ①/②를 안 열었어도 최근 결과를 자동으로 불러와 연동
  if (forceSource === 'analysis' && !state.analysis) {
    const first = state.history.analyses[0];
    if (first) { try { const r = await api(`/api/report?id=${encodeURIComponent(first.id)}`); state.analysis = r.data; } catch (e) {} }
    if (!state.analysis) { showToast('분석된 영상이 없습니다. ① 탭에서 먼저 분석해주세요.', true); return; }
  }
  if (forceSource === 'plan' && !state.plan) {
    const first = state.history.plans[0];
    if (first) { try { const r = await api(`/api/plan?id=${encodeURIComponent(first.plan_id)}`); renderPlan(r.data); } catch (e) {} }
    if (!state.plan) { showToast('기획서가 없습니다. ② 탭에서 먼저 만들어주세요.', true); return; }
  }
  const badge = $('marketingSourceBadge');
  const topicInput = $('marketingTopicInput');
  const contextInput = $('marketingContextInput');
  const contextWrapper = $('marketingContextWrapper');

  if (forceSource === 'analysis' || (!forceSource && state.analysis && state.mode === 'marketing' && state.marketing.source !== 'plan')) {
    if (state.analysis) {
      state.marketing.source = 'analysis';
      const meta = state.analysis.info || {};
      const title = meta.title || state.analysis.id || '분석 영상';
      topicInput.value = title;

      let ctx = `[영상 제목] ${title}\n[채널] ${meta.channel || ''} | [조회수] ${(meta.view_count || 0).toLocaleString()}회 | [좋아요] ${(meta.like_count || 0).toLocaleString()}개\n`;
      if (state.analysis.report) {
        ctx += `\n[분석 리포트 요약]\n${state.analysis.report.slice(0, 2500)}\n`;
      }
      if (state.analysis.visual?.core_message) ctx += `\n[핵심 메시지] ${state.analysis.visual.core_message}\n`;
      contextInput.value = ctx;
      contextWrapper.style.display = 'block';
      badge.innerHTML = `연동 모드: <span class="text-red-600 font-bold">📹 분석 영상 연동</span> (${escapeHtml(title).slice(0, 25)}...)`;
      showToast('분석 영상 데이터가 마케팅 허브에 연동되었습니다.');
      return;
    }
  }

  if (forceSource === 'plan' || (!forceSource && state.plan && state.mode === 'marketing')) {
    if (state.plan) {
      state.marketing.source = 'plan';
      const title = state.plan.topic || '기획 콘텐츠';
      topicInput.value = title;
      
      let ctx = `[기획 주제] ${title}\n[추천 제목] ${state.plan.meta?.recommended?.title || ''}\n[설명란]\n${(state.plan.description_plain || '').slice(0, 500)}\n\n[씬별 나레이션 대본]\n`;
      const scenes = state.plan.structured_scenes || [];
      scenes.forEach((s) => {
        ctx += `씬 ${s.scene_num}: ${s.subtitle || ''}\n`;
      });
      contextInput.value = ctx;
      contextWrapper.style.display = 'block';
      badge.innerHTML = `연동 모드: <span class="text-indigo-600 font-bold">🎬 기획 대본 연동</span> (${escapeHtml(title).slice(0, 25)}...)`;
      showToast('기획 대본 데이터가 마케팅 허브에 연동되었습니다.');
      return;
    }
  }

  if (forceSource === 'custom') {
    state.marketing.source = 'custom';
    badge.textContent = '연동 모드: 직접 입력 모드';
    topicInput.value = '';
    contextInput.value = '';
    contextWrapper.style.display = 'none';
    topicInput.focus();
    showToast('새로운 마케팅 주제를 입력해주세요.');
  }
}

async function executeMarketingGeneration(mode) {
  const topic = ($('marketingTopicInput')?.value || '').trim();
  if (!topic) {
    showToast('마케팅 주제 또는 키워드를 입력해주세요.', true);
    $('marketingTopicInput')?.focus();
    return;
  }

  const context = ($('marketingContextInput')?.value || '').trim();
  const audience = ($('marketingAudienceInput')?.value || '크리에이터, 직장인, 마케터').trim();

  const options = {
    platform: $('threadPlatformSelect')?.value || 'threads',
    tone: $('threadToneSelect')?.value || 'viral_hook',
    count: parseInt($('threadCountSelect')?.value || '5', 10),
    audience,
    blog_platform: $('blogPlatformSelect')?.value || 'general',
    campaign_type: $('newsCampaignSelect')?.value || 'video_launch',
    offer: ($('newsOfferInput')?.value || '').trim()
  };

  const btnMap = {
    all: $('btnRunMarketingAll'),
    threads: $('btnRunThreadX'),
    blog: $('btnRunBlog'),
    newsletter: $('btnRunNewsletter')
  };
  const activeBtn = btnMap[mode] || $('btnRunMarketingAll');

  const btnLabels = {
    all: '올인원 생성 중...',
    threads: '스레드 생성 중...',
    blog: '블로그 생성 중...',
    newsletter: '뉴스레터 생성 중...'
  };

  setBusy(activeBtn, true, btnLabels[mode] || '생성 중...');

  try {
    const payload = {
      mode,
      topic,
      context,
      options
    };

    const statusEl = $('marketingJobStatus');
    if (statusEl) { statusEl.style.display = 'block'; statusEl.textContent = '생성 시작...'; }
    const resp = await api('/api/marketing/generate', payload);
    const result = await runJob(resp, (job) => {
      if (statusEl) statusEl.textContent = `⏳ ${job.message || '생성 중...'} (${job.progress || 0}%)`;
    });
    if (statusEl) { statusEl.textContent = ''; statusEl.style.display = 'none'; }

    state.marketing.currentData = result;

    if (mode === 'all') {
      if (result.threads_x) renderThreadsOutput(result.threads_x);
      if (result.seo_blog) renderBlogOutput(result.seo_blog);
      if (result.newsletter) renderNewsletterOutput(result.newsletter);
      showToast('🚀 전채널 마케팅 콘텐츠가 모두 완성되었습니다!');
    } else if (mode === 'threads') {
      renderThreadsOutput(result);
      showToast('🧵 스레드 & X 바이럴 타래가 생성되었습니다.');
    } else if (mode === 'blog') {
      renderBlogOutput(result);
      showToast('📝 SEO 블로그 글이 생성되었습니다.');
    } else if (mode === 'newsletter') {
      renderNewsletterOutput(result);
      showToast('📧 뉴스레터 캠페인이 생성되었습니다.');
    }
  } catch (err) {
    showToast(`마케팅 생성 실패: ${err.message}`, true);
  } finally {
    setBusy(activeBtn, false);
    icons();
  }
}

// AI 응답 해석 실패로 기본 틀이 표시된 경우 경고 배너
function marketingFallbackNotice(wrapId, data) {
  const wrap = $(wrapId); if (!wrap) return;
  wrap.querySelector('.fallback-note')?.remove();
  if (data && (data.is_fallback || data.note)) {
    const div = document.createElement('div');
    div.className = 'notice notice-warn fallback-note mb-3';
    div.innerHTML = `<i data-lucide="alert-triangle" class="w-4 h-4 shrink-0"></i><span><b>이 내용은 AI가 만든 것이 아닙니다.</b> ${escapeHtml(data.note || 'AI 응답을 해석하지 못해 기본 틀이 표시되었습니다.')} — 로컬 AI 모델을 더 큰 것으로 바꾸거나 다시 생성해보세요.</span>`;
    wrap.prepend(div);
  }
}

function renderThreadsOutput(data) {
  if (!data || !data.posts) return;
  const wrap = $('threadOutputWrapper');
  const empty = $('threadEmptyState');
  if (wrap) wrap.style.display = 'block';
  if (empty) empty.style.display = 'none';
  marketingFallbackNotice('threadOutputWrapper', data);

  $('threadHookFormula').textContent = `후킹 공식: ${data.hook_formula || '호기심 유발 + 데이터 증명'}`;
  $('threadHookScore').textContent = `바이럴 점수: ${data.hook_score || 95}점 🔥`;
  $('threadSummaryText').textContent = data.summary || `${data.topic} 핵심 요약 스레드`;

  // Hashtags
  const hashList = $('threadHashtagsList');
  if (hashList) {
    const tags = data.hashtags || ['#AI', '#생산성', '#자동화', '#TubeInsight'];
    hashList.innerHTML = tags.map((t) => `<span class="hashtag-chip" data-copy="${escapeHtml(t)}">${escapeHtml(t)}</span>`).join('');
    hashList.querySelectorAll('[data-copy]').forEach((el) => el.addEventListener('click', () => copyText(el.dataset.copy, '해시태그를 복사했습니다.')));
  }

  // Posts Container
  const container = $('threadPostsContainer');
  if (container) {
    const isTwitter = data.platform === 'twitter';
    const maxLimit = isTwitter ? 280 : 500;

    container.innerHTML = data.posts.map((p, idx) => {
      const charCount = p.text ? p.text.length : 0;
      let badgeClass = 'ok';
      if (charCount > maxLimit) badgeClass = 'danger';
      else if (charCount > maxLimit * 0.85) badgeClass = 'warn';

      const roleClass = p.role === 'hook' ? 'role-hook' : (p.role === 'cta' ? 'role-cta' : '');
      const roleLabel = p.role === 'hook' ? 'HOOK (후킹 첫인상)' : (p.role === 'cta' ? 'CTA (행동 촉구/요약)' : 'BODY (핵심 내용)');

      const tweetIntentUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(p.text || '')}`;

      return `
        <div class="thread-card ${roleClass}" id="threadCard_${idx}">
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
              <span class="thread-index-badge">${p.index || (idx + 1)}</span>
              <span class="text-[11px] font-bold text-neutral-700">${roleLabel}</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="char-count-badge ${badgeClass}" id="charBadge_${idx}">${charCount}자 / ${maxLimit}자</span>
              <button class="btn btn-ghost !p-1 text-xs" title="이 포스트 복사" onclick="copyText(document.getElementById('threadText_${idx}').value, '${p.index || (idx + 1)}번 포스트를 복사했습니다.')">
                <i data-lucide="copy" class="w-3.5 h-3.5"></i>
              </button>
              <a href="${tweetIntentUrl}" target="_blank" rel="noopener" class="btn btn-ghost !p-1 text-sky-500 hover:text-sky-600" title="X에 즉시 공유">
                <i data-lucide="share-2" class="w-3.5 h-3.5"></i>
              </a>
            </div>
          </div>
          <textarea id="threadText_${idx}" rows="4" class="w-full input p-3 text-xs leading-relaxed font-sans bg-white/80" oninput="updateThreadCharCount(${idx}, ${maxLimit})">${escapeHtml(p.text || '')}</textarea>
        </div>
      `;
    }).join('');
  }

  // Bind Copy All & Download
  $('btnCopyAllThreads').onclick = () => {
    const allText = (data.posts || []).map((p, i) => {
      const el = $(`threadText_${i}`);
      return el ? el.value : (p.text || '');
    }).join('\n\n---\n\n');
    copyText(allText, '전체 스레드 타래를 복사했습니다.');
  };

  $('btnDownloadThreadsTxt').onclick = () => {
    const allText = (data.posts || []).map((p, i) => {
      const el = $(`threadText_${i}`);
      return el ? el.value : (p.text || '');
    }).join('\n\n====================\n\n');
    downloadText(`${data.topic || 'threads'}_스레드_타래.txt`, allText);
  };

  icons();
}

function updateThreadCharCount(idx, maxLimit) {
  const textarea = $(`threadText_${idx}`);
  const badge = $(`charBadge_${idx}`);
  if (!textarea || !badge) return;
  const count = textarea.value.length;
  badge.textContent = `${count}자 / ${maxLimit}자`;
  badge.className = 'char-count-badge ' + (count > maxLimit ? 'danger' : (count > maxLimit * 0.85 ? 'warn' : 'ok'));
}

function renderBlogOutput(data) {
  if (!data || !data.markdown_content) return;
  const wrap = $('blogOutputWrapper');
  const empty = $('blogEmptyState');
  if (wrap) wrap.style.display = 'block';
  if (empty) empty.style.display = 'none';
  marketingFallbackNotice('blogOutputWrapper', data);

  const meta = data.meta || {};
  $('blogReadingTime').textContent = `예상 완독 시간: ${meta.reading_time_min || 5}분`;
  $('blogMetaTitleText').textContent = meta.title || `${data.topic} 완벽 가이드`;
  $('blogMetaDescText').textContent = meta.description || `${data.topic}에 대한 핵심 요약 및 실전 가이드입니다.`;

  // Keywords
  const kwList = $('blogKeywordsList');
  if (kwList) {
    const kws = meta.keywords || [data.topic, 'AI자동화', '생산성', 'TubeInsight', '가이드'];
    kwList.innerHTML = kws.map((k) => `<span class="hashtag-chip" data-copy="${escapeHtml(k)}">#${escapeHtml(k)}</span>`).join('');
    kwList.querySelectorAll('[data-copy]').forEach((el) => el.addEventListener('click', () => copyText(el.dataset.copy, '키워드를 복사했습니다.')));
  }

  // Cover Image Prompt
  $('blogCoverPromptText').textContent = data.cover_image_prompt || 'Minimalist modern 3D workspace aesthetic, 8k resolution, cinematic lighting --ar 16:9';

  // Markdown Render
  const mdContent = data.markdown_content || '';
  $('blogRenderedViewer').innerHTML = md(mdContent);
  $('blogRawTextarea').value = mdContent;

  // Copy Buttons
  $('btnCopyMetaTitle').onclick = () => copyText($('blogMetaTitleText').textContent, '메타 타이틀을 복사했습니다.');
  $('btnCopyMetaDesc').onclick = () => copyText($('blogMetaDescText').textContent, '메타 디스크립션을 복사했습니다.');
  $('btnCopyCoverPrompt').onclick = () => copyText($('blogCoverPromptText').textContent, '커버 이미지 프롬프트를 복사했습니다.');
  
  $('btnCopyBlogMarkdown').onclick = () => copyText($('blogRawTextarea').value, '블로그 마크다운 본문을 복사했습니다.');
  $('btnCopyBlogHtml').onclick = () => copyText($('blogRenderedViewer').innerHTML, '블로그 HTML 본문을 복사했습니다.');
  $('btnDownloadBlogMd').onclick = () => downloadText(`${data.topic || 'blog'}_SEO_블로그.md`, $('blogRawTextarea').value);

  icons();
}

function renderNewsletterOutput(data) {
  if (!data || !data.html_template) return;
  const wrap = $('newsletterOutputWrapper');
  const empty = $('newsletterEmptyState');
  if (wrap) wrap.style.display = 'block';
  if (empty) empty.style.display = 'none';
  marketingFallbackNotice('newsletterOutputWrapper', data);

  // A/B Subject lines
  const subList = $('newsSubjectLinesList');
  if (subList) {
    const subjects = data.subject_lines || [];
    subList.innerHTML = subjects.map((s, idx) => `
      <div class="subject-item-card" data-copy="${escapeHtml(s.subject || '')}" title="클릭하면 제목 복사">
        <div class="flex items-center gap-2">
          <span class="badge badge-purple text-[10px] font-bold">${escapeHtml(s.type || `안 ${idx + 1}`)}</span>
          <span class="text-xs font-bold text-neutral-800">${escapeHtml(s.subject || '')}</span>
        </div>
        <span class="text-[11px] text-neutral-400 font-normal truncate max-w-[200px]">${escapeHtml(s.preview_text || '')}</span>
      </div>
    `).join('');
    subList.querySelectorAll('[data-copy]').forEach((el) => el.addEventListener('click', () => copyText(el.dataset.copy, '이메일 제목을 복사했습니다.')));
  }

  // HTML Frame Preview
  const iframe = $('newsIframePreview');
  if (iframe) {
    iframe.srcdoc = data.html_template;
  }

  // Plain text
  $('newsPlainViewer').value = data.plain_text || '';

  // Copy & Download
  $('btnCopyNewsHtml').onclick = () => copyText(data.html_template, '이메일 HTML 템플릿을 복사했습니다.');
  $('btnDownloadNewsHtml').onclick = () => downloadText(`${data.topic || 'newsletter'}_이메일_뉴스레터.html`, data.html_template);
  $('btnCopyNewsPlain').onclick = () => copyText($('newsPlainViewer').value, '이메일 일반 텍스트를 복사했습니다.');

  icons();
}

async function openMarketingHistoryModal() {
  try {
    const res = await api('/api/marketing/history');
    const items = res.history || [];
    const list = $('marketingHistoryList');
    const modeLabel = { all: '올인원', threads: '스레드', blog: '블로그', newsletter: '뉴스레터' };
    list.innerHTML = items.length ? items.map((it) => `
      <button class="subtle-box p-2.5 w-full text-left hover:border-black transition-all" data-entry="${escapeHtml(it.id)}">
        <div class="flex items-center justify-between gap-2">
          <span class="text-xs font-bold text-black truncate">${escapeHtml(it.topic || '무제')}</span>
          <span class="badge shrink-0">${modeLabel[it.mode] || it.mode || '올인원'}</span>
        </div>
        <div class="text-[10px] text-neutral-400 font-mono mt-0.5">${fmtTs(it.timestamp)}</div>
      </button>`).join('') : '<p class="text-xs text-neutral-400">저장된 기록이 없습니다. 생성하면 자동으로 보관됩니다.</p>';
    list.querySelectorAll('[data-entry]').forEach((b) => b.addEventListener('click', async () => {
      try {
        const r = await api(`/api/marketing/get?id=${encodeURIComponent(b.dataset.entry)}`);
        const entry = r.entry || {}; const result = entry.result || entry;  // 신·구 형식 모두
        $('marketingHistoryModal').classList.remove('open');
        if (entry.topic) $('marketingTopicInput').value = entry.topic;
        state.marketing.currentData = result;
        if (result.threads_x || result.seo_blog || result.newsletter) {
          if (result.threads_x) renderThreadsOutput(result.threads_x);
          if (result.seo_blog) renderBlogOutput(result.seo_blog);
          if (result.newsletter) renderNewsletterOutput(result.newsletter);
        } else if (result.posts) renderThreadsOutput(result);
        else if (result.markdown_content) renderBlogOutput(result);
        else if (result.html_template) renderNewsletterOutput(result);
        showToast('보관함에서 불러왔습니다.');
      } catch (e) { showToast(e.message, true); }
    }));
    $('marketingHistoryModal').classList.add('open'); icons();
  } catch (e) {
    showToast(e.message, true);
  }
}


// ══════════════════════════ 00 채널 세팅 스튜디오 ══════════════════════════

function bindChannelStudio() {
  $('btnRunChannelGen')?.addEventListener('click', generateChannelSetup);
  $('btnGenChannelImages')?.addEventListener('click', generateChannelImages);
  $('btnCheckManualHandle')?.addEventListener('click', checkManualHandle);
  $('manualHandleInput')?.addEventListener('keypress', (e) => { if (e.key === 'Enter') checkManualHandle(); });
  $('btnApplyChannelBranding')?.addEventListener('click', applyChannelBranding);
  $('channelHistorySelect')?.addEventListener('change', (e) => {
    if (e.target.value) loadChannelData(e.target.value);
  });
  $('btnChannelFromAnalysis')?.addEventListener('click', () => {
    if (state.analysis) {
      transferBenchToChannel();
    } else {
      showToast('분석된 영상이 없습니다. 01 영상 분석 탭에서 영상을 분석해주세요.', true);
    }
  });

  // 복사 버튼들
  $('btnCopyChannelName')?.addEventListener('click', () => {
    copyText($('channelNameOutput').textContent, '채널 이름을 복사했습니다.');
  });
  $('btnCopyChannelDesc')?.addEventListener('click', () => {
    copyText($('channelDescOutput').value, '채널 설명을 복사했습니다.');
  });
  $('btnCopyKeywords')?.addEventListener('click', () => {
    const kws = (state.channel.currentData?.channel_keywords || []).join(', ');
    copyText(kws, '채널 키워드를 복사했습니다.');
  });
  $('btnCopyAvatarPrompt')?.addEventListener('click', () => {
    copyText($('channelAvatarPromptText').textContent, '아바타 프롬프트를 복사했습니다.');
  });
  $('btnCopyBannerPrompt')?.addEventListener('click', () => {
    copyText($('channelBannerPromptText').textContent, '배너 프롬프트를 복사했습니다.');
  });
  $('btnCopyUploadDefaults')?.addEventListener('click', () => {
    const def = state.channel.currentData?.upload_defaults;
    if (!def) return;
    const txt = `[제목 템플릿]\n${def.title_template}\n\n[설명란 템플릿]\n${def.description_template}\n\n[태그]\n${(def.tags || []).join(', ')}\n\n[카테고리] ${def.category_id}\n[공개] ${def.privacy_status}`;
    copyText(txt, '업로드 기본값을 복사했습니다.');
  });
}

async function loadChannelHistory() {
  try {
    const r = await api('/api/channel/history');
    state.channel.history = r.channels || [];
    const sel = $('channelHistorySelect');
    if (sel) {
      sel.innerHTML = '<option value="">저장된 채널 목록…</option>' +
        state.channel.history.map(c => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.channel_name || c.topic)} (${c.lang})</option>`).join('');
      if (state.channel.currentData) sel.value = state.channel.currentData.channel_id;
    }
  } catch (e) {
    console.error('채널 히스토리 로드 실패:', e);
  }
}

async function loadChannelData(id) {
  try {
    const r = await api(`/api/channel?id=${encodeURIComponent(id)}`);
    if (r.data) {
      renderChannelOutput(r.data);
      showToast(`'${r.data.channel_name}' 채널 설정을 불러왔습니다.`);
    }
  } catch (e) {
    showToast(e.message, true);
  }
}

async function generateChannelSetup() {
  const topic = $('channelTopicInput').value.trim();
  if (!topic) {
    showToast('채널 주제를 입력해주세요.', true);
    $('channelTopicInput').focus();
    return;
  }
  const lang = $('channelLangSelect').value || 'ko';
  const audience = $('channelAudienceInput').value.trim() || undefined;
  const tone = $('channelToneSelect').value || undefined;
  const persona_type = $('channelPersonaSelect').value || 'character';
  const audio_lang = $('channelAudioLangSelect').value || lang;

  const btn = $('btnRunChannelGen');
  setBusy(btn, true, '채널 세팅 8종 생성 및 핸들 검사 중…');
  try {
    const res = await api('/api/channel/generate', {
      topic, lang, audience, tone, persona_type, audio_lang
    });
    const result = await runJob(res, (job) => {
      setProgress('channel', job);
    });
    hideProgress('channel');
    renderChannelOutput(result);
    await loadChannelHistory();
    showToast('🎉 채널 세팅 8종이 성공적으로 생성되었습니다!');
  } catch (e) {
    hideProgress('channel');
    showToast(`채널 생성 실패: ${e.message}`, true);
  } finally {
    setBusy(btn, false);
  }
}

async function generateChannelImages() {
  if (!state.channel.currentData) {
    showToast('먼저 채널 세팅을 생성해주세요.', true);
    return;
  }
  const btn = $('btnGenChannelImages');
  setBusy(btn, true, '나노바나나로 프로필/배너 생성 중…');
  try {
    const res = await api('/api/channel/images', {
      channel_id: state.channel.currentData.channel_id,
      channel_data: state.channel.currentData
    });
    const result = await runJob(res, (job) => {
      setProgress('channel', job);
    });
    hideProgress('channel');
    renderChannelOutput(result);
    showToast('📸 AI 프로필 및 배너 이미지가 생성되었습니다!');
  } catch (e) {
    hideProgress('channel');
    showToast(`이미지 생성 실패: ${e.message}`, true);
  } finally {
    setBusy(btn, false);
  }
}

async function checkManualHandle() {
  const input = $('manualHandleInput');
  const handle = (input.value || '').trim().replace(/^@/, '');
  if (!handle) {
    showToast('확인할 핸들을 입력해주세요.', true);
    return;
  }
  const btn = $('btnCheckManualHandle');
  setBusy(btn, true, '중복 확인 중…');
  const resBox = $('manualHandleResult');
  try {
    const r = await api('/api/channel/check-handle', { handle });
    resBox.style.display = 'block';
    if (r.available) {
      resBox.className = 'mt-2 text-xs font-bold text-emerald-600 flex items-center gap-1';
      resBox.innerHTML = `<i data-lucide="check-circle" class="w-3.5 h-3.5"></i> @${escapeHtml(r.handle)} 은(는) 사용 가능합니다!`;
    } else {
      resBox.className = 'mt-2 text-xs font-bold text-red-600 flex items-center gap-1';
      resBox.innerHTML = `<i data-lucide="alert-circle" class="w-3.5 h-3.5"></i> @${escapeHtml(r.handle)} 은(는) 이미 사용 중입니다. (<a href="${r.url}" target="_blank" class="underline">채널 확인</a>)`;
    }
    icons();
  } catch (e) {
    showToast(`핸들 확인 오류: ${e.message}`, true);
  } finally {
    setBusy(btn, false);
  }
}

async function applyChannelBranding() {
  if (!state.channel.currentData) {
    showToast('적용할 채널 데이터가 없습니다.', true);
    return;
  }
  const d = state.channel.currentData;
  const btn = $('btnApplyChannelBranding');
  setBusy(btn, true, '유튜브 Data API 전송 중…');
  try {
    const r = await api('/api/channel/apply-branding', {
      description: d.channel_description,
      keywords: d.channel_keywords,
      default_language: d.channel_language
    });
    if (r.status === 'success') {
      showToast('🎉 유튜브 채널 설명 & 키워드가 성공적으로 업데이트되었습니다!');
    } else {
      showToast(r.message || '업데이트 실패', true);
    }
  } catch (e) {
    showToast(`브랜딩 적용 실패: ${e.message}`, true);
  } finally {
    setBusy(btn, false);
  }
}

async function checkChannelYtStatus() {
  const badge = $('channelYtStatusBadge');
  if (!badge) return;
  try {
    const r = await api('/api/render/status');
    const yt = r.youtube || {};
    if (yt.authorized) {
      badge.textContent = `연결됨 (${yt.channel?.title || yt.channel_title || '내 채널'})`;
      badge.className = 'badge badge-ok';
    } else {
      badge.textContent = '계정 미연결 (03 탭에서 연결 가능)';
      badge.className = 'badge badge-warn';
    }
  } catch (e) {
    badge.textContent = '상태 확인 불가';
    badge.className = 'badge';
  }
}

function renderChannelOutput(data) {
  if (!data) return;
  state.channel.currentData = data;
  $('channelEmptyState').style.display = 'none';
  $('channelResultWrapper').style.display = 'block';

  // 1. 이름 & 핸들
  $('channelNameOutput').textContent = data.channel_name || '—';
  $('channelLangBadge').textContent = `${data.channel_language || 'ko'}`;

  const handlesList = $('channelHandlesList');
  if (handlesList) {
    const handles = data.handle_candidates || [];
    handlesList.innerHTML = handles.map(h => {
      const isAvail = h.available !== false;
      const badgeCls = isAvail ? 'available' : 'taken';
      const badgeText = isAvail ? '사용 가능' : '사용 중';
      return `
        <div class="handle-card ${badgeCls}">
          <div class="flex items-center gap-2">
            <span class="font-mono font-bold text-sm text-neutral-900">@${escapeHtml(h.handle)}</span>
            <span class="handle-status-badge ${badgeCls}">${badgeText}</span>
            <span class="text-[10px] text-neutral-400 font-mono">(${escapeHtml(h.style || 'candidate')})</span>
          </div>
          <div class="flex items-center gap-1.5">
            <a href="${escapeHtml(h.url)}" target="_blank" rel="noopener" class="text-xs text-neutral-500 hover:text-black underline" title="유튜브 채널 이동">확인</a>
            <button class="btn btn-ghost !py-1 text-xs copy-handle-btn" data-handle="@${escapeHtml(h.handle)}">
              <i data-lucide="copy" class="w-3 h-3"></i>
            </button>
          </div>
        </div>
      `;
    }).join('');

    handlesList.querySelectorAll('.copy-handle-btn').forEach(btn => {
      btn.addEventListener('click', () => copyText(btn.dataset.handle, '핸들을 복사했습니다.'));
    });
  }

  // 2. 설명 & 키워드
  $('channelDescOutput').value = data.channel_description || '';
  const kwList = $('channelKeywordsList');
  if (kwList) {
    const kws = data.channel_keywords || [];
    kwList.innerHTML = kws.map(k => `
      <button class="chip hover:border-black text-xs kw-chip" data-kw="${escapeHtml(k)}">
        #${escapeHtml(k)}
      </button>
    `).join('');
    kwList.querySelectorAll('.kw-chip').forEach(btn => {
      btn.addEventListener('click', () => copyText(btn.dataset.kw, `'${btn.dataset.kw}' 키워드를 복사했습니다.`));
    });
  }

  // 3. 프로필 & 배너 프롬프트 및 이미지
  $('channelAvatarPromptText').textContent = data.avatar_prompt || '—';
  $('channelBannerPromptText').textContent = data.banner_prompt || '—';

  const avatarImg = $('channelAvatarImg');
  const avatarEmpty = $('channelAvatarEmpty');
  const dlAvatar = $('btnDownloadAvatar');
  if (data.avatar_image) {
    avatarImg.src = data.avatar_image + `?t=${Date.now()}`;
    avatarImg.style.display = 'block';
    avatarEmpty.style.display = 'none';
    dlAvatar.href = data.avatar_image;
    dlAvatar.style.display = 'inline-flex';
  } else {
    avatarImg.style.display = 'none';
    avatarEmpty.style.display = 'block';
    dlAvatar.style.display = 'none';
  }

  const bannerImg = $('channelBannerImg');
  const bannerEmpty = $('channelBannerEmpty');
  const dlBanner = $('btnDownloadBanner');
  if (data.banner_image) {
    bannerImg.src = data.banner_image + `?t=${Date.now()}`;
    bannerImg.style.display = 'block';
    bannerEmpty.style.display = 'none';
    dlBanner.href = data.banner_image;
    dlBanner.style.display = 'inline-flex';
  } else {
    bannerImg.style.display = 'none';
    bannerEmpty.style.display = 'block';
    dlBanner.style.display = 'none';
  }

  // 4. 업로드 기본값
  const def = data.upload_defaults || {};
  $('defTitleTmpl').textContent = def.title_template || '—';
  $('defDescTmpl').value = def.description_template || '';
  $('defCategoryBadge').textContent = `카테고리: ${def.category_id || '27'}`;
  $('defPrivacyBadge').textContent = `공개: ${def.privacy_status || 'private'}`;
  $('defLangBadge').textContent = `언어: ${def.default_language || data.channel_language || 'ko'}`;

  // 5. 8단계 체크리스트
  const stepsList = $('channelSetupStepsList');
  if (stepsList) {
    const steps = data.setup_steps || [];
    stepsList.innerHTML = steps.map((s, idx) => `
      <label class="step-checklist-item cursor-pointer">
        <input type="checkbox" class="step-check mt-0.5 rounded border-neutral-300">
        <div class="text-xs text-neutral-800 leading-snug">
          <span class="font-bold text-neutral-900">${idx + 1}. ${escapeHtml(s.step)}</span>:
          <span class="text-neutral-600">${escapeHtml(s.guide)}</span>
        </div>
      </label>
    `).join('');

    stepsList.querySelectorAll('.step-check').forEach(chk => {
      chk.addEventListener('change', (e) => {
        const item = e.target.closest('.step-checklist-item');
        if (item) item.classList.toggle('completed', e.target.checked);
      });
    });
  }

  icons();
}


