/**
 * NavPulse — Vue 3 应用入口
 */
import { createApp, ref, provide, onMounted, onUnmounted } from 'vue'
import { store } from './store.js'
import { fetchStatus } from './api.js'

// ── 组件导入 ──
import LoadingOverlay from './components/LoadingOverlay.js'
import TopBar         from './components/TopBar.js'
import StatusBar      from './components/StatusBar.js'
import BottomNav      from './components/BottomNav.js'
import HoldingsView   from './components/HoldingsView.js'
import WatchlistView  from './components/WatchlistView.js'
import MarketView     from './components/MarketView.js'
import AddFundModal   from './components/AddFundModal.js'
import FundDetailModal from './components/FundDetailModal.js'
import SettingsView   from './components/SettingsView.js'
import OcrImportModal from './components/OcrImportModal.js'

// ── 认证检查 ──
if (!localStorage.getItem('token')) {
  location.href = '/login'
}

// ── 创建应用 ──
const app = createApp({
  setup() {
    const addModalRef   = ref(null)
    const detailModalRef = ref(null)
    const ocrModalRef    = ref(null)

    // 向后代组件提供打开弹窗的方法
    provide('openAddModal', (mode = 'holding') => {
      addModalRef.value?.open(mode)
    })
    provide('openDetailModal', (code, name) => {
      detailModalRef.value?.open(code, name)
    })
    provide('openOcrModal', () => {
      ocrModalRef.value?.open()
    })

    // 轮询系统状态
    let timer = null
    async function pollStatus() {
      try {
        const data = await fetchStatus()
        store.schedulerRunning = data.scheduler_running
        store.lastUpdateTime = data.last_update_time || '--'
        // 交易状态
        if (data.trading) {
          store.isTradingTime = data.trading.is_trading_time
          store.tradingStatusText = data.trading.status_text || ''
        }
        if (data.official_nav) {
          store.officialNavUpdated = !!data.official_nav.is_updated
          store.officialNavUpdatedCount = data.official_nav.updated_count || 0
          store.officialNavTotalTracked = data.official_nav.total_tracked || 0
        }
      } catch (_) {}
    }

    onMounted(() => {
      pollStatus()
      timer = setInterval(pollStatus, 30000)
    })

    onUnmounted(() => {
      if (timer) clearInterval(timer)
    })

    return { store, addModalRef, detailModalRef, ocrModalRef }
  }
})

// ── 注册组件 ──
app.component('loading-overlay',   LoadingOverlay)
app.component('top-bar',           TopBar)
app.component('status-bar',        StatusBar)
app.component('bottom-nav',        BottomNav)
app.component('holdings-view',     HoldingsView)
app.component('watchlist-view',    WatchlistView)
app.component('market-view',       MarketView)
app.component('add-fund-modal',    AddFundModal)
app.component('fund-detail-modal', FundDetailModal)
app.component('settings-view',     SettingsView)
app.component('ocr-import-modal',  OcrImportModal)

// ── 挂载 ──
app.mount('#app')
