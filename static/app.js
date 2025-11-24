const state = {
  groups: [],
  filteredGroups: [],
  token: '',
  includeChannels: false,
  selectedIds: new Set(),
  account: '',
  accounts: [],
  sending: false,
};

function loadToken() {
  const t = localStorage.getItem('adminToken') || '';
  state.token = t;
  const input = document.getElementById('adminToken');
  if (input) input.value = t;
}

function saveToken() {
  const t = document.getElementById('adminToken').value.trim();
  state.token = t;
  localStorage.setItem('adminToken', t);
  const el = document.getElementById('tokenStatus');
  if (!t) {
    if (el) { el.textContent = '请输入令牌'; el.style.color = '#d9534f'; }
    alert('请输入令牌');
    return;
  }
  if (el) { el.textContent = '令牌已保存'; el.style.color = '#28a745'; }
  localStorage.setItem('tokenLocked', '1');
  updateTokenLockUI();
}

function groupsCacheKey() {
  const acc = state.account || '';
  const scope = state.includeChannels ? 'all' : 'groups';
  return `groups:${acc}:${scope}`;
}

function loadGroupsFromCache() {
  try {
    const raw = localStorage.getItem(groupsCacheKey());
    if (!raw) return null;
    const arr = JSON.parse(raw);
    if (Array.isArray(arr)) return arr;
    return null;
  } catch { return null; }
}

function saveGroupsToCache(data) {
  try { localStorage.setItem(groupsCacheKey(), JSON.stringify(data || [])); } catch {}
}

function renderGroupsFromCacheIfAvailable() {
  const cached = loadGroupsFromCache();
  if (cached && cached.length) {
    state.groups = cached;
    state.filteredGroups = cached;
    renderGroups();
  }
}

async function fetchGroups(forceRefresh = false) {
  const onlyGroups = state.includeChannels ? 'false' : 'true';
  const acc = encodeURIComponent(state.account || '');
  const refresh = forceRefresh ? 'true' : 'false';
  const res = await fetch(`/api/groups?only_groups=${onlyGroups}&account=${acc}&refresh=${refresh}`, {
    headers: { 'X-Admin-Token': state.token },
  });
  if (!res.ok) {
    try {
      const d = await res.json();
      if (res.status === 401) {
        alert('令牌错误，请在顶部输入后点击“保存令牌”');
      } else if (res.status === 403 && d.detail === 'session_not_authorized') {
        alert('账号未登录，请在上方登录管理中发送验证码并确认登录');
      } else {
        alert('群列表获取失败，请稍后重试');
      }
    } catch {
      alert('群列表获取失败，请稍后重试');
    }
    return;
  }
  const data = await res.json();
  if (Array.isArray(data) && data.length === 0 && !state.includeChannels) {
    state.includeChannels = true;
    try { localStorage.setItem('includeChannels', '1'); } catch {}
    const res2 = await fetch(`/api/groups?only_groups=false&account=${acc}&refresh=${refresh}`, { headers: { 'X-Admin-Token': state.token } });
    if (res2.ok) {
      const data2 = await res2.json();
      state.groups = data2;
      state.filteredGroups = data2;
      saveGroupsToCache(data2);
      const el = document.getElementById('includeChannels');
      if (el) el.checked = true;
      renderGroups();
      return;
    }
  }
  state.groups = data;
  state.filteredGroups = data;
  saveGroupsToCache(data);
  renderGroups();
}

async function fetchAccounts() {
  const res = await fetch('/api/accounts/status', { headers: { 'X-Admin-Token': state.token } });
  if (!res.ok) return;
  const data = await res.json();
  state.accounts = data.map(item => item.account);
  const sel = document.getElementById('accountSelect');
  sel.innerHTML = '';
  data.forEach(item => {
    const opt = document.createElement('option');
    opt.value = item.account;
    opt.textContent = item.authorized ? `${item.account} (已授权)` : item.account;
    sel.appendChild(opt);
  });
  const saved = localStorage.getItem('selectedAccount');
  state.account = saved && state.accounts.includes(saved) ? saved : (state.accounts[0] || '');
  sel.value = state.account;
  localStorage.setItem('selectedAccount', state.account);
}

function renderGroups() {
  const ul = document.getElementById('groupList');
  ul.innerHTML = '';
  state.filteredGroups.forEach(g => {
    const li = document.createElement('li');
    const badge = g.is_channel ? '频道' : (g.is_megagroup ? '超级群' : '群');
    const checked = state.selectedIds.has(g.id) ? 'checked' : '';
    const disabled = (g.is_channel && !g.is_megagroup) ? 'disabled' : '';
    li.innerHTML = `
      <label>
        <input type="checkbox" class="groupCheck" value="${g.id}" ${checked} ${disabled} />
        <span class="title">${g.title}</span>
        ${g.member_count ? `<span class="count">(${g.member_count})</span>` : ''}
        <span class="badge">${badge}</span>
        ${g.username ? `<span class="uname">@${g.username}</span>` : ''}
        ${disabled ? `<span class="warn">不可发送</span>` : ''}
      </label>
    `;
    ul.appendChild(li);
  });
  document.getElementById('groupCount').textContent = `共 ${state.filteredGroups.length} 项`;
}

function filterGroups() {
  const q = document.getElementById('searchInput').value.trim().toLowerCase();
  if (!q) {
    state.filteredGroups = state.groups;
  } else {
    state.filteredGroups = state.groups.filter(g => (g.title || '').toLowerCase().includes(q));
  }
  renderGroups();
}

function setAll(selected) {
  document.querySelectorAll('.groupCheck').forEach(ch => { 
    ch.checked = selected; 
    const id = parseInt(ch.value);
    if (selected) state.selectedIds.add(id); else state.selectedIds.delete(id);
  });
  persistSelected();
}

function getSelectedIds() {
  return Array.from(state.selectedIds);
}

async function send(path) {
  if (state.sending) return;
  state.sending = true;
  const sendBtn = document.getElementById('sendBtn');
  const testBtn = document.getElementById('testBtn');
  if (sendBtn) sendBtn.disabled = true;
  if (testBtn) testBtn.disabled = true;
  const resultEl = document.getElementById('result');
  if (resultEl) resultEl.textContent = '发送中...';
  if (!state.token) {
    alert('请输入令牌并点击“保存令牌”');
    if (resultEl) resultEl.textContent = '未设置令牌';
    state.sending = false;
    if (sendBtn) sendBtn.disabled = false;
    if (testBtn) testBtn.disabled = false;
    return;
  }
  const ids = getSelectedIds();
  const msg = document.getElementById('message').value;
  const parseMode = document.getElementById('parseMode').value;
  const delayMs = parseInt(document.getElementById('delayMs').value || '1500');
  const rounds = parseInt(document.getElementById('rounds')?.value || '1');
  const roundInterval = parseInt(document.getElementById('roundInterval')?.value || '1200');
  const disablePreview = document.getElementById('disablePreview').checked;
  if (!ids.length) { alert('请选择至少一个群'); state.sending = false; if (sendBtn) sendBtn.disabled = false; if (testBtn) testBtn.disabled = false; return; }
  if (!msg.trim()) { alert('消息不能为空'); state.sending = false; if (sendBtn) sendBtn.disabled = false; if (testBtn) testBtn.disabled = false; return; }
  const reqId = generateRequestId();
  const expectedMs = (delayMs * Math.max(ids.length, 1)) + 15000;
  const timeoutMs = path === 'send' ? 30000 : Math.min(900000, Math.max(20000, expectedMs));
  try {
    const apiPath = path === 'send' ? 'send-async' : path;
    const res = await fetchWithRetry(`/api/${apiPath}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Token': state.token,
      },
      body: JSON.stringify({
        group_ids: ids,
        message: msg,
        parse_mode: parseMode,
        disable_web_page_preview: disablePreview,
        delay_ms: delayMs,
        rounds: Math.max(1, rounds),
        round_interval_s: Math.max(0, roundInterval),
        account: state.account,
        request_id: reqId,
      }),
    }, timeoutMs, path === 'send' ? 2 : 3);
    if (!res.ok) {
      if (res.status === 429) {
        if (resultEl) resultEl.textContent = '请求频率过高或重复，已忽略';
      } else if (res.status === 401) {
        if (resultEl) resultEl.textContent = '令牌错误，请在顶部保存令牌';
      } else if (res.status === 403) {
        if (resultEl) resultEl.textContent = '账号未登录，请先完成登录';
      } else {
        if (resultEl) resultEl.textContent = '发送失败';
      }
    } else {
      const data = await res.json();
      if (path === 'send') {
        if (resultEl) resultEl.textContent = `任务已创建(${data.task_id})，正在发送...`;
        await pollTaskUntilDone(data.task_id, resultEl);
      } else {
        if (resultEl) resultEl.textContent = `总数 ${data.total}｜成功 ${data.success}｜失败 ${data.failed}`;
        await fetchLogs();
      }
    }
  } catch (e) {
    if (resultEl) resultEl.textContent = '请求超时或网络错误，后台可能仍在发送';
  } finally {
    state.sending = false;
    if (sendBtn) sendBtn.disabled = false;
    if (testBtn) testBtn.disabled = false;
  }
}

async function pollTaskUntilDone(taskId, resultEl) {
  return new Promise(async (resolve) => {
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/api/task-status?task_id=${encodeURIComponent(taskId)}`, { headers: { 'X-Admin-Token': state.token } });
        if (!res.ok) return;
        const s = await res.json();
        const roundInfo = (s.rounds && s.current_round) ? `｜轮次 ${s.current_round}/${s.rounds}` : '';
        if (resultEl) resultEl.textContent = `总数 ${s.total}｜成功 ${s.success}｜失败 ${s.failed}${roundInfo}`;
        if (s.status === 'done') {
          clearInterval(timer);
          await fetchLogs();
          resolve();
        }
      } catch {}
    }, 1000);
  });
}

async function fetchLogs() {
  const res = await fetch('/api/logs?limit=50', {
    headers: { 'X-Admin-Token': state.token },
  });
  if (!res.ok) return;
  const data = await res.json();
  const tbody = document.getElementById('logsBody');
  tbody.innerHTML = '';
  data.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${r.created_at || ''}</td>
      <td>${r.group_title || r.group_id}</td>
      <td>${r.status}</td>
      <td>${r.message_id || ''}</td>
      <td>${r.error || ''}</td>
    `;
    tbody.appendChild(tr);
  });
}

function bindEvents() {
  document.getElementById('saveToken').addEventListener('click', () => { saveToken(); fetchAccounts(); fetchAuthStatus(); fetchGroups(true); fetchLogs(); });
  const editTokenBtn = document.getElementById('editToken');
  if (editTokenBtn) {
    editTokenBtn.addEventListener('click', () => {
      localStorage.setItem('tokenLocked', '0');
      updateTokenLockUI();
      const el = document.getElementById('tokenStatus');
      if (el) { el.textContent = '已解锁令牌'; el.style.color = '#17a2b8'; }
    });
  }
  document.getElementById('searchInput').addEventListener('input', filterGroups);
  document.getElementById('selectAll').addEventListener('click', () => setAll(true));
  document.getElementById('clearAll').addEventListener('click', () => setAll(false));
  document.getElementById('refreshGroups').addEventListener('click', () => fetchGroups(true));
  const clearBtn = document.getElementById('clearCacheBtn');
  if (clearBtn) {
    clearBtn.addEventListener('click', clearCache);
  }
  const debugBtn = document.getElementById('debugGroups');
  if (debugBtn) {
    debugBtn.addEventListener('click', debugGroups);
  }
  document.getElementById('includeChannels').addEventListener('change', (e) => { state.includeChannels = e.target.checked; persistIncludeChannels(); fetchGroups(true); });
  const accountSel = document.getElementById('accountSelect');
  if (accountSel) {
    accountSel.addEventListener('change', (e) => {
      state.account = e.target.value;
      localStorage.setItem('selectedAccount', state.account);
      fetchGroups(true);
      fetchAuthStatus();
    });
  }
  document.getElementById('groupList').addEventListener('change', (e) => {
    if (e.target && e.target.classList.contains('groupCheck')) {
      const id = parseInt(e.target.value);
      if (e.target.checked) state.selectedIds.add(id); else state.selectedIds.delete(id);
      persistSelected();
    }
  });
  document.getElementById('sendBtn').addEventListener('click', () => send('send'));
  document.getElementById('testBtn').addEventListener('click', () => send('test-send'));
  const sendCodeBtn = document.getElementById('sendCodeBtn');
  if (sendCodeBtn) {
    sendCodeBtn.addEventListener('click', sendLoginCode);
  }
  const confirmLoginBtn = document.getElementById('confirmLoginBtn');
  if (confirmLoginBtn) {
    confirmLoginBtn.addEventListener('click', submitLoginCode);
  }
  const unlockBtn = document.getElementById('unlockAccount');
  if (unlockBtn) {
    unlockBtn.addEventListener('click', () => {
      setAccountLocked(false);
      setLoginInputsVisible(true);
    });
  }
}

function persistSelected() {
  try { localStorage.setItem('selectedGroupIds', JSON.stringify(Array.from(state.selectedIds))); } catch {}
}

function restoreSelected() {
  try {
    const raw = localStorage.getItem('selectedGroupIds');
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr)) state.selectedIds = new Set(arr.map(x => parseInt(x)));
    }
  } catch {}
}

function persistIncludeChannels() {
  try { localStorage.setItem('includeChannels', state.includeChannels ? '1' : '0'); } catch {}
}

function restoreIncludeChannels() {
  try {
    const v = localStorage.getItem('includeChannels');
    state.includeChannels = v === '1';
    const el = document.getElementById('includeChannels');
    if (el) el.checked = state.includeChannels;
  } catch {}
}

window.addEventListener('DOMContentLoaded', async () => {
  loadToken();
  updateTokenLockUI();
  restoreSelected();
  restoreIncludeChannels();
  bindEvents();
  await fetchAccounts();
  await fetchAuthStatus();
  renderGroupsFromCacheIfAvailable();
  await fetchGroups();
  await fetchLogs();
});

function generateRequestId() {
  return 'req_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
}

async function fetchWithRetry(url, options, timeoutMs = 5000, maxRetries = 3) {
  let lastErr;
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(timer);
      if (res.status === 429) return res;
      if (!res.ok && attempt < maxRetries) {
        lastErr = new Error('HTTP ' + res.status);
        continue;
      }
      return res;
    } catch (e) {
      clearTimeout(timer);
      lastErr = e;
      if (attempt >= maxRetries) throw e;
    }
  }
  throw lastErr || new Error('网络错误');
}

async function fetchAuthStatus() {
  if (!state.account) return;
  const res = await fetch(`/api/account-status?account=${encodeURIComponent(state.account)}`, { headers: { 'X-Admin-Token': state.token } });
  if (!res.ok) return;
  const data = await res.json();
  const el = document.getElementById('authStatus');
  if (el) el.textContent = data.authorized ? '已授权' : '未授权';
  const wasLocked = getAccountLocked();
  if (data.authorized || wasLocked) {
    setAccountLocked(true);
    setLoginInputsVisible(false);
  } else {
    setAccountLocked(false);
    setLoginInputsVisible(true);
  }
}

async function clearCache() {
  if (!state.token) { alert('请输入令牌并点击“保存令牌”'); return; }
  const acc = encodeURIComponent(state.account || '');
  const url = acc ? `/api/groups/cache/clear?account=${acc}` : '/api/groups/cache/clear';
  const res = await fetch(url, { headers: { 'X-Admin-Token': state.token } });
  if (res.ok) {
    await fetchGroups(true);
    alert('缓存已清除');
  } else {
    alert('清除缓存失败');
  }
}

async function debugGroups() {
  const acc = encodeURIComponent(state.account || '');
  const onlyGroups = state.includeChannels ? 'false' : 'true';
  const res = await fetch(`/api/groups/debug?only_groups=${onlyGroups}&account=${acc}`, { headers: { 'X-Admin-Token': state.token } });
  const d = await res.json().catch(() => ({}));
  const msg = `账号: ${d.account || ''}\n已授权: ${d.authorized ? '是' : '否'}\n会话: ${d.session_path || ''}\n总会话条目: ${d.dialogs_count || 0}\n采样返回: ${Array.isArray(d.sample) ? d.sample.length : 0}`;
  alert(msg);
}

async function sendLoginCode() {
  const phone = document.getElementById('loginPhone').value.trim();
  const forceSms = document.getElementById('forceSms')?.checked || false;
  if (!phone) { alert('请输入手机号'); return; }
  const res = await fetch('/api/login/send-code', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Token': state.token },
    body: JSON.stringify({ account: state.account, phone, force_sms: forceSms })
  });
  if (res.ok) {
    alert('验证码已发送');
  } else if (res.status === 429) {
    const d = await res.json();
    alert(`发送频率过高，请在 ${d.retry_after || 60} 秒后重试`);
  } else {
    const d = await res.json().catch(() => ({}));
    alert(`发送验证码失败：${d.detail || '未知错误'}`);
  }
}

async function submitLoginCode() {
  const phone = document.getElementById('loginPhone').value.trim();
  const code = document.getElementById('loginCode').value.trim();
  const password = document.getElementById('loginPassword').value.trim();
  if (!phone || !code) { alert('请输入手机号与验证码'); return; }
  const res = await fetch('/api/login/submit-code', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Token': state.token },
    body: JSON.stringify({ account: state.account, phone, code, password })
  });
  if (res.ok) {
    alert('登录成功');
    await fetchAccounts(); // Refresh accounts to update the dropdown status
    await fetchAuthStatus();
    setAccountLocked(true);
    setLoginInputsVisible(false);
    await fetchGroups(true);
  } else {
    alert('登录失败');
  }
}

function updateTokenLockUI() {
  const locked = (localStorage.getItem('tokenLocked') === '1');
  const input = document.getElementById('adminToken');
  const saveBtn = document.getElementById('saveToken');
  const editBtn = document.getElementById('editToken');
  if (input) input.disabled = locked;
  if (saveBtn) saveBtn.disabled = locked;
  if (editBtn) editBtn.style.display = locked ? 'inline-block' : 'none';
}

function setLoginInputsVisible(visible) {
  const ids = ['loginPhone','loginCode','loginPassword','forceSms','sendCodeBtn','confirmLoginBtn'];
  ids.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    // for label/checkbox forceSms, parent label holds id forceSms
    const node = el.tagName === 'INPUT' && el.type === 'checkbox' ? el.parentElement : el;
    if (node) node.style.display = visible ? '' : 'none';
  });
  const unlockBtn = document.getElementById('unlockAccount');
  if (unlockBtn) unlockBtn.style.display = visible ? 'none' : 'inline-block';
}

function setAccountLocked(locked) {
  const sel = document.getElementById('accountSelect');
  if (sel) sel.disabled = locked;
  try { localStorage.setItem('lockedAccount:' + (state.account || ''), locked ? '1' : '0'); } catch {}
}

function getAccountLocked() {
  try {
    const v = localStorage.getItem('lockedAccount:' + (state.account || ''));
    return v === '1';
  } catch { return false; }
}