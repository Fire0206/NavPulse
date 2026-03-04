import { ref, computed, inject, watch, onMounted, onUnmounted } from 'vue'
import { store, showToast, readCache, writeCache, refreshStatus } from '../store.js'
import { fetchWatchlist, deleteWatchlistItem } from '../api.js'
import { sign, cls } from '../utils.js'
import { usePullToRefresh } from './usePullToRefresh.js'

const CACHE_KEY = 'watchlist'

export default {
  name: 'WatchlistView',
  setup() {
    const sortOrder = ref('default')
    const refreshing = ref(false)
    const initialLoading = ref(false)
    const silentRefreshing = ref(false)
    const openAddModal = inject('openAddModal')
    const openDetailModal = inject('openDetailModal')

    const funds = computed(() => {
      if (!store.watchlistData?.funds) return []
      const list = [...store.watchlistData.funds]
      if (sortOrder.value === 'desc') list.sort((a, b) => (b.estimate_change || 0) - (a.estimate_change || 0))
      else if (sortOrder.value === 'asc') list.sort((a, b) => (a.estimate_change || 0) - (b.estimate_change || 0))
      return list
    })

    const hasFunds = computed(() => funds.value.length > 0)
    const watchCount = computed(() => funds.value.length)

    // ── 缓存优先加载 ──
    async function loadWatchlist() {
      const cached = readCache(CACHE_KEY)
      if (cached) {
        store.watchlistData = cached
        silentRefreshing.value = true
      } else {
        initialLoading.value = true
      }

      try {
        const data = await fetchWatchlist()
        store.watchlistData = data
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
        const data = await fetchWatchlist()
        store.watchlistData = data
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

    async function delWatchlist(code) {
      if (!confirm('确定移除该自选基金？')) return
      try {
        await deleteWatchlistItem(code)
        showToast('✓ 已移除自选')
        store.watchlistData = null
        localStorage.removeItem('navpulse_c_' + CACHE_KEY)
      } catch (e) {
        showToast('✗ ' + e.message)
      }
    }

    function setSortOrder(order) {
      sortOrder.value = order
    }

    // ── 下拉刷新 ──
    const viewRef = ref(null)
    const { ptrState } = usePullToRefresh(() => viewRef.value, refresh)

    watch(
      [() => store.currentView, () => store.watchlistData],
      ([view, data]) => {
        if (view === 'watchlist' && !data) loadWatchlist()
      },
      { immediate: true }
    )

    // ── 基金类型标签 CSS class（与持有页保持一致） ──
    function typeTagClass(f) {
      const t = f.fund_type || ''
      if (t.startsWith('qdii')) return 'fund-type-tag tag-qdii'
      if (t === 'etf' || t === 'etf_linked') return 'fund-type-tag tag-etf'
      if (t === 'bond') return 'fund-type-tag tag-bond'
      if (t === 'money') return 'fund-type-tag tag-money'
      if (t === 'mixed') return 'fund-type-tag tag-mixed'
      if (t === 'stock') return 'fund-type-tag tag-stock'
      if (f.fund_type_label) return 'fund-type-tag tag-other'
      return ''
    }

    return {
      store, sortOrder, refreshing, initialLoading, silentRefreshing,
      funds, hasFunds, watchCount,
      loadWatchlist, refresh, delWatchlist, setSortOrder,
      openAddModal, openDetailModal,
      viewRef, ptrState,
      sign, cls, typeTagClass,
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
      <div class="view-inner">
        <div class="section-header">
          <span class="sh-label">
            我的自选 <strong>{{ watchCount }}</strong> 只
            <span class="silent-spinner" v-if="silentRefreshing" style="margin-left:6px" title="更新中"></span>
          </span>
          <div style="display:flex;gap:6px;align-items:center">
            <button class="btn-ghost-sm" @click="refresh" :disabled="refreshing" title="刷新估值">
              <template v-if="refreshing">
                <span class="silent-spinner" style="width:12px;height:12px;border-width:2px"></span>
              </template>
              <template v-else>
                <i class="bi bi-arrow-clockwise"></i>
              </template>
            </button>
            <button class="btn-pink-sm" @click="openAddModal('watchlist')">
              <i class="bi bi-plus"></i> 添加自选
            </button>
          </div>
        </div>

        <!-- ═══ 骨架屏 ═══ -->
        <template v-if="initialLoading">
          <div class="skel-card skel-watch" v-for="i in 4" :key="i">
            <div style="flex:1">
              <div class="skel-line skel-w50 skel-h14" style="margin-bottom:6px"></div>
              <div class="skel-line skel-w30 skel-h10"></div>
            </div>
            <div class="skel-line skel-h20" style="width:70px"></div>
          </div>
        </template>

        <!-- ═══ 真实数据 ═══ -->
        <template v-else>
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
          </div>

          <div>
            <div class="watch-item" v-for="f in funds" :key="f.code"
                 @click="openDetailModal(f.code, f.fund_name || f.name || f.code)">
              <div class="wi-info">
                <div class="wi-name">{{ f.fund_name || f.name || f.code }}</div>
                <div class="wi-code" style="display:flex;align-items:center;gap:4px">{{ f.code }}<span :class="typeTagClass(f)" v-if="f.fund_type_label">{{ f.fund_type_label }}</span></div>
              </div>
              <div class="wi-right">
                <div class="wi-change" :class="cls(f.estimate_change || 0)">
                  {{ sign(f.estimate_change || 0) }}%
                </div>
                <button class="btn-remove" @click.stop="delWatchlist(f.code)" title="移除">
                  <i class="bi bi-x"></i>
                </button>
              </div>
            </div>
          </div>

          <div class="empty-state" v-if="!hasFunds && store.watchlistData">
            <div class="empty-icon"><i class="bi bi-star"></i></div>
            <p>暂无自选基金<br>添加关注的基金随时查看涨跌</p>
          </div>
        </template>
      </div>
    </div>
  `
}
