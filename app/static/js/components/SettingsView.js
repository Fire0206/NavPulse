import { ref } from 'vue'
import { store, showToast } from '../store.js'

// ── 主题定义 ──────────────────────────────────────
const THEMES = [
  {
    id: 'pink', name: '樱花粉', icon: 'bi-heart-fill',
    primary: '#FB7299', primaryDark: '#e8648a', secondary: '#FFACB7',
    gradient: 'linear-gradient(135deg, #FB7299 0%, #FFBDD6 100%)',
    shadowRgb: '251, 114, 153',
  },
  {
    id: 'blue', name: '天空蓝', icon: 'bi-water',
    primary: '#4A90D9', primaryDark: '#3A7BC8', secondary: '#8BB8E8',
    gradient: 'linear-gradient(135deg, #4A90D9 0%, #A8D0F5 100%)',
    shadowRgb: '74, 144, 217',
  },
  {
    id: 'purple', name: '星空紫', icon: 'bi-stars',
    primary: '#8B5CF6', primaryDark: '#7C3AED', secondary: '#B794F6',
    gradient: 'linear-gradient(135deg, #8B5CF6 0%, #C4B5FD 100%)',
    shadowRgb: '139, 92, 246',
  },
  {
    id: 'green', name: '薄荷绿', icon: 'bi-leaf',
    primary: '#10B981', primaryDark: '#059669', secondary: '#6EE7B7',
    gradient: 'linear-gradient(135deg, #10B981 0%, #A7F3D0 100%)',
    shadowRgb: '16, 185, 129',
  },
  {
    id: 'orange', name: '落日橙', icon: 'bi-sunset-fill',
    primary: '#F97316', primaryDark: '#EA580C', secondary: '#FDBA74',
    gradient: 'linear-gradient(135deg, #F97316 0%, #FED7AA 100%)',
    shadowRgb: '249, 115, 22',
  },
  {
    id: 'teal', name: '湖水青', icon: 'bi-droplet-fill',
    primary: '#14B8A6', primaryDark: '#0D9488', secondary: '#5EEAD4',
    gradient: 'linear-gradient(135deg, #14B8A6 0%, #99F6E4 100%)',
    shadowRgb: '20, 184, 166',
  },
]

/** 将主题应用到 CSS 变量 */
function applyTheme(theme) {
  const root = document.documentElement
  root.style.setProperty('--primary', theme.primary)
  root.style.setProperty('--primary-dark', theme.primaryDark)
  root.style.setProperty('--secondary', theme.secondary)
  root.style.setProperty('--accent-gradient', theme.gradient)
  root.style.setProperty('--shadow-soft', `0 8px 24px rgba(${theme.shadowRgb}, 0.12)`)
  root.style.setProperty('--shadow-card-hover', `0 8px 28px rgba(${theme.shadowRgb}, 0.16)`)
}

/** 页面加载时恢复已保存的主题 */
function restoreSavedTheme() {
  const savedId = localStorage.getItem('navpulse_theme') || 'pink'
  const theme = THEMES.find(t => t.id === savedId) || THEMES[0]
  applyTheme(theme)
  return theme.id
}

// 启动时立即恢复
const _initialTheme = restoreSavedTheme()

export default {
  name: 'SettingsView',
  setup() {
    const currentTheme = ref(_initialTheme)
    const appVersion = '2.1.0'

    function selectTheme(theme) {
      currentTheme.value = theme.id
      applyTheme(theme)
      localStorage.setItem('navpulse_theme', theme.id)
      showToast(`已切换为「${theme.name}」主题`)
    }

    function selectPrivacyMode(mode) {
      store.privacyMode = mode
      localStorage.setItem('navpulse_privacy_mode', mode.toString())
      const modeNames = ['关闭隐私', '仅隐藏持有金额', '隐藏持有金额+收益金额', '隐藏持有金额+收益金额+持有收益率']
      showToast(`已切换为「${modeNames[mode]}」`)
    }

    function clearCache() {
      const token = localStorage.getItem('token')
      fetch('/api/cache', {
        method: 'DELETE',
        headers: { 'Authorization': 'Bearer ' + token }
      })
        .then(r => {
          if (r.status === 401) {
            localStorage.removeItem('token')
            localStorage.removeItem('username')
            location.href = '/login'
            return
          }
          // 清除客户端 localStorage 缓存
          const keys = Object.keys(localStorage)
          keys.forEach(k => { if (k.startsWith('navpulse_c_')) localStorage.removeItem(k) })
          // 清空内存中的数据
          store.holdingsData = null
          store.watchlistData = null
          store.marketData = null
          showToast('缓存已清空，数据将重新加载')
        })
        .catch(() => showToast('清空缓存失败'))
    }

    function logout() {
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      location.href = '/login'
    }

    return {
      store, THEMES, currentTheme, appVersion,
      selectTheme, selectPrivacyMode, clearCache, logout,
    }
  },
  template: `
    <div class="view">
      <div class="view-inner">

        <!-- 用户信息卡 -->
        <div class="settings-profile-card">
          <div class="sp-avatar">
            <i class="bi bi-person-fill"></i>
          </div>
          <div class="sp-info">
            <div class="sp-name">{{ store.username || '未登录' }}</div>
            <div class="sp-sub">NavPulse 用户</div>
          </div>
        </div>

        <!-- 主题颜色 -->
        <div class="settings-section">
          <div class="ss-title"><i class="bi bi-palette-fill"></i> 主题颜色</div>
          <div class="theme-grid">
            <div class="theme-item" v-for="t in THEMES" :key="t.id"
                 :class="{ active: currentTheme === t.id }"
                 @click="selectTheme(t)">
              <div class="theme-dot" :style="{ background: t.gradient }">
                <i v-if="currentTheme === t.id" class="bi bi-check-lg"></i>
              </div>
              <span class="theme-name">{{ t.name }}</span>
            </div>
          </div>
        </div>

        <!-- 显示设置 -->
        <div class="settings-section">
          <div class="ss-title"><i class="bi bi-eye-slash"></i> 隐私模式</div>
          <div style="padding: 0 16px 8px;">
            <!-- 模式选择卡片 -->
            <div class="privacy-mode-card" :class="{ active: store.privacyMode === 0 }" @click="selectPrivacyMode(0)">
              <div class="pmc-header">
                <span class="pmc-title">关闭隐私</span>
                <i v-if="store.privacyMode === 0" class="bi bi-check-circle-fill" style="color:var(--primary)"></i>
              </div>
              <div class="pmc-desc">显示所有金额和收益数据</div>
            </div>
            
            <div class="privacy-mode-card" :class="{ active: store.privacyMode === 1 }" @click="selectPrivacyMode(1)">
              <div class="pmc-header">
                <span class="pmc-title">模式一</span>
                <i v-if="store.privacyMode === 1" class="bi bi-check-circle-fill" style="color:var(--primary)"></i>
              </div>
              <div class="pmc-desc">仅隐藏 <strong>【持有金额】</strong></div>
            </div>

            <div class="privacy-mode-card" :class="{ active: store.privacyMode === 2 }" @click="selectPrivacyMode(2)">
              <div class="pmc-header">
                <span class="pmc-title">模式二</span>
                <i v-if="store.privacyMode === 2" class="bi bi-check-circle-fill" style="color:var(--primary)"></i>
              </div>
              <div class="pmc-desc">隐藏 <strong>【持有金额】【收益金额】</strong></div>
            </div>

            <div class="privacy-mode-card" :class="{ active: store.privacyMode === 3 }" @click="selectPrivacyMode(3)">
              <div class="pmc-header">
                <span class="pmc-title">模式三</span>
                <i v-if="store.privacyMode === 3" class="bi bi-check-circle-fill" style="color:var(--primary)"></i>
              </div>
              <div class="pmc-desc">隐藏 <strong>【持有金额】【收益金额】【持有收益率】</strong></div>
            </div>
          </div>
        </div>

        <!-- 数据管理 -->
        <div class="settings-section">
          <div class="ss-title"><i class="bi bi-database"></i> 数据管理</div>
          <div class="settings-list">
            <div class="settings-row" @click="clearCache">
              <div class="sr-left">
                <i class="bi bi-arrow-repeat"></i>
                <div>
                  <div class="sr-label">清空缓存</div>
                  <div class="sr-desc">清除行情和估值缓存，重新获取数据</div>
                </div>
              </div>
              <div class="sr-right"><i class="bi bi-chevron-right"></i></div>
            </div>
          </div>
        </div>

        <!-- 系统信息 -->
        <div class="settings-section">
          <div class="ss-title"><i class="bi bi-info-circle"></i> 系统信息</div>
          <div class="settings-list">
            <div class="settings-row static">
              <div class="sr-left">
                <i class="bi bi-cpu"></i>
                <div><div class="sr-label">调度器状态</div></div>
              </div>
              <div class="sr-right">
                <span class="sr-badge" :class="store.schedulerRunning ? 'online' : 'offline'">
                  {{ store.schedulerRunning ? '运行中' : '已停止' }}
                </span>
              </div>
            </div>
            <div class="settings-row static">
              <div class="sr-left">
                <i class="bi bi-clock-history"></i>
                <div><div class="sr-label">最后更新</div></div>
              </div>
              <div class="sr-right">
                <span style="font-size:12px;color:var(--text-secondary)">{{ store.lastUpdateTime }}</span>
              </div>
            </div>
            <div class="settings-row static">
              <div class="sr-left">
                <i class="bi bi-tag"></i>
                <div><div class="sr-label">版本号</div></div>
              </div>
              <div class="sr-right">
                <span style="font-size:12px;color:var(--text-secondary)">v{{ appVersion }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 退出登录 -->
        <button class="settings-logout" @click="logout">
          <i class="bi bi-box-arrow-right"></i> 退出登录
        </button>

      </div>
    </div>
  `
}
