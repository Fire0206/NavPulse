import { computed } from 'vue'
import { store } from '../store.js'

export default {
  name: 'TopBar',
  setup() {
    const viewTitle = computed(() => {
      const map = {
        holdings: '个人持仓看板',
        watchlist: '我的自选',
        market: '行情中心',
        settings: '设置'
      }
      return map[store.currentView] || 'NavPulse'
    })

    function logout() {
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      location.href = '/login'
    }

    return { store, viewTitle, logout }
  },
  template: `
    <div class="top-bar">
      <div class="d-flex justify-content-between align-items-center px-3" style="max-width:760px;margin:0 auto;width:100%">
        <div style="width:60px"></div>
        <div class="text-center">
          <h1><i class="bi bi-heart-pulse"></i> NavPulse</h1>
          <small>{{ viewTitle }}</small>
        </div>
        <div class="d-flex align-items-center gap-2">
          <span style="font-size:12px;opacity:.85">{{ store.username }}</span>
          <button class="btn btn-sm btn-outline-light" @click="logout" title="退出登录">
            <i class="bi bi-box-arrow-right"></i>
          </button>
        </div>
      </div>
    </div>
  `
}
