import { ref } from 'vue'
import { store, showToast } from '../store.js'

// ── 主题定义 ──────────────────────────────────────
const THEMES = [
  {
    id: 'day', name: 'Day', icon: 'bi-sun-fill',
    primary: '#1F2937', primaryDark: '#111827', primaryLight: '#F3F4F6', secondary: '#9CA3AF',
    gradient: 'linear-gradient(135deg, #1F2937 0%, #374151 100%)',
    swatchGradient: 'linear-gradient(135deg, #FFFFFF 0%, #F3F4F6 100%)',
    bg: '#FFFFFF',
    cardBg: '#FFFFFF',
    textMain: '#111111',
    textSecondary: '#444444',
    textLight: '#777777',
    border: '#E5E7EB',
    borderHover: '#D1D5DB',
    shadowRgb: '17, 17, 17',
  },
  {
    id: 'night', name: 'Night', icon: 'bi-moon-stars-fill',
    primary: '#5B6B82', primaryDark: '#46556A', primaryLight: '#2A3340', secondary: '#8FA1B8',
    gradient: 'linear-gradient(135deg, #374151 0%, #2B3442 100%)',
    bg: '#2A313C',
    cardBg: '#202734',
    textMain: '#F1F5F9',
    textSecondary: '#D3DCE7',
    textLight: '#A7B4C6',
    border: '#465265',
    borderHover: '#607089',
    shadowRgb: '13, 18, 26',
  },
  {
    id: 'pink', name: 'Pink', icon: 'bi-heart-fill',
    primary: '#FB7299', primaryDark: '#e8648a', primaryLight: '#FFF0F5', secondary: '#FFACB7',
    gradient: 'linear-gradient(135deg, #FB7299 0%, #FFBDD6 100%)',
    bg: '#FFF3F7',
    cardBg: '#FFFFFF',
    textMain: '#3D2332',
    textSecondary: '#7A5A6A',
    textLight: '#B18BA0',
    border: '#F3D8E4',
    borderHover: '#E9BFD3',
    shadowRgb: '251, 114, 153',
  },
  {
    id: 'blue', name: 'Blue', icon: 'bi-water',
    primary: '#4A90D9', primaryDark: '#3A7BC8', primaryLight: '#EFF6FF', secondary: '#8BB8E8',
    gradient: 'linear-gradient(135deg, #4A90D9 0%, #A8D0F5 100%)',
    bg: '#F2F7FF',
    cardBg: '#FFFFFF',
    textMain: '#13253A',
    textSecondary: '#49617A',
    textLight: '#7E97B1',
    border: '#D7E5F5',
    borderHover: '#BDD3EB',
    shadowRgb: '74, 144, 217',
  },
  {
    id: 'purple', name: 'Purple', icon: 'bi-stars',
    primary: '#8B5CF6', primaryDark: '#7C3AED', primaryLight: '#F3EEFF', secondary: '#B794F6',
    gradient: 'linear-gradient(135deg, #8B5CF6 0%, #C4B5FD 100%)',
    bg: '#F5F3FF',
    cardBg: '#FFFFFF',
    textMain: '#22163F',
    textSecondary: '#54477C',
    textLight: '#8D81B7',
    border: '#E4DDFB',
    borderHover: '#D3C7F8',
    shadowRgb: '139, 92, 246',
  },
  {
    id: 'green', name: 'Green', icon: 'bi-leaf',
    primary: '#10B981', primaryDark: '#059669', primaryLight: '#ECFDF5', secondary: '#6EE7B7',
    gradient: 'linear-gradient(135deg, #10B981 0%, #A7F3D0 100%)',
    bg: '#ECFDF5',
    cardBg: '#FFFFFF',
    textMain: '#10332A',
    textSecondary: '#2D6252',
    textLight: '#6A9A8D',
    border: '#CDEEE1',
    borderHover: '#AEE1CD',
    shadowRgb: '16, 185, 129',
  },
]

/** 将主题应用到 CSS 变量 */
function applyTheme(theme) {
  const root = document.documentElement
  root.style.setProperty('--primary', theme.primary)
  root.style.setProperty('--primary-dark', theme.primaryDark)
  root.style.setProperty('--primary-light', theme.primaryLight)
  root.style.setProperty('--secondary', theme.secondary)
  root.style.setProperty('--accent-gradient', theme.gradient)
  root.style.setProperty('--bg', theme.bg)
  root.style.setProperty('--card-bg', theme.cardBg)
  root.style.setProperty('--text-main', theme.textMain)
  root.style.setProperty('--text-secondary', theme.textSecondary)
  root.style.setProperty('--text-light', theme.textLight)
  root.style.setProperty('--border', theme.border)
  root.style.setProperty('--border-hover', theme.borderHover)
  root.style.setProperty('--surface-soft', `rgba(${theme.shadowRgb}, 0.10)`)
  root.style.setProperty('--surface-strong', `rgba(${theme.shadowRgb}, 0.16)`)
  root.style.setProperty('--focus-ring', `rgba(${theme.shadowRgb}, 0.24)`)
  root.style.setProperty('--overlay-bg', theme.id === 'night' ? 'rgba(22, 28, 38, 0.62)' : 'rgba(255, 255, 255, 0.86)')
  root.style.setProperty('--nav-bg', theme.id === 'night' ? 'rgba(32, 39, 52, .94)' : 'rgba(255,255,255,.96)')
  root.style.setProperty('--glass-bg', theme.id === 'night' ? 'rgba(255,255,255,.05)' : 'rgba(255,255,255,.92)')
  root.style.setProperty('--glass-border', theme.id === 'night' ? 'rgba(203,213,225,.18)' : 'rgba(17,17,17,.08)')
  root.style.setProperty('--bg-gradient', theme.id === 'night'
    ? '#2A313C'
    : theme.id === 'day'
      ? '#FFFFFF'
      : `radial-gradient(1000px 460px at -10% -5%, rgba(${theme.shadowRgb}, .12), transparent 62%), radial-gradient(1000px 420px at 110% 0%, rgba(${theme.shadowRgb}, .08), transparent 58%), ${theme.bg}`)
  root.style.setProperty('--shadow-soft', `0 8px 24px rgba(${theme.shadowRgb}, 0.12)`)
  root.style.setProperty('--shadow-card-hover', `0 8px 28px rgba(${theme.shadowRgb}, 0.16)`)
}

/** 页面加载时恢复已保存的主题 */
function restoreSavedTheme() {
  const rawId = localStorage.getItem('navpulse_theme') || 'day'
  const migrateThemeId = {
    orange: 'day',
    teal: 'green',
    light: 'day',
    dark: 'night',
  }
  const savedId = migrateThemeId[rawId] || rawId
  const theme = THEMES.find(t => t.id === savedId) || THEMES.find(t => t.id === 'day') || THEMES[0]
  if (savedId !== rawId) {
    localStorage.setItem('navpulse_theme', savedId)
  }
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
              <div class="theme-dot" :style="{ background: t.swatchGradient || t.gradient, border: t.id === 'day' ? '1px solid #E5E7EB' : 'none' }">
                <i v-if="currentTheme === t.id" class="bi bi-check-lg" :style="{ color: t.id === 'day' ? '#111111' : '#FFFFFF' }"></i>
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
