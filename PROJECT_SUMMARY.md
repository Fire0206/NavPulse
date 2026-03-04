# NavPulse 项目架构概要

> 本文档用于快速恢复上下文。当 AI 上下文丢失时，读此文件即可理解全部代码架构。并且请你每一次修改完同步更新此文档并进行git备份。

## 一、项目定位

**NavPulse** 是一个**基金实时估值 Web 系统（多用户版）**，基于基金公开的季度重仓持仓 + 股票实时行情来**估算基金当日净值涨跌幅**。

**安全特性**（开源项目标准）：
- 强密码要求（8位+大小写+数字）+ bcrypt 哈希
- 登录速率限制（5分钟5次失败尝试）
- 安全响应头（HSTS、CSP、X-Frame-Options 等）
- 生产环境 JWT_SECRET_KEY 强制检查
- 模糊化认证错误（防用户名枚举）

核心功能：
1. **基金实时估值** — 通过重仓股票实时价格加权计算基金今日估值涨跌幅
2. **持仓组合管理** — 用户可添加多只基金持仓，查看总市值、当日盈亏
3. **自选基金** — 不实际持有，仅关注涨跌
4. **行情总览** — 大盘指数、全市场涨跌分布、行业板块
5. **基金历史净值** — 历史净值走势图
6. **联接基金穿透** — 自动识别联接基金并穿透到底层 ETF 真实持仓
7. **OCR 截图导入** — 拍照/上传支付宝持仓截图，自动识别基金名称+市值+收益并批量导入
8. **设置中心** — 多主题色切换（6色：樱花粉/天空蓝/星空紫/薄荷绿/light（纯白风）/dark（纯黑风））、隐私模式、缓存管理、系统信息

---

## 二、技术栈

| 层级     | 技术                                          |
| -------- | --------------------------------------------- |
| Web 框架 | **FastAPI** (异步) + **Uvicorn**               |
| 模板引擎 | **Jinja2** (服务端渲染 HTML)                   |
| 前端     | **Vue 3** CDN (ESM) + **ECharts 5.5** + **Bootstrap 5.3** |
| ORM      | **SQLAlchemy** + **SQLite**                    |
| 认证     | **JWT** (`python-jose`) + **bcrypt** (`passlib`) |
| 行情数据 | **akshare** (基金持仓/名称/历史/类型) + **腾讯行情接口** (股票+ETF实时价格) + **新浪财经接口** (海外指数) |
| OCR 识别 | **rapidocr-onnxruntime** (支付宝截图持仓导入) + **Pillow** (图片预处理) |
| 异步 HTTP| **aiohttp** (股票实时行情获取)                  |
| 缓存     | **cachetools.TTLCache** (内存 TTL 缓存)        |
| 调度器   | **APScheduler** (AsyncIOScheduler, 定时刷新)   |
| 部署     | **Gunicorn** + Uvicorn Worker（宝塔面板）       |

依赖文件: `requirements.txt`

---

## 三、目录结构

```
NavPulse/
├── app/
│   ├── __init__.py          # 空文件
│   ├── main.py              # ★ FastAPI 入口 + lifespan 生命周期（~130行）
│   ├── database.py          # SQLAlchemy 引擎 + SQLite WAL 模式
│   ├── scheduler.py         # APScheduler 后台定时任务（~470行）
│   ├── state.py             # GlobalCache 全局内存缓存容器（253行）
│   ├── models/
│   │   └── __init__.py      # ORM 模型：User, Holding, Watchlist, FundTransaction, IntradayEstimate 等
│   ├── routers/
│   │   └── __init__.py      # 空，路由全在 main.py 中
│   ├── services/
│   │   ├── __init__.py      # 空
│   │   ├── auth_service.py  # 认证：注册/登录/JWT/密码哈希
│   │   ├── fund_classifier.py # ★ 基金类型自动分类（ETF/QDII/股票/混合/债券/货币）
│   │   ├── fund_service.py  # 基金持仓获取 + 联接基金穿透 + 历史净值
│   │   ├── market_service.py# 行情：大盘指数/涨跌分布/板块
│   │   ├── ocr_service.py   # ★ OCR 截图解析（支付宝持仓导入）
│   │   ├── overseas_service.py # ★ 海外指数实时数据（新浪财经API，8大全球指数）
│   │   ├── portfolio_service.py # 持仓 CRUD + 组合估值整合
│   │   ├── stock_service.py # 股票实时行情（同步版，已被 valuation 的异步版替代）
│   │   ├── trading_calendar.py # 交易日历判断 + 休市检测
│   │   ├── transaction_service.py # ★ 交易记录 CRUD + 持仓同步 + 统计
│   │   └── valuation_service.py # ★ 核心多策略估值引擎（ETF场内+海外指数+重仓股加权）
│   ├── data/
│   │   ├── holdings.json    # 示例持仓数据（旧版残留）
│   │   └── navpulse.db      # SQLite 数据库文件（运行时生成）
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css    # ★ 全局样式（~1250行）
│   │   └── js/
│   │       ├── app.js       # Vue 3 应用入口（注册组件 + provide 弹窗方法）
│   │       ├── api.js       # API 调用层（统一封装所有后端接口）
│   │       ├── store.js     # 响应式全局状态 + Toast + 缓存读写(readCache/writeCache)
│   │       ├── utils.js     # 工具函数（sign, cls, formatPrice）
│   │       └── components/
│   │           ├── AddFundModal.js     # 添加基金弹窗
│   │           ├── BottomNav.js        # 底部导航栏（4Tab：持有/自选/行情/设置）
│   │           ├── FundDetailModal.js  # ★ 基金详情全屏弹窗（~590行）
│   │           ├── HoldingsView.js     # 持仓看板视图
│   │           ├── LoadingOverlay.js   # 加载遮罩
│   │           ├── MarketView.js       # 行情总览视图
│   │           ├── OcrImportModal.js   # ★ OCR 截图导入弹窗（支付宝持仓导入）
│   │           ├── SettingsView.js     # 设置页（主题切换/隐私模式/缓存管理/系统信息）
│   │           ├── StatusBar.js        # 状态栏
│   │           ├── TopBar.js           # 顶部栏 + 隐私模式
│   │           └── WatchlistView.js    # 自选基金视图
│   └── templates/
│       ├── index.html       # 主页面（Vue 3 SPA 入口，引用 static 资源）
│       ├── login.html       # 登录页
│       └── register.html    # 注册页
├── docs/
│   ├── feeder_fund_penetration.md  # 联接基金穿透功能文档
│   └── fund_name_display.md       # 基金名称展示功能文档
├── gunicorn_conf.py         # Gunicorn 部署配置
├── start.sh                 # 宝塔面板启动脚本
├── requirements.txt         # Python 依赖（版本范围锁定）
├── .env.example             # 环境变量配置示例
├── .gitignore               # Git 忽略规则
├── LICENSE                  # MIT 许可证
├── DEPLOY.md                # 部署文档
└── README.md                # 项目说明
```

---

## 四、数据模型（ORM）

文件：`app/models/__init__.py`

### User（用户表）
| 字段            | 类型       | 说明           |
| --------------- | ---------- | -------------- |
| id              | Integer PK | 自增主键       |
| username        | String(50) | 唯一用户名     |
| hashed_password | String(128)| bcrypt 哈希密码 |

关系：`holdings` → Holding (一对多), `watchlist` → Watchlist (一对多)

### Holding（持仓表）
| 字段       | 类型       | 说明             |
| ---------- | ---------- | ---------------- |
| id         | Integer PK | 自增主键         |
| user_id    | Integer FK | 关联 User.id     |
| code       | String(10) | 基金代码（6位）  |
| shares     | Float      | 持有份额         |
| cost_price | Float      | 总投入本金（元） |

### Watchlist（自选基金表）
| 字段      | 类型       | 说明             |
| --------- | ---------- | ---------------- |
| id        | Integer PK | 自增主键         |
| user_id   | Integer FK | 关联 User.id     |
| fund_code | String(10) | 基金代码（6位）  |

唯一约束：`(user_id, fund_code)`

### FundTransaction（交易记录表）
| 字段       | 类型       | 说明                     |
| ---------- | ---------- | ------------------------ |
| id         | Integer PK | 自增主键                 |
| user_id    | Integer FK | 关联 User.id             |
| fund_code  | String(10) | 基金代码                 |
| type       | String(10) | "buy" 或 "sell"          |
| date       | String(10) | 交易日期 YYYY-MM-DD      |
| shares     | Float      | 交易份额                 |
| amount     | Float      | 交易金额（元）           |
| nav        | Float      | 交易时净值（自动计算）   |
| created_at | String(30) | 创建时间                 |

复合索引：`(user_id, fund_code)`

### IntradayEstimate（日内估值快照表）
| 字段            | 类型       | 说明                        |
| --------------- | ---------- | --------------------------- |
| id              | Integer PK | 自增主键                    |
| fund_code       | String(10) | 基金代码                    |
| trade_date      | String(10) | 交易日期 YYYY-MM-DD         |
| time            | String(8)  | 时间点 HH:MM                |
| estimate_change | Float      | 估值涨跌幅 %                |

唯一约束：`(fund_code, trade_date, time)`；复合索引：`(fund_code, trade_date)`

### 持久化缓存表
- **CachedData** — 通用 KV 缓存（行情数据持久化）
- **CachedFundValuation** — 基金估值持久化
- **CachedPortfolio** — 用户持仓估值持久化

### FundNavHistory（基金历史净值持久化表）★ 新增
| 字段       | 类型        | 说明                                    |
| ---------- | ----------- | --------------------------------------- |
| id         | Integer PK  | 自增主键                                |
| fund_code  | String(10)  | 基金代码                                |
| date       | String(10)  | 净值日期 YYYY-MM-DD                     |
| nav        | Float       | 单位净值                                |
| change_pct | Float       | 日涨跌幅 %（null = 待补全）             |
| is_filled  | Integer     | 1=正常数据, 0=待补全占位符              |

唯一约束：`(fund_code, date)`；索引：`(fund_code, date)`

### FundPortfolioCache（基金重仓持仓持久化缓存）★ 新增
| 字段            | 类型        | 说明                                    |
| --------------- | ----------- | --------------------------------------- |
| id              | Integer PK  | 自增主键                                |
| fund_code       | String(10)  | 基金代码（唯一）                         |
| holdings_json   | Text        | 重仓列表 JSON（含 code/name/weight）     |
| data_date       | String(10)  | 数据对应的季度末日期                    |
| updated_at      | String(30)  | 最后爬取时间 YYYY-MM-DD HH:MM:SS        |
| penetrated_from | String(10)  | ETF联接穿透来源ETF代码（如510300），非联接基金为NULL |

缓存有效期 7 天，超期触发后台静默刷新。

---


## 五、核心模块详解（2024重构版）

### 5.1 目录结构与模块化说明

2024年已完成后端模块化重构，目录结构如下：

```
app/
   main.py           # FastAPI 入口，仅负责加载和注册routers
   routers/          # 路由模块，按功能拆分（auth/portfolio/market/fund/system等）
      auth.py
      portfolio.py
      watchlist.py
      market.py
      fund.py
      system.py
      __init__.py
   schemas.py        # Pydantic请求/响应模型，所有API数据结构集中管理
   services/         # 业务服务层，功能分层（auth/valuation/portfolio/market/fund/transaction等）
      auth_service.py
      valuation_service.py
      fund_service.py
      market_service.py
      portfolio_service.py
      transaction_service.py
      trading_calendar.py
   state.py          # 全局缓存容器
   database.py       # 数据库配置与Session管理
   static/           # 前端静态资源
   templates/        # Jinja2模板
   data/             # 数据文件（如SQLite DB）
```

**重构要点：**
- main.py 仅为入口，所有路由已拆分到 routers/，每个功能独立维护，便于扩展和维护。
- schemas.py 独立，所有Pydantic模型集中，前后端数据结构一目了然。
- services/ 业务分层，逻辑清晰，便于单元测试和后续功能扩展。
- 旧版 stock_service.py（同步版）和 holdings.json 已删除，所有实时行情和持仓数据均走异步服务和数据库。
- .gitignore 已增强，忽略pyc/venv/db/logs等。

### 5.1.1 路由拆分与注册

所有API路由已按功能模块拆分至 routers/ 目录，main.py 仅负责统一注册：

```python
from fastapi import FastAPI
from app.routers import auth, portfolio, watchlist, market, fund, system

app = FastAPI()
app.include_router(auth.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(market.router)
app.include_router(fund.router)
app.include_router(system.router)
```

各路由文件内通过 APIRouter 定义接口，支持独立权限控制、依赖注入、分组文档。

**路由一览表**（详见 routers/ 各py文件）：

| 方法   | 路径                          | 鉴权 | 说明                       |
| ------ | ----------------------------- | ---- | -------------------------- |
| GET    | `/`                           | ✗    | 主页（渲染 index.html）    |
| GET    | `/login`                      | ✗    | 登录页                     |
| GET    | `/register`                   | ✗    | 注册页                     |
| POST   | `/register`                   | ✗    | 用户注册 API               |
| POST   | `/token`                      | ✗    | 用户登录，返回 JWT Token   |
| GET    | `/api/me`                     | ✓    | 获取当前用户信息           |
| GET    | `/api/valuation/{fund_code}`  | ✗    | 单只基金估值（可穿透查看） |
| GET    | `/api/portfolio`              | ✓    | 获取持仓看板数据           |
| POST   | `/api/portfolio`              | ✓    | 添加/更新持仓              |
| DELETE | `/api/portfolio/{fund_code}`  | ✓    | 删除持仓                   |
| GET    | `/api/watchlist`              | ✓    | 获取自选列表（带估值）     |
| POST   | `/api/watchlist`              | ✓    | 添加自选                   |
| DELETE | `/api/watchlist/{fund_code}`  | ✓    | 删除自选                   |
| GET    | `/api/market`                 | ✗    | 行情总览（指数+分布+板块） |
| GET    | `/api/market/indices`         | ✗    | 大盘指数                   |
| GET    | `/api/market/distribution`    | ✗    | 涨跌分布                   |
| GET    | `/api/market/sectors`         | ✗    | 板块列表                   |
| GET    | `/api/fund/history/{code}`    | ✗    | 基金历史净值               |
| GET    | `/api/cache`                  | ✗    | 缓存状态（调试）           |
| DELETE | `/api/cache`                  | ✗    | 清空缓存                   |
| GET    | `/api/status`                 | ✗    | 系统状态                   |
| GET    | `/health`                     | ✗    | 健康检查                   |
| GET    | `/api/fund/{code}/detail`     | ✓    | 基金详情综合（估值+持仓+交易） |
| GET    | `/api/fund/{code}/transactions` | ✓  | 获取持仓统计+交易记录列表  |
| POST   | `/api/fund/{code}/transactions` | ✓  | 添加交易记录（自动同步持仓）|
| DELETE | `/api/fund/{code}/transactions/{id}` | ✓ | 删除交易记录            |
| GET    | `/api/fund/{code}/intraday`   | ✗    | 日内估值走势快照           |

鉴权方式：JWT Bearer Token，通过 `Depends(get_current_user)` 注入。

### 5.2 valuation_service.py — 多策略估值引擎（核心）

**文件行数**：~1069行  
**核心函数**：`calculate_fund_estimate(fund_code)`

**多策略估值路由**：
```
1. 查 TTLCache（300秒/5分钟）→ 命中直接返回
2. 调用 fund_classifier.classify_fund(fund_code) 获取基金类型
3. 根据类型选择估值策略:
   A. ETF联接(penetrated_from) → _estimate_via_etf_price() → 底层ETF场内实时价格
   B. 场内ETF                   → _estimate_via_etf_price() → 自身场内实时价格
   C. QDII(overseas_index)      → _estimate_qdii_fund() → 海外指数涨跌幅
   D. 普通股票/混合型           → weighted_holdings → 重仓股实时加权(原有算法)
   E. 债券/货币/其他            → nav_history → 历史净值回退
4. 写入缓存，返回结果(含 estimation_method, fund_type, fund_type_label)
```

**估值策略详解**：
| 策略 | 适用基金 | 数据源 | 精度 |
|------|----------|--------|------|
| `etf_realtime` | 场内ETF / ETF联接(穿透) | 腾讯行情 qt.gtimg.cn | ★★★★★ |
| `overseas_index` | QDII基金 | 新浪财经 hq.sinajs.cn + 汇率修正 | ★★★★ |
| `weighted_holdings` | 普通股票型/混合型 | 腾讯行情(重仓股) + 市场代理 | ★★★☆ |
| `nav_history` | 债券/货币/兜底 | 东方财富历史净值 | ★★ |

**估值优化参数（回测进化引擎 v2.4，MAE↓22%）**：
| 参数 | 值 | 说明 |
|------|----|------|
| `_NON_TOP_PROXY_CHANGE` | 0.12% | 非重仓股市场代理涨跌幅 |
| `_ETF_POSITION_RATIO` | 0.92 | ETF联接实际投资ETF比例 |
| `_ETF_CASH_DRAG` | 0.005% | 现金仓位日拖累 |
| `_QDII_MGMT_FEE_DAILY` | 0.004% | QDII日均管理费 |
| `_QDII_TRACKING_BETA` | 1.0 | 海外指数跟踪β |
| `_DRIFT_DECAY_RATE` | 0.02/月 | 季报持仓权重衰减率 |
| `_SECTOR_BETA` | 0.92~1.10 | 行业β对冲系数 |
| `_get_fx_rate_change()` | 实时 | USD/CNY汇率联动修正 |

**日内分时估值计算** (`calculate_intraday_from_stocks(fund_code)`)：
```
1. 获取基金持仓（股票代码 + 权重）
2. 异步获取各股票分时数据（腾讯 ifzq.gtimg.cn 分时接口）
3. 前向填充缺失分钟数据
4. 每分钟加权计算基金估值涨跌幅
```
- 用于非交易时段 DB 无快照时的回退计算
- 股票分时接口非交易日返回上一交易日数据

**辅助函数**：
- `_get_qt_code(stock_code)` — 股票代码转腾讯行情格式
- `_get_stock_minute_data_async(stock_codes)` — 异步获取多只股票分时数据

**行情数据源**：腾讯股票行情接口 `http://qt.gtimg.cn/q=s_sh601138,s_sz002230,...`
- 使用 `s_` 前缀获取简要数据（更快）
- 支持沪市(`sh`)、深市(`sz`)、北交所(`bj`)、港股(`hk`)
- 响应格式：`v_s_sh601138="1~工业富联~601138~24.50~0.30~1.25~..."` → 用 `~` 分割

**组合估值**：`get_portfolio_valuation(holdings)` — 用 `asyncio.gather` 并行计算 N 只基金估值。

### 5.3 fund_service.py — 基金数据服务

**两大功能**：

#### A. 基金持仓获取 + 联接基金穿透
- `get_fund_portfolio(fund_code)` — 通过 `akshare.fund_portfolio_hold_em()` 获取基金季报持仓
- 自动取最新季度数据
- **联接基金穿透**：若第一大重仓是 ETF 且权重 > 60%，递归获取 ETF 底层持仓（最大深度 3）
- ETF 识别规则：代码前缀 `51/15/56/58` 或名称含 "ETF"

#### B. 基金历史净值
- `get_fund_history_async(fund_code, days)` — 通过 `akshare.fund_open_fund_info_em()` 获取历史净值走势
- 带 TTLCache 缓存（5分钟过期）
- 返回最高点/最低点统计

#### C. 基金名称
- `get_fund_name(fund_code)` — 通过 `akshare.fund_name_em()` 获取名称

### 5.3a fund_classifier.py — 基金类型自动分类 ★ 新增

**核心功能**：根据基金代码/名称/东方财富基金类型字段，自动识别基金类别并返回最优估值策略。

**分类优先级**：
1. QDII 类（海外投资）→ `overseas_index` 估值
2. ETF 联接基金 → `etf_linked` 估值（底层 ETF 场内实时价格）
3. 场内 ETF → `etf_realtime` 估值（ETF 场内价格直取）
4. 普通股票/混合型 → `weighted_holdings`（重仓股加权算法）
5. 债券/货币型 → `nav_only`（仅显示历史净值）

**QDII 指数匹配规则**（12条正则规则）：
| 关键词匹配 | 指数标识 | 延迟 | 描述 |
|-----------|----------|------|------|
| 纳斯达克/纳指/NASDAQ | nasdaq | T+2 | QDII-纳斯达克 |
| 标普500/S&P | sp500 | T+2 | QDII-标普500 |
| 道琼斯 | dji | T+2 | QDII-道琼斯 |
| 恒生/港股/中概互联 | hangseng | T+1 | QDII-港股 |
| 日经/日本 | nikkei | T+1 | QDII-日本 |
| DAX/德国 | dax | T+2 | QDII-欧洲 |
| 全球/MSCI/国际 | sp500 | T+2 | QDII-全球 |

**缓存策略**：
- 基金分类结果: `TTLCache(2h)`（基金类型极少变化）
- 全量基金列表: 单例缓存(2h)，所有基金共享同一次 API 下载

**数据来源**：`akshare.fund_name_em()` 的 `基金类型` 字段（如 "指数型-股票"、"QDII-普通股票"、"指数型-海外股票" 等）

### 5.3b overseas_service.py — 海外指数服务 ★ 新增

**核心功能**：通过新浪财经 API (`hq.sinajs.cn`) 获取全球主要指数实时涨跌幅，为 QDII 基金估值提供数据源。

**支持的指数**：
| 标识 | 新浪代码 | 指数名称 |
|------|----------|----------|
| nasdaq | int_nasdaq | 纳斯达克综合 |
| sp500 | int_sp500 | 标普500 |
| dji | int_dji | 道琼斯工业 |
| hangseng | int_hangseng | 恒生指数 |
| nikkei | int_nikkei | 日经225 |
| dax | int_dax | 德国DAX |
| ftse | int_ftse | 英国富时100 |
| cac | int_cac | 法国CAC40 |

**缓存策略**：`TTLCache(60s)` — 海外指数变化频率适中

**API 响应格式**：`"纳斯达克,22484.07,99.37,0.44"` → 名称, 最新价, 涨跌额, 涨跌幅%

### 5.4 market_service.py — 行情服务

提供三类数据（全部异步 + TTLCache）：
1. **大盘指数** — 上证指数、深证成指、创业板指（`akshare.stock_zh_index_spot_em`，缓存60s）
2. **涨跌分布** — 全 A 股涨跌家数 + 按幅度区间分布（`akshare.stock_zh_a_spot_em`，缓存60s）
3. **板块数据** — 行业板块涨跌排行 Top20（`akshare.stock_board_industry_name_em`，缓存120s）
4. **基金涨跌榜** — 全市场基金日涨跌幅 TOP50（`akshare.fund_open_fund_rank_em`，缓存300s）
   - **A/C 类去重**：通过 `_dedup_ac_class()` 在取 TOP/BOTTOM 前对 DataFrame 去重，C 类优先保留；若只有 A 类则保留 A 类

所有 akshare 同步调用通过 `loop.run_in_executor(ThreadPoolExecutor)` 转异步。

### 5.5 portfolio_service.py — 持仓管理

- CRUD：`get_holdings()`, `add_holding()`, `remove_holding()`, `clear_holdings()`
- 整合入口：`get_portfolio_with_valuation_async(db, user_id)` — 查 DB 取持仓 → 调用估值引擎 → 返回看板数据

### 5.6 transaction_service.py — 交易记录服务

**文件行数**：~237行

管理基金买卖交易记录，使用**加权平均成本法**计算持仓成本。

**核心函数**：
| 函数                  | 说明                                                        |
| --------------------- | ----------------------------------------------------------- |
| `get_transactions()`  | 获取某基金全部交易记录（按日期升序）                        |
| `add_transaction()`   | 添加交易 + 自动同步 Holding 表                              |
| `delete_transaction()`| 删除交易 + 自动同步 Holding 表                              |
| `_sync_holding()`     | 从全部交易重算持仓（加权平均成本法），更新/创建/删除 Holding 行 |
| `calculate_holding_stats()` | 计算持仓统计：份额、成本、平均成本、持有天数等        |

**加权平均成本法**：
```
买入: total_shares += shares, total_cost += amount
卖出: cost_removed = sell_shares × (total_cost / total_shares)
       total_cost -= cost_removed, total_shares -= sell_shares
平均成本 = total_cost / total_shares
```

**容错**：当没有交易记录时，从 Holding 表读取遗留数据（向后兼容）。

### 5.7 auth_service.py — 认证服务

- 密码加密：bcrypt
- Token：JWT（HS256），有效期由环境变量 `TOKEN_EXPIRE_MINUTES` 控制（默认 24h）
- SECRET_KEY：从环境变量 `JWT_SECRET_KEY` 读取，未配置时自动随机生成（重启失效）
- 依赖注入：`get_current_user()` 从 Token 解析用户，鉴权路由用 `Depends(get_current_user)`

### 5.8 stock_service.py — 股票行情（同步版）

- `get_realtime_prices(stock_codes)` — 同步版腾讯行情接口（用 `requests`）
- **已被 `valuation_service.py` 中的 `_get_realtime_prices_async()` 异步版替代**
- 保留为独立模块，可能用于调试/测试

### 5.9 trading_calendar.py — 交易日历判断

- `is_market_open()` — 当前是否为交易时段（周一~五 9:30-15:00，排除午休）
- `is_trading_day(dt)` — 给定日期是否为交易日（排除周末和中国法定节假日）
- 用于日内估值快照存取和调度器控制

### 5.10 scheduler.py — 后台调度器

使用 APScheduler `AsyncIOScheduler`（时区 `Asia/Shanghai`）。

**定时任务**：
| 任务                       | 频率      | 时间范围           | 说明                                    |
| ----------------------- | --------- | --------------- | ---------------------------------------- |
| `update_all_data`       | 每 3 分钟 | 周一~五 9:00-15:30  | 全量更新：行情→估値→持仓                   |
| `update_market_only`    | 每 1 分钟 | 周一~五 9:00-15:30  | 仅更新行情（变化频繁）                     |
| `daily_nav_update`      | 16:00     | 周一~五          | 每日收盘后增量更新所有被跟踪基金历史净値 |
| `daily_gap_fill`        | 20:00     | 每日              | 扫描并修复缺失/零値历史净値             |

**全量更新流程** (`update_all_data`)：
1. `update_market_data()` — 并行获取指数+分布+板块
2. `update_fund_valuations()` — 查 DB 取所有基金代码（持仓∪自选），并行估值（Semaphore 限制 5 并发）
   - ★ 交易时段自动存储日内估值快照 (`IntradayEstimate`)，供分时走势图使用
3. `update_user_portfolios()` — 遍历所有有持仓的用户，更新组合数据

**辅助函数**：
- `_store_intraday_snapshot(fund_code, estimate_change)` — 存储单条日内快照到 IntradayEstimate 表

**应用启动时**：`on_startup` → 初始化 DB → 启动调度器 → 立即执行一次全量更新

### 5.11 state.py — 全局缓存容器

`GlobalCache` 单例 (`global_cache`)，存储在内存中，API 直接读取实现秒级响应：

```python
global_cache.market_indices     # list[dict]  — 大盘指数
global_cache.stock_distribution # dict        — 涨跌分布
global_cache.sectors            # list[dict]  — 板块
global_cache.fund_valuations    # {code: data} — 基金估值
global_cache.portfolio_cache    # {user_id: data} — 用户持仓
global_cache.last_update_time   # str — 最后更新时间
global_cache.scheduler_running  # bool — 调度器状态
```

### 5.12 database.py — 数据库配置

- 引擎：SQLite（文件 `app/data/navpulse.db`）
- `check_same_thread=False` — 支持多线程
- `get_db()` — FastAPI 依赖注入，yield Session
- `init_db()` — 创建所有表（`Base.metadata.create_all`）

---

## 六、缓存架构

### 数据获取策略（重点优化）

| 数据类型       | 第一次请求                  | 后续请求                             | 定期刺探                         |
| ------------ | ----------------------- | --------------------------------- | ---------------------------- |
| 历史净値     | akshare 全量拉取并内共入 DB   | DB 直接返回 + 陪老数据后台静默刷新    | 每日 16:00 增量更新         |
| 重仓持仓     | akshare 全量拉取并内共入 DB   | DB 有效期 7 天内直接返回       | 超期后后台静默刷新         |
| 实时估値     | 调度器定期计算，写入内存缓存 | API 直接读 L1 内存缓存           | 每 3 分钟                   |
| 行情数据     | 调度器定期计算，写入内存缓存 | API 直接读 L1 内存缓存           | 每 1 分钟                   |
| 日内分时走势 | 展示时读 DB ，调度器写入     | DB 直接返回                      | 每 3 分钟存储快照             |

### 缓存分层

| 级别 | 位置                              | TTL    | 用途                       |
| ---- | --------------------------------- | ------ | --------------------------- |
| L1   | `GlobalCache` (state.py)          | 无过期  | 调度器写入，API 秒级读取        |
| L2   | `TTLCache` (valuation_service.py) | 300s   | 单基金估値结果缓存             |
| L3   | `TTLCache` (market_service.py)    | 60-120s | 行情数据缓存               |
| L4   | `FundNavHistory` (SQLite DB)      | 量本   | 历史净値持久化，增量更新     |
| L4   | `FundPortfolioCache` (SQLite DB)  | 7天    | 重仓持仓持久化，调度器刷新   |

**数据刷新流程**：调度器定时触发 → 调用 service 层 → 写入 L1 内存缓存 + L4 DB（卸度）→ API 读 L1

**后台静默刷新策略**：
- 首次请求：返回空数据结构，后台 `asyncio.create_task` 异步爬取，不阻塞响应
- 后续请求：从 L1 内存缓存毫秒返回，调度器定期刷新数据
- 用户手动刷新（force_refresh）：立即返回当前缓存，后台异步爬取，前端轮询检测更新
- 数据陈旧：触发 `asyncio.create_task(增量更新)` ，不阻塞当前请求
- 缺失数据：每日 20:00 `batch_fill_all_gaps()` 扫描并修复所有零値行

**行情 API 非阻塞策略**（`/api/market`）：
- API 绝不在请求处理中调用慢速 akshare 接口
- 正常请求：直接返回 `global_cache` 数据（< 1ms）
- `force_refresh=true`：触发 `_background_market_refresh()` 后台任务，立即返回当前缓存
- 缓存为空（首次启动）：同样触发后台任务，返回空结构，前端自动重试
- 后台刷新任务有 `_bg_refreshing` 锁防止重复触发

**基金详情/估值 API 非阻塞策略**（`/api/valuation/{code}`, `/api/fund/{code}/detail`, `/api/fund/{code}/intraday`）：
- `/api/valuation/{code}`：始终立即返回 `global_cache` 缓存，无缓存时返回空壳 `{_pending: true}` + 后台 `asyncio.create_task` 计算
- `/api/fund/{code}/detail`：第一阶段 DB 并行查询（< 10ms），第二阶段估值如无缓存则后台异步，不阻塞
- `/api/fund/{code}/intraday`：优先从 DB 读取已有快照（毫秒级），后台异步计算完整分时曲线
- 后台估值刷新有 per-fund_code 锁（`_bg_valuation_locks`）防止重复触发

**持仓/自选 API 非阻塞策略**（`/api/portfolio`, `/api/watchlist`）：
- `/api/portfolio`：`force_refresh=true` 时立即返回缓存 + 后台 `asyncio.create_task` 刷新
- `/api/watchlist`：立即从 `global_cache` 逐基金构建结果，无缓存的基金后台异步计算

**前端基金详情秒开策略**（`FundDetailModal.js`）：
- `open()` 优先从 `store.holdingsData` 或 `store.watchlistData` 提取预览数据立即展示
- 后端 API 秒级返回缓存后替换预览数据
- 若后端返回空壳数据（`estimate_change=0` + 无 stocks），3 秒后自动重拉
- 30 秒轮询静默刷新 detail + intraday（`_silentRefresh`），无 loading 状态

---

## 七、前端架构

前端重构为 **Vue 3 CDN**（ESM 浏览器模块）+ **组件化** 架构。

### 技术选型
- **Vue 3**：通过 CDN（`vue.esm-browser.prod.js`）引入，使用 Composition API + `<script type="module">`
- **ECharts 5.5**：图表库（实时走势图、业绩走势图）
- **Bootstrap 5.3**：布局、模态框、图标

### 架构分层

| 层   | 文件                  | 职责                           |
| ---- | --------------------- | ------------------------------ |
| 入口 | `app.js`              | 创建 Vue app，注册组件，provide 弹窗方法 |
| 状态 | `store.js`            | reactive 全局状态 + Toast + localStorage 缓存读写 |
| API  | `api.js`              | 所有后端接口统一封装           |
| 工具 | `utils.js`            | sign/cls/formatPrice 等工具    |
| 组件 | `components/*.js`     | 各视图/弹窗组件               |

### 组件清单

| 组件                | 行数  | 说明                                           |
| ------------------- | ----- | ---------------------------------------------- |
| `HoldingsView.js`   | ~260  | 持仓看板：缓存优先 + 骨架屏 + 静默刷新          |
| `WatchlistView.js`  | ~140  | 自选基金：缓存优先 + 骨架屏 + 静默刷新          |
| `MarketView.js`     | ~340  | 行情总览：缓存优先 + 骨架屏 + 后台静默刷新 + 自动重试 |
| `OcrImportModal.js` | ~280  | OCR 截图导入：上传图片→识别→预览确认→批量导入 |
| `FundDetailModal.js`| ~590  | ★ 基金详情全屏弹窗（核心，见下方详述）          |
| `AddFundModal.js`   | ~180  | 添加基金弹窗（持仓/自选模式切换）                |
| `TopBar.js`         | ~50   | 顶部栏：标题 + 隐私模式开关                      |
| `StatusBar.js`      | ~40   | 系统状态条：更新时间 + 调度器状态                 |
| `BottomNav.js`      | ~40   | 底部导航栏（持仓/行情/自选/设置 四切换）           |
| `SettingsView.js`   | ~210  | 设置页：主题切换(6色，含 light/dark)/隐私模式/缓存管理/系统信息   |
| `LoadingOverlay.js` | ~30   | 顶部进度条（保留，各视图已改用骨架屏加载）        |

### FundDetailModal.js — 基金详情页（核心）

全屏模态框（`modal-fullscreen`），功能包括：

**Header 区域**：
- 基金名称 + 代码
- 返回按钮（关闭模态框）
- 持仓管理按钮（✏️ 图标）

**持仓概览区域（Hero）**：
- 当日估值涨跌幅（大字体）
- 3×3 持仓统计网格：持有金额、持有份额、持仓占比、持有收益、收益率、持仓成本、当日收益、持有天数
- 无持仓时显示引导文字

**持仓管理面板（可折叠）**：
- 买入/卖出切换按钮
- 日期、份额、金额输入框
- 自动计算对应净值
- 交易记录列表（带删除按钮）

**Tab 1 — 实时走势**：
- ECharts 日内估值走势图（09:30-15:00，跳过午休 11:31-12:59）
- LIVE 标识（交易时段自动30秒轮询刷新）
- 非交易时段显示上一交易日数据
- 基金重仓股列表（Top 10，显示涨跌幅 + 持仓权重）

**Tab 2 — 业绩走势**：
- 时间段选择器：近1月/近3月/近6月/近1年/近3年
- ECharts 历史净值走势图 + 买卖标记点（红色▲买入、绿色◆卖出）+ 平均成本虚线（黄色）
- 每日净值列表（日期、净值、日涨幅）

### 通信机制
- 父子通信：`provide/inject`（app.js provide `openDetailModal` / `openAddModal`）
- 组件通过 `inject()` 获取打开弹窗的方法
- 全局状态通过 `store.js` 的 `reactive()` 对象共享
- **缓存优先加载**：各视图 `loadXxx()` 先 `readCache()` → 渲染缓存数据 → `fetch` API → `writeCache()` 更新
- **两种加载态**：`initialLoading`（骨架屏，无缓存时）、`silentRefreshing`（小转圈，有缓存后台刷新时）

### 认证流程
- Token 存储在 `localStorage`
- 所有需鉴权的请求通过 `authHeaders()` 添加 `Authorization: Bearer <token>` 头
- 未登录或 Token 过期自动跳转 `/login`
- API 层统一 `checkAuth()` 拦截 401 响应

---

## 八、部署方式

- **生产环境**：宝塔面板 + Gunicorn + Uvicorn Worker
  - `gunicorn -c gunicorn_conf.py app.main:app`
  - 绑定 `127.0.0.1:8000`，Nginx 反代
  - Worker 数 = `min(CPU核数, 4)`
  - 超时 120s（akshare 可能慢）
- **本地开发**：`python -m app.main` 或 `uvicorn app.main:app --reload`

---

## 九、数据流全景图

```
┌──────────────────────────────────────────────────────────────────┐
│                         浏览器 (index.html)                       │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────────┐            │
│  │持仓看板│  │行情总览│  │自选基金│  │基金详情模态│            │
│  └───┬────┘  └───┬────┘  └───┬────┘  └─────┬──────┘            │
│      │           │           │              │                    │
│  JWT Bearer Token (localStorage)                                 │
└──────┼───────────┼───────────┼──────────────┼────────────────────┘
       │           │           │              │  HTTP API
═══════╪═══════════╪═══════════╪══════════════╪════════════════════
       ▼           ▼           ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI (main.py)                              │
│  ┌──────────────────────────────────────────────────────┐       │
│  │              GlobalCache (state.py)                   │       │
│  │  market_indices | fund_valuations | portfolio_cache   │       │
│  └───────────────────────┬──────────────────────────────┘       │
│                          │ 定时写入                               │
│  ┌───────────────────────┴──────────────────────────────┐       │
│  │           APScheduler (scheduler.py)                  │       │
│  │  每1分钟: update_market  |  每3分钟: update_all       │       │
│  └────┬──────────┬──────────┬───────────────────────────┘       │
│       ▼          ▼          ▼                                    │
│  ┌────────┐ ┌────────┐ ┌──────────────┐                        │
│  │market  │ │fund    │ │ valuation    │                         │
│  │service │ │service │ │ service      │                         │
│  └───┬────┘ └───┬────┘ └──────┬───────┘                        │
│      │          │             │                                  │
│   akshare    akshare     aiohttp                                │
│      │          │          (腾讯行情)                             │
│      ▼          ▼             ▼                                  │
│  东方财富API  东方财富API  qt.gtimg.cn                            │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────┐
│ SQLite       │
│ navpulse.db  │
│ Users        │
│ Holdings     │
│ Watchlist    │
│ FundTx       │
│ IntradayEst  │
│ CachedData   │
└──────────────┘
```

---

## 十、已知设计要点

1. **路由已拆分** — `routers/` 目录下 6 个路由模块（auth/portfolio/watchlist/market/fund/system）
2. **联接基金穿透**：若基金第一大重仓为 ETF 且权重 > 60%，自动递归获取 ETF 底层持仓
3. **环境变量驱动配置** — JWT 密钥、CORS 域名、ICP 备案号等均从 `.env` / 环境变量读取
4. **前端 Vue 3 组件化**：`static/js/` 下的 ES Module 组件，CDN 加载 Vue/Bootstrap/ECharts
5. **akshare 是同步库**，通过 `asyncio.to_thread` 或 `loop.run_in_executor` 在线程池中执行
6. **多策略估值**：ETF基金→场内实时价格；QDII基金→海外指数涨跌幅；普通股票/混合型→`Σ(weight_i × stock_change_pct_i) / Σ(weight_i)`重仓股加权；债券/货币→历史净值
7. **交易记录与持仓表自动同步**：每次增删交易记录后，`_sync_holding()` 从全部交易重算 Holding 表
8. **日内估值快照**：调度器每 3 分钟自动存储快照；用户请求 `/api/fund/{code}/intraday` 时也会存储。非交易时段若 DB 无数据，自动从重仓股分时数据回退计算完整日内走势
9. **休市估值显示**：非交易时段 `get_fund_detail` 和 `calculate_fund_estimate` 优先使用历史净值真实涨跌幅
10. **缓存策略**：cache-first + 骨架屏 + 后台静默刷新（silent-spinner）
11. **SQLite WAL 模式**：`database.py` 启用 WAL + busy_timeout=5000ms，提升多 worker 并发性能
12. **多主题色支持**：6 种主题（樱花粉/天空蓝/星空紫/薄荷绿/light（纯白风）/dark（纯黑风）），CSS 变量 + localStorage 持久化（含旧主题 ID 迁移：orange→light，teal→green）

### 2026-03-05：主题命名与风格调整（light / dark）

- 需求：将“高级浅色/高级黑色（深色）”统一命名为 `light` / `dark`，并改为纯白风与纯黑风。
- 修改文件：
   - `app/static/js/components/SettingsView.js`
   - `README.md`
   - `PROJECT_SUMMARY.md`
- 实现内容：
   1. 设置页主题名称改为 `light`、`dark`。
   2. `light` 主题调整为纯白背景 + 黑灰中性色文本体系。
   3. `dark` 主题调整为纯黑背景 + 灰白中性色文本体系。
   4. 主题应用逻辑中将 `light/dark` 的背景渐变分别固定为 `#FFFFFF` / `#000000`，移除原有彩色晕染。

### 2026-03-05：主题圆圈与 dark 反相配色微调

- 需求：
   1. `light` 主题预览圆圈改为白色（原来看起来偏黑）。
   2. `dark` 主题进一步调整为与 `light` 相反的黑底白字风格。
- 修改文件：
   - `app/static/js/components/SettingsView.js`
   - `app/templates/index.html`
   - `PROJECT_SUMMARY.md`
- 实现：
   1. `light.gradient` 调整为白色渐变（`#FFFFFF -> #F3F4F6`），并为白色圆圈增加浅灰边框。
   2. 选中 `light` 主题时勾选图标改为深色，避免白底白勾不可见。
   3. `dark` 主题主色与文本体系改为黑底白字反相方案（primary/secondary/text/border 全量调整）。
   4. 前端资源版本升级到 `app.js?v=20260305-12`。

### 2026-03-05：dark 背景改为 light 同款灰底 + 边框可见性增强

- 需求：
   1. `dark` 背景改为 `light` 中的灰色背景风格。
   2. 修复暗色下白色/浅色边框不明显的问题。
- 修改文件：
   - `app/static/js/components/SettingsView.js`
   - `app/templates/index.html`
   - `PROJECT_SUMMARY.md`
- 实现：
   1. `dark.bg` 与 `dark` 的页面背景渐变统一改为灰底（`#F3F4F6`）。
   2. `dark` 边框变量提亮（`border/borderHover`），提升按钮与卡片边界可见性。
   3. `dark` 遮罩透明度微调，避免整体过暗。
   4. 前端资源版本升级到 `app.js?v=20260305-13`。

### 2026-03-05：修复 light 下白字不可见（仅保留白色主题圆圈）

- 现象：light 主题下部分白字内容不可见。
- 根因：将 `light.gradient` 改为白色后，页面中依赖主题渐变且使用白字的区域（如设置页顶部信息卡）对比度不足。
- 修改文件：
   - `app/static/js/components/SettingsView.js`
   - `app/templates/index.html`
   - `PROJECT_SUMMARY.md`
- 修复：
   1. 恢复 `light.gradient` 为深色渐变，保证白字可读性。
   2. 新增 `swatchGradient`，主题选择圆圈仅使用 `swatchGradient`（light 为白色圆圈），不影响全局主题配色。
   3. 前端资源版本升级到 `app.js?v=20260305-14`。
13. **Swagger 文档仅 DEBUG 模式可见**：生产环境 `docs_url=None, redoc_url=None`
14. **NoCacheJS 中间件仅 DEBUG 模式启用**：生产环境正常缓存 JS 文件

---

## 十一、部署与多用户须知

> **本项目设计为多用户 Web 服务**，整个文件夹将部署到远程服务器，通过域名/IP 对外提供访问。

### 部署方式
- **生产环境**：宝塔面板 + Gunicorn + Uvicorn Worker → Nginx 反代
- **启动命令**：`gunicorn -c gunicorn_conf.py app.main:app`
- **绑定地址**：`127.0.0.1:8000`（Nginx 反代到 80/443 端口）
- **环境变量**：通过 `.env` 文件或宝塔面板配置（详见 `.env.example`）

### 多用户注意事项
1. **用户隔离**：每个用户有独立的持仓、自选、交易记录（通过 `user_id` FK）
2. **全局共享缓存**：行情数据（`GlobalCache`）、基金估值缓存对所有用户共享，减少重复请求
3. **主题偏好 + 数据缓存存储在浏览器端**（`localStorage`），各用户设备独立
4. **JWT 认证**：Token 有效期可配置（`TOKEN_EXPIRE_MINUTES`），存储在浏览器 `localStorage`
5. **SQLite WAL 模式**：适合中小规模用户量；高并发场景建议迁移 PostgreSQL
6. **SECRET_KEY**：生产环境 **必须通过 `JWT_SECRET_KEY` 环境变量设置固定密钥**
7. **开发修改时需考虑**：所有前端状态修改不能影响其他在线用户；缓存策略需考虑多用户并发读取

---

## 十二、最近修复记录

### 2026-03-04：OCR“开始识别”按钮点击无反应

- 现象：在 OCR 导入弹窗已选中截图后，点击“开始识别”无任何反应。
- 根因：`OcrImportModal` 模板里按钮禁用条件使用了 `imageFile`，但 `setup()` 返回对象未暴露该响应式变量，导致模板侧判断异常，按钮处于不可触发状态。
- 修复：在 `app/static/js/components/OcrImportModal.js` 的 `return` 中补充 `imageFile` 暴露给模板。
- 结果：选图后按钮可正常触发 `startParse()`，OCR 请求可发起到 `/api/portfolio/ocr-parse`。

### 2026-03-04：OCR 识别准确度优化（支付宝持仓截图）

- 现象：识别结果中出现基金名称污染（如把“金选指数基金”标签拼进基金名），并导致部分基金代码匹配失败。
- 根因：
   1) 基金名称分行合并规则过宽，误把标签行并入名称；
   2) 噪声识别依赖完全相等，无法处理带符号/变体文本；
   3) 代码匹配仅靠精确/包含，缺少归一化和模糊容错。
- 修复文件：`app/services/ocr_service.py`
   - 新增名称清洗与归一化：`_clean_fund_name` / `_normalize_text` / `_normalize_for_match`
   - 新增噪声判定：`_is_noise_text`（支持关键词和归一化匹配）
   - 强化分行合并：增加对齐约束并排除噪声行，避免把“金选指数基金”等标签拼接到基金名
   - 强化代码匹配：增加归一化精确匹配、去类别尾字母匹配（A/B/C/E/H）、`SequenceMatcher` 模糊匹配
- 本地验证：对截图同类样本名称（含“金选指数基金?”污染、截断名称）测试后，匹配准确度显著提升。

### 2026-03-04：OCR 二次优化（两行名称 + C/A 类 + 可手改名称金额）

- 现象：
   1) 部分基金名称在支付宝页面是两行，OCR 仅取到一行导致截断；
   2) 多个 C 类基金被匹配成 A 类基金；
   3) 用户希望可直接修改识别结果中的基金名和金额。
- 修复文件：
   - `app/services/ocr_service.py`
   - `app/static/js/components/OcrImportModal.js`
- 后端优化（ocr_service）：
   - 增加名称碎片判断 `_looks_like_name_fragment`，放宽并稳固两行名称合并规则（含“单独一行 C/A 尾字母”场景）
   - 增加份额类别识别 `_extract_share_class` 与优先级策略 `_share_class_priority`
   - 匹配时优先保留 OCR 中的份额类别；当名称截断但同根多份额并存时，优先选择 C 类，降低 C→A 误配
- 前端优化（OcrImportModal）：
   - 识别结果页支持点击编辑基金名（`name`）
   - 识别结果页支持点击编辑市值金额（`market_value`），失焦/回车自动校验并保存
   - 导入时直接使用用户修正后的金额进行批量导入
- 本地验证：
   - C/A 回归样例测试通过（含完整名、截断名、无尾缀名）
   - `py_compile app/services/ocr_service.py` 通过
   - 前端文件无语法诊断错误

### 2026-03-04：认证系统安全加固（适配开源/生产环境）

- 背景：准备开源到 GitHub，需强化认证安全性，符合开源项目标准与生产环境要求。
- 修复文件：
   - `app/services/auth_service.py`
   - `app/routers/auth.py`
   - `app/main.py`
   - `app/templates/register.html`
   - 新增 `SECURITY.md`
- 安全改进：
   1. **密码强度校验**：最少 8 位，必须包含大小写字母+数字（`validate_password_strength`）
   2. **登录速率限制**：5 分钟内最多 5 次失败尝试，基于 IP+用户名，内存 TTL 缓存实现
   3. **生产环境检查**：`ENVIRONMENT=production` 时强制要求配置 `JWT_SECRET_KEY`，否则启动失败
   4. **安全响应头中间件**：
      - `X-Content-Type-Options: nosniff`
      - `X-Frame-Options: DENY`
      - `X-XSS-Protection: 1; mode=block`
      - `Referrer-Policy: strict-origin-when-cross-origin`
      - `Permissions-Policy: geolocation=(), microphone=(), camera=()`
      - 生产环境自动添加 `Strict-Transport-Security` (HSTS)
   5. **模糊化认证错误**：
      - 注册时不提示"用户名已存在"（防止用户名枚举）
      - 登录时不区分"用户名不存在"和"密码错误"
   6. **前端密码提示**：注册页面更新密码要求说明与前端校验逻辑
- 文档与规范：
   - 创建 `SECURITY.md`：安全策略、最佳实践、漏洞报告流程、环境变量说明
   - 更新 `PROJECT_SUMMARY.md`：在项目定位部分补充安全特性概述
- 本地验证：
   - `get_errors` 检查通过，无语法/诊断错误
   - 前后端修改文件均编译/加载正常
### 2026-03-04：持有页添加网格/列表显示模式切换

- 需求：用户希望持有页支持两种显示方式：卡片网格（详细）和横向列表（简洁）。
- 修复文件：
   - `app/static/js/components/HoldingsView.js`
- 功能实现：
   1. **显示模式状态**：新增 `displayMode` ref（'grid' 或 'list'），默认 'grid'
   2. **本地存储持久化**：使用 `localStorage.getItem/setItem('holdings_display_mode')` 保存用户选择
   3. **切换按钮**：在排序栏添加网格图标（`bi-grid-3x2`）和列表图标（`bi-list`）两个切换按钮
   4. **条件渲染**：
      - **网格模式** (`displayMode === 'grid'`)：使用 `.funds-grid` + `.fund-item` 显示完整卡片，包含持有金额、当日盈亏、持有收益等详细指标
      - **列表模式** (`displayMode === 'list'`)：使用 `.watch-item` 样式显示简洁列表，仅显示基金名称、代码和涨跌幅
   5. **交互保持一致**：两种模式均支持点击查看详情、点击按钮删除持仓
- 用户体验：
   - 切换按钮的 active 状态与当前显示模式同步
   - 状态持久化到下次访问
   - 简洁模式适合快速浏览，详细模式适合深度分析
- 本地验证：
   - 无语法错误，服务器正常启动
   - 功能可通过 http://localhost:8000 访问测试
### 2026-03-04：隐私模式升级为三种模式选择，使用 *** 替代 blur 显示

- 背景：参考支付宝基金 APP 的"闭眼模式选择"功能，提供更灵活的隐私保护选项。
- 修复文件：
   - `app/static/js/store.js`
   - `app/static/js/components/HoldingsView.js`
   - `app/static/js/components/SettingsView.js`
   - `app/static/css/style.css`
- 功能升级：
   1. **隐私模式类型重构**：
      - 将 `store.blurred` (boolean) 改为 `store.privacyMode` (0/1/2/3)
      - **模式 0**：关闭隐私，显示所有数据
      - **模式 1**：仅隐藏【持有金额】
      - **模式 2**：隐藏【持有金额】【收益金额】
      - **模式 3**：隐藏【持有金额】【收益金额】【持有收益率】
   2. **显示方式改进**：
      - 移除所有 `filter: blur(6px)` 马赛克模糊效果
      - 使用 `***` 符号替代被隐藏的金额/收益数据
      - 新增工具函数 `shouldMask(type)` 和 `maskValue(value, type)` 处理条件显示
   3. **设置页 UI 重构**：
      - 将单一开关改为四张卡片式选择（类似主题选择UI）
      - 每张卡片显示模式标题、描述和选中状态图标
      - 支持点击卡片直接切换模式，Toast 提示当前模式名称
   4. **持有页交互优化**：
      - 点击眼睛图标在"关闭隐私"和"当前设置的模式"之间切换
      - 眼睛图标根据 `privacyMode > 0` 动态显示开/闭眼状态
      - 所有金额字段根据模式自动调用 `maskValue` 决定显示内容
   5. **本地存储持久化**：
      - 使用 `localStorage.getItem/setItem('navpulse_privacy_mode')` 保存用户选择
      - 页面刷新后自动恢复上次设置的隐私模式
- CSS 样式：
   - 新增 `.privacy-mode-card` 卡片样式（与主题卡片风格一致）
   - active 状态使用主题色边框和浅色背景
   - hover 状态轻微上移和边框/背景变化
- 数据分类：
   - **amount 类（持有金额）**：`summary.mv`, `f.market_value`
   - **profit 类（收益金额）**：`summary.dp`, `summary.hp`, `f.daily_profit`, `f.holding_profit`
   - **rate 类（收益率）**：`summary.dpr`, `summary.hpr`
- 本地验证：
   - 无语法/诊断错误
   - 三种模式切换流畅，*** 符号正确显示
   - 眼睛图标交互符合预期
### 2026-03-04：持仓总市值 Hero 卡片视觉优化（右侧小卡片重构）

- 背景：持仓页“总市值”卡片右侧在部分场景下出现浅白底衬托，导致“当日盈亏/当日收益率”观感突兀。
- 修改文件：
   - `app/static/css/style.css`
   - `PROJECT_SUMMARY.md`
- 优化内容：
   1. **右侧指标卡重构**：`hero-right` 由横排改为竖排，改为更紧凑的双小卡信息层级。
   2. **字号与密度优化**：`hero-stat` 数值字号下调（34 → 20），标签字号下调，信息更克制。
   3. **背景冲突修复**：`hero-card::after` 装饰由浅白光斑改为深色光斑并调整位置，消除右下角白底违和感。
   4. **移动端布局强化**：`max-width:640px` 下右侧指标改为 2 列网格，避免拥挤与遮挡。
- 本地验证：
   - CSS 诊断通过，无语法错误。

### 2026-03-04：持仓总市值卡片改为留白背景 + 单指标结构

- 背景：用户希望“总市值”卡片不再使用纯色背景，整体改为留白卡片；右侧只展示“当日盈亏”，并将“当日收益率”改为下方小字。
- 修改文件：
   - `app/static/js/components/HoldingsView.js`
   - `app/static/css/style.css`
   - `PROJECT_SUMMARY.md`
- 实现内容：
   1. **结构调整**：`hero-right` 由双卡片改为单卡片，`当日收益率` 作为 `stat-sub` 小字放在 `当日盈亏` 下方。
   2. **背景调整**：`hero-card` 从主题渐变改为 `var(--card-bg)` 白底留白卡片，边框和阴影与主界面卡片体系统一。
   3. **文字与层级**：标题/数值颜色改为深色体系，右侧小字收益率采用次级字号与次级色，视觉更接近持仓明细区风格。
   4. **响应式修正**：移动端 `hero-right` 取消双列网格逻辑，改为单卡片自适应布局。
- 本地验证：
   - `HoldingsView.js` 与 `style.css` 均无语法/诊断错误。

### 2026-03-04：基金详情“实时走势断点”修复（收盘后/弱网场景）

- 现象：收盘后基金详情页实时走势出现大量断点、短线段，曲线不连续。
- 根因：
   1. `fund.py` 中 `_backfill_intraday_gaps()` 已实现但未被调用，DB 分钟缺口长期不回补。
   2. `/api/fund/{code}/intraday` 在 DB 无数据时未真正执行“分时兜底并落库”，仅返回空或稀疏点。
   3. 调度快照为周期写入（非逐分钟），前端 `connectNulls=false` 下会将稀疏点渲染成断线。
- 修复文件：
   - `app/routers/fund.py`
   - `PROJECT_SUMMARY.md`
- 修复内容：
   1. **启用缺口回补**：接口读取 DB 后，实际调用 `_backfill_intraday_gaps()` 回补缺失分钟。
   2. **DB 空数据兜底**：DB 无数据时同步调用 `calculate_intraday_from_stocks()` 计算完整分时并 upsert 回写数据库。
   3. **连续化输出**：新增 `_densify_intraday_points()`，按交易分钟前向填充返回数据，减少收盘后断点。
   4. **时段控制**：交易时段只输出到当前分钟；非交易时段输出完整交易日分钟序列。
- 本地验证：
   - `fund.py` 语法/诊断通过，无错误。

### 2026-03-04：实时走势残余断点修复（前端 0 值过滤导致）

- 现象：后端分钟数据已连续（242 点），图上仍出现少量白色竖向断点。
- 根因：前端 `FundDetailModal.js` 中“孤立 0%”过滤逻辑将可疑点直接置为 `null`，ECharts 在 `connectNulls=false` 下会断线。
- 修改文件：
   - `app/static/js/components/FundDetailModal.js`
   - `PROJECT_SUMMARY.md`
- 修复内容：
   1. 将异常 0 值处理从“置空 `null`”改为“邻近值插值/前值回填”，不再产生断点。
   2. 保留异常点识别阈值（邻域绝对均值 > 0.5%）用于过滤噪声，但输出保证连续。
- 本地验证：
   - `FundDetailModal.js` 诊断通过，无语法错误。

### 2026-03-04：实时走势“绝对不断线”最终修复（前端双保险 + 缓存更新）

- 背景：部分终端仍出现断点，排查发现前端仍可能产生 `null` 点位，且旧静态资源缓存导致修复未生效。
- 修改文件：
   - `app/static/js/components/FundDetailModal.js`
   - `app/templates/index.html`
   - `PROJECT_SUMMARY.md`
- 修复内容：
   1. **前向填充原始序列**：`rawData` 改为按分钟 carry-forward，不再直接写入 `null`。
   2. **图表强制连线**：ECharts `connectNulls` 改为 `true`，即使边缘场景也不断线。
   3. **静态资源缓存击穿**：`index.html` 的 `app.js` 增加版本参数 `?v=20260304-3`，强制客户端拉取最新脚本。
- 本地验证：
   - `FundDetailModal.js` 与 `index.html` 诊断通过，无错误。

### 2026-03-04：修复“首次打开实时走势坍缩到左侧”问题

- 现象：收盘后首次打开某些基金详情页，实时走势会挤成左侧一团；切换到“业绩走势”再切回后恢复正常。
- 根因：图表在弹窗动画/布局尚未稳定时初始化，拿到错误容器尺寸（宽高过小）。
- 修改文件：
   - `app/static/js/components/FundDetailModal.js`
   - `app/templates/index.html`
   - `PROJECT_SUMMARY.md`
- 修复内容：
   1. 在 `shown.bs.modal` 事件中强制重绘/多次 `resize`，确保弹窗完全展开后图表重新布局。
   2. `renderIntradayChart` 新增容器尺寸守卫（宽<220 或 高<160 时延迟重试，最多 10 次）。
   3. 图表 setOption 后增加二次延迟 `resize`，提升移动端首次显示稳定性。
   4. `index.html` 静态资源版本升级到 `app.js?v=20260304-4`，避免旧脚本缓存。
- 本地验证：
   - `FundDetailModal.js` 与 `index.html` 诊断通过，无语法错误。

### 2026-03-04：修复联接基金“历史净值被伪装成分时线”问题（如 024195）

- 现象：部分基金（如 `024195`）在实时走势中出现长时间水平线/异常“坍缩”，且与分时行情不符。
- 根因：该基金估值策略退化为 `nav_history`（仅日级别涨跌，无分钟数据），旧逻辑仍将日级别值前向填充为“分时曲线”，造成误导。
- 修改文件：
   - `app/routers/fund.py`
   - `app/static/js/components/FundDetailModal.js`
   - `app/templates/index.html`
   - `PROJECT_SUMMARY.md`
- 修复内容：
   1. `intraday` 接口新增策略守卫：当 `estimation_method in {nav_history, history}` 时返回空点位并标记 `no_intraday=true`。
   2. 详情页实时 Tab 显示明确提示："当前仅有历史净值估值，暂无分钟级实时走势"。
   3. 静态资源版本升级到 `app.js?v=20260304-5`，确保客户端加载新逻辑。
- 本地验证：
   - `GET /api/fund/024195/intraday` 返回：`points=0, no_intraday=True, reason=nav_history_only`。

### 2026-03-04：联接基金智能穿透增强（名称匹配 + 历史净值相关性反推）

- 背景：部分联接基金在 akshare 持仓接口中返回空，导致无法识别底层 ETF，估值退化为 `nav_history`。
- 修改文件：
   - `app/services/fund_service.py`
   - `app/routers/fund.py`
   - `PROJECT_SUMMARY.md`
- 核心增强：
   1. **智能推断底层 ETF**：新增 `_infer_linked_etf_code()`，先做基金名称相似度匹配，再用历史净值日收益相关性校验候选。
   2. **严格候选约束**：底层候选仅允许场内 ETF 代码（`51/15/56/58/52/16` 开头），避免误匹配到联接份额（如 `024194`）。
   3. **无持仓时兜底穿透**：`_sync_fetch_portfolio()` 在原始持仓为空时自动尝试穿透推断 ETF 并拉取其持仓。
   4. **缓存自愈**：发现 DB 缓存中的 `penetrated_from` 不是场内 ETF 代码时自动触发刷新修正。
   5. **持久化策略改进**：即使仅拿到 `penetrated_from`（无持仓）也允许写入缓存，供后续估值链路使用。
   6. **intraday 守卫细化**：`fund.py` 中 `nav_history` 守卫仅在确实无持仓分钟源时生效；若已穿透拿到持仓，继续输出分钟走势。
- 结果（024195）：
   - `penetrated_from` 由错误的 `024194` 修正为场内 ETF `159206`。
   - `get_fund_portfolio('024195')` 返回 `holdings_count=15`。
   - `/api/fund/024195/intraday` 返回 `points=242`（09:30-15:00 完整分钟序列）。

### 2026-03-04：持有页收益率视觉一致性调整

- 需求：
   1. 去掉总市值卡片中当日盈亏下方“当日收益率”文字，仅保留百分比值。
   2. 持有页所有收益率需与收益金额一致，按正负显示红/绿。
- 修改文件：
   - `app/static/js/components/HoldingsView.js`
   - `app/templates/index.html`
   - `PROJECT_SUMMARY.md`
- 实现：
   1. Hero 卡片中删除“当日收益率”标签文本，仅显示 `summary.dpr` 百分比。
   2. 列表模式下 `holding_profit_rate`（`.hl-rate`）新增正负色 class 绑定：`cls(f.holding_profit_rate || 0)`。
   3. 前端资源版本更新至 `app.js?v=20260304-6`，确保客户端加载最新 UI 逻辑。

### 2026-03-04：自选页基金类型标签颜色与持有页统一

- 现象：自选页中“混合型-偏股”标签显示为灰色，而持有页同类型为紫色（`tag-mixed`）。
- 根因：自选页标签 class 同时命中 `tag-mixed` 与 `tag-other`，后者样式覆盖前者导致变灰。
- 修改文件：
   - `app/static/js/components/WatchlistView.js`
   - `app/templates/index.html`
   - `PROJECT_SUMMARY.md`
- 修复：
   1. 为自选页新增 `typeTagClass(f)`，逻辑与持有页完全一致。
   2. 模板中改为直接使用 `:class="typeTagClass(f)"`，避免多 class 冲突。
   3. 前端资源版本升级到 `app.js?v=20260304-7`，确保客户端立即生效。

### 2026-03-05：多策略基金估值引擎 — ETF场内实时 + QDII海外指数 + 自动分类

- 需求：像"养基宝""支付宝"等平台一样，根据基金类型自动选择最优估值算法。ETF直接取场内实时价格，QDII用海外指数估算，T+2等特殊基金标注结算延迟。
- 新增文件：
   - `app/services/fund_classifier.py` — 基金类型自动分类服务
   - `app/services/overseas_service.py` — 海外指数实时数据服务（新浪财经API）
- 修改文件（10处）：
   - `app/services/valuation_service.py` — 重构为多策略估值引擎（~1069行）
   - `app/services/fund_service.py` — 支持保存/读取 penetrated_from 字段
   - `app/models/__init__.py` — FundPortfolioCache 新增 penetrated_from 列
   - `app/database.py` — 新增 penetrated_from 列迁移
   - `app/routers/fund.py` — 返回 fund_type/estimation_method 等元数据
   - `app/routers/watchlist.py` — 返回 fund_type/fund_type_label/estimation_method
   - `app/static/css/style.css` — 基金类型徽章样式（7色分类）
   - `app/static/js/components/HoldingsView.js` — 持仓页基金类型徽章
   - `app/static/js/components/WatchlistView.js` — 自选页基金类型徽章
   - `app/static/js/components/FundDetailModal.js` — 详情弹窗估值来源标注
- 核心实现：
   1. **基金分类器**：通过 `akshare.fund_name_em()` 的 `基金类型` 字段 + 基金名称关键词匹配，自动识别 ETF/QDII/股票/混合/债券/货币 类型
   2. **ETF场内估值**：腾讯行情API直取场内ETF实时涨跌幅（如 sh510300, sz159915），联接基金通过 penetrated_from 穿透到底层ETF
   3. **QDII海外指数**：新浪财经API获取全球8大指数实时数据（纳斯达克/标普500/道琼斯/恒生/日经225/DAX/富时100/CAC40）
   4. **策略路由**：valuation_service 根据分类结果自动选择 etf_realtime → overseas_index → weighted_holdings → nav_history
   5. **前端展示**：基金类型彩色徽章（ETF蓝/QDII琥珀/股票红/混合紫/债券绿/货币靛/其他灰）+ 估值来源标注
- 验证结果（8只基金分类测试通过）：
   - 005963(宝盈人工智能) → stock/weighted_holdings
   - 510300(沪深300ETF) → etf/etf_realtime
   - 159915(创业板ETF) → etf/etf_realtime
   - 006479(广发纳指100ETF联接QDII) → qdii_nasdaq/overseas_index
   - 000614(华安德国DAX联接QDII) → qdii_dax/overseas_index
   - 486001(工银全球股票QDII) → qdii_sp500/overseas_index
   - 024195(永赢卫星通信ETF联接) → etf_linked/etf_linked
   - 320007(诺安成长混合) → mixed/weighted_holdings

### 2026-03-05：交易面板交互优化（减仓按份额 + 日期提示）

- 需求：
   1. 加仓/减仓时增加日期说明，提示默认日期与 15:00 前后确认规则。
   2. 减仓操作改为按“份额”输入，不再按金额输入。
   3. 提供减仓快捷选项：全部、1/2、1/3、1/4。
- 修改文件：
   - `app/static/js/components/FundDetailModal.js`
   - `app/static/css/style.css`
   - `app/templates/index.html`
   - `PROJECT_SUMMARY.md`
- 实现内容：
   1. 交易表单新增 `shares` 字段与份额输入过滤（支持最多 4 位小数）。
   2. 减仓分支改为份额校验（>0 且不超过当前持有份额），提交时携带 `shares`。
   3. 增加减仓快捷按钮（全部/1/2/1/3/1/4），一键填充份额。
   4. 日期输入下方新增提示：默认当天，交易日 15:00 前通常按当日确认，15:00 后多为下一交易日。
   5. 前端资源版本升级至 `app.js?v=20260305-8`，避免旧缓存导致样式/交互不生效。

### 2026-03-05：持有页“当日盈亏”文案统一为“当日收益”

- 需求：
   1. 持有页将“当日盈亏”统一改为“当日收益”。
   2. Hero 卡片下方收益率颜色需跟随“当日收益”红/绿，而不是按收益率自身正负独立着色。
- 修改文件：
   - `app/static/js/components/HoldingsView.js`
   - `app/templates/index.html`
   - `PROJECT_SUMMARY.md`
- 实现内容：
   1. Hero 区域标签从“当日盈亏”改为“当日收益”。
   2. 网格卡片中的“当日盈亏”标签同步改为“当日收益”。
   3. Hero 下方当日收益率百分比的颜色 class 改为基于 `summary.dp`（当日收益金额）判定红绿，保证上下颜色一致。
   4. 前端资源版本升级至 `app.js?v=20260305-9`。

### 2026-03-05：修复持有页 Hero 收益率仍显示黑色

- 现象：总市值卡片右侧“当日收益”下方百分比在部分主题下仍显示黑色。
- 根因：`.hero-stat .stat-sub-value` 缺少 `clr-up/clr-down` 颜色覆盖规则，继承了父级默认文本色。
- 修改文件：
   - `app/static/css/style.css`
   - `app/templates/index.html`
   - `PROJECT_SUMMARY.md`
- 修复：
   1. 新增 `.hero-stat .stat-sub-value.clr-up/.clr-down` 规则，确保收益率按红绿显示。
   2. 前端资源版本升级至 `app.js?v=20260305-10`，避免缓存导致旧样式继续生效。