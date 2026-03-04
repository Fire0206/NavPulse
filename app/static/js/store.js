/**
 * NavPulse 全局响应式状态
 */
import { reactive } from 'vue'

export const store = reactive({
  // 认证
  username: localStorage.getItem('username') || '',

  // 当前视图: 'holdings' | 'watchlist' | 'market' | 'settings'
  currentView: 'holdings',

  // 加载遮罩（保留兼容，不再由主视图触发）
  loading: false,
  loadingText: '正在加载数据',

  // 隐私模式：0=不隐藏, 1=仅隐藏持有金额, 2=隐藏持有金额+收益金额, 3=隐藏持有金额+收益金额+持有收益率
  privacyMode: parseInt(localStorage.getItem('navpulse_privacy_mode') || '0'),

  // 业务数据（由各组件加载并写入）
  holdingsData: null,
  watchlistData: null,
  marketData: null,

  // 系统状态
  schedulerRunning: false,
  lastUpdateTime: '--',

  // 交易状态
  isTradingTime: false,
  tradingStatusText: '',

  // Toast 消息内容
  toastMsg: '',
})

// ── 全局工具函数 ─────────────────────────

/** 显示 Toast */
export function showToast(msg) {
  store.toastMsg = msg
  const el = document.getElementById('liveToast')
  if (el && typeof bootstrap !== 'undefined') {
    bootstrap.Toast.getOrCreateInstance(el).show()
  }
}

/** 显示加载条（保留兼容） */
export function showLoading(text = '正在加载数据') {
  store.loadingText = text
  store.loading = true
}

/** 隐藏加载条（保留兼容） */
export function hideLoading() {
  store.loading = false
}

// ── 本地缓存策略 ─────────────────────────

const CACHE_PREFIX = 'navpulse_c_'

/**
 * 从 localStorage 读取缓存数据
 * @param {string} key 缓存键名
 * @returns {any|null} 解析后的数据，失败返回 null
 */
export function readCache(key) {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + key)
    if (!raw) return null
    return JSON.parse(raw)
  } catch {
    return null
  }
}

/**
 * 将数据写入 localStorage 缓存
 * @param {string} key 缓存键名
 * @param {any} data 要缓存的数据
 */
export function writeCache(key, data) {
  try {
    localStorage.setItem(CACHE_PREFIX + key, JSON.stringify(data))
  } catch {
    // localStorage 满或不可用，静默忽略
  }
}

/**
 * 刷新系统状态（更新时间戳、交易状态）
 * 在下拉刷新完成后调用，使 StatusBar 立即反映最新时间
 */
export async function refreshStatus() {
  try {
    const r = await fetch('/api/status', {
      headers: { 'Authorization': 'Bearer ' + localStorage.getItem('token') },
    })
    if (!r.ok) return
    const data = await r.json()
    store.lastUpdateTime = data.last_update_time || store.lastUpdateTime
    store.schedulerRunning = data.scheduler_running
    if (data.trading) {
      store.isTradingTime = data.trading.is_trading_time
      store.tradingStatusText = data.trading.status_text || ''
    }
  } catch (_) {}
}

/**
 * 根据隐私模式判断是否隐藏某类数据
 * @param {string} type 数据类型: 'amount'(持有金额), 'profit'(收益金额), 'rate'(收益率)
 * @returns {boolean} 是否应该隐藏
 */
export function shouldMask(type) {
  const mode = store.privacyMode
  if (mode === 0) return false
  if (mode === 1) return type === 'amount' // 仅隐藏持有金额
  if (mode === 2) return type === 'amount' || type === 'profit' // 隐藏持有金额+收益金额
  if (mode === 3) return true // 全部隐藏
  return false
}

/**
 * 显示值或隐藏符号
 * @param {any} value 原始值
 * @param {string} type 数据类型: 'amount', 'profit', 'rate'
 * @returns {string} 显示内容
 */
export function maskValue(value, type) {
  if (shouldMask(type)) return '***'
  return value
}
