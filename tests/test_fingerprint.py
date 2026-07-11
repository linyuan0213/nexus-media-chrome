"""FingerprintManager 单元测试。"""

import pytest

from src.core.fingerprint import FingerprintManager


class TestFingerprintManager:
    def test_default_profile_is_stealth(self):
        fm = FingerprintManager()
        assert fm.profile_name == "stealth"

    def test_explicit_profile(self):
        fm = FingerprintManager("default")
        assert fm.profile_name == "default"

    def test_unknown_profile_raises(self):
        with pytest.raises(ValueError, match="未知指纹 profile"):
            FingerprintManager("nonexistent")

    def test_get_init_js_default(self):
        fm = FingerprintManager("default")
        js = fm.get_init_js()
        assert "modifyClickEvent" in js

    def test_get_init_js_stealth(self):
        fm = FingerprintManager("stealth")
        js = fm.get_init_js()
        assert "modifyClickEvent" in js
        assert "navigator" in js
        assert "'webdriver'" in js

    def test_get_browser_args_default(self):
        fm = FingerprintManager("default")
        assert fm.get_browser_args() == []

    def test_get_browser_args_paranoid(self):
        fm = FingerprintManager("paranoid")
        args = fm.get_browser_args()
        assert "--disable-webgl" in args

    def test_list_profiles(self):
        profiles = FingerprintManager.list_profiles()
        assert "default" in profiles
        assert "stealth" in profiles
        assert "paranoid" in profiles

    def test_register_custom_profile(self):
        FingerprintManager.register_profile("custom", {
            "name": "自定义",
            "js_scripts": ["/* custom */"],
            "disable_webgl": True,
        })
        fm = FingerprintManager("custom")
        assert fm.profile_name == "custom"
        assert fm.get_init_js() == "/* custom */"
        assert "--disable-webgl" in fm.get_browser_args()

    def test_config_property(self):
        fm = FingerprintManager("stealth")
        config = fm.config
        assert config["name"] == "完整指纹伪装（推荐）"
