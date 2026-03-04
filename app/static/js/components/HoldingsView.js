import { ref, computed, inject, watch, onMounted, onUnmounted } from 'vue'
import { store, showToast, readCache, writeCache, refreshStatus, maskValue } from '../store.js'
import { fetchPortfolio, deleteHolding } from '../api.js'
import { sign, cls, formatPrice } from '../utils.js'
import { usePullToRefresh } from './usePullToRefresh.js'

const CACHE_KEY = 'holdings'

export default {
  name: 'HoldingsView',
  setup() {
    const sortOrder = ref('default')
    const displayMode = ref(localStorage.getItem('holdings_display_mode') || 'grid') // 'grid' 或 'list'
    const refreshing = ref(false)
    const initialLoading = ref(false)   // 骨架屏：无缓存时首次加载
    const silentRefreshing = ref(false)  // 静默刷新：有缓存时后台更新
    const openAddModal = inject('openAddModal')
    const openDetailModal = inject('openDetailModal')
    const openOcrModal = inject('openOcrModal')

    // ── 计算属性 ──
    const summary = computed(() => {
      const d = store.holdingsData
      if (!d) return { mv: 0, dp: 0, dpr: 0, hp: 0, hpr: 0 }
      return {
        mv: d.total_market_value || 0,
        dp: d.total_daily_profit || 0,
        dpr: d.total_daily_profit_rate || 0,
        hp: d.total_profit || 0,
        hpr: d.total_profit_rate || 0,
      }
    })

    const sortedFunds = computed(() => {
      if (!store.holdingsData?.funds) return []
      const funds = [...store.holdingsData.funds]
      if (sortOrder.value === 'desc') funds.sort((a, b) => (b.estimate_change || 0) - (a.estimate_change || 0))
      else if (sortOrder.value === 'asc') funds.sort((a, b) => (a.estimate_change || 0) - (b.estimate_change || 0))
      return funds
    })

    const hasFunds = computed(() => sortedFunds.value.length > 0)

    // ── 缓存优先加载 ──
    async function loadHoldings() {
      // Step 1: 尝试读取缓存
      const cached = readCache(CACHE_KEY)
      if (cached) {
        store.holdingsData = cached
        silentRefreshing.value = true
      } else {
        initialLoading.value = true
      }

      // Step 2: 发起网络请求
      try {
        const data = await fetchPortfolio(true)
        store.holdingsData = data
        writeCache(CACHE_KEY, data)
      } catch (e) {
        if (!cached) showToast('加载失败: ' + e.message)
      } finally {
        initialLoading.value = false
        silentRefreshing.value = false
      }
    }

    async function refresh() {
      refreshing.value = true
      silentRefreshing.value = true
      try {
        const data = await fetchPortfolio(true)
        store.holdingsData = data
        writeCache(CACHE_KEY, data)
        showToast('✓ 刷新完成')
        refreshStatus()
      } catch (e) {
        showToast('加载失败: ' + e.message)
      } finally {
        refreshing.value = false
        silentRefreshing.value = false
      }
    }

    async function delHolding(code) {
      if (!confirm('确认删除 ' + code + ' ？')) return
      showToast('正在删除')
      try {
        await deleteHolding(code)
        showToast('✓ 已删除')
        // ── 乐观更新：立即从列表移除，无需等待全量刷新 ──
        if (store.holdingsData && store.holdingsData.funds) {
          store.holdingsData.funds = store.holdingsData.funds.filter(f => f.code !== code)
          // 重新计算汇总
          const funds = store.holdingsData.funds
          const tmv = funds.reduce((s, f) => s + (f.market_value || 0), 0)
          const tc  = funds.reduce((s, f) => s + (f.cost || 0), 0)
          const tdp = funds.reduce((s, f) => s + (f.daily_profit || 0), 0)
          store.holdingsData.total_market_value = parseFloat(tmv.toFixed(2))
          store.holdingsData.total_cost = parseFloat(tc.toFixed(2))
          store.holdingsData.total_profit = parseFloat((tmv - tc).toFixed(2))
          store.holdingsData.total_profit_rate = tc > 0 ? parseFloat(((tmv - tc) / tc * 100).toFixed(2)) : 0
          store.holdingsData.total_daily_profit = parseFloat(tdp.toFixed(2))
          store.holdingsData.total_daily_profit_rate = tmv > 0 ? parseFloat((tdp / tmv * 100).toFixed(2)) : 0
          writeCache(CACHE_KEY, store.holdingsData)
          // 后台静默刷新
          fetchPortfolio(true).then(data => {
            store.holdingsData = data
            writeCache(CACHE_KEY, data)
          }).catch(() => {})
        } else {
          store.holdingsData = null
          localStorage.removeItem('navpulse_c_' + CACHE_KEY)
        }
      } catch (e) {
        showToast('✗ ' + e.message)
      }
    }

    // ── 下拉刷新 ──
    const viewRef = ref(null)
    const { ptrState } = usePullToRefresh(() => viewRef.value, refresh)

    function toggleBlur() {
      // 点击眼睛图标时切换隐私模式: 0 → 当前设置的模式（非0） → 0
      if (store.privacyMode === 0) {
        // 恢复到上次设置的模式（默认模式1）
        const savedMode = parseInt(localStorage.getItem('navpulse_privacy_mode') || '1')
        store.privacyMode = savedMode || 1
      } else {
        store.privacyMode = 0
      }
    }

    function setSortOrder(order) {
      sortOrder.value = order
    }

    function toggleDisplayMode() {
      displayMode.value = displayMode.value === 'grid' ? 'list' : 'grid'
      localStorage.setItem('holdings_display_mode', displayMode.value)
    }

    // ── 视图切换时加载 ──
    watch(
      [() => store.currentView, () => store.holdingsData],
      ([view, data]) => {
        if (view === 'holdings' && !data) loadHoldings()
      },
      { immediate: true }
    )

    // ── 基金类型标签 CSS class ──
    function typeTagClass(f) {
      const t = f.fund_type || ''
      if (t.startsWith('qdii'))  return 'fund-type-tag tag-qdii'
      if (t === 'etf' || t === 'etf_linked') return 'fund-type-tag tag-etf'
      if (t === 'bond')   return 'fund-type-tag tag-bond'
      if (t === 'money')  return 'fund-type-tag tag-money'
      if (t === 'mixed')  return 'fund-type-tag tag-mixed'
      if (t === 'stock')  return 'fund-type-tag tag-stock'
      if (f.fund_type_label) return 'fund-type-tag tag-other'
      return ''
    }

    return {
      store, sortOrder, displayMode, refreshing, initialLoading, silentRefreshing,
      summary, sortedFunds, hasFunds,
      loadHoldings, refresh, delHolding, toggleBlur, setSortOrder, toggleDisplayMode,
      openAddModal, openDetailModal, openOcrModal,
      viewRef, ptrState,
      sign, cls, formatPrice, maskValue, typeTagClass,
    }
  },
  template: `
    <div class="view" ref="viewRef">
      <div class="ptr-bar" :class="ptrState">
        <template v-if="ptrState === 'loading'">
          <span class="silent-spinner" style="width:16px;height:16px;border-width:2px"></span>
          <span>刷新中…</span>
        </template>
        <template v-else>
          <i class="bi bi-arrow-down ptr-icon" :class="{ flip: ptrState === 'triggered' }"></i>
          <span>{{ ptrState === 'triggered' ? '释放刷新' : '下拉刷新' }}</span>
        </template>
      </div>
      <!-- ═══ 骨架屏状态 ═══ -->
      <template v-if="initialLoading">
        <div class="hero-card">
          <div class="skel-line skel-w40 skel-h12" style="margin-bottom:10px"></div>
          <div class="skel-line skel-w60 skel-h36" style="margin-bottom:16px"></div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <div class="skel-tag"></div><div class="skel-tag"></div>
            <div class="skel-tag"></div><div class="skel-tag"></div>
          </div>
        </div>
        <div class="action-bar">
          <div class="skel-btn"></div>
          <div class="skel-btn"></div>
        </div>
        <div class="view-inner">
          <div class="skel-card" v-for="i in 3" :key="i">
            <div style="display:flex;justify-content:space-between;margin-bottom:12px">
              <div>
                <div class="skel-line skel-w50 skel-h14" style="margin-bottom:6px"></div>
                <div class="skel-line skel-w30 skel-h10"></div>
              </div>
              <div class="skel-line skel-h22" style="width:70px"></div>
            </div>
            <div style="display:flex;gap:16px;padding-top:10px;border-top:1px solid var(--border)">
              <div style="flex:1"><div class="skel-line skel-w60 skel-h10" style="margin-bottom:4px"></div><div class="skel-line skel-w80 skel-h14"></div></div>
              <div style="flex:1"><div class="skel-line skel-w60 skel-h10" style="margin-bottom:4px"></div><div class="skel-line skel-w80 skel-h14"></div></div>
              <div style="flex:1"><div class="skel-line skel-w60 skel-h10" style="margin-bottom:4px"></div><div class="skel-line skel-w80 skel-h14"></div></div>
            </div>
          </div>
        </div>
      </template>

      <!-- ═══ 真实数据状态 ═══ -->
      <template v-else>
        <!-- Hero Card -->
        <div class="hero-card">
          <div class="hero-row">
            <div class="hero-left">
              <div class="hero-label">
                总市值（元）
                <i :class="store.privacyMode > 0 ? 'bi bi-eye-slash' : 'bi bi-eye'" @click="toggleBlur"></i>
                <span class="silent-spinner" v-if="silentRefreshing" title="数据校准中"></span>
              </div>
              <div class="hero-value privacy">
                {{ maskValue(formatPrice(summary.mv), 'amount') }}
              </div>
            </div>
            <div class="hero-right">
              <div class="hero-stat">
                <span class="stat-label">当日盈亏</span>
                <span class="stat-value privacy" :class="summary.dp >= 0 ? 'clr-up' : 'clr-down'">{{ maskValue(sign(summary.dp), 'profit') }}</span>
                <span class="stat-sub">
                  当日收益率
                  <span class="stat-sub-value" :class="summary.dpr >= 0 ? 'clr-up' : 'clr-down'">{{ maskValue(sign(summary.dpr) + '%', 'rate') }}</span>
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 操作栏 -->
        <div class="action-bar">
          <button class="btn-pink" @click="openAddModal('holding')">
            <i class="bi bi-plus-circle"></i> 添加基金
          </button>
          <button class="btn-ghost" @click="openOcrModal" title="截图导入持仓">
            <i class="bi bi-camera"></i> 截图导入
          </button>
          <button class="btn-ghost" @click="refresh" :disabled="refreshing">
            <template v-if="refreshing">
              <span class="silent-spinner" style="width:14px;height:14px;border-width:2px"></span> 计算中
            </template>
            <template v-else>
              <i class="bi bi-arrow-clockwise"></i> 刷新估值
            </template>
          </button>
        </div>

        <!-- 持仓列表 -->
        <div class="view-inner">
          <div class="sort-bar" v-if="hasFunds">
            <span style="font-size:11px;color:var(--text-light);margin-right:auto">排序</span>
            <button class="sort-btn" :class="{ active: sortOrder === 'default' }" @click="setSortOrder('default')">
              <i class="bi bi-list-ul"></i> 默认
            </button>
            <button class="sort-btn" :class="{ active: sortOrder === 'desc' }" @click="setSortOrder('desc')">
              <i class="bi bi-sort-down"></i> 涨幅↓
            </button>
            <button class="sort-btn" :class="{ active: sortOrder === 'asc' }" @click="setSortOrder('asc')">
              <i class="bi bi-sort-up"></i> 涨幅↑
            </button>
            <span style="width:1px;height:16px;background:var(--border);margin:0 4px"></span>
            <button class="sort-btn" :class="{ active: displayMode === 'grid' }" @click="toggleDisplayMode" title="网格视图">
              <i class="bi bi-grid-3x2"></i>
            </button>
            <button class="sort-btn" :class="{ active: displayMode === 'list' }" @click="toggleDisplayMode" title="列表视图">
              <i class="bi bi-list"></i>
            </button>
          </div>

          <!-- 网格卡片模式 -->
          <div class="funds-grid" v-if="displayMode === 'grid'">
            <div class="fund-item" v-for="f in sortedFunds" :key="f.code"
                 @click="openDetailModal(f.code, f.fund_name || f.name || f.code)">
              <div class="fi-header">
                <div>
                  <div class="fi-name">{{ f.fund_name || f.name || f.code }}</div>
                  <div class="fi-code">{{ f.code }}<span :class="typeTagClass(f)" v-if="f.fund_type_label">{{ f.fund_type_label }}</span></div>
                </div>
                <div class="fi-change" :class="cls(f.estimate_change || 0)">
                  {{ sign(f.estimate_change || 0) }}%
                </div>
              </div>
              <div class="fi-grid">
                <div class="fi-metric">
                  <div class="fi-label">持有金额</div>
                  <div class="fi-val privacy">
                    {{ maskValue(formatPrice(f.market_value || 0), 'amount') }}
                  </div>
                </div>
                <div class="fi-metric">
                  <div class="fi-label">当日盈亏</div>
                  <div class="fi-val" :class="cls(f.daily_profit || 0)">{{ maskValue(sign(f.daily_profit || 0), 'profit') }}</div>
                </div>
                <div class="fi-metric">
                  <div class="fi-label">持有收益</div>
                  <div class="fi-val" :class="cls(f.holding_profit || 0)">{{ maskValue(sign(f.holding_profit || 0), 'profit') }}</div>
                </div>
              </div>
              <div class="fi-actions" @click.stop>
                <button class="btn-del" @click="delHolding(f.code)"><i class="bi bi-trash3"></i> 删除</button>
              </div>
            </div>
          </div>

          <!-- 列表模式 -->
          <div v-else>
            <div class="watch-item holding-list-item" v-for="f in sortedFunds" :key="f.code"
                 @click="openDetailModal(f.code, f.fund_name || f.name || f.code)">
              <div class="hl-top">
                <div class="wi-info">
                  <div class="wi-name">{{ f.fund_name || f.name || f.code }}</div>
                  <div class="wi-code">{{ f.code }}<span :class="typeTagClass(f)" v-if="f.fund_type_label" style="margin-left:4px">{{ f.fund_type_label }}</span></div>
                </div>
                <div class="hl-values">
                  <div class="hl-col" :class="cls(f.estimate_change || 0)">
                    <div class="hl-label">当日涨幅</div>
                    <div class="hl-val">{{ sign(f.estimate_change || 0) }}%</div>
                  </div>
                  <div class="hl-col" :class="cls(f.daily_profit || 0)">
                    <div class="hl-label">当日收益</div>
                    <div class="hl-val privacy">{{ maskValue(sign(f.daily_profit || 0), 'profit') }}</div>
                  </div>
                  <div class="hl-col" :class="cls(f.holding_profit || 0)">
                    <div class="hl-label">持有收益</div>
                    <div class="hl-val privacy">{{ maskValue(sign(f.holding_profit || 0), 'profit') }}</div>
                    <div class="hl-rate">{{ sign(f.holding_profit_rate || 0) }}%</div>
                  </div>
                </div>
                <button class="btn-remove" @click.stop="delHolding(f.code)" title="删除">
                  <i class="bi bi-trash3"></i>
                </button>
              </div>
            </div>
          </div>

          <div class="empty-state" v-if="!hasFunds && store.holdingsData">
            <div class="empty-icon"><i class="bi bi-inbox"></i></div>
            <p>暂无持仓记录<br>点击上方「添加基金」开始记录</p>
          </div>
        </div>
      </template>
    </div>
  `
}
