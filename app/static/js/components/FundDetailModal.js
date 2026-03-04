import { ref, computed, reactive, nextTick, onMounted, onUnmounted } from 'vue'
import { showToast, store } from '../store.js'
import {
  fetchFundDetail, fetchFundHistory, fetchFundIntraday,
  fetchValuation, addTransaction, deleteTransaction,
} from '../api.js'
import { sign, cls, formatPrice } from '../utils.js'

export default {
  name: 'FundDetailModal',
  setup() {
    const modalEl = ref(null)
    let bsModal = null

    // ── 基础状态 ──
    const fundCode = ref('')
    const fundName = ref('')
    const activeTab = ref('realtime')
    const loading = ref(false)

    // ── 详情数据 ──
    const detail = ref(null)
    const stocks = computed(() => detail.value?.stocks || [])

    // ── 实时走势 ──
    const intradayData = ref(null)
    const intradayChartRef = ref(null)
    let intradayChart = null
    let intradayTimer = null

    // ── 业绩走势 ──
    const periodDays = ref(90)
    const historyData = ref(null)
    const loadingHistory = ref(false)
    const perfChartRef = ref(null)
    let perfChart = null
    const historyList = computed(() => {
      const h = historyData.value?.history || []
      return h.slice().reverse().slice(0, 30)
    })
    const periods = [
      { days: 30,   label: '近1月' },
      { days: 90,   label: '近3月' },
      { days: 180,  label: '近6月' },
      { days: 365,  label: '近1年' },
      { days: 1095, label: '近3年' },
    ]

    // ── 持仓管理 ──
    const showTxPanel = ref(false)
    const txForm = reactive({ type: 'buy', date: '', amount: '' })
    const submittingTx = ref(false)

    /** 金额输入过滤：只允许数字和小数点，自动保留两位小数 */
    function onTxAmountInput(e) {
      let v = e.target.value
      v = v.replace(/[^\d.]/g, '')
      const parts = v.split('.')
      if (parts.length > 2) v = parts[0] + '.' + parts.slice(1).join('')
      if (parts.length === 2 && parts[1].length > 2) {
        v = parts[0] + '.' + parts[1].slice(0, 2)
      }
      txForm.amount = v
      e.target.value = v
    }

    // ── 计算属性 ──
    const holdingStats = computed(() => {
      const d = detail.value
      if (!d || !d.has_holding) return null
      return {
        shares: d.total_shares || 0,
        marketValue: d.market_value || 0,
        cost: d.total_cost || 0,
        avgCost: d.avg_cost_per_share || 0,
        profit: d.holding_profit || 0,
        profitRate: d.holding_profit_rate || 0,
        dailyProfit: d.daily_profit || 0,
        positionRatio: d.position_ratio || 0,
        holdingDays: d.holding_days || 0,
      }
    })
    const transactions = computed(() => detail.value?.transactions || [])

    // 重仓数据更新时间
    const portfolioUpdatedAt = computed(() => {
      const t = detail.value?.portfolio_updated_at || ''
      if (!t) return ''
      return t.slice(0, 16)  // YYYY-MM-DD HH:MM
    })
    // 历史净値更新时间
    const historyUpdatedAt = computed(() => {
      const t = historyData.value?.updated_at || ''
      if (!t) return ''
      return t  // YYYY-MM-DD
    })

    onMounted(() => {
      bsModal = new bootstrap.Modal(modalEl.value)
      // 弹窗关闭时清理定时器和图表
      modalEl.value.addEventListener('hidden.bs.modal', () => {
        clearIntraday()
        if (perfChart) { perfChart.dispose(); perfChart = null }
      })
      window.addEventListener('resize', handleResize)
    })

    onUnmounted(() => {
      window.removeEventListener('resize', handleResize)
      clearIntraday()
      if (perfChart) { perfChart.dispose(); perfChart = null }
    })

    function handleResize() {
      if (intradayChart) intradayChart.resize()
      if (perfChart) perfChart.resize()
    }

    function clearIntraday() {
      if (intradayTimer) { clearInterval(intradayTimer); intradayTimer = null }
      if (intradayChart) { intradayChart.dispose(); intradayChart = null }
    }

    // ═════════ 打开弹窗 ═════════
    function open(code, name) {
      fundCode.value = code
      fundName.value = name || code
      activeTab.value = 'realtime'
      detail.value = null
      historyData.value = null
      intradayData.value = null
      showTxPanel.value = false
      clearIntraday()

      // ── 速显: 从已有的持仓数据中提取预览，立即展示 ──
      const existing = store.holdingsData?.funds?.find(f => f.code === code)
      if (existing) {
        fundName.value = existing.name || name || code
        detail.value = {
          fund_code: code,
          fund_name: existing.name || name || code,
          estimate_change: existing.estimate_change || 0,
          last_nav: existing.last_nav || 0,
          has_holding: true,
          total_shares: existing.shares || 0,
          total_cost: existing.cost || 0,
          avg_cost_per_share: existing.avg_cost || 0,
          market_value: existing.market_value || 0,
          daily_profit: existing.daily_profit || 0,
          holding_profit: existing.holding_profit || 0,
          holding_profit_rate: existing.holding_profit_rate || 0,
          position_ratio: 0,
          holding_days: 0,
          stocks: [],
          transactions: [],
          _preview: true,  // 标记为预览数据
        }
      }

      loading.value = !detail.value  // 有预览则不显示全屏loading
      Promise.all([
        loadDetail(code),
        loadIntraday(code),
      ]).finally(() => { loading.value = false })

      bsModal.show()

      // 交易时段自动轮询日内数据
      intradayTimer = setInterval(() => {
        if (intradayData.value?.is_live) loadIntraday(fundCode.value)
      }, 30000)
    }

    async function loadDetail(code) {
      try {
        detail.value = await fetchFundDetail(code)
        const apiName = detail.value?.fund_name
        if (apiName && apiName !== code) {
          fundName.value = apiName
        }
      } catch (e) {
        try {
          const val = await fetchValuation(code)
          detail.value = {
            ...val, has_holding: false, transactions: [],
            stocks: val.holdings || [],
          }
          const fallbackName = val?.fund_name
          if (fallbackName && fallbackName !== code) {
            fundName.value = fallbackName
          }
        } catch (_) {
          showToast('获取详情失败')
        }
      }
    }

    async function loadIntraday(code) {
      try {
        intradayData.value = await fetchFundIntraday(code)
        await nextTick()
        renderIntradayChart()
      } catch (_) {}
    }

    // ═════════ Tab 切换 ═════════
    function switchTab(tab) {
      activeTab.value = tab
      if (tab === 'performance' && !historyData.value) {
        periodDays.value = 90
        loadPerformance(fundCode.value, 90)
      }
      if (tab === 'realtime') {
        nextTick(() => renderIntradayChart())
      }
    }

    // ═════════ 实时走势图 ═════════
    function renderIntradayChart() {
      if (!intradayChartRef.value) return
      const pts = intradayData.value?.points || []

      if (intradayChart) intradayChart.dispose()
      intradayChart = echarts.init(intradayChartRef.value)

      // ── 生成交易时间轴，AM/PM 直接拼接（跳过午休 11:31-12:59）──
      const amTimes = [], pmTimes = []
      for (let h = 9; h <= 11; h++) {
        const start = h === 9 ? 30 : 0
        const end   = h === 11 ? 31 : 60
        for (let m = start; m < end; m++)
          amTimes.push(String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0'))
      }
      for (let h = 13; h <= 14; h++)
        for (let m = 0; m < 60; m++)
          pmTimes.push(String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0'))
      pmTimes.push('15:00')

      const fullTimes  = [...amTimes, ...pmTimes]
      const noonSepIdx = amTimes.length - 1  // 11:30 的索引，告云各下午分隔线位置
      const pmStartIdx = amTimes.length      // 13:00 的索引

      // 映射数据
      const dataMap = {}
      pts.forEach(p => { dataMap[p.time] = p.change })
      const rawData = fullTimes.map(t => dataMap[t] !== undefined ? dataMap[t] : null)

      // ── 异常尖刺过滤：将"孤立的 0%"替换为 null ──
      // 当某个点为 0，而前后各取最多3个有效点的均值绝对值 > 0.5% 时，视为采集失败的坏点
      const data = rawData.map((v, i) => {
        if (v !== 0) return v
        // 收集前3个有效邻居
        const neighbors = []
        for (let di = 1; di <= 3 && neighbors.length < 3; di++) {
          if (i - di >= 0 && rawData[i - di] !== null && rawData[i - di] !== 0) neighbors.push(rawData[i - di])
          if (i + di < rawData.length && rawData[i + di] !== null && rawData[i + di] !== 0) neighbors.push(rawData[i + di])
        }
        if (neighbors.length === 0) return v
        const avg = neighbors.reduce((s, x) => s + Math.abs(x), 0) / neighbors.length
        return avg > 0.5 ? null : v  // 绝对均值 > 0.5% → 坏点，替为 null
      })

      // ── 颜色：跟随最新有效値（上涨=红，下跌=绿）──
      const lastVal   = [...data].reverse().find(v => v !== null)
      const lineColor = lastVal == null ? '#94A3B8' : lastVal >= 0 ? '#EF4444' : '#10B981'
      const areaBase  = lastVal == null ? '148,163,184' : lastVal >= 0 ? '239,68,68' : '16,185,129'

      intradayChart.setOption({
        grid: { left: 54, right: 14, top: 20, bottom: 32 },
        xAxis: {
          type: 'category', data: fullTimes, boundaryGap: false,
          axisLabel: {
            fontSize: 11, color: '#94A3B8',
            interval: (i) => i === 0 || i === noonSepIdx || fullTimes[i] === '15:00',
            formatter: (val, i) => {
              if (i === 0)          return '09:30'
              if (i === noonSepIdx) return '11:30\n13:30'
              if (val === '15:00')  return '15:00'
              return ''
            },
          },
          axisLine: { lineStyle: { color: '#E2E8F0' } },
          splitLine: { show: false },
        },
        yAxis: {
          type: 'value',
          axisLine: { show: false }, axisTick: { show: false },
          splitLine: { lineStyle: { color: '#F0F4FA' } },
          axisLabel: { fontSize: 11, color: '#94A3B8', formatter: v => v.toFixed(2) + '%' },
        },
        series: [{
          type: 'line', data,
          connectNulls: false,   // 断网期间保留真实缺口
          smooth: false, symbol: 'none',
          lineStyle: { color: lineColor, width: 1.8 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: `rgba(${areaBase},0.16)` },
              { offset: 1, color: `rgba(${areaBase},0.01)` },
            ]),
          },
          markLine: {
            silent: true, symbol: 'none',
            data: [
              // 零轴
              { yAxis: 0, lineStyle: { color: '#CBD5E1', type: 'dashed', width: 1 } },
            ],
          },
        }],
        tooltip: {
          trigger: 'axis', confine: true,
          formatter: params => {
            if (!params[0]) return ''
            const idx      = params[0].dataIndex
            const realTime = idx < amTimes.length ? amTimes[idx] : pmTimes[idx - amTimes.length]
            const val      = params[0].data
            return realTime + '<br/>估值: ' + (val != null ? val.toFixed(2) + '%' : '--')
          },
        },
      })
      setTimeout(() => { if (intradayChart) intradayChart.resize() }, 80)
    }

    // ═════════ 业绩走势 ═════════
    function changePeriod(days) {
      periodDays.value = days
      loadPerformance(fundCode.value, days)
    }

    async function loadPerformance(code, days) {
      loadingHistory.value = true
      try {
        historyData.value = await fetchFundHistory(code, days)
        await nextTick()
        renderPerfChart()
      } catch (e) {
        showToast('获取走势失败')
      } finally {
        loadingHistory.value = false
      }
    }

    function renderPerfChart() {
      if (!perfChartRef.value) return
      const history = historyData.value?.history || []
      if (!history.length) return

      if (perfChart) perfChart.dispose()
      perfChart = echarts.init(perfChartRef.value)

      const dates = history.map(h => h.date)
      const navs = history.map(h => h.nav)

      // 标记买卖节点
      const txList = transactions.value || []
      const markData = []
      txList.forEach(tx => {
        const idx = dates.indexOf(tx.date)
        if (idx === -1) return
        markData.push({
          coord: [idx, navs[idx]],
          value: '',
          symbol: 'circle',
          symbolSize: 8,
          itemStyle: { color: tx.type === 'sell' ? '#10B981' : '#EF4444' },
          label: { show: false },
        })
      })

      // 平均成本虚线
      const avgCost = holdingStats.value?.avgCost || 0
      const markLines = []
      if (avgCost > 0) {
        markLines.push({
          yAxis: avgCost,
          label: {
            formatter: '成本 ' + avgCost.toFixed(4),
            fontSize: 10, color: '#F5A623', position: 'insideEndTop',
          },
          lineStyle: { color: '#F5A623', type: 'dashed', width: 1.5 },
        })
      }

      perfChart.setOption({
        grid: { left: 50, right: 20, top: 24, bottom: 30 },
        xAxis: {
          type: 'category', data: dates, boundaryGap: false,
          axisLine: { lineStyle: { color: '#F0F0F3' } },
          axisLabel: { fontSize: 10, color: '#95A5A6' },
        },
        yAxis: {
          type: 'value',
          axisLine: { show: false }, axisTick: { show: false },
          splitLine: { lineStyle: { color: '#F8F8FB' } },
          axisLabel: { fontSize: 11, color: '#95A5A6' },
          min: v => Number((v.min - 0.02).toFixed(4)),
          max: v => Number((v.max + 0.02).toFixed(4)),
        },
        series: [{
          type: 'line', data: navs, smooth: true, symbol: 'none',
          lineStyle: { color: '#FB7299', width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(251,114,153,0.22)' },
              { offset: 1, color: 'rgba(251,114,153,0.01)' },
            ]),
          },
          markPoint: { data: markData },
          markLine: { silent: true, symbol: 'none', data: markLines },
        }],
        tooltip: {
          trigger: 'axis', confine: true,
          formatter: p => {
            if (!p[0]) return ''
            return p[0].axisValue + '<br/>净值: ' +
              (p[0].data != null ? Number(p[0].data).toFixed(4) : '--')
          },
        },
      })
      setTimeout(() => { if (perfChart) perfChart.resize() }, 80)
    }

    // ═════════ 持仓管理 ═════════
    function toggleTxPanel() {
      showTxPanel.value = !showTxPanel.value
      if (showTxPanel.value) {
        const today = new Date()
        txForm.date = today.getFullYear() + '-' +
          String(today.getMonth() + 1).padStart(2, '0') + '-' +
          String(today.getDate()).padStart(2, '0')
        txForm.type = 'buy'
        txForm.amount = ''
      }
    }

    async function submitTx() {
      if (!txForm.amount || !txForm.date) {
        showToast('请填写完整信息'); return
      }
      const amount = parseFloat(txForm.amount)
      if (isNaN(amount) || amount <= 0) {
        showToast('金额必须大于 0'); return
      }

      // 防呆校验: 日期不能早于首次买入日期
      const stats = holdingStats.value
      if (stats) {
        const firstDate = detail.value?.first_buy_date
        if (firstDate && txForm.date < firstDate) {
          showToast('操作日期不能早于首次买入日期 (' + firstDate + ')')
          return
        }
      }

      // 减仓校验: 卖出金额不能大于当前持仓市值
      if (txForm.type === 'sell' && stats) {
        const mv = stats.marketValue || 0
        if (amount > mv) {
          showToast('卖出金额不能超过当前持仓市值 (¥' + mv.toFixed(2) + ')')
          return
        }
      }

      submittingTx.value = true
      try {
        await addTransaction(fundCode.value, {
          type: txForm.type,
          date: txForm.date,
          amount: amount,
        })
        showToast('✓ 交易已记录，持仓成本已更新')
        txForm.amount = ''
        // 使持仓数据失效，回到持仓列表时自动刷新
        store.holdingsData = null
        await loadDetail(fundCode.value)
        if (activeTab.value === 'performance' && historyData.value) {
          await nextTick()
          renderPerfChart()
        }
      } catch (e) {
        showToast('✗ ' + e.message)
      } finally {
        submittingTx.value = false
      }
    }

    async function removeTx(txId) {
      if (!confirm('确认删除该交易记录？')) return
      try {
        await deleteTransaction(fundCode.value, txId)
        showToast('✓ 已删除')
        // 使持仓数据失效
        store.holdingsData = null
        await loadDetail(fundCode.value)
        if (activeTab.value === 'performance' && historyData.value) {
          await nextTick()
          renderPerfChart()
        }
      } catch (e) {
        showToast('✗ ' + e.message)
      }
    }

    return {
      modalEl, fundCode, fundName, activeTab, loading,
      detail, stocks, holdingStats, transactions,
      portfolioUpdatedAt, historyUpdatedAt,
      intradayData, intradayChartRef,
      periodDays, historyData, loadingHistory, historyList, perfChartRef, periods,
      showTxPanel, txForm, submittingTx,
      open, switchTab, changePeriod, toggleTxPanel, submitTx, removeTx,
      sign, cls, formatPrice, onTxAmountInput,
    }
  },

  template: `
<div class="modal fade" ref="modalEl" tabindex="-1">
  <div class="modal-dialog modal-fullscreen fd-dialog">
    <div class="modal-content fund-detail-page">

      <!-- ═══ 顶部导航 ═══ -->
      <div class="fd-header">
        <button class="fd-back" data-bs-dismiss="modal"><i class="bi bi-chevron-left"></i></button>
        <div class="fd-title">
          <div class="fd-name">{{ fundName }}</div>
          <div class="fd-code">{{ fundCode }}</div>
        </div>
        <button class="fd-tx-btn" @click="toggleTxPanel" title="持仓管理">
          <i class="bi bi-pencil-square"></i>
        </button>
      </div>

      <!-- ═══ 估值 + 持仓概览 ═══ -->
      <div class="fd-hero">
        <div class="fd-change" :class="cls(detail?.estimate_change || 0)">
          <div class="fd-change-label">当日估值</div>
          <div class="fd-change-value">{{ detail ? sign(detail.estimate_change || 0) + '%' : '--' }}</div>
          <div class="estimation-source" v-if="detail?.estimation_method">
            <template v-if="detail.estimation_method === 'etf_realtime'">
              <i class="bi bi-lightning-charge-fill"></i> 参考ETF: {{ detail.etf_name || detail.etf_code || '' }}
            </template>
            <template v-else-if="detail.estimation_method === 'overseas_index'">
              <i class="bi bi-globe2"></i> 参考指数: {{ detail.benchmark_name || '' }}
              <span v-if="detail.settlement_delay">(T+{{ detail.settlement_delay }})</span>
            </template>
            <template v-else-if="detail.estimation_method === 'weighted_holdings'">
              <i class="bi bi-calculator"></i> 重仓股估算
            </template>
            <template v-else-if="detail.estimation_method === 'nav_history'">
              <i class="bi bi-clock-history"></i> 历史净值
            </template>
          </div>
        </div>

        <div class="fd-stats-grid" v-if="holdingStats">
          <div class="fd-stat">
            <span class="fd-stat-label">持有金额</span>
            <span class="fd-stat-value">{{ formatPrice(holdingStats.marketValue) }}</span>
          </div>
          <div class="fd-stat">
            <span class="fd-stat-label">持有份额</span>
            <span class="fd-stat-value">{{ holdingStats.shares.toFixed(2) }}</span>
          </div>
          <div class="fd-stat">
            <span class="fd-stat-label">持仓占比</span>
            <span class="fd-stat-value">{{ holdingStats.positionRatio.toFixed(2) }}%</span>
          </div>
          <div class="fd-stat">
            <span class="fd-stat-label">持有收益</span>
            <span class="fd-stat-value" :class="cls(holdingStats.profit)">{{ sign(holdingStats.profit) }}</span>
          </div>
          <div class="fd-stat">
            <span class="fd-stat-label">收益率</span>
            <span class="fd-stat-value" :class="cls(holdingStats.profitRate)">{{ sign(holdingStats.profitRate) }}%</span>
          </div>
          <div class="fd-stat">
            <span class="fd-stat-label">持仓成本</span>
            <span class="fd-stat-value">{{ holdingStats.avgCost.toFixed(4) }}</span>
          </div>
          <div class="fd-stat">
            <span class="fd-stat-label">当日收益</span>
            <span class="fd-stat-value" :class="cls(holdingStats.dailyProfit)">{{ sign(holdingStats.dailyProfit) }}</span>
          </div>
          <div class="fd-stat">
            <span class="fd-stat-label">持有天数</span>
            <span class="fd-stat-value">{{ holdingStats.holdingDays }}</span>
          </div>
        </div>
        <div v-else-if="detail && !detail.has_holding" class="fd-no-holding">
          暂无持仓，点击右上角 <i class="bi bi-pencil-square"></i> 添加交易记录
        </div>
      </div>

      <!-- ═══ 持仓管理面板 ═══ -->
      <div class="fd-tx-panel" v-show="showTxPanel">
        <div class="fd-tx-form">
          <div class="fd-tx-type">
            <button :class="['fd-type-btn', txForm.type === 'buy' ? 'active buy' : '']"
                    @click="txForm.type='buy'">加仓</button>
            <button :class="['fd-type-btn', txForm.type === 'sell' ? 'active sell' : '']"
                    @click="txForm.type='sell'">减仓</button>
          </div>
          <div class="fd-tx-row">
            <label>{{ txForm.type === 'buy' ? '加仓确认日期' : '减仓/赎回确认日期' }}</label>
            <input type="date" v-model="txForm.date">
          </div>
          <div class="fd-tx-row">
            <label>{{ txForm.type === 'buy' ? '买入金额 (元)' : '卖出金额 (元)' }}</label>
            <input type="text" inputmode="decimal"
                   v-model="txForm.amount" @input="onTxAmountInput"
                   :placeholder="txForm.type === 'buy' ? '请输入本次申购扣款金额' : '请输入实际到账金额 (或预估金额)'"
                   step="0.01">
          </div>
          <div class="fd-tx-row fd-tx-nav-row">
            <span></span>
            <button class="fd-tx-submit" @click="submitTx" :disabled="submittingTx" style="min-width:80px">
              <span v-if="submittingTx"><span class="spinner-border spinner-border-sm me-1"></span>提交中</span>
              <span v-else>确认</span>
            </button>
          </div>
        </div>

        <div class="fd-tx-list" v-if="transactions.length">
          <div class="fd-tx-list-title">交易记录</div>
          <div class="fd-tx-item" v-for="tx in transactions" :key="tx.id">
            <span class="fd-tx-tag" :class="tx.type">{{ tx.type === 'init' ? '初始' : tx.type === 'buy' ? '加仓' : '减仓' }}</span>
            <span class="fd-tx-date">{{ tx.date }}</span>
            <span class="fd-tx-info">¥{{ tx.amount.toFixed(2) }}</span>
            <button class="fd-tx-del" @click="removeTx(tx.id)"><i class="bi bi-x-circle"></i></button>
          </div>
        </div>
      </div>

      <!-- ═══ Tab 切换 ═══ -->
      <div class="fd-tabs">
        <div class="fd-tab" :class="{ active: activeTab === 'realtime' }" @click="switchTab('realtime')">实时走势</div>
        <div class="fd-tab" :class="{ active: activeTab === 'performance' }" @click="switchTab('performance')">业绩走势</div>
      </div>

      <!-- ═══ Tab 内容 ═══ -->
      <div class="fd-body">

        <!-- 实时走势 Tab -->
        <div v-show="activeTab === 'realtime'">
          <div class="fd-section-label" v-if="intradayData">
            <span>{{ intradayData.trade_date }}</span>
            <span v-if="intradayData.is_live" class="fd-live-badge">● LIVE</span>
            <span v-else style="color:#95A5A6;font-size:11px">上一交易日</span>
          </div>
          <div ref="intradayChartRef" style="width:100%;height:260px"></div>

          <div class="fd-section-label" style="margin-top:16px">
            <span><i class="bi bi-bar-chart"></i> 基金重仓股</span>
            <span v-if="portfolioUpdatedAt" style="font-size:11px;color:var(--text-light);font-weight:400">持仓数据 {{ portfolioUpdatedAt }}</span>
          </div>
          <div class="fd-stock-list" v-if="stocks.length">
            <div class="fd-stock-header">
              <div class="fd-stock-header-left">股票</div>
              <div class="fd-stock-header-mid">涨跌幅</div>
              <div class="fd-stock-header-right">持仓比</div>
            </div>
            <div class="fd-stock-item" v-for="(s, i) in stocks.slice(0, 10)" :key="s.code">
              <div class="fd-stock-rank">{{ i+1 }}</div>
              <div class="fd-stock-left">
                <div class="fd-stock-name">{{ s.name || '-' }}</div>
                <div class="fd-stock-code">{{ s.code }}</div>
              </div>
              <div class="fd-stock-mid">
                <span class="fd-stock-badge" :class="cls(s.change_pct || s.change || 0)">
                  {{ s.change_pct != null ? sign(s.change_pct) + '%' : (s.change != null ? sign(s.change) + '%' : '--') }}
                </span>
              </div>
              <div class="fd-stock-right">
                {{ s.weight ? s.weight.toFixed(2) + '%' : '-' }}
              </div>
            </div>
          </div>
          <div v-else-if="!loading" class="fd-empty">暂无重仓股数据</div>
        </div>

        <!-- 业绩走势 Tab -->
        <div v-show="activeTab === 'performance'">
          <div class="period-selector" style="margin-bottom:8px">
            <button v-for="p in periods" :key="p.days" class="period-btn"
                    :class="{ active: periodDays === p.days }"
                    @click="changePeriod(p.days)">{{ p.label }}</button>
          </div>
          <div ref="perfChartRef" style="width:100%;height:260px;margin-bottom:8px"></div>
          <div v-if="historyUpdatedAt" style="text-align:right;font-size:11px;color:var(--text-light);margin-bottom:8px;padding-right:4px">
            净値更新至 {{ historyUpdatedAt }}
          </div>

          <div class="fd-section-label" v-if="historyList.length">
            <span>每日净值</span>
          </div>
          <div class="fd-nav-list" v-if="historyList.length">
            <div class="fd-nav-header">
              <span>日期</span><span>净值</span><span>日涨幅</span>
            </div>
            <div class="fd-nav-row" v-for="h in historyList" :key="h.date">
              <span>{{ h.date }}</span>
              <span>{{ h.nav != null ? h.nav.toFixed(4) : '-' }}</span>
              <span :class="cls(h.change_pct || 0)">{{ h.change_pct != null ? sign(h.change_pct) + '%' : '-' }}</span>
            </div>
          </div>
          <div v-if="loadingHistory" style="text-align:center;padding:20px;color:var(--text-light)">
            <div class="spinner-border spinner-border-sm"></div> 加载中
          </div>
        </div>
      </div>

      <!-- 加载遮罩 -->
      <div v-if="loading" class="fd-loading">
        <div class="spinner-border spinner-border-sm text-secondary"></div>
        <span>加载中...</span>
      </div>

    </div>
  </div>
</div>
  `
}
