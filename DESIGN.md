# Nexus Media Chrome Server - 架构设计文档

## 概述

基于 Chrome 自动化的挑战绕过与 Cookie 提取服务器。支持多种 WAF/CDN 防护类型（Cloudflare、五秒盾、雷池、通用型），支持可自定义的浏览器指纹以降低被标记概率，支持 Session 级别隔离，提供浏览器模式与 HTTP 模式协同工作的能力。

## 核心概念

### Session（会话）

每个 Session 是独立的隔离单元，拥有：
- **独立的标签页池**：Session A 的标签页与 Session B 完全隔离
- **独立的 Cookie 存储**：不同 Session 的 Cookie 互不可见
- **独立的指纹配置**：每个 Session 可指定不同的指纹 profile
- **独立的挑战状态**：一个 Session 内的挑战解除不影响其他 Session

Session 之间共享同一个 Chrome 进程，通过 DrissionPage 的标签页管理实现逻辑隔离。

```
┌──────────────────────────────────────────────────────────┐
│                     Chrome 进程                           │
│  ┌───────────────────────┐  ┌───────────────────────┐    │
│  │      Session A        │  │      Session B        │    │
│  │  ├─ CookieStore (独立)│  │  ├─ CookieStore (独立)│    │
│  │  ├─ 标签页池  (独立)  │  │  ├─ 标签页池  (独立)  │    │
│  │  ├─ 指纹配置  (独立)  │  │  ├─ 指纹配置  (独立)  │    │
│  │  └─ 挑战状态  (独立)  │  │  └─ 挑战状态  (独立)  │    │
│  └───────────────────────┘  └───────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### 指纹（Fingerprint）

浏览器指纹是一系列可被网站检测的属性组合，用于识别和追踪访客。通过 JS 注入覆写这些属性，可降低被风控系统标记的概率：

- `navigator.webdriver` → false（掩藏自动化特征）
- `navigator.plugins` → 真实插件列表（Chrome PDF Viewer 等）
- `navigator.languages` → zh-CN,en-US,en（中英文混合）
- Canvas 指纹 → 在 `getImageData` / `toDataURL` 中注入微小随机噪声，每次渲染结果略有差异
- WebGL 指纹 → 伪装 `UNMASKED_VENDOR_WEBGL` 为 `Intel Inc.`，`UNMASKED_RENDERER_WEBGL` 为 `Intel Iris OpenGL Engine`
- AudioContext 指纹 → 在 `getChannelData` 中注入 `±1e-9` 量级随机噪声
- Screen 分辨率 → 伪装为 1920×1080，24-bit 色深
- `chrome.runtime` → 设为 undefined（移除自动化标识）
- `navigator.permissions` → 正常化权限查询行为

**预置指纹配置文件：**

| profile | 名称 | 说明 |
|---------|------|------|
| `default` | 基础反检测 | 仅注入点击坐标随机化 JS，不做 Canvas/WebGL 伪装 |
| `stealth` | 完整指纹伪装（推荐） | 注入全部反检测 JS：点击随机化 + 属性覆写 + Canvas 噪声 + WebGL 伪装 + Audio 噪声 |
| `paranoid` | 最大程度隐藏 | stealth 全部能力 + `--disable-webgl` 启动参数 |

### JA3 模拟

JA3 是 TLS 握手指纹，通过分析 ClientHello 中的加密套件、扩展列表及其顺序来识别客户端。无头浏览器通常有固定的 TLS 参数组合，容易被识别。

通过 Chromium 启动参数实现 JA3 模拟：
- `--enable-features=NetworkService,NetworkServiceInProcess,LoadCryptoTokenExtension,PermuteTLSExtensions`
  - `PermuteTLSExtensions` 随机化 TLS 扩展顺序，产生与常规 Chrome 一致的 JA3 指纹
- `--disable-features=FlashDeprecationWarning,EnablePasswordsAccountStorage`
- 禁用 metrics/reporting 减少统计特征

### Cookie 共享机制

1. 浏览器模式下，Session 内某个标签页成功加载目标网站后，自动提取该域名的所有 Cookie 存入 Session 的 CookieStore
2. HTTP 模式下，`HttpClient` 在发起请求前从指定 Session 的 CookieStore 按域名查找对应 Cookie 并注入请求头
3. 不同 Session 的 CookieStore 物理隔离，Session A 无法读取 Session B 的 Cookie

## 架构图

```
┌──────────────────────────────────────────────────────────────┐
│                     FastAPI 服务器                             │
│                      (src/main.py)                             │
├──────────────────────────────────────────────────────────────┤
│  API 层 (src/api/)                                            │
│  POST /sessions/                         创建会话              │
│  GET  /sessions/                         列出会话              │
│  DELETE /sessions/{id}                   删除会话              │
│  POST /sessions/{id}/challenge/solve     绕过挑战（返回HTML+Cookie）│
│  POST /sessions/{id}/tabs/               创建标签页            │
│  GET  /sessions/{id}/tabs/               列出标签页            │
│  GET  /sessions/{id}/tabs/{n}/html       获取HTML              │
│  GET  /sessions/{id}/tabs/{n}/cookie     提取Cookie            │
│  GET  /sessions/{id}/tabs/{n}/iframe     iframe内容           │
│  POST /sessions/{id}/tabs/click/         点击元素              │
│  POST /sessions/{id}/tabs/{n}/refresh    刷新标签页            │
│  DELETE /sessions/{id}/tabs/{n}          关闭标签页            │
│  DELETE /sessions/{id}/tabs/             关闭全部标签页        │
│  POST /sessions/{id}/http/fetch          HTTP请求（注入会话Cookie）│
├──────────────────────────────────────────────────────────────┤
│  核心层 (src/core/)                                           │
│  ┌─────────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ SessionManager  │  │ CookieStore  │  │FingerprintManager│  │
│  │ 会话创建/销毁   │  │ 域名→Cookie  │  │ 指纹配置+JS注入   │  │
│  │ 标签页池管理    │  │ 共享但隔离    │  │ 3种预置profile   │  │
│  └─────────────────┘  └──────────────┘  └─────────────────┘  │
├──────────────────────────────────────────────────────────────┤
│  挑战层 (src/challenge/)                                      │
│  ┌────────────────────────────────────────────────────────┐   │
│  │           ChallengeOrchestrator（编排器）                │   │
│  │  检测(detect) → 识别(identify) → 解析(resolve) → 验证(verify) │
│  └────────────────────────────────────────────────────────┘   │
│  ┌──────────────┐ ┌─────────────────┐ ┌─────────┐ ┌────────┐  │
│  │ Cloudflare   │ │FiveSecondShield │ │ Leichi  │ │Generic │  │
│  │ 标准+Turnstile│ │ 五秒盾           │ │ 雷池    │ │通用WAF │  │
│  └──────────────┘ └─────────────────┘ └─────────┘ └────────┘  │
├──────────────────────────────────────────────────────────────┤
│  HTTP 层 (src/http/)                                          │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  HttpClient (基于 httpx)                                │   │
│  │  - 从指定 Session 的 CookieStore 按域名注入 Cookie       │   │
│  │  - 自定义 TLS / headers / timeout / redirect            │   │
│  │  - 遇到挑战可回退到浏览器模式                             │   │
│  └────────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────┤
│  配置层 (src/config/)                                         │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  settings.py - 常量、JS脚本、挑战选择器、指纹配置        │   │
│  └────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

## 核心组件详细说明

### 1. CookieStore（`src/core/cookie_store.py`）

线程安全的 Cookie 存储器，以域名为键。每个 Session 持有独立实例。

```
CookieStore
├── store(domain, cookies)       # 从浏览器存储 Cookie（list of dict）
├── get(domain) → list[dict]     # 获取 Cookie 列表
├── as_header(domain) → str      # 格式化为 HTTP Cookie 头
├── as_dict(domain) → dict       # 格式化为键值对
├── list_domains() → list[str]   # 列出所有已存储域名
├── clear(domain)                # 清除指定域名
└── clear_all()                  # 清除全部
```

Cookie 存储格式（与 DrissionPage 一致）：
```python
[
    {"name": "session_id", "value": "abc123", "domain": ".example.com", "path": "/"},
    {"name": "csrf_token", "value": "xyz789", "domain": ".example.com", "path": "/"},
]
```

### 2. FingerprintManager（`src/core/fingerprint.py`）

管理浏览器指纹配置，支持三种预置 profile 和自定义扩展。

```
FingerprintManager
├── __init__(profile_name)              # 加载指定 profile
├── get_init_js() → str                 # 获取初始化 JS 脚本
├── get_browser_args() → list[str]      # 获取 Chromium 启动参数
└── PROFILES (class var)                # 预置 profile 注册表
```

JS 注入时机：在 `create_tab` 时通过 DrissionPage 的 `tab.add_init_js()` 注入，确保在页面 JS 执行之前生效。

### 3. Session + SessionManager（`src/core/session.py`）

```
SessionManager
├── create_session(name, fingerprint_profile) → Session
├── get_session(session_id) → Session
├── list_sessions() → list[Session]
├── delete_session(session_id)
└── sessions: dict[str, Session]

Session
├── id: str
├── tabs_pool: dict[str, MixTab]
├── cookie_store: CookieStore
├── fingerprint: FingerprintManager
├── create_tab(url, tab_name, ...)      # 创建标签页（注入指纹JS）
├── close_tab(tab_name)
├── get_tab_html(tab_name) → str        # 获取HTML（自动过挑战）
├── get_tab_cookie(tab_name) → str      # 提取Cookie
├── get_tab_iframe(tab_name) → str      # 获取iframe
├── click_element(tab_name, selector)   # 点击元素
├── challenge_solve(tab_name)           # 解决当前页面挑战
└── get_cookies_for_domain(domain)      # 获取指定域名的Cookie
```

### 4. ChallengeOrchestrator（`src/challenge/resolver.py`）

挑战处理的中央调度器，采用策略模式。

**四阶段流水线：**

```
detect(html_text) → challenge_type | None
  │
  ├─ 检测标题是否命中 CHALLENGE_TITLES
  ├─ 检测 HTML 是否命中各类选择器
  └─ 返回挑战类型：cloudflare / cloudflare_box / five_second_shield / leichi / generic / none

identify(html_text) → challenge_type
  │
  └─ 进一步细粒度识别（如区分 Cloudflare 标准挑战 vs Turnstile 盒子挑战）

resolve(tab, challenge_type) → bool
  │
  ├─ cloudflare       → CloudflareResolver
  ├─ cloudflare_box   → CloudflareResolver (turnstile)
  ├─ five_second_shld → FiveSecondShieldResolver
  ├─ leichi           → LeichiResolver
  └─ generic          → GenericResolver

verify(tab) → bool
  │
  └─ 确认页面不再是挑战状态，内容可正常访问
```

### 5. CloudflareResolver（`src/challenge/cloudflare.py`）

支持两种 Cloudflare 挑战类型：

**标准挑战（"Just a moment..."）：**
1. 等待 5 秒让页面 JS 执行
2. 重新检查页面状态
3. 通过 shadow DOM → iframe → shadow DOM 路径找到验证按钮
4. 点击验证按钮
5. 轮询等待 `#success` div 可见
6. 验证通过后提取 Cookie 存入 CookieStore

**Turnstile 盒子挑战：**
1. 检测 `input[name="cf-turnstile-response"]`
2. 通过 shadow DOM 路径定位验证复选框
3. 点击并等待挑战完成
4. 同上验证流程

### 6. FiveSecondShieldResolver（`src/challenge/five_second_shield.py`）

五秒盾（常见于中国 CDN，如又拍云、阿里云 CDN）：

1. 检测倒计时元素（`#sec`、`.loading-countdown` 等）
2. 等待页面 JS 倒计时完成（通常 5 秒）
3. 等待页面自动刷新或重定向
4. 验证 Cookie（`__cdnuid`、`__tlog` 等）已设置

### 7. LeichiResolver（`src/challenge/leichi.py`）

雷池（SafeLine）WAF：

1. 检测雷池特征元素（`#safeline-block`、`meta[name="safeline"]` 等）
2. 等待 JS 验证执行完毕
3. 获取 `__safeline_*` 系列 Cookie
4. 重新加载页面验证通过

### 8. GenericResolver（`src/challenge/generic.py`）

通用 WAF 处理：

1. 检测通用挑战标识
2. 等待一定时间让 JS 执行
3. 尝试查找并点击通用验证元素（如 reCAPTCHA 容器）
4. 超时后返回状态

### 9. HttpClient（`src/http/client.py`）

基于 httpx 的异步 HTTP 客户端，与 Session 的 CookieStore 集成：

```
HttpClient(session)
├── get(url, headers, follow_redirects, timeout) → Response
├── post(url, data, headers, ...) → Response
├── fetch(request: HttpFetchRequest) → HttpResponse
└── _inject_cookies(headers, url) → headers  # 从 CookieStore 注入 Cookie
```

关键能力：
- 请求前自动从 Session 的 CookieStore 按域名注入 Cookie
- 支持自定义 headers 合并
- 支持重定向策略
- 超时控制

## 数据流

### Session 间隔离示例

```
客户端 A:
  POST /sessions  → 创建 session-aaa (profile=stealth)
  POST /sessions/aaa/navigate {"url": "https://siteA.com"}
      → Cookie 存入 session-aaa.CookieStore
  POST /sessions/aaa/fetch {"url": "https://siteA.com/api"}
      → 自动注入 session-aaa 的 Cookie

客户端 B:
  POST /sessions  → 创建 session-bbb (profile=paranoid)
  POST /sessions/bbb/navigate {"url": "https://siteB.com"}
      → Cookie 存入 session-bbb.CookieStore
  POST /sessions/bbb/fetch {"url": "https://siteB.com/api"}
      → 仅注入 session-bbb 的 Cookie，完全独立
```

### navigate — 浏览器导航 + 自动过挑战

```
POST /sessions/{id}/navigate {"url": "https://protected.com"}
  │
  ├─ SessionManager.get_session(id)
  ├─ session.create_tab(url)                              # 内部创建标签页
  │   ├─ tab.add_init_js(fingerprint_js)                  # 注入指纹JS
  │   ├─ tab.get(url)                                     # 导航
  │   └─ tab.wait.ele_displayed('tag:body', timeout=15)   # 等待加载
  ├─ ChallengeOrchestrator.resolve(tab)
  │   ├─ detect(tab.html) → cloudflare
  │   ├─ CloudflareResolver.resolve(tab)
  │   │   ├─ 定位 iframe → shadow_root
  │   │   ├─ 点击验证按钮
  │   │   └─ 等待 success div visible
  │   └─ verify(tab) → True
  ├─ cookies = tab.cookies()
  ├─ session.cookie_store.store(domain, cookies)          # Cookie 自动入库
  └─ 返回 {"code":0, "data":{"html":"...", "cookies":{...}, "challenge":{...}}}
```

### fetch — HTTP 模式复用 Cookie

```
POST /sessions/{id}/fetch {"url": "https://example.com/api/data"}
  │
  ├─ SessionManager.get_session(id)
  ├─ domain = urlparse(url).netloc
  ├─ headers["Cookie"] = session.cookie_store.as_header(domain)
  ├─ response = httpx.get(url, headers=headers, ...)
  └─ 返回 {"code":0, "data":{"status_code":200, "body":"...", "cookies_used":[...]}}
```

## API 设计

### 设计理念

- **Session 为核心**：所有操作围绕 Session 展开，Session 内部自动管理标签页，调用方不需要关心标签页细节
- **自动过挑战**：`navigate` 接口自动检测并解决 Challenge，无需单独调用 challenge 接口
- **Cookie 自动存储**：navigate 成功后，Cookie 自动存入 Session 的 CookieStore，后续 HTTP 请求直接复用
- **浏览器 vs HTTP 分离**：`navigate`（浏览器模式，可过挑战）和 `fetch`（HTTP 模式，快但不过挑战）各司其职
- **扁平路径**：避免深层嵌套，路径不超过三级

### 端点总览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | API 信息 |
| `GET` | `/status` | 服务状态 |
| `POST` | `/sessions` | 创建会话 |
| `GET` | `/sessions` | 列出会话 |
| `DELETE` | `/sessions/{id}` | 销毁会话 |
| `POST` | `/sessions/{id}/navigate` | 浏览器导航（自动过挑战、提取 Cookie） |
| `GET` | `/sessions/{id}/html` | 获取当前页面 HTML |
| `POST` | `/sessions/{id}/click` | 在当前页面点击元素 |
| `POST` | `/sessions/{id}/input` | 在当前页面输入文本 |
| `POST` | `/sessions/{id}/execute` | 执行自定义 JavaScript |
| `GET` | `/sessions/{id}/cookies` | 获取已存储的 Cookie |
| `POST` | `/sessions/{id}/fetch` | 纯 HTTP 请求（自动注入该 Session 的 Cookie） |

### 典型工作流

```
                     ┌── 创建 Session（指定指纹）──┐
                     │                            │
              ┌──────▼──────┐              ┌──────▼──────┐
              │  navigate   │              │  navigate   │
              │  (浏览器模式) │              │  (浏览器模式) │
              │  自动过挑战  │              │  自动过挑战  │
              │  Cookie 入库 │              │  Cookie 入库 │
              └──────┬──────┘              └──────┬──────┘
                     │                            │
              ┌──────▼──────┐              ┌──────▼──────┐
              │   fetch     │              │   fetch     │
              │  (HTTP模式) │              │  (HTTP模式) │
              │  自动带Cookie│              │  自动带Cookie│
              └─────────────┘              └─────────────┘
```

### 请求/响应 Schema

#### 创建会话

```json
// POST /sessions
{
    "session_id": "my-session",
    "fingerprint_profile": "stealth",
    "user_agent": "Mozilla/5.0 ..."
}

// Response 200
{
    "code": 0,
    "session_id": "my-session",
    "fingerprint": "stealth"
}
```

#### 浏览器导航（核心接口）

```json
// POST /sessions/{id}/navigate
{
    "url": "https://protected-site.com",
    "cookie": "key=value",
    "referer": "https://google.com",
    "timeout": 30
}

// Response 200 — 成功（自动过挑战）
{
    "code": 0,
    "data": {
        "url": "https://protected-site.com",
        "title": "页面标题",
        "html": "<!DOCTYPE html>...",
        "cookies": {
            "cf_clearance": "abc123",
            "session": "xyz789"
        },
        "cookie_header": "cf_clearance=abc123; session=xyz789",
        "challenge": {
            "detected": true,
            "type": "cloudflare",
            "solved": true,
            "duration_ms": 8234
        }
    }
}

// Response 200 — 挑战超时未解决
{
    "code": -1,
    "message": "挑战未能在 30s 内解决: cloudflare",
    "data": {
        "challenge": {
            "detected": true,
            "type": "cloudflare",
            "solved": false
        }
    }
}
```

#### 获取当前 HTML

```json
// GET /sessions/{id}/html

// Response 200
{
    "code": 0,
    "data": {
        "url": "https://protected-site.com/page",
        "html": "<!DOCTYPE html>..."
    }
}
```

#### 点击/输入/执行

```json
// POST /sessions/{id}/click
{ "selector": "#submit-btn" }
// → {"code": 0}

// POST /sessions/{id}/input
{ "selector": "#search", "text": "keyword" }
// → {"code": 0}

// POST /sessions/{id}/execute
{ "script": "return document.title" }
// → {"code": 0, "data": { "result": "页面标题" } }
```

#### 获取 Cookie

```json
// GET /sessions/{id}/cookies
// GET /sessions/{id}/cookies?domain=example.com

// Response 200
{
    "code": 0,
    "data": {
        "example.com": {
            "cf_clearance": "abc123",
            "session": "xyz789"
        }
    }
}
```

#### HTTP 请求

```json
// POST /sessions/{id}/fetch
{
    "url": "https://example.com/api/data",
    "method": "GET",
    "headers": { "Accept": "application/json" },
    "data": null,
    "timeout": 30
}

// Response 200
{
    "code": 0,
    "data": {
        "url": "https://example.com/api/data",
        "status_code": 200,
        "headers": { "content-type": "application/json" },
        "body": "{...}",
        "cookies_used": ["cf_clearance", "session"]
    }
}
```

## 使用示例

### 完整流程

```bash
# 1. 创建会话
curl -X POST http://localhost:9850/sessions \
  -H "Content-Type: application/json" \
  -d '{"session_id": "work", "fingerprint_profile": "stealth"}'

# 2. 浏览器导航（自动过 Cloudflare 挑战，Cookie 自动入库）
curl -X POST http://localhost:9850/sessions/work/navigate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://protected-site.com", "timeout": 60}'

# 3. 后续请求直接用 HTTP 模式（速度飞快，自动带 Cookie）
curl -X POST http://localhost:9850/sessions/work/fetch \
  -H "Content-Type: application/json" \
  -d '{"url": "https://protected-site.com/api/search?q=test"}'
```

### 多 Session 并发（Cookie 隔离）

```bash
# Session A: stealth 指纹 → siteA
curl -X POST http://localhost:9850/sessions -d '{"session_id":"sa","fingerprint_profile":"stealth"}'
curl -X POST http://localhost:9850/sessions/sa/navigate -d '{"url":"https://siteA.com"}'
curl -X POST http://localhost:9850/sessions/sa/fetch -d '{"url":"https://siteA.com/api"}'

# Session B: paranoid 指纹 → siteB （完全隔离）
curl -X POST http://localhost:9850/sessions -d '{"session_id":"sb","fingerprint_profile":"paranoid"}'
curl -X POST http://localhost:9850/sessions/sb/navigate -d '{"url":"https://siteB.com"}'
curl -X POST http://localhost:9850/sessions/sb/fetch -d '{"url":"https://siteB.com/api"}'
```

### 需要交互的页面

```bash
# 导航到登录页
curl -X POST http://localhost:9850/sessions/work/navigate -d '{"url":"https://site.com/login"}'

# 输入用户名密码
curl -X POST http://localhost:9850/sessions/work/input -d '{"selector":"#username","text":"admin"}'
curl -X POST http://localhost:9850/sessions/work/input -d '{"selector":"#password","text":"pass123"}'

# 点击登录
curl -X POST http://localhost:9850/sessions/work/click -d '{"selector":"#login-btn"}'

# 获取登录后的 HTML（含 Cookie）
curl http://localhost:9850/sessions/work/html

# 提取 Cookie 给 HTTP 模式用
curl http://localhost:9850/sessions/work/cookies
```

## 项目目录结构

```
src/
├── main.py                       # FastAPI 应用入口（不变）
├── config/
│   ├── __init__.py
│   └── settings.py               # 配置常量（增量扩展）
├── core/
│   ├── __init__.py
│   ├── browser_manager.py        # 浏览器管理（增加 iframe/cookie 方法）
│   ├── cookie_store.py           # Cookie 共享存储（新增）
│   ├── fingerprint.py            # 指纹管理器（新增）
│   └── session.py                # Session + SessionManager（新增）
├── challenge/
│   ├── __init__.py               # 公开导出（新增）
│   ├── base.py                   # 抽象 ChallengeResolver（新增）
│   ├── resolver.py               # ChallengeOrchestrator（新增）
│   ├── cloudflare.py             # Cloudflare 解析器（从 utils 迁移+扩展）
│   ├── five_second_shield.py     # 五秒盾解析器（新增）
│   ├── leichi.py                 # 雷池解析器（新增）
│   └── generic.py                # 通用 WAF 解析器（新增）
├── http/
│   ├── __init__.py               # 公开导出（新增）
│   └── client.py                 # HTTP 客户端（新增）
├── api/
│   ├── __init__.py
│   ├── schemas.py                # 请求/响应模型（增量扩展）
│   └── routes.py                 # API 路由（增量扩展）
└── utils/
    ├── __init__.py
    └── challenge_utils.py        # 原有挑战工具（不变，challenge/ 包引用它）
tests/
├── __init__.py
├── test_cookie_store.py
├── test_fingerprint.py
├── test_challenge.py
├── test_session.py
└── test_api.py
```

## 技术选型

| 组件 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI | 异步支持，自动 OpenAPI 文档 |
| 浏览器控制 | DrissionPage | CDP 协议控制 Chromium，支持 shadow DOM |
| HTTP 客户端 | httpx | 异步支持，连接池，TLS 配置 |
| UA 生成 | fake-useragent | 随机 User-Agent 生成 |
| 日志 | loguru | 结构化日志 |
| 数据模型 | Pydantic v2 | 请求验证和序列化 |
| 测试 | pytest | 异步测试支持 |

## 配置

环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_HOST` | `0.0.0.0` | 服务器监听地址 |
| `APP_PORT` | `9850` | 服务器端口 |
| `CHROME_PATH` | `/usr/bin/chromium-browser` | Chromium 路径 |
| `USER_DATA_PATH` | `/var/lib/chromium/user_data` | 用户数据目录 |
| `CHALLENGE_TIMEOUT` | `30` | 挑战等待超时（秒） |
| `CHALLENGE_RETRY_COUNT` | `3` | 挑战重试次数 |
| `HTTP_CLIENT_TIMEOUT` | `30` | HTTP 客户端超时（秒） |
| `HTTP_MAX_REDIRECTS` | `10` | HTTP 最大重定向次数 |
