"""Shared layout for local pages displayed inside native game menus."""

# Reading guide: Shared HTML document wrapper for pages opened inside the native game
# menus.
# Editing notes: Edit layout here when multiple local pages need the same presentation.
# Callers supply the body content.
# Checks: offline/test_menu_pages.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

HEAD = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'"><style>
*{box-sizing:border-box}html{width:100%;min-height:100%;background:#fff;overflow-x:hidden}
body{width:100%;min-width:0;margin:0;padding:clamp(10px,2.5vw,24px);font:16px/1.5 -apple-system,BlinkMacSystemFont,sans-serif;color:#222;background:#fff;overflow-wrap:anywhere}
h1{font-size:clamp(22px,3.5vw,30px)}h2{font-size:clamp(19px,3vw,25px)}h3{font-size:18px;margin-top:24px}h1,h2,h3{line-height:1.25}h1:first-child,h2:first-child{margin-top:0}
a{color:#164a91}p,ol,ul{max-width:100%}ol,ul{padding-left:1.5em}table{border-collapse:collapse;width:100%;max-width:100%;table-layout:fixed;margin:12px 0}
th,td{border:1px solid #ccc;padding:clamp(4px,1vw,8px);text-align:left;vertical-align:top;overflow-wrap:anywhere}th:first-child,td:first-child{width:52%}summary{cursor:pointer;font-weight:bold;padding:8px 0}small{color:#555}img,video,iframe{max-width:100%;height:auto}pre{white-space:pre-wrap}
</style>"""


def document(body):
    """Wrap supplied page content in the shared local menu HTML layout."""
    return (HEAD + body).encode("utf-8")
