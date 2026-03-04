import { store } from '../store.js'

export default {
  name: 'LoadingOverlay',
  setup() {
    return { store }
  },
  template: `
    <Transition name="loading-bar">
      <div class="gload-bar" v-if="store.loading">
        <div class="gload-bar-track">
          <div class="gload-bar-fill"></div>
        </div>
        <span class="gload-bar-text">{{ store.loadingText }}</span>
      </div>
    </Transition>
  `
}
