import { ref, computed, watch, onMounted } from 'vue'
import { store, showToast, writeCache } from '../store.js'
import { addHolding, addWatchlistItem, fetchValuation, fetchPortfolio } from '../api.js'

export default {
  name: 'AddFundModal',
  setup() {
    const modalEl = ref(null)
    let bsModal = null

    // ── 表单状态 ──
    const currentMode = ref('holding')  // 'holding' | 'watchlist'
    const code = ref('')
    const firstBuyDate = ref('')
    const marketValue = ref('')    // 当前持仓总市值
    const holdingProfit = ref('')  // 当前持有收益（盈亏）
    const alsoAddToWatchlist = ref(true)  // 同时添加到自选
    const submitting = ref(false)
    const isWatchlistMode = computed(() => currentMode.value === 'watchlist')

    // ── 基金信息（输入代码后自动查询）──
    const fundInfo = ref(null)
    const loadingFund = ref(false)
    let codeTimer = null

    // ── 自动计算提示 ──
    const calcHint = computed(() => {
      const mv = parseFloat(marketValue.value)
      const profit = parseFloat(holdingProfit.value) || 0
      if (!mv || mv <= 0) return ''
      const cost = mv - profit
      if (cost <= 0) return '⚠ 投入本金不能为负 (市值 - 收益 ≤ 0)'
      const profitRate = (profit / cost * 100).toFixed(2)
      return `投入本金 ≈ ¥${cost.toFixed(2)}，收益率 ${profit >= 0 ? '+' : ''}${profitRate}%`
    })

    // 获取今天日期
    function getTodayStr() {
      const d = new Date()
      return d.getFullYear() + '-' +
        String(d.getMonth() + 1).padStart(2, '0') + '-' +
        String(d.getDate()).padStart(2, '0')
    }

    // 监听代码变化，自动查询基金信息
    watch(code, (newCode) => {
      fundInfo.value = null
      if (codeTimer) clearTimeout(codeTimer)
      
      const c = newCode.trim()
      if (c.length === 6 && /^\d{6}$/.test(c)) {
        codeTimer = setTimeout(() => lookupFund(c), 500)
      }
    })

    async function lookupFund(c) {
      loadingFund.value = true
      try {
        const data = await fetchValuation(c)
        if (data && !data.error) {
          fundInfo.value = {
            name: data.fund_name || c,
            sector: guessSector(data.holdings || [], data.fund_name || '')
          }
        }
      } catch (e) {
        fundInfo.value = null
      } finally {
        loadingFund.value = false
      }
    }

    // 根据基金名称和持仓推断板块
    function guessSector(holdings, name) {
      const keywords = {
        '半导体': '半导体', '芯片': '半导体', '科技': '科技', '信息': '科技',
        '医药': '医药', '医疗': '医药', '生物': '医药', '创新药': '医药',
        '消费': '消费', '白酒': '消费', '食品': '消费', '饮料': '消费',
        '新能源': '新能源', '光伏': '新能源', '锂电': '新能源', '电力': '新能源',
        '军工': '军工', '国防': '军工',
        '金融': '金融', '银行': '金融', '券商': '金融', '保险': '金融',
        '地产': '地产', '房地产': '地产',
        '纳斯达克': 'QDII', '标普': 'QDII', '美股': 'QDII', '恒生': 'QDII', '港股': 'QDII',
        '沪深300': '宽基', '中证500': '宽基', '上证50': '宽基', '创业板': '宽基',
        '指数': '指数', 'ETF': 'ETF',
      }
      for (const [kw, sector] of Object.entries(keywords)) {
        if (name.includes(kw)) return sector
      }
      return '混合'
    }

    onMounted(() => {
      bsModal = new bootstrap.Modal(modalEl.value)
    })

    /** 供父组件调用：打开弹窗 */
    function open(mode = 'holding') {
      currentMode.value = mode
      code.value = ''
      firstBuyDate.value = getTodayStr()
      marketValue.value = ''
      holdingProfit.value = ''
      alsoAddToWatchlist.value = true
      fundInfo.value = null
      bsModal.show()
      setTimeout(() => {
        const el = document.getElementById('mCode')
        if (el) el.focus()
      }, 300)
    }

    async function confirm() {
      const c = code.value.trim()
      if (!c || c.length !== 6) {
        showToast('请输入6位基金代码')
        return
      }

      // 自选模式：只需要代码
      if (isWatchlistMode.value) {
        submitting.value = true
        try {
          await addWatchlistItem(c)
          bsModal.hide()
          showToast('✓ 已添加到自选')
          store.watchlistData = null
        } catch (e) {
          showToast('✗ ' + e.message)
        } finally {
          submitting.value = false
        }
        return
      }

      // 持仓模式：需要完整信息
      const mv = parseFloat(marketValue.value)
      if (!mv || mv <= 0) {
        showToast('请输入当前持仓市值')
        return
      }

      const profit = parseFloat(holdingProfit.value) || 0
      if (mv - profit <= 0) {
        showToast('投入本金不能 ≤ 0 (市值 - 收益)')
        return
      }

      if (!firstBuyDate.value) {
        showToast('请选择初次买入日期')
        return
      }

      submitting.value = true
      try {
        // 懒人初始化: 发送 market_value + profit
        const result = await addHolding(c, mv, profit, firstBuyDate.value)
        
        // 同时添加到自选
        if (alsoAddToWatchlist.value) {
          try {
            await addWatchlistItem(c)
          } catch (_) {}
        }

        bsModal.hide()
        showToast('✓ 持仓已添加，成本已同步')

        // ── 乐观更新：立即显示新基金，无需等待完整估值 ──
        if (store.holdingsData && result.data) {
          const d = result.data
          const fundName = d.name || fundInfo.value?.name || c
          const profitRate = d.total_cost > 0 ? parseFloat((d.profit / d.total_cost * 100).toFixed(2)) : 0
          const newFund = {
            code: c, name: fundName,
            shares: d.shares, cost: d.total_cost,
            market_value: d.market_value,
            estimate_change: 0, daily_profit: 0,
            holding_profit: d.profit,
            holding_profit_rate: profitRate,
            last_nav: d.nav, avg_cost: d.unit_cost,
            data_date: null, holdings_count: 0,
            update_time: null, cached: false,
          }
          // 已存在则更新，否则追加
          const idx = store.holdingsData.funds.findIndex(f => f.code === c)
          if (idx >= 0) store.holdingsData.funds[idx] = { ...store.holdingsData.funds[idx], ...newFund }
          else store.holdingsData.funds.push(newFund)
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
          writeCache('holdings', store.holdingsData)
          // 后台静默刷新获取实时估值
          fetchPortfolio(true).then(data => {
            store.holdingsData = data
            writeCache('holdings', data)
          }).catch(() => {})
        } else {
          // 首次添加（无现有数据）：走传统重载
          store.holdingsData = null
        }

        if (alsoAddToWatchlist.value) {
          store.watchlistData = null
        }
      } catch (e) {
        showToast('✗ ' + e.message)
      } finally {
        submitting.value = false
      }
    }

    /** 限制基金代码只接受数字 */
    function onCodeInput(e) {
      code.value = e.target.value.replace(/\D/g, '')
    }

    /** 金额输入过滤：只允许数字、小数点、负号，自动保留两位小数 */
    function onAmountInput(e, field) {
      let v = e.target.value
      // 只保留数字、小数点、负号
      v = v.replace(/[^\d.\-]/g, '')
      // 负号只能在开头
      const hasLeadingMinus = v.startsWith('-')
      v = v.replace(/-/g, '')
      if (hasLeadingMinus) v = '-' + v
      // 最多一个小数点
      const parts = v.split('.')
      if (parts.length > 2) v = parts[0] + '.' + parts.slice(1).join('')
      // 小数最多两位
      if (parts.length === 2 && parts[1].length > 2) {
        v = parts[0] + '.' + parts[1].slice(0, 2)
      }
      if (field === 'marketValue') marketValue.value = v
      else if (field === 'holdingProfit') holdingProfit.value = v
      e.target.value = v
    }

    return {
      modalEl, code, firstBuyDate, marketValue, holdingProfit,
      alsoAddToWatchlist, submitting, fundInfo, loadingFund, calcHint,
      isWatchlistMode,
      open, confirm, onCodeInput, onAmountInput,
    }
  },
  template: `
    <div class="modal fade" ref="modalEl" tabindex="-1">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content" style="background:#fff;border:none;border-radius:18px;overflow:hidden">
          <!-- 标题 -->
          <div class="modal-header" style="background:var(--accent-gradient);color:#fff;border:none;padding:18px 22px">
            <h5 class="modal-title" style="font-weight:700">{{ isWatchlistMode ? '添加自选' : '添加持仓' }}</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" style="filter:brightness(0) invert(1)"></button>
          </div>

          <div class="modal-body" style="padding:18px 22px">
            <!-- 基金代码 -->
            <div class="mb-3">
              <label class="form-label" style="font-size:13px;font-weight:600;color:var(--text-light)">基金代码</label>
              <input type="text" class="form-control form-control-lg" id="mCode" maxlength="6"
                     placeholder="请输入6位基金代码 (如 000001)" v-model="code"
                     @input="onCodeInput"
                     style="background:var(--bg);border:1.5px solid #F0F0F3;border-radius:12px;font-size:15px">
            </div>

            <!-- 基金信息显示 -->
            <div v-if="loadingFund" style="padding:10px 0;color:var(--text-light);font-size:13px">
              <span class="spinner-border spinner-border-sm me-2"></span>查询中...
            </div>
            <div v-else-if="fundInfo" class="fund-info-card" style="background:linear-gradient(135deg,#FFF5F7,#FFF);border:1px solid #FFE4E8;border-radius:12px;padding:12px 14px;margin-bottom:14px">
              <div style="font-size:15px;font-weight:700;color:var(--text-main)">{{ fundInfo.name }}</div>
              <div style="font-size:12px;color:var(--text-light);margin-top:4px">
                <span style="background:var(--primary);color:#fff;padding:2px 8px;border-radius:10px;font-size:11px">{{ fundInfo.sector }}</span>
              </div>
            </div>

            <!-- 持仓模式专属字段 -->
            <template v-if="!isWatchlistMode">
              <!-- 首次买入日期 -->
              <div class="mb-3">
                <label class="form-label" style="font-size:13px;font-weight:600;color:var(--text-light)">首次买入日期</label>
                <input type="date" class="form-control form-control-lg" v-model="firstBuyDate"
                       style="background:var(--bg);border:1.5px solid #F0F0F3;border-radius:12px;font-size:15px">
                <div style="font-size:11px;color:#95A5A6;margin-top:4px;padding-left:2px">仅用于记录起始点，不影响收益计算</div>
              </div>

              <!-- 当前持仓总金额 -->
              <div class="mb-3">
                <label class="form-label" style="font-size:13px;font-weight:600;color:var(--text-light)">当前持仓总金额 (元)</label>
                <input type="text" inputmode="decimal" class="form-control form-control-lg"
                       v-model="marketValue" @input="onAmountInput($event, 'marketValue')"
                       placeholder="请查阅支付宝等平台，填入最新的持仓金额"
                       style="background:var(--bg);border:1.5px solid #F0F0F3;border-radius:12px;font-size:15px">
              </div>

              <!-- 当前持有收益 -->
              <div class="mb-3">
                <label class="form-label" style="font-size:13px;font-weight:600;color:var(--text-light)">当前持有收益 (元)</label>
                <input type="text" inputmode="decimal" class="form-control form-control-lg"
                       v-model="holdingProfit" @input="onAmountInput($event, 'holdingProfit')"
                       placeholder="填入对应的累计收益金额，亏损请填负数"
                       style="background:var(--bg);border:1.5px solid #F0F0F3;border-radius:12px;font-size:15px">
              </div>

              <!-- 计算提示 -->
              <div v-if="calcHint"
                   style="font-size:12px;color:var(--primary);background:rgba(251,114,153,.07);padding:8px 13px;border-radius:10px;margin-bottom:14px">
                {{ calcHint }}
              </div>

              <!-- 同时添加到自选 -->
              <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-top:1px solid var(--border)">
                <span style="font-size:13px;color:var(--text-secondary)">同时添加到自选</span>
                <div class="form-check form-switch" style="transform:scale(1.1)">
                  <input class="form-check-input" type="checkbox" v-model="alsoAddToWatchlist">
                </div>
              </div>
            </template>
          </div>

          <div class="modal-footer" style="border:none;padding:0 22px 18px;gap:10px">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal"
                    style="border-radius:12px;padding:8px 22px">取消</button>
            <button type="button" class="btn" @click="confirm" :disabled="submitting"
                    style="background:var(--primary);color:#fff;border-radius:12px;padding:8px 22px;min-width:110px">
              <span v-if="submitting"><span class="spinner-border spinner-border-sm me-1"></span>添加中...</span>
              <span v-else>{{ isWatchlistMode ? '添加自选' : '确认添加' }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  `
}
