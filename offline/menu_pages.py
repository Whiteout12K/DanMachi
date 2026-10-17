"""Small local gear-menu pages; no network access or player-state writes."""

# Reading guide: Local menu content: provide policies/help pages and the retained
# support layout.
# Editing notes: These pages are read-only UI content. Shared HTML styling lives in
# web_pages.py.
# Checks: offline/test_menu_pages.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import functools, gzip, json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SUPPORT_LAYOUTS = {
    "modal_support_top.json": {
        6: "CommonButton",
        13: "CommonButton",
        12: "LabelBMFont",
    },
    "modal_cache_clear_confirm.json": {8: "CommonButton"},
    "modal_novelasset_dl_confirm.json": {8: "CommonButton"},
}


def protected_support_layout(path, source):
    """Keep native node tags, but make obsolete cache/download controls unreachable."""
    parts = path.split("/")
    if (
        len(parts) != 5
        or parts[0] not in ("1", "3")
        or parts[1:4] != ["files", "ui_atlas", "title"]
        or parts[4] not in SUPPORT_LAYOUTS
    ):
        return None
    from asset_store import ArchivedAsset, MemoryAsset

    if not source:
        return None
    layout = json.loads(
        ArchivedAsset(
            {**source, "size": source.get("archive_size", source["size"])}
        ).read_bytes()
    )
    nodes = {n["tag"]: n for n in layout["root"]["childs"]}
    for tag, kind in SUPPORT_LAYOUTS[parts[4]].items():
        node = nodes[tag]
        if node["class"] != kind:
            raise ValueError("Unexpected Support layout node")
        # Removing nodes breaks the original client's tag bindings. Moving the
        # retained controls outside the modal prevents drawing and touch hits.
        node["position"] = {"x": -8192, "y": -8192}
        node["opacity"] = 0
    return MemoryAsset(
        json.dumps(layout, separators=(",", ":"), ensure_ascii=False).encode()
    )


from web_pages import HEAD, document

STYLE = HEAD
HELP = document(
    "<h1>Offline Help</h1><p>Use the close button to return to the game.</p><h2>Your player</h2><p>Progress is stored in the DanMachi folder. To back up or move your player, close the game and use Export User.command or Import User.command in User Data. The old online Import button cannot transfer a cloud account.</p><h2>Sound and display</h2><p>Gear &gt; Settings controls BGM, sound effects, voices, animation skipping and unit display. Mac volume controls the final output. All retained media is read locally; network download preferences do not require internet.</p><h2>Gacha</h2><p>Used free banners are replaced when you reopen the game. Gacha Details lists the actual offline pools and rates. Online purchases, social links and publisher support are unavailable.</p><h2>Menu features</h2><p>Inventory, Story Digest, Profile, Change Hero and Voice Management use your local progress. Hero selections retain their story unlock requirements. Voice files already stored in the archives need no second download. Alarm Clock is disabled in this Europe build. Contact and Official SNS show offline guidance; they do not send messages or open social feeds.</p><h2>Folder maintenance</h2><p>Keep the entire DanMachi folder together. Close the game before copying it. Use the folder checker to check missing dependencies. Keep the state folder and bundled game files intact.</p>"
)


@functools.lru_cache(maxsize=1)
def policies():
    """Build local policy text for the retained offline menu."""
    with gzip.open(Path(__file__).with_name("policy-pages.json.gz"), "rt") as source:
        return json.load(source)


def page(path, query=""):
    """Select a supported local menu page and wrap its HTML content."""
    if path.rstrip("/") in ("/content", "/webview/production/help"):
        return HELP
    if path == "/offline/page":
        original = urlsplit(parse_qs(query).get("url", [""])[0])
        if original.hostname == "www.wfs.games" and "/policies/" in original.path:
            section = "index"
        elif original.hostname == "www.wfs.games":
            section = next(
                (
                    kind
                    for route, kind in (
                        ("/terms/", "terms"),
                        ("/privacypolicy/", "privacy"),
                        ("/gem/", "currency"),
                    )
                    if route in original.path
                ),
                "index",
            )
        else:
            return (
                STYLE
                + "<h1>Offline information</h1><p>This feature originally used an online website. Online publisher support and social feeds are unavailable. Your player stays on this Mac. Open Gear &gt; Help for local help and player backup instructions.</p>"
            ).encode()
    elif path.startswith("/offline/policy/"):
        section = path.rsplit("/", 1)[-1]
        if section not in ("index", "terms", "privacy", "currency"):
            return None
    else:
        return None
    links = '<p><a href="/offline/policy/index">Policies</a> | <a href="/offline/policy/terms">Terms of Use</a> | <a href="/offline/policy/privacy">Privacy Policy</a> | <a href="/offline/policy/currency">In-app Currency Terms</a></p>'
    body = (
        "<h1>Policies</h1><p>These are local copies of the publisher pages retrieved on 12 October 2026. Reading them does not accept a new agreement. Online purchases and account transfers are unavailable in this offline game.</p>"
        if section == "index"
        else policies()[section]
    )
    return (
        STYLE
        + links
        + body
        + "<p>Publisher: WFS. Offline copy; close this page to return to the game.</p>"
    ).encode()
