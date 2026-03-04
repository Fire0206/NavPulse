import { ref, onMounted, onUnmounted } from 'vue'

/**
 * 下拉刷新 composable
 * @param {() => HTMLElement | null} getEl  返回需要监听触摸事件的 DOM 元素
 * @param {() => Promise<void>} onRefresh   触发刷新时调用的异步函数
 * @returns {{ ptrState: Ref<'idle'|'pulling'|'triggered'|'loading'> }}
 */
export function usePullToRefresh(getEl, onRefresh) {
  const ptrState = ref('idle')  // idle | pulling | triggered | loading

  let startY = 0
  let active = false

  function _scrollTop() {
    return window.scrollY ?? document.documentElement.scrollTop ?? 0
  }

  function onTouchStart(e) {
    if (_scrollTop() <= 0 && e.touches.length === 1) {
      startY = e.touches[0].clientY
      active = true
    }
  }

  function onTouchMove(e) {
    if (!active || ptrState.value === 'loading') return
    const dy = e.touches[0].clientY - startY
    if (dy > 0 && _scrollTop() <= 0) {
      e.preventDefault()
      ptrState.value = dy > 60 ? 'triggered' : 'pulling'
    } else {
      ptrState.value = 'idle'
      active = false
    }
  }

  async function onTouchEnd() {
    if (!active) return
    active = false
    if (ptrState.value === 'triggered') {
      ptrState.value = 'loading'
      try {
        await onRefresh()
      } finally {
        ptrState.value = 'idle'
      }
    } else {
      ptrState.value = 'idle'
    }
  }

  onMounted(() => {
    const el = getEl()
    if (!el) return
    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd, { passive: true })
  })

  onUnmounted(() => {
    const el = getEl()
    if (!el) return
    el.removeEventListener('touchstart', onTouchStart)
    el.removeEventListener('touchmove', onTouchMove)
    el.removeEventListener('touchend', onTouchEnd)
  })

  return { ptrState }
}
