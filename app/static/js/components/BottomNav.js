import { store } from '../store.js'

export default {
  name: 'BottomNav',
  setup() {
    function switchView(view) {
      store.currentView = view
    }
    return { store, switchView }
  },
  template: `
    <nav class="bottom-nav">
      <a class="nav-item" :class="{ active: store.currentView === 'holdings' }" @click="switchView('holdings')">
        <i class="bi bi-wallet2"></i>
        <span>持有</span>
      </a>
      <a class="nav-item" :class="{ active: store.currentView === 'watchlist' }" @click="switchView('watchlist')">
        <i class="bi bi-star"></i>
        <span>自选</span>
      </a>
      <a class="nav-item" :class="{ active: store.currentView === 'market' }" @click="switchView('market')">
        <i class="bi bi-bar-chart-line"></i>
        <span>行情</span>
      </a>
      <a class="nav-item" :class="{ active: store.currentView === 'settings' }" @click="switchView('settings')">
        <i class="bi bi-gear"></i>
        <span>设置</span>
      </a>
    </nav>
  `
}
