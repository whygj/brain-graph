"""BrainGraph adapters — pluggable data sources."""

from adapters.sqlite_adapter import SQLiteAdapter
from adapters.markdown_adapter import MarkdownAdapter
from adapters.json_adapter import JSONAdapter
from adapters.obsidian_adapter import ObsidianAdapter

ADAPTER_MAP = {
    "sqlite": SQLiteAdapter,
    "markdown": MarkdownAdapter,
    "json": JSONAdapter,
    "obsidian": ObsidianAdapter,
}


def get_adapter(source_config):
    """Instantiate an adapter from a source config dict."""
    stype = source_config.get("type", "sqlite")
    cls = ADAPTER_MAP.get(stype)
    if not cls:
        raise ValueError(f"Unknown source type: {stype}")
    return cls(source_config)
