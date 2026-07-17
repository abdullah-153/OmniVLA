"""Compatibility shim for integrations that previously imported embedded HTML."""

from cogniagent.gui.web_assets import get_asset


_index_asset = get_asset("index.html")
HTML_CONTENT = _index_asset[0].decode("utf-8") if _index_asset else ""
