"""Search providers must only use credentials configured by the operator."""
from unittest.mock import MagicMock, patch

from cogniagent.tools import browser_search


def test_no_credentials_means_no_authenticated_provider(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("MONID_API_KEY", raising=False)
    with patch("dotenv.load_dotenv"), patch.object(browser_search, "Exa") as exa:
        assert browser_search._get_exa_client() is None
        assert browser_search._get_monid_api_key() == ""
        assert browser_search._search_exa("test") == []
        assert browser_search._search_monid("test") == []
        exa.assert_not_called()


def test_explicit_provider_credentials_are_used(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "test-configured-exa")
    monkeypatch.setenv("MONID_API_KEY", "test-configured-monid")
    factory = MagicMock()
    with patch.object(browser_search, "Exa", factory):
        assert browser_search._get_exa_client() is factory.return_value
    factory.assert_called_once_with(api_key="test-configured-exa")
    assert browser_search._get_monid_api_key() == "test-configured-monid"
