/**
 * NavPulse API 调用层 — 统一封装所有后端接口
 */

function getToken() {
  return localStorage.getItem('token')
}

function authHeaders() {
  return {
    'Authorization': 'Bearer ' + getToken(),
    'Content-Type': 'application/json'
  }
}

/** 检查 401 → 跳转登录页 */
function checkAuth(response) {
  if (response.status === 401) {
    localStorage.removeItem('token')
    localStorage.removeItem('username')
    location.href = '/login'
    throw new Error('未登录')
  }
  return response
}

// ── 持仓 API ──────────────────────────────

export async function fetchPortfolio(forceRefresh = false) {
  const url = forceRefresh ? '/api/portfolio?force_refresh=true' : '/api/portfolio'
  const r = checkAuth(await fetch(url, { headers: authHeaders() }))
  if (!r.ok) throw new Error('网络错误')
  return r.json()
}

export async function addHolding(code, marketValue, profit, firstBuyDate) {
  const r = checkAuth(await fetch('/api/portfolio', {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ code, market_value: marketValue, profit, first_buy_date: firstBuyDate })
  }))
  if (!r.ok) { const e = await r.json(); throw new Error(e.detail || '添加失败') }
  return r.json()
}

export async function deleteHolding(code) {
  const r = checkAuth(await fetch('/api/portfolio/' + code, {
    method: 'DELETE', headers: authHeaders()
  }))
  if (!r.ok) { const e = await r.json(); throw new Error(e.detail || '删除失败') }
  return r.json()
}

// ── 自选 API ──────────────────────────────

export async function fetchWatchlist() {
  const r = checkAuth(await fetch('/api/watchlist', { headers: authHeaders() }))
  if (!r.ok) throw new Error('网络错误')
  return r.json()
}

export async function addWatchlistItem(code) {
  const r = checkAuth(await fetch('/api/watchlist', {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ code })
  }))
  if (!r.ok) { const e = await r.json(); throw new Error(e.detail || '添加失败') }
  return r.json()
}

export async function deleteWatchlistItem(code) {
  const r = checkAuth(await fetch('/api/watchlist/' + code, {
    method: 'DELETE', headers: authHeaders()
  }))
  if (!r.ok) { const e = await r.json(); throw new Error(e.detail || '删除失败') }
  return r.json()
}

// ── 行情 API ──────────────────────────────

export async function fetchMarket(forceRefresh = false) {
  const url = forceRefresh ? '/api/market?force_refresh=true' : '/api/market'
  const r = await fetch(url)
  if (!r.ok) throw new Error('网络错误')
  return r.json()
}

// ── 基金详情 API ──────────────────────────

export async function fetchValuation(code) {
  const r = await fetch('/api/valuation/' + code)
  if (!r.ok) throw new Error('获取失败')
  return r.json()
}

export async function fetchFundHistory(code, days = 90) {
  const r = await fetch('/api/fund/history/' + code + '?days=' + days)
  if (!r.ok) throw new Error('获取失败')
  return r.json()
}

export async function fetchFundDetail(code) {
  const r = checkAuth(await fetch('/api/fund/' + code + '/detail', { headers: authHeaders() }))
  if (!r.ok) throw new Error('获取失败')
  return r.json()
}

export async function fetchFundIntraday(code) {
  const r = await fetch('/api/fund/' + code + '/intraday')
  if (!r.ok) throw new Error('获取失败')
  return r.json()
}

export async function fetchTransactions(code) {
  const r = checkAuth(await fetch('/api/fund/' + code + '/transactions', { headers: authHeaders() }))
  if (!r.ok) throw new Error('获取失败')
  return r.json()
}

export async function addTransaction(code, data) {
  const r = checkAuth(await fetch('/api/fund/' + code + '/transactions', {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify(data)
  }))
  if (!r.ok) { const e = await r.json(); throw new Error(e.detail || '操作失败') }
  return r.json()
}

export async function deleteTransaction(code, txId) {
  const r = checkAuth(await fetch('/api/fund/' + code + '/transactions/' + txId, {
    method: 'DELETE', headers: authHeaders()
  }))
  if (!r.ok) { const e = await r.json(); throw new Error(e.detail || '删除失败') }
  return r.json()
}

// ── 基金洨跌榜 API ───────────────────

export async function fetchFundRank() {
  const r = await fetch('/api/market/fund-rank')
  if (!r.ok) throw new Error('获取失败')
  return r.json()
}

// ── 系统状态 API ──────────────────────────

export async function fetchStatus() {
  const r = await fetch('/api/status')
  if (!r.ok) throw new Error('获取状态失败')
  return r.json()
}
// ── OCR 截图导入 API ─────────────────

export async function ocrParseImage(file) {
  const formData = new FormData()
  formData.append('file', file)
  const r = checkAuth(await fetch('/api/portfolio/ocr-parse', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + getToken() },
    body: formData,
  }))
  if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'OCR 识别失败') }
  return r.json()
}

export async function batchImportHoldings(funds) {
  const r = checkAuth(await fetch('/api/portfolio/batch-import', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ funds }),
  }))
  if (!r.ok) { const e = await r.json(); throw new Error(e.detail || '批量导入失败') }
  return r.json()
}