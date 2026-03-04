/**
 * OcrImportModal — 支付宝持仓截图 OCR 导入弹窗
 *
 * 流程：上传截图 → OCR 识别 → 预览确认 → 批量导入
 */
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { store, showToast, writeCache } from '../store.js'
import { ocrParseImage, batchImportHoldings, addWatchlistItem, fetchPortfolio } from '../api.js'

export default {
  name: 'OcrImportModal',
  setup() {
    const modalEl = ref(null)
    let bsModal = null

    // ── 状态 ──
    const step = ref('upload')       // 'upload' | 'parsing' | 'results' | 'importing' | 'done'
    const previewUrl = ref(null)
    const imageFile = ref(null)
    const parsedFunds = ref([])
    const importResults = ref(null)
    const errorMsg = ref('')
    const fileInputRef = ref(null)

    const selectedCount = computed(() =>
      parsedFunds.value.filter(f => f.selected && f.code).length
    )

    const hasUnmatched = computed(() =>
      parsedFunds.value.some(f => !f.code)
    )

    // ── 打开弹窗 ──
    function open() {
      step.value = 'upload'
      previewUrl.value = null
      imageFile.value = null
      parsedFunds.value = []
      importResults.value = null
      errorMsg.value = ''
      bsModal.show()
    }

    // ── 文件选择 / 拍照 ──
    function handleFileInput(e) {
      const file = e.target.files?.[0]
      if (file) processImage(file)
    }

    // ── 拖放 ──
    function handleDrop(e) {
      e.preventDefault()
      const file = e.dataTransfer?.files?.[0]
      if (file && file.type.startsWith('image/')) processImage(file)
    }

    // ── 粘贴 ──
    function handlePaste(e) {
      const items = e.clipboardData?.items
      if (!items) return
      for (const item of items) {
        if (item.type.startsWith('image/')) {
          const file = item.getAsFile()
          if (file) processImage(file)
          break
        }
      }
    }

    function processImage(file) {
      imageFile.value = file
      previewUrl.value = URL.createObjectURL(file)
    }

    // ── 开始识别 ──
    async function startParse() {
      if (!imageFile.value) {
        showToast('请先选择截图')
        return
      }

      step.value = 'parsing'
      errorMsg.value = ''

      try {
        console.log('[OCR] 开始上传识别...')
        const data = await ocrParseImage(imageFile.value)
        console.log('[OCR] 识别完成:', data)

        if (!data.funds || data.funds.length === 0) {
          errorMsg.value = '未识别到基金持仓数据，请确认截图内容正确'
          step.value = 'upload'
          return
        }

        // 为每条记录添加 selected 和可编辑状态
        parsedFunds.value = data.funds.map(f => ({
          ...f,
          selected: !!f.code,  // 有代码的默认选中
          editing: false,
          editingName: false,
          editingValue: false,
          nameDraft: f.name || '',
          marketValueDraft: (f.market_value ?? '').toString(),
        }))
        step.value = 'results'
      } catch (e) {
        console.error('[OCR] 识别失败:', e)
        errorMsg.value = e.message || 'OCR 识别失败'
        step.value = 'upload'
      }
    }

    // ── 确认导入 ──
    async function doImport() {
      const selectedFunds = parsedFunds.value.filter(f => f.selected && f.code)
      const toImport = selectedFunds.map(f => ({
          code: f.code,
          market_value: f.market_value,
          profit: f.total_profit || 0,
        }))

      if (!toImport.length) {
        showToast('请至少选择一只基金')
        return
      }

      step.value = 'importing'

      try {
        const data = await batchImportHoldings(toImport)
        importResults.value = data

        // 同时添加到自选（静默）
        for (const item of toImport) {
          try { await addWatchlistItem(item.code) } catch (_) {}
        }

        step.value = 'done'
        if (data.imported > 0) {
          // ── 乐观更新：立即将导入的基金插入页面，无需等待估值 ──
          if (store.holdingsData) {
            const successCodes = new Set(
              (data.results || []).filter(r => r.success).map(r => r.code)
            )
            for (const f of selectedFunds) {
              if (!successCodes.has(f.code)) continue
              const mv = f.market_value || 0
              const profit = f.total_profit || 0
              const cost = mv - profit
              const newFund = {
                code: f.code, name: f.name || f.code,
                shares: 0, cost: Math.max(cost, 0),
                market_value: mv,
                estimate_change: 0, daily_profit: 0,
                holding_profit: profit,
                holding_profit_rate: cost > 0 ? parseFloat((profit / cost * 100).toFixed(2)) : 0,
                last_nav: 0, avg_cost: 0,
                data_date: null, holdings_count: 0,
                update_time: null, cached: false,
              }
              const idx = store.holdingsData.funds.findIndex(x => x.code === f.code)
              if (idx >= 0) store.holdingsData.funds[idx] = { ...store.holdingsData.funds[idx], ...newFund }
              else store.holdingsData.funds.push(newFund)
            }
            // 重新计算汇总
            const funds = store.holdingsData.funds
            const tmv = funds.reduce((s, x) => s + (x.market_value || 0), 0)
            const tc  = funds.reduce((s, x) => s + (x.cost || 0), 0)
            const tdp = funds.reduce((s, x) => s + (x.daily_profit || 0), 0)
            store.holdingsData.total_market_value = parseFloat(tmv.toFixed(2))
            store.holdingsData.total_cost = parseFloat(tc.toFixed(2))
            store.holdingsData.total_profit = parseFloat((tmv - tc).toFixed(2))
            store.holdingsData.total_profit_rate = tc > 0 ? parseFloat(((tmv - tc) / tc * 100).toFixed(2)) : 0
            store.holdingsData.total_daily_profit = parseFloat(tdp.toFixed(2))
            store.holdingsData.total_daily_profit_rate = tmv > 0 ? parseFloat((tdp / tmv * 100).toFixed(2)) : 0
            writeCache('holdings', store.holdingsData)
            // 后台静默刷新获取实时估值
            fetchPortfolio(true).then(fullData => {
              store.holdingsData = fullData
              writeCache('holdings', fullData)
            }).catch(() => {})
          } else {
            // 首次导入（无现有数据）：走传统重载
            store.holdingsData = null
          }
          store.watchlistData = null
        }
      } catch (e) {
        errorMsg.value = e.message || '导入失败'
        step.value = 'results'
      }
    }

    function editFundName(f) {
      f.nameDraft = f.name || ''
      f.editingName = true
    }

    function commitFundName(f) {
      const v = String(f.nameDraft || '').trim()
      if (v) f.name = v
      f.nameDraft = f.name || ''
      f.editingName = false
    }

    function editMarketValue(f) {
      f.marketValueDraft = (f.market_value ?? '').toString()
      f.editingValue = true
    }

    function commitMarketValue(f) {
      const v = Number(String(f.marketValueDraft || '').replace(/,/g, '').trim())
      if (!Number.isFinite(v) || v <= 0) {
        showToast('金额格式不正确')
        f.marketValueDraft = (f.market_value ?? '').toString()
        f.editingValue = false
        return
      }
      f.market_value = Math.round(v * 100) / 100
      f.marketValueDraft = f.market_value.toString()
      f.editingValue = false
    }

    // ── 关闭弹窗 ──
    function close() {
      bsModal.hide()
    }

    // ── 重新开始 ──
    function restart() {
      step.value = 'upload'
      previewUrl.value = null
      imageFile.value = null
      parsedFunds.value = []
      importResults.value = null
      errorMsg.value = ''
    }

    onMounted(() => {
      bsModal = new bootstrap.Modal(modalEl.value)
      // 全局粘贴监听 — 用 document 级别确保在弹窗打开时能捕获 Ctrl+V
      document.addEventListener('paste', _globalPaste)
    })

    onUnmounted(() => {
      document.removeEventListener('paste', _globalPaste)
    })

    function _globalPaste(e) {
      // 只在弹窗打开且处于上传阶段时处理粘贴
      if (step.value !== 'upload') return
      if (!modalEl.value?.classList.contains('show')) return
      handlePaste(e)
    }

    return {
      modalEl, fileInputRef,
      step, previewUrl, imageFile, parsedFunds, importResults, errorMsg,
      selectedCount, hasUnmatched,
      open, close, restart,
      handleFileInput, handleDrop, handlePaste,
      editFundName, commitFundName,
      editMarketValue, commitMarketValue,
      startParse, doImport,
    }
  },
  template: `
    <div class="modal fade" ref="modalEl" tabindex="-1" data-bs-backdrop="static">
      <div class="modal-dialog modal-dialog-centered modal-lg modal-fullscreen-sm-down">
        <div class="modal-content" style="border-radius:16px;overflow:hidden">

          <!-- Header -->
          <div class="modal-header" style="border-bottom:1px solid var(--border);padding:14px 20px">
            <h6 class="modal-title" style="font-weight:600;font-size:15px">
              <i class="bi bi-camera"></i>
              {{ step === 'done' ? '导入完成' : '截图导入持仓' }}
            </h6>
            <button type="button" class="btn-close" @click="close"></button>
          </div>

          <!-- Body -->
          <div class="modal-body" style="padding:16px 20px;max-height:70vh;overflow-y:auto">

            <!-- ═══ Step 1: 上传 ═══ -->
            <div v-if="step === 'upload'">
              <div class="ocr-upload-area"
                   @dragover.prevent
                   @drop="handleDrop"
                   @click="fileInputRef?.click()">
                <input type="file" accept="image/*" capture="environment"
                       @change="handleFileInput" ref="fileInputRef"
                       style="display:none">

                <template v-if="!previewUrl">
                  <div style="text-align:center;padding:32px 16px">
                    <i class="bi bi-image" style="font-size:40px;color:var(--primary);opacity:0.6"></i>
                    <p style="margin:12px 0 4px;font-size:14px;font-weight:500;color:var(--text-primary)">
                      点击选择或拍摄支付宝持仓截图
                    </p>
                    <p style="margin:0;font-size:12px;color:var(--text-light)">
                      支持拖放 · 粘贴(Ctrl+V) · 手机拍照
                    </p>
                  </div>
                </template>

                <template v-else>
                  <img :src="previewUrl" class="ocr-preview-img">
                </template>
              </div>

              <div v-if="errorMsg" style="margin-top:12px;padding:10px 14px;background:#fff3f3;border-radius:8px;color:#e74c3c;font-size:13px">
                <i class="bi bi-exclamation-circle"></i> {{ errorMsg }}
              </div>

              <div style="margin-top:16px;display:flex;gap:10px;justify-content:flex-end">
                <button class="btn btn-sm" style="color:var(--text-secondary)" @click="close">取消</button>
                <button class="btn-pink" :disabled="!imageFile" @click="startParse">
                  <i class="bi bi-magic"></i> 开始识别
                </button>
              </div>
            </div>

            <!-- ═══ Step 2: 识别中 ═══ -->
            <div v-if="step === 'parsing'" style="text-align:center;padding:40px 0">
              <span class="silent-spinner" style="width:32px;height:32px;border-width:3px"></span>
              <p style="margin-top:16px;color:var(--text-secondary);font-size:14px">
                正在识别截图内容...
              </p>
              <p style="color:var(--text-light);font-size:12px">首次识别可能较慢；超时请裁剪到持仓区域后重试</p>
            </div>

            <!-- ═══ Step 3: 预览结果 ═══ -->
            <div v-if="step === 'results'">
              <div style="font-size:12px;color:var(--text-light);margin-bottom:12px">
                共识别 {{ parsedFunds.length }} 只基金，已匹配 {{ parsedFunds.filter(f=>f.code).length }} 只代码
              </div>

              <div class="ocr-fund-list">
                <div v-for="(f, i) in parsedFunds" :key="i"
                     class="ocr-fund-row"
                     :class="{ 'ocr-unmatched': !f.code }">
                  <div class="ocr-fund-check">
                    <input type="checkbox" v-model="f.selected" :disabled="!f.code">
                  </div>
                  <div class="ocr-fund-info">
                    <div class="ocr-fund-name">
                      <template v-if="f.editingName">
                        <input v-model="f.nameDraft"
                               style="width:100%;font-size:14px;padding:2px 6px;border:1px solid var(--primary);border-radius:4px;outline:none"
                               @blur="commitFundName(f)"
                               @keyup.enter="commitFundName(f)">
                      </template>
                      <template v-else>
                        <span style="cursor:pointer" @click="editFundName(f)">{{ f.name }}</span>
                      </template>
                    </div>
                    <div class="ocr-fund-code">
                      <template v-if="f.editing">
                        <input v-model="f.code" placeholder="输入6位代码"
                               maxlength="6"
                               style="width:80px;font-size:12px;padding:2px 6px;border:1px solid var(--primary);border-radius:4px;outline:none"
                               @blur="f.editing = false; if(f.code) f.selected = true"
                               @keyup.enter="f.editing = false; if(f.code) f.selected = true">
                      </template>
                      <template v-else-if="f.code">
                        <span style="color:var(--primary);cursor:pointer" @click="f.editing = true">{{ f.code }}</span>
                        <span v-if="f.matched_name && f.matched_name !== f.name"
                              style="font-size:11px;color:var(--text-light);margin-left:4px">
                          ✓ {{ f.matched_name }}
                        </span>
                      </template>
                      <template v-else>
                        <span style="color:#e67e22;cursor:pointer" @click="f.editing = true">
                          <i class="bi bi-pencil"></i> 手动输入代码
                        </span>
                      </template>
                    </div>
                  </div>
                  <div class="ocr-fund-values">
                    <div class="ocr-val">
                      <span class="ocr-val-label">市值</span>
                      <template v-if="f.editingValue">
                        <input v-model="f.marketValueDraft"
                               style="width:100px;font-size:14px;padding:2px 6px;border:1px solid var(--primary);border-radius:4px;outline:none;text-align:right"
                               @blur="commitMarketValue(f)"
                               @keyup.enter="commitMarketValue(f)">
                      </template>
                      <template v-else>
                        <span class="ocr-val-num" style="cursor:pointer" @click="editMarketValue(f)">{{ f.market_value?.toFixed(2) }}</span>
                      </template>
                    </div>
                    <div class="ocr-val" v-if="f.total_profit != null">
                      <span class="ocr-val-label">收益</span>
                      <span class="ocr-val-num"
                            :style="{ color: f.total_profit >= 0 ? 'var(--rise)' : 'var(--fall)' }">
                        {{ f.total_profit >= 0 ? '+' : '' }}{{ f.total_profit?.toFixed(2) }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="hasUnmatched" style="margin-top:10px;padding:8px 12px;background:#fffbe6;border-radius:8px;font-size:12px;color:#d48806">
                <i class="bi bi-exclamation-triangle"></i>
                部分基金未自动匹配代码，请手动输入后勾选
              </div>

              <div v-if="errorMsg" style="margin-top:10px;padding:8px 12px;background:#fff3f3;border-radius:8px;color:#e74c3c;font-size:13px">
                <i class="bi bi-exclamation-circle"></i> {{ errorMsg }}
              </div>

              <div style="margin-top:16px;display:flex;gap:10px;justify-content:space-between">
                <button class="btn btn-sm" style="color:var(--text-secondary)" @click="restart">
                  <i class="bi bi-arrow-left"></i> 重新选图
                </button>
                <button class="btn-pink" :disabled="selectedCount === 0" @click="doImport">
                  <i class="bi bi-download"></i> 确认导入 ({{ selectedCount }}只)
                </button>
              </div>
            </div>

            <!-- ═══ Step 4: 导入中 ═══ -->
            <div v-if="step === 'importing'" style="text-align:center;padding:40px 0">
              <span class="silent-spinner" style="width:32px;height:32px;border-width:3px"></span>
              <p style="margin-top:16px;color:var(--text-secondary);font-size:14px">
                正在导入持仓数据...
              </p>
            </div>

            <!-- ═══ Step 5: 完成 ═══ -->
            <div v-if="step === 'done' && importResults">
              <div style="text-align:center;padding:40px 0 20px">
                <i class="bi bi-check-circle" style="font-size:48px;color:var(--primary)"></i>
                <p style="margin:12px 0 4px;font-size:16px;font-weight:600">导入完成</p>
                <p style="color:var(--text-secondary);font-size:13px">
                  成功 {{ importResults.imported }} 只
                  <template v-if="importResults.failed > 0">
                    ，失败 {{ importResults.failed }} 只
                  </template>
                </p>
              </div>

              <!-- 失败详情 -->
              <div v-if="importResults.results?.some(r => !r.success)"
                   style="margin-top:12px;padding:10px 14px;background:#fff3f3;border-radius:8px;font-size:12px">
                <div v-for="r in importResults.results.filter(r => !r.success)" :key="r.code"
                     style="color:#e74c3c;margin-bottom:4px">
                  {{ r.code }}: {{ r.error }}
                </div>
              </div>

              <div style="margin-top:24px;padding-bottom:8px;text-align:center">
                <button class="btn-pink" style="min-width:120px;padding:10px 32px;font-size:15px" @click="close">完成</button>
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  `
}
