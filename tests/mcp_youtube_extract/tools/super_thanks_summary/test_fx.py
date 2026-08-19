"""Unit tests for frankfurter.dev FX rate fetching and cache fallback."""

import urllib.error
from unittest.mock import patch

from mcp_youtube_extract.tools.super_thanks_summary.utils import fx as _mod


class TestFxFallback:
    def test_returns_stale_cache_on_network_failure(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "inr.json"
        cache_path.write_text(
            '{"rates": {"USD": 80.0}, "unsupported": [], "fetched_at": 100}'
        )
        monkeypatch.setattr(_mod, "_CACHE_DIR", tmp_path)
        monkeypatch.setattr(_mod, "_CACHE_PATH", cache_path)

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no network")):
            fx = _mod.fetch_rates_to_inr({"USD"})

        assert fx["rates"]["USD"] == 80.0
        assert fx["stale"] is True
        assert "stale" in fx["source"]

    def test_returns_empty_when_no_cache_and_no_network(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_CACHE_DIR", tmp_path)
        monkeypatch.setattr(_mod, "_CACHE_PATH", tmp_path / "inr.json")

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no network")):
            fx = _mod.fetch_rates_to_inr({"USD", "GBP"})

        assert fx["rates"] == {"INR": 1.0}
        assert set(fx["unsupported"]) == {"USD", "GBP"}
        assert fx["stale"] is True
