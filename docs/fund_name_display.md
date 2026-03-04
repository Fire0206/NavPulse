# 基金名称展示功能

## 功能说明

在前端输入基金代码后，系统会自动获取并展示基金的完整名称。

## 实现细节

### 1. 后端实现

#### 新增函数：`get_fund_name()`

**位置**：`app/services/fund_service.py`

```python
def get_fund_name(fund_code: str) -> str:
    """
    获取基金名称
    
    Args:
        fund_code: 基金代码
    
    Returns:
        基金名称，如果获取失败返回基金代码本身
    """
    try:
        # 使用 akshare 的基金名称查询接口
        fund_list = ak.fund_name_em()
        
        if fund_list is not None and not fund_list.empty:
            # 查找对应的基金代码
            matched = fund_list[fund_list["基金代码"] == fund_code]
            if not matched.empty:
                return str(matched.iloc[0]["基金简称"])
    except Exception as e:
        print(f"⚠️ 获取基金名称失败: {e}")
    
    # 如果获取失败，返回基金代码
    return fund_code
```

#### 修改估值服务

**位置**：`app/services/valuation_service.py`

在 `calculate_fund_estimate()` 函数中添加：

```python
# 1. 获取基金名称
fund_name = get_fund_name(fund_code)

# ...计算估值...

# 在返回结果中添加 fund_name 字段
return {
    "fund_code": fund_code,
    "fund_name": fund_name,  # ← 新增字段
    "data_date": portfolio.get("data_date"),
    "total_weight": portfolio.get("total_weight", 0.0),
    "estimate_change": round(estimate_change, 2),
    "holdings": enriched_holdings,
    "coverage": round(total_weight_with_price, 2),
}
```

### 2. 前端实现

**位置**：`app/templates/index.html`

在 `renderResult()` 函数中添加：

```javascript
// 基金名称和代码显示
document.getElementById('fundName').textContent = data.fund_name || '基金名称';
document.getElementById('fundCodeDisplay').textContent = `代码: ${data.fund_code}`;
```

## 数据流

```
用户输入基金代码 (005963)
    ↓
前端调用 API: /api/valuation/005963
    ↓
后端 valuation_service.py
    ├─ 调用 get_fund_name("005963")
    │   └─ 返回: "宝盈人工智能股票C"
    ├─ 调用 get_fund_portfolio("005963")
    └─ 调用 get_realtime_prices([...])
    ↓
返回 JSON: {
    "fund_code": "005963",
    "fund_name": "宝盈人工智能股票C",  ← 新增
    "estimate_change": -1.21,
    ...
}
    ↓
前端 JavaScript 渲染
    └─ 显示: "宝盈人工智能股票C"
```

## 使用示例

### API 请求

```bash
curl http://localhost:8000/api/valuation/005963
```

### API 响应

```json
{
  "fund_code": "005963",
  "fund_name": "宝盈人工智能股票C",
  "data_date": "2025-12-31",
  "total_weight": 43.15,
  "estimate_change": -1.21,
  "holdings": [...]
}
```

### 前端展示

```
┌─────────────────────────────────────┐
│  宝盈人工智能股票C                    │  ← 基金名称（新增）
│  代码: 005963                        │  ← 基金代码
│                                     │
│  估算涨跌幅: -1.21%                  │
└─────────────────────────────────────┘
```

## 测试验证

### 1. 测试基金名称获取

```python
from app.services.fund_service import get_fund_name

print(get_fund_name("005963"))  # 输出: 宝盈人工智能股票C
print(get_fund_name("512480"))  # 输出: 国联安中证半导体ETF
```

### 2. 测试完整估值 API

```python
from app.services.valuation_service import calculate_fund_estimate

result = calculate_fund_estimate("005963")
print(f"基金名称: {result['fund_name']}")
```

### 3. 测试 HTTP API

```bash
# 启动服务
python -m app.main

# 测试 API
curl http://localhost:8000/api/valuation/005963
```

## 常见基金代码示例

| 基金代码 | 基金名称 |
|---------|---------|
| 005963  | 宝盈人工智能股票C |
| 512480  | 国联安中证半导体ETF |
| 001632  | 天弘中证食品饮料ETF联接C |
| 110022  | 易方达消费行业股票 |

## 错误处理

如果基金名称获取失败（网络错误、代码不存在等），系统会：

1. **后端**：返回基金代码本身作为名称（降级处理）
2. **前端**：显示 "基金代码" 或从 API 返回的名称

示例：

```python
# 无效基金代码
get_fund_name("999999")  # 返回: "999999"

# API 返回
{
  "fund_code": "999999",
  "fund_name": "999999",  # 降级返回代码本身
  ...
}
```

## 性能影响

- **额外 API 调用**：每次估值查询增加 1 次基金名称查询
- **响应时间增加**：约 100-300ms（取决于网络）
- **缓存优化**：可考虑添加本地缓存减少 API 调用

## 浏览器效果

访问 http://localhost:8000 输入基金代码后：

**之前**：
```
┌───────────────────┐
│  基金名称          │  ← 固定文本
│  代码: 005963     │
└───────────────────┘
```

**改进后**：
```
┌─────────────────────────────┐
│  宝盈人工智能股票C            │  ← 动态显示
│  代码: 005963               │
└─────────────────────────────┘
```

## 更新日志

- **2026-02-15**：新增基金名称展示功能
- 后端：添加 `get_fund_name()` 函数
- API：返回结果增加 `fund_name` 字段
- 前端：动态渲染基金名称

---

**开发者**: NavPulse Team  
**版本**: v1.1.0  
**最后更新**: 2026年2月15日
