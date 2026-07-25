"""
Vite integration for FastAPI

Provides helpers to load Vite assets in templates:
- Development: loads from Vite dev server with HMR
- Production: loads from built manifest with content hashes
"""

import json
from pathlib import Path
from functools import lru_cache
from markupsafe import Markup

# Configuration
VITE_DEV_SERVER = "http://localhost:5173"
MANIFEST_PATH = Path(__file__).parent / "static" / "dist" / "manifest.json"


def is_vite_dev_mode() -> bool:
    """Check if Vite dev server is running"""
    import os
    return os.environ.get("VITE_DEV", "false").lower() == "true"


@lru_cache(maxsize=1)
def load_manifest() -> dict:
    """Load and cache the Vite manifest"""
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            return json.load(f)
    return {}


def clear_manifest_cache():
    """Clear the manifest cache (useful for testing)"""
    load_manifest.cache_clear()


def vite_asset(entry: str) -> Markup:
    """
    Generate script/link tags for a Vite entry point.

    Usage in Jinja2 templates:
        {{ vite_asset('src/main.js') }}

    Args:
        entry: The entry point path (e.g., 'src/main.js')

    Returns:
        HTML markup with appropriate script/link tags
    """
    if is_vite_dev_mode():
        # Development: load from Vite dev server
        return Markup(f'''
    <script type="module" src="{VITE_DEV_SERVER}/@vite/client"></script>
    <script type="module" src="{VITE_DEV_SERVER}/{entry}"></script>
''')

    # Production: load from manifest
    manifest = load_manifest()

    if entry not in manifest:
        # Fallback: entry not in manifest
        return Markup(f'<!-- Vite entry "{entry}" not found in manifest -->')

    entry_data = manifest[entry]
    tags = []

    # CSS files
    for css_file in entry_data.get("css", []):
        tags.append(f'<link rel="stylesheet" href="/static/dist/{css_file}">')

    # JavaScript (with modulepreload for imports)
    js_file = entry_data.get("file", "")
    if js_file:
        tags.append(f'<script type="module" src="/static/dist/{js_file}"></script>')

    # Preload imported chunks
    for import_file in entry_data.get("imports", []):
        import_data = manifest.get(import_file, {})
        import_js = import_data.get("file", "")
        if import_js:
            tags.append(f'<link rel="modulepreload" href="/static/dist/{import_js}">')

    return Markup("\n    ".join(tags))


def vite_hmr_client() -> Markup:
    """
    Include Vite HMR client in development mode.
    Only needed if not using vite_asset().
    """
    if is_vite_dev_mode():
        return Markup(f'<script type="module" src="{VITE_DEV_SERVER}/@vite/client"></script>')
    return Markup("")


def register_vite_helpers(templates):
    """
    Register Vite helpers as Jinja2 globals.

    Usage:
        from vite_integration import register_vite_helpers
        register_vite_helpers(templates)
    """
    templates.env.globals["vite_asset"] = vite_asset
    templates.env.globals["vite_hmr_client"] = vite_hmr_client
    templates.env.globals["vite_dev_mode"] = is_vite_dev_mode
