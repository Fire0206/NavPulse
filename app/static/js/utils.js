/**
 * NavPulse 工具函数
 */

/** 格式化涨跌幅：正数加 + 号 */
export const sign = v => (v > 0 ? '+' : '') + v.toFixed(2)

/** 返回 CSS class 名：up / down / 空 */
export const cls = v => v > 0 ? 'up' : (v < 0 ? 'down' : '')

/** 金额格式化：≥10000 显示 x.xx万 */
export const formatPrice = v => v >= 10000 ? (v / 10000).toFixed(2) + '万' : v.toFixed(2)

/** 金额格式化：始终显示完整数字 */
export const formatAmount = v => Number(v || 0).toFixed(2)
