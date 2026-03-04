import { ref, computed, watch, inject, onMounted, onUnmounted, nextTick } from 'vue'
import { store, showToast, readCache, writeCache, refreshStatus } from '../store.js'
import { fetchMarket, fetchFundRank } from '../api.js'
import { sign, cls } from '../utils.js'
import { usePullToRefresh } from './usePullToRefresh.js'

const CACHE_KEY = 'market'

export default {
  name: 'MarketView',
  setup() {
    const chartRef = ref(null)
    const viewRef = ref(null)
    let chartInstance = null

    const initialLoading = ref(false)
    const silentRefreshing = ref(false)
    const openDetailModal = inject('openDetailModal')

    const indexNames = ['上证指数', '深证成指', '创业板指']

    const indices = computed(() => {
      const list = store.marketData?.indices || []
      return indexNames.map(name => {
        const found = list.find(x => x.name === name)
        return found || { name, price: 0, change: 0, change_pct: 0 }
      })
    })

    const distribution = computed(() => store.marketData?.distribution || {})
    const sectors = computed(() => (store.marketData?.sectors || []).slice(0, 10))
    const updateTime = computed(() => store.marketData ? new Date().toLocaleTimeString() : '--')

    // ── 基金涨跌榜 ──
    const fundRank = ref(null)
    const loadingRank = ref(false)
    const rankTab = ref('top')
    const showAllRank = ref(false)

    const rankDate = computed(() => fundRank.value?.date || '')
    const rankTopList = computed(() => {
      const list = fundRank.value?.top || []
      return showAllRank.value ? list : list.slice(0, 5)
    })
    const rankBottomList = computed(() => {
      const list = fundRank.value?.bottom || []
      return showAllRank.value ? list : list.slice(0, 5)
    })
    const currentRankList = computed(() => rankTab.value === 'top' ? rankTopList.value : rankBottomList.value)

    // ── 缓存优先加载 ──
    async function loadMarket() {
      // 1. 优先展示 localStorage 缓存（秒开）
      const cached = readCache(CACHE_KEY)
      if (cached) {
        store.marketData = cached
        nextTick(() => renderChart())
      } else {
        initialLoading.value = true
      }

      // 2. 后台静默拉取最新数据（后端从 global_cache 秒级返回）
      try {
        const data = await fetchMarket()
        const hasData = data?.indices?.length && data.indices.some(x => x.price)
        if (hasData) {
          store.marketData = data
          writeCache(CACHE_KEY, data)
          nextTick(() => renderChart())
          initialLoading.value = false
        } else if (!cached) {
          // 后端缓存也为空（首次启动），自动重试等待后台刷新完成
          _retryUntilData(3)
        }
      } catch (e) {
        if (!cached) showToast('行情加载失败: ' + e.message)
        initialLoading.value = false
      }
    }

    /** 后端缓存为空时自动重试（首次启动场景） */
    async function _retryUntilData(maxRetries) {
      for (let i = 0; i < maxRetries; i++) {
        await new Promise(r => setTimeout(r, 2000))
        try {
          const data = await fetchMarket()
          if (data?.indices?.length && data.indices.some(x => x.price)) {
            store.marketData = data
            writeCache(CACHE_KEY, data)
            nextTick(() => renderChart())
            initialLoading.value = false
            return
          }
        } catch (e) {}
      }
      // 重试完仍无数据
      initialLoading.value = false
    }

    async function refresh() {
      silentRefreshing.value = true
      const oldTime = store.marketData?.last_update_time
      try {
        // 触发后台异步刷新（后端立即返回当前缓存，不阻塞）
        fetchMarket(true).catch(() => {})

        // 轮询等待后台刷新完成（最多 4 次 × 1.5 秒 = 6 秒）
        let updated = false
        for (let i = 0; i < 4; i++) {
          await new Promise(r => setTimeout(r, 1500))
          try {
            const data = await fetchMarket()
            if (data.last_update_time !== oldTime || !oldTime) {
              store.marketData = data
              writeCache(CACHE_KEY, data)
              nextTick(() => renderChart())
              updated = true
              break
            }
          } catch (e) {}
        }
        showToast(updated ? '✓ 刷新完成' : '✓ 数据暂无变化')
        refreshStatus()
      } catch (e) {
        showToast('行情刷新失败: ' + e.message)
      } finally {
        silentRefreshing.value = false
      }
    }

    async function loadFundRank() {
      if (fundRank.value) return
      loadingRank.value = true
      try {
        fundRank.value = await fetchFundRank()
      } catch (e) {
        // 静默失败
      } finally {
        loadingRank.value = false
      }
    }

    function openFundDetail(code, name) {
      openDetailModal(code, name)
    }

    function renderChart() {
      if (!chartRef.value) return
      const dist = distribution.value.distribution || {}

      if (!chartInstance) {
        chartInstance = echarts.init(chartRef.value)
      }

      const labels = ['≤-5', '-5~-3', '-3~-1', '-1~0', '0', '0~1', '1~3', '3~5', '≥5']
      const values = [
        dist.down_5||0, dist.down_3_5||0, dist.down_1_3||0, dist.down_0_1||0,
        dist.flat||0, dist.up_0_1||0, dist.up_1_3||0, dist.up_3_5||0, dist.up_5||0
      ]
      const colors = values.map((_, i) => {
        if (i < 4) return '#00B578'
        if (i === 4) return '#B0B8C1'
        return '#FF4D4F'
      })

      chartInstance.setOption({
        grid: { left: 35, right: 10, top: 20, bottom: 28 },
        xAxis: {
          type: 'category', data: labels,
          axisLine: { lineStyle: { color: '#F0F0F3' } },
          axisLabel: { fontSize: 10, color: '#95A5A6' }
        },
        yAxis: {
          type: 'value',
          axisLine: { show: false }, axisTick: { show: false },
          splitLine: { lineStyle: { color: '#F8F8FB' } },
          axisLabel: { fontSize: 10, color: '#95A5A6' }
        },
        series: [{
          type: 'bar',
          data: values.map((v, i) => ({
            value: v,
            itemStyle: { color: colors[i], borderRadius: [3, 3, 0, 0] }
          })),
          barWidth: '55%',
          label: {
            show: true, position: 'top', fontSize: 9, color: '#95A5A6',
            formatter: p => p.value > 0 ? p.value : ''
          }
        }]
      })
    }

    function handleResize() {
      if (chartInstance) chartInstance.resize()
    }

    // 切到行情视图时加载数据
    watch(() => store.currentView, (view) => {
      if (view === 'market' && !store.marketData) loadMarket()
      if (view === 'market') {
        loadFundRank()
        if (store.marketData) nextTick(() => renderChart())
      }
    }, { immediate: true })

    // 数据到达后渲染图表
    watch(() => store.marketData, (data) => {
      if (data && store.currentView === 'market') {
        nextTick(() => renderChart())
      }
    })

    // ── 下拉刷新 ──
    const { ptrState } = usePullToRefresh(() => viewRef.value, refresh)

    onMounted(() => window.addEventListener('resize', handleResize))
    onUnmounted(() => {
      window.removeEventListener('resize', handleResize)
      if (chartInstance) { chartInstance.dispose(); chartInstance = null }
    })

    return {
      chartRef, viewRef, initialLoading, silentRefreshing,
      indices, distribution, sectors, updateTime,
      fundRank, loadingRank, rankTab, showAllRank, rankDate,
      rankTopList, rankBottomList, currentRankList,
      openFundDetail, refresh, ptrState,
      sign, cls,
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

        <!-- ═══ 骨架屏 ═══ -->
        <template v-if="initialLoading">
          <!-- 指数骨架 -->
          <div class="index-cards">
            <div class="index-card" v-for="i in 3" :key="i">
              <div class="skel-line skel-w60 skel-h10" style="margin-bottom:8px"></div>
              <div class="skel-line skel-w80 skel-h22" style="margin-bottom:6px"></div>
              <div class="skel-line skel-w50 skel-h10"></div>
            </div>
          </div>
          <!-- 图表骨架 -->
          <div class="chart-card">
            <div class="skel-line skel-w40 skel-h14" style="margin-bottom:12px"></div>
            <div class="skel-line skel-h120" style="width:100%;border-radius:6px"></div>
          </div>
          <!-- 板块骨架 -->
          <div class="sector-card">
            <div class="skel-line skel-w40 skel-h14" style="margin-bottom:14px"></div>
            <div class="skel-card skel-sector" v-for="i in 5" :key="'s'+i">
              <div style="display:flex;align-items:center;gap:10px;flex:1">
                <div class="skel-line" style="width:24px;height:24px;border-radius:50%"></div>
                <div>
                  <div class="skel-line skel-w60 skel-h12" style="margin-bottom:4px"></div>
                  <div class="skel-line skel-w30 skel-h10"></div>
                </div>
              </div>
              <div class="skel-line skel-h14" style="width:50px"></div>
            </div>
          </div>
        </template>

        <!-- ═══ 真实数据 ═══ -->
        <template v-else>
          <!-- 指数卡片 -->
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:2px">
            <span style="font-size:11px;color:var(--text-light)">{{ updateTime }}</span>
            <button class="btn-ghost-sm" @click="refresh" :disabled="silentRefreshing" title="刷新行情">
              <template v-if="silentRefreshing">
                <span class="silent-spinner" style="width:12px;height:12px;border-width:2px"></span>
              </template>
              <template v-else>
                <i class="bi bi-arrow-clockwise"></i>
              </template>
            </button>
          </div>
          <div class="index-cards">
            <div class="index-card" v-for="idx in indices" :key="idx.name">
              <div class="idx-name">
                {{ idx.name }}
              </div>
              <div class="idx-price" :class="cls(idx.change_pct || 0)">
                {{ idx.price != null && idx.price !== 0 ? idx.price.toFixed(2) : '--' }}
              </div>
              <div class="idx-change" :class="cls(idx.change_pct || 0)">
                {{ idx.price != null && idx.price !== 0 ? ((idx.change||0) >= 0 ? '+' : '') + (idx.change||0).toFixed(2) + ' ' + ((idx.change_pct||0) >= 0 ? '+' : '') + (idx.change_pct||0).toFixed(2) + '%' : '--' }}
              </div>
            </div>
          </div>

          <!-- 基金涨跌分布 -->
          <div class="chart-card">
            <div class="card-title">
              <span>基金涨跌分布</span>
              <span class="update-time">{{ updateTime }}</span>
            </div>
            <div id="distributionChart" ref="chartRef"></div>
            <div class="distribution-summary">
              <span class="ds-down"><i class="bi bi-caret-down-fill"></i> 下跌 <strong>{{ distribution.down_count || '--' }}</strong></span>
              <span class="ds-up"><i class="bi bi-caret-up-fill"></i> 上涨 <strong>{{ distribution.up_count || '--' }}</strong></span>
            </div>
          </div>

          <!-- 板块排行 -->
          <div class="sector-card">
            <div class="card-title">
              <span>板块排行</span>
              <span style="font-size:11px;color:var(--text-light)">TOP 10</span>
            </div>
            <div>
              <div class="sector-row" v-for="(s, i) in sectors" :key="s.name">
                <div class="sr-left">
                  <div class="sr-rank">{{ i + 1 }}</div>
                  <div>
                    <div class="sr-name">{{ s.name }}</div>
                    <div class="sr-sub">{{ s.fund_count || '-' }}只基金</div>
                  </div>
                </div>
                <div class="sr-right">
                  <span class="sr-streak" v-if="s.streak">连涨{{ s.streak }}天</span>
                  <span class="sr-change" :class="cls(s.change_pct || 0)">{{ sign(s.change_pct || 0) }}%</span>
                </div>
              </div>
              <p v-if="!sectors.length" class="text-center py-3" style="color:var(--text-light);font-size:13px">暂无数据</p>
            </div>
          </div>

          <!-- 基金涨跌榜 -->
          <div class="sector-card" style="margin-top:14px">
            <div class="card-title" style="margin-bottom:10px">
              <span>基金涨跌榜</span>
              <span v-if="rankDate" style="font-size:11px;color:var(--text-light)">{{ rankDate }}</span>
            </div>

            <div style="display:flex;gap:6px;margin-bottom:12px">
              <button class="rank-tab" :class="{ active: rankTab === 'top', 'rank-up': rankTab === 'top' }"
                      @click="rankTab='top'; showAllRank=false">
                <i class="bi bi-graph-up-arrow"></i> 涨幅榜
              </button>
              <button class="rank-tab" :class="{ active: rankTab === 'bottom', 'rank-down': rankTab === 'bottom' }"
                      @click="rankTab='bottom'; showAllRank=false">
                <i class="bi bi-graph-down-arrow"></i> 跌幅榜
              </button>
            </div>

            <div v-if="loadingRank" style="text-align:center;padding:20px;color:var(--text-light);font-size:13px">
              <span class="spinner-border spinner-border-sm me-2"></span>加载中...
            </div>
            <div v-else-if="currentRankList.length">
              <div class="rank-row" v-for="(f, i) in currentRankList" :key="f.code"
                   @click="openFundDetail(f.code, f.name)">
                <div class="rr-rank" :class="{ 'rr-top3': i < 3 }">{{ i + 1 }}</div>
                <div class="rr-info">
                  <div class="rr-name">{{ f.name }}</div>
                  <div class="rr-code">{{ f.code }}</div>
                </div>
                <div class="rr-nav">{{ f.nav ? f.nav.toFixed(4) : '--' }}</div>
                <div class="rr-change" :class="cls(f.daily_change || 0)">
                  {{ sign(f.daily_change || 0) }}%
                </div>
              </div>

              <div style="text-align:center;padding:10px 0" v-if="(rankTab === 'top' ? (fundRank?.top?.length || 0) : (fundRank?.bottom?.length || 0)) > 5">
                <button class="btn-show-all" @click="showAllRank = !showAllRank">
                  {{ showAllRank ? '收起' : '查看全部' }}
                  <i :class="showAllRank ? 'bi bi-chevron-up' : 'bi bi-chevron-down'" style="margin-left:4px"></i>
                </button>
              </div>
            </div>
            <p v-else class="text-center py-3" style="color:var(--text-light);font-size:13px">暂无数据</p>
          </div>
        </template>
      </div>
    </div>
  `
}
