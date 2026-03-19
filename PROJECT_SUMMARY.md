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
8. **设置中心** — 多主题色切换（6色：Day/Night/Pink/Blue/Purple/Green）、隐私模式、缓存管理、系统信息

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

## 十、核心设计与架构规范

> 本章节浓缩了项目迭代全生命周期中的全部架构精髓，帮助以后快速掌握核心策略。

1. **模块化与组件化架构 (Modular & Component-based Architecture)**
   后端路由 (`routers/`) 和业务逻辑 (`services/`) 彻底解耦；前端采用 Vue 3 CDN (ESM) + Bootstrap 组件化，摒弃繁杂的构建工具链以实现极简部署。
2. **多层异步与并发控制 (Multi-level Async & Concurrency)**
   FastAPI 提供全量异步接口，阻塞型依赖（如 akshare）全部放入线程池 (`loop.run_in_executor`)。配合 SQLite WAL 模式极大地提升多 Worker 读写并发性能。
3. **分级缓存与后台静默刷新机制 (Multi-tier Cache & Silent Background Refresh)**
   拥有四级缓存池 (`GlobalCache` 内存 -> 行情/估值 TTLCache -> SQLite 持久化层 -> 前端 localStorage)。采用 Cache-First + 骨架屏 + 后台调度器自动接管数据定向刷新，实现页面“秒开”与无阻塞前端体验。
4. **智能多策略估值引擎 (Smart Multi-Strategy Valuation Engine)**
   系统内置基金类型分类器，根据资产类别自动分发最优模型：场内 ETF 及联接基金采用实时穿透估算、QDII 使用海外各大指数联动估算、股票/混合采用重仓加权、债券/货币退化使用历史净值。
5. **智能 OCR 识别与容错导入 (Smart OCR with Fault Tolerance)**
   集成 OnnxRuntime 进行截图持仓导入，独创先进的名称清洗、多行合并、噪声过滤与 C/A 份额推断机制，同时支持用户前端可视化二次编辑修正，极大增强稳定性。
6. **数据连续断点修补与日内分时快照 (Data Smoothing & Intraday Gap Filling)**
   支持异步补全分钟缺口、历史净值零值修复。非交易时间自动从持仓股分时回推曲线并落库快照；前端图表强制连接空值，确保任意复杂场景下趋势线“绝不断连”。
7. **交易账簿与实时仓位同步联动 (Ledger & Portfolio Synchronization)**
   由 `FundTransaction` 主导加权平均成本逻辑。任何增减操作引发自动重算 `Holding` 表与收益大盘，保持数据自洽；夜间官方净值发布后自动刷新验证相关估值与缓存。
8. **UI 进阶规范：多主题适配与留白交互 (Advanced UI: Multi-Theme & White-Space Design)**
   提供 Day/Night 等 6 套高定主题色系，夜间模式采用“高级灰底白字”替代刺眼纯黑。全面优化弹窗适配、卡片网格/列表切换交互，严格遵循 CSS 变量语义化，保证极高视觉一致度与留白率。
9. **分级隐私脱敏体系 (Granular Privacy Modes)**
   内置细粒度多级隐私控制（0级全显，1级隐持仓，2级隐总收益，3级隐收益率），配置由本地 `localStorage` 记忆持久化，统一切换为 `***` 脱敏，完全剔除耗性能且丑陋的模糊滤镜。
10. **全链路项目安全与工程规范化 (Full-Chain Security & Engineering Specs)**
    满足严苛开源标准：生产环境强制校验 `JWT_SECRET_KEY`，实现强密码规则、登录频率阻断防爆破、防止账号枚举错误模糊化，附带 HSTS、CSP 安全防线。代码工程层面集成 `.editorconfig`/`pyproject.toml` 自动化检测与环境变参驱动，Swagger/文档页仅非生产环境可见。

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

