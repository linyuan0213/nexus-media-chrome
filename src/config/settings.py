"""应用配置和设置"""

import os
import platform
import tomllib
from pathlib import Path
from typing import Any, Dict, List

_IS_WINDOWS = platform.system() == "Windows"
_DEFAULT_CHROME = (
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    if _IS_WINDOWS
    else "/opt/google/chrome/google-chrome"
)

# ============================================================
# 浏览器 JS 脚本
# ============================================================

# 点击坐标随机化 JS
CLICK_RANDOMIZE_JS = """
function getRandomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
}
function modifyClickEvent(event) {
    if (!event._isModified) {
        event._screenX = event.screenX;
        event._screenY = event.screenY;
        Object.defineProperty(event, 'screenX', {
            get: function() {
                return this._screenX + getRandomInt(0, 200);
            }
        });
        Object.defineProperty(event, 'screenY', {
            get: function() {
                return this._screenY + getRandomInt(0, 200);
            }
        });
        event._isModified = true;
    }
}
const originalAddEventListener = EventTarget.prototype.addEventListener;
EventTarget.prototype.addEventListener = function(type, listener, options) {
    if (type === 'click') {
        const wrappedListener = function(event) {
            modifyClickEvent(event);
            listener.call(this, event);
        };
        originalAddEventListener.call(this, type, wrappedListener, options);
    } else {
        originalAddEventListener.call(this, type, listener, options);
    }
};
"""

# 完整指纹伪装 JS
FINGERPRINT_STEALTH_JS = """
(function() {
    'use strict';
    const rnd = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;

    // 1. navigator.webdriver - Blink 级禁用 + Proxy 兜底
    Object.defineProperty(window, 'navigator', {
        value: new Proxy(navigator, {
            has: (target, key) => (key === 'webdriver' ? false : key in target),
            get: (target, key) =>
                key === 'webdriver'
                    ? false
                    : typeof target[key] === 'function'
                    ? target[key].bind(target)
                    : target[key],
        }),
        configurable: true,
    });

    // 2. plugins
    Object.defineProperty(navigator, 'plugins', { get: () => {
        const arr = [1,2,3,4,5];
        arr.item = i => arr[i] || null;
        arr.namedItem = n => arr[0];
        arr.refresh = () => {};
        return arr;
    }});

    // 3. languages / platform / hardware
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN','zh','en-US','en'] });
    Object.defineProperty(navigator, 'language', { get: () => 'zh-CN' });
    Object.defineProperty(navigator, 'platform', { get: () => 'Linux x86_64' });
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
    Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
    Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });

    // 4. chrome.runtime - 完整 API
    window.chrome = {
        app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } },
        runtime: { OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' }, OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' }, PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' }, PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' } },
    };

    // 5. permissions
    if (!window.Notification) { window.Notification = { permission: 'denied' }; }
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.__proto__.query = parameters =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: window.Notification.permission })
            : origQuery(parameters);

    // 6. Screen / Window
    Object.defineProperty(screen, 'width', { get: () => 1920 });
    Object.defineProperty(screen, 'height', { get: () => 1080 });
    Object.defineProperty(screen, 'availWidth', { get: () => 1920 });
    Object.defineProperty(screen, 'availHeight', { get: () => 1080 });
    Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
    Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });
    Object.defineProperty(window, 'outerWidth', { get: () => 1920 });
    Object.defineProperty(window, 'outerHeight', { get: () => 1080 });
    Object.defineProperty(window, 'innerWidth', { get: () => 1920 });
    Object.defineProperty(window, 'innerHeight', { get: () => 1080 });
    Object.defineProperty(window, 'devicePixelRatio', { get: () => 1 });

    // 7. connection
    if (!navigator.connection) {
        Object.defineProperty(navigator, 'connection', { get: () => ({ effectiveType: '4g', rtt: 50, downlink: 10, saveData: false }) });
    }

    // 8. Canvas 指纹噪声
    const origTDU = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        const ctx = this.getContext('2d');
        if (ctx) {
            const d = ctx.getImageData(0, 0, this.width, this.height);
            for (let i = 0; i < d.data.length; i += 4) d.data[i] += rnd(-1, 1);
            const cv = document.createElement('canvas');
            cv.width = this.width; cv.height = this.height;
            cv.getContext('2d').putImageData(d, 0, 0);
            return origTDU.call(cv, type);
        }
        return origTDU.call(this, type);
    };
    const origGID = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(x, y, w, h) {
        const d = origGID.call(this, x, y, w, h);
        for (let i = 0; i < d.data.length; i += 4) d.data[i] += rnd(-1, 1);
        return d;
    };

    // 9. WebGL 伪装
    const origGP = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return 'Intel Inc.';
        if (p === 37446) return 'Intel Iris OpenGL Engine';
        return origGP.call(this, p);
    };

    // 10. Audio 指纹噪声
    const origGCD = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function(c) {
        const d = origGCD.call(this, c);
        for (let i = 0; i < d.length; i++) d[i] += (Math.random() - 0.5) * 1e-10;
        return d;
    };

    // 11. Function.prototype.toString 修补 - 关键！
    const nativeFnStr = Error.toString().replace(/Error/g, 'toString');
    const oldCall = Function.prototype.call;
    function call() { return oldCall.apply(this, arguments); }
    Function.prototype.call = call;
    const oldToString = Function.prototype.toString;
    function functionToString() {
        if (this === window.navigator.permissions.query) return 'function query() { [native code] }';
        if (this === functionToString) return nativeFnStr;
        return oldCall.call(oldToString, this);
    }
    Function.prototype.toString = functionToString;

    // 12. navigator.userAgentData — 关键缺失项
    try {
        Object.defineProperty(navigator, 'userAgentData', {
            get: () => ({
                brands: [
                    {brand:'Google Chrome',version:'149'},
                    {brand:'Chromium',version:'149'},
                    {brand:'Not=A?Brand',version:'24'}
                ],
                mobile: false,
                platform: 'Linux',
                getHighEntropyValues: (hints) => {
                    const data = {
                        platform: 'Linux',
                        platformVersion: '6.8.0',
                        architecture: 'x64',
                        model: '',
                        uaFullVersion: '149.0.7827.53',
                        bitness: '64',
                        fullVersionList: [
                            {brand:'Google Chrome',version:'149.0.7827.53'},
                            {brand:'Chromium',version:'149.0.7827.53'},
                            {brand:'Not=A?Brand',version:'24.0.0.0'}
                        ]
                    };
                    return Promise.resolve(data);
                }
            })
        });
    } catch(e) {}

    // 13. AudioContext.sampleRate 锁定 44100
    try {
        const OrigCtx = window.AudioContext || window.webkitAudioContext;
        if (OrigCtx) {
            const origCtor = window.AudioContext || window.webkitAudioContext;
            const FakeCtx = function() {
                const ctx = new origCtor();
                Object.defineProperty(ctx, 'sampleRate', { get: () => 44100 });
                return ctx;
            };
            FakeCtx.prototype = origCtor.prototype;
            window.AudioContext = FakeCtx;
            window.webkitAudioContext = FakeCtx;
        }
    } catch(e) {}

    // 14. 自动化标记清理
    delete window.callPhantom;
    delete window._phantom;
    delete window.__nightmare;
    delete window.domAutomation;
    delete window.domAutomationController;
})();
"""

# ============================================================
# 挑战检测配置
# ============================================================

CHALLENGE_TITLES: List[str] = [
    "Just a moment...",
    "请稍候…",
    "DDOS-GUARD",
]

CHALLENGE_SELECTORS: List[str] = [
    "#cf-challenge-running",
    ".ray_id",
    ".attack-box",
    "#cf-please-wait",
    "#challenge-spinner",
    "#trk_jschal_js",
    "td.info #js_info",
    "div.vc div.text-box h2",
]

CHALLENGE_BOX_SELECTORS: List[str] = [
    'input[name="cf-turnstile-response"]'
]

# Cloudflare 专用
CF_CHALLENGE_SELECTORS: List[str] = CHALLENGE_SELECTORS
CF_BOX_SELECTORS: List[str] = CHALLENGE_BOX_SELECTORS

# 五秒盾
FIVE_SECOND_SELECTORS: List[str] = [
    "#sec",
    ".loading-countdown",
    ".countdown-timer",
    "#wait-time",
    'span[class*="second"]',
    'div[class*="countdown"]',
]

# 雷池
LEICHI_SELECTORS: List[str] = [
    "#safeline-block",
    'div[class*="safeline"]',
    'meta[name="safeline"]',
    'input[name="__safeline_"]',
    'script[src*="safeline"]',
    ".safeline-challenge",
]

# 通用挑战
GENERIC_CHALLENGE_SELECTORS: List[str] = [
    "#challenge-running",
    ".challenge-container",
    ".verification",
    ".captcha-container",
    "#recaptcha",
    ".g-recaptcha",
    "[data-challenge]",
]

# 挑战类型常量
CHALLENGE_TYPE_CLOUDFLARE = "cloudflare"
CHALLENGE_TYPE_CLOUDFLARE_BOX = "cloudflare_box"
CHALLENGE_TYPE_FIVE_SECOND = "five_second_shield"
CHALLENGE_TYPE_LEICHI = "leichi"
CHALLENGE_TYPE_GENERIC = "generic"
CHALLENGE_TYPE_NONE = "none"

# 挑战超时与重试
CHALLENGE_TIMEOUT = int(os.getenv("CHALLENGE_TIMEOUT", "30"))
CHALLENGE_RETRY_COUNT = int(os.getenv("CHALLENGE_RETRY_COUNT", "3"))

# ============================================================
# 指纹配置
# ============================================================
FINGERPRINT_PROFILES: Dict[str, Dict[str, Any]] = {
    "default": {
        "name": "基础反检测",
        "js_scripts": [CLICK_RANDOMIZE_JS],
        "disable_webgl": False,
        "browser_args": [],
        "disable_features": [],
    },
    "stealth": {
        "name": "完整指纹伪装（推荐）",
        "js_scripts": [CLICK_RANDOMIZE_JS, FINGERPRINT_STEALTH_JS],
        "disable_webgl": False,
        "browser_args": [
            "--enable-features=NetworkService,NetworkServiceInProcess,LoadCryptoTokenExtension,PermuteTLSExtensions",
            "--disable-features=FlashDeprecationWarning,EnablePasswordsAccountStorage",
            "--disable-component-extensions-with-background-pages",
            "--disable-background-networking",
            "--disable-client-side-phishing-detection",
            "--disable-default-apps",
            "--disable-hang-monitor",
            "--disable-popup-blocking",
            "--disable-prompt-on-repost",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--password-store=basic",
        ],
        "disable_features": [
            "FlashDeprecationWarning",
            "EnablePasswordsAccountStorage",
        ],
    },
    "paranoid": {
        "name": "最大程度隐藏",
        "js_scripts": [CLICK_RANDOMIZE_JS, FINGERPRINT_STEALTH_JS],
        "disable_webgl": True,
        "browser_args": [
            "--enable-features=NetworkService,NetworkServiceInProcess,LoadCryptoTokenExtension,PermuteTLSExtensions",
            "--disable-features=FlashDeprecationWarning,EnablePasswordsAccountStorage",
            "--disable-component-extensions-with-background-pages",
            "--disable-background-networking",
            "--disable-client-side-phishing-detection",
            "--disable-default-apps",
            "--disable-hang-monitor",
            "--disable-popup-blocking",
            "--disable-prompt-on-repost",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--password-store=basic",
            "--disable-webgl",
        ],
        "disable_features": [
            "FlashDeprecationWarning",
            "EnablePasswordsAccountStorage",
        ],
    },
}

DEFAULT_FINGERPRINT_PROFILE = "stealth"

# ============================================================
# 应用设置
# ============================================================
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "9850"))
CHROME_PATH = os.getenv("CHROME_PATH", _DEFAULT_CHROME)
HEADLESS_MODE = os.getenv("HEADLESS_MODE", "")
REMOTE_CHROME_ADDRESS = os.getenv("REMOTE_CHROME_ADDRESS", "")  # 如 127.0.0.1:9222
BROWSER_MONITOR_INTERVAL = 10
def _read_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        with open(pyproject, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError):
        return "0.0.0"


APP_VERSION = os.getenv("APP_VERSION", _read_version())
USER_DATA_PATH = os.getenv("USER_DATA_PATH", os.path.join(os.path.expanduser("~"), ".cache", "nexus-media-chrome", "user_data"))

# HTTP 客户端配置
HTTP_CLIENT_TIMEOUT = int(os.getenv("HTTP_CLIENT_TIMEOUT", "30"))
HTTP_MAX_REDIRECTS = int(os.getenv("HTTP_MAX_REDIRECTS", "10"))

# 向后兼容别名
JS_SCRIPT = CLICK_RANDOMIZE_JS

# Turnstile hook JS，在创建 tab 时通过 add_init_js 注入
with open(os.path.join(os.path.dirname(__file__), "turnstile_hook.js")) as _f:
    TURNSTILE_HOOK_JS = _f.read()
