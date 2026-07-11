"""CookieStore 单元测试。"""

from src.core.cookie_store import CookieStore


class TestCookieStore:
    def test_store_and_get(self):
        store = CookieStore()
        cookies = [
            {"name": "session", "value": "abc123", "domain": "example.com"},
            {"name": "token", "value": "xyz789", "domain": "example.com"},
        ]
        store.store("example.com", cookies)
        result = store.get("example.com")
        assert len(result) == 2
        names = {c["name"] for c in result}
        assert names == {"session", "token"}

    def test_store_merge_updates_existing(self):
        store = CookieStore()
        store.store("example.com", [{"name": "a", "value": "1"}])
        store.store("example.com", [{"name": "a", "value": "2"}, {"name": "b", "value": "3"}])
        result = store.get("example.com")
        assert len(result) == 2
        assert {c["name"]: c["value"] for c in result} == {"a": "2", "b": "3"}

    def test_store_empty_domain_skips(self):
        store = CookieStore()
        store.store("", [{"name": "a", "value": "1"}])
        assert store.list_domains() == []

    def test_store_empty_cookies_skips(self):
        store = CookieStore()
        store.store("example.com", [])
        assert store.list_domains() == []

    def test_as_header(self):
        store = CookieStore()
        store.store("example.com", [
            {"name": "a", "value": "1"},
            {"name": "b", "value": "2"},
        ])
        header = store.as_header("example.com")
        assert "a=1" in header
        assert "b=2" in header

    def test_as_header_empty_domain(self):
        store = CookieStore()
        assert store.as_header("nonexistent.com") == ""

    def test_as_dict(self):
        store = CookieStore()
        store.store("example.com", [
            {"name": "a", "value": "1"},
            {"name": "b", "value": "2"},
        ])
        result = store.as_dict("example.com")
        assert result == {"a": "1", "b": "2"}

    def test_as_full_dict(self):
        store = CookieStore()
        store.store("example.com", [{"name": "a", "value": "1"}])
        store.store("other.com", [{"name": "b", "value": "2"}])
        full = store.as_full_dict()
        assert full == {"example.com": {"a": "1"}, "other.com": {"b": "2"}}

    def test_list_domains(self):
        store = CookieStore()
        store.store("a.com", [{"name": "x", "value": "1"}])
        store.store("b.com", [{"name": "y", "value": "2"}])
        domains = store.list_domains()
        assert set(domains) == {"a.com", "b.com"}

    def test_clear_domain(self):
        store = CookieStore()
        store.store("a.com", [{"name": "x", "value": "1"}])
        store.store("b.com", [{"name": "y", "value": "2"}])
        store.clear("a.com")
        assert store.list_domains() == ["b.com"]

    def test_clear_all(self):
        store = CookieStore()
        store.store("a.com", [{"name": "x", "value": "1"}])
        store.clear()
        assert store.list_domains() == []

    def test_store_from_url(self):
        store = CookieStore()
        store.store_from_url("https://example.com/path?q=1", [{"name": "a", "value": "1"}])
        assert "example.com" in store.list_domains()

    def test_get_for_url(self):
        store = CookieStore()
        store.store("example.com", [{"name": "a", "value": "1"}])
        result = store.get_for_url("https://example.com/page")
        assert len(result) == 1

    def test_as_header_for_url(self):
        store = CookieStore()
        store.store("example.com", [{"name": "a", "value": "1"}])
        header = store.as_header_for_url("https://example.com/page")
        assert "a=1" in header

    def test_thread_safety(self):
        import threading

        store = CookieStore()

        def write_cookies(domain, start, end):
            for i in range(start, end):
                store.store(domain, [{"name": f"c{i}", "value": str(i)}])

        threads = []
        for i, domain in enumerate(["a.com", "b.com", "c.com", "d.com"]):
            t = threading.Thread(target=write_cookies, args=(domain, i * 100, (i + 1) * 100))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for domain in ["a.com", "b.com", "c.com", "d.com"]:
            assert len(store.get(domain)) == 100
