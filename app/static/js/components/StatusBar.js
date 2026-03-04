import { computed } from 'vue'
import { store } from '../store.js'

export default {
  name: 'StatusBar',
  setup() {
    const statusText = computed(() => {
      const navUpdatedText = store.officialNavUpdated
        ? ` | 官方净值已更新 ${store.officialNavUpdatedCount}/${store.officialNavTotalTracked}`
        : ''
      if (store.tradingStatusText && !store.isTradingTime) {
        return store.tradingStatusText + navUpdatedText + ' | 数据更新于 ' + store.lastUpdateTime
      }
      if (store.schedulerRunning) {
        return '数据更新于: ' + store.lastUpdateTime
      }
      return '调度器未运行'
    })

    const dotClass = computed(() => {
      if (store.isTradingTime) return 'online'
      if (store.tradingStatusText) return 'idle'
      return store.schedulerRunning ? 'online' : 'offline'
    })

    return { store, statusText, dotClass }
  },
  template: `
    <div class="status-bar">
      <span class="status-dot" :class="dotClass"></span>
      <span>{{ statusText }}</span>
    </div>
  `
}
