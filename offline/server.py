"""Local bootstrap research server; this does not launch or modify the game."""

# Reading guide: Request coordinator: persistent_api_response() adds local gameplay
# services to the baseline protocol.
# Editing notes: Asset routes are below the API dispatch. The baseline module is loaded
# at startup; importing this file initializes the live save. Inspect it without
# importing during maintenance.
# Checks: tools/maintain.py test all.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import copy
import functools
import hashlib
import importlib.util
import json
import os
import threading
import gacha
import tutorial_starter
import familia
import event_box
import shooting
import account_unlocks

gacha_request = threading.local()
from urllib.parse import unquote, urlsplit, parse_qs
from pathlib import Path
from save_store import SaveStore, unpack
from play_days import record as record_play_day
from asset_store import resolve as resolve_asset, MemoryAsset

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "danmemore_reference", Path(__file__).parent / "reference/offline_client.py"
)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
backend.ROOT = ROOT
backend.CONTENTS = ROOT / "contents"
backend.WORK = ROOT / "state/offline"
backend.WORK.mkdir(parents=True, exist_ok=True)
# Android retains its original local URL. A separate host port keeps it from
# reaching the obsolete bootstrap process left running by the first launcher.
backend.PORT = 28766
backend.API_ACTIONS = (
    *backend.API_ACTIONS,
    "lottery/draw",
    "lottery/ticket/draw",
    "notice/show",
    "tutorial/draw",
    "character/friendship/complete",
    "adventure/stage/complete",
    "achievement/familia/add",
    "achievement/complete",
    "friend/support/list",
)
backend.API_ACTIONS = (
    *backend.API_ACTIONS,
    *familia.ACTIONS,
    "event_box/show",
    "event_box/draw",
)
backend.API_ACTIONS = (*backend.API_ACTIONS, *shooting.ACTIONS)
save = SaveStore(backend.WORK / "player-state.json")
save.repair_legacy_tutorial_attack()
save.prepare_reward_backfill()
if "UserCommunicationCharacter" not in save.state["tables"]:
    initial = unpack(backend.pull_response({"tables": ["UserCommunicationCharacter"]}))
    save.apply(
        {
            "deltas": [{"putItems": initial["data"], "deleteItems": {}}],
            "checksums": {"after": initial["dataTokens"]},
        }
    )
save.repair_bootstrap_costume()
original_api_response = backend.api_response
player_logged_in = False


# Account reset boundary and local gameplay API dispatch
def consume_reset():
    # The reset utility stops the Android client before queuing this operation.
    # Consume it under the same lock as save writes, before the next login.
    """Consume the queued reset marker while holding the same lock as save writes."""
    with save.lock:
        marker = backend.WORK / "reset-account.pending"
        if marker.exists():
            save.reset(
                unpack(
                    backend.pull_response({"tables": ["UserCommunicationCharacter"]})
                )
            )
            save.repair_bootstrap_costume()
            marker.unlink()
            print(
                "Local account reset: previous player tables and tokens cleared.",
                flush=True,
            )


def persistent_api_response(action, request_body=b""):
    """Dispatch local API actions, then reconcile native pushes and pending grants."""
    global player_logged_in
    consume_reset()
    if action == "user/login":
        player_logged_in = True
    if player_logged_in:
        record_play_day(save, login=action == "user/login")
    if action in shooting.ACTIONS:
        response = shooting.handle(action, backend.decode_request(request_body))
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action in familia.ACTIONS:
        response = familia.handle(
            save,
            action,
            backend.decode_request(request_body),
            getattr(gacha_request, "key", hashlib.sha256(request_body).hexdigest()),
        )
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action == "event_box/show":
        response = event_box.show(save, backend.decode_request(request_body))
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action == "event_box/draw":
        response = event_box.draw(
            save,
            backend.decode_request(request_body),
            getattr(gacha_request, "key", hashlib.sha256(request_body).hexdigest()),
        )
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action == "friend/support/list":
        # Original DomainSupporterDataRepository consumes supporters at the
        # response root. Offline has no remote player accounts to lend units.
        response = {"code": 0, "supporters": [], "is_fullset": True}
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action == "notice/show":
        request = backend.decode_request(request_body)
        with save.lock:
            state = copy.deepcopy(save.state)
        response = {
            "code": 0,
            "html": gacha.details_html(request.get("lotteryId"), state),
            "data": {},
            "dataTokens": {},
            "operations": [],
            "dones": [],
        }
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action in ("lottery/draw", "lottery/ticket/draw"):
        request = backend.decode_request(request_body)
        response = gacha.draw(
            save,
            request,
            getattr(gacha_request, "key", hashlib.sha256(request_body).hexdigest()),
        )
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action == "achievement/complete":
        response = save.achievement_complete(backend.decode_request(request_body))
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action == "achievement/familia/add":
        response = save.familia_record(backend.decode_request(request_body))
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action == "adventure/stage/complete":
        value = backend.decode_request(request_body)
        response = save.adventure_complete(value, getattr(gacha_request, "key", None))
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action == "character/friendship/complete":
        response = save.friendship_complete(backend.decode_request(request_body))
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action == "tutorial/draw":
        value = backend.decode_request(request_body)
        from sync_unit import ensure_unit

        with save.lock:
            unit = save.state.get("tutorialDraw", value).get("pcId")
        ensure_unit(unit)
        response = save.tutorial_draw(value)
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action == "user_data/push":
        value = backend.decode_request(request_body)
        response = backend.push_response(value)
        save.apply(value)
        with save.lock:
            if (
                "UserLimitBreakItem" in value["checksums"]["after"]
                and save.state["tokens"].get("UserLimitBreakItem")
                != value["checksums"]["after"]["UserLimitBreakItem"]
            ):
                response["data"]["UserLimitBreakItem"] = copy.deepcopy(
                    save.state["tables"].get("UserLimitBreakItem", [])
                )
                response["dataTokens"]["UserLimitBreakItem"] = save.state["tokens"][
                    "UserLimitBreakItem"
                ]
        with save.lock:
            for name in (
                "UserEventItem",
                "UserEventBox",
                "UserEventBoxStep",
                "UserEventBoxContent",
            ):
                if (
                    name in value["checksums"]["after"]
                    and save.state["tokens"].get(name)
                    != value["checksums"]["after"][name]
                ):
                    response["data"][name] = copy.deepcopy(
                        save.state["tables"].get(name, [])
                    )
                    response["dataTokens"][name] = save.state["tokens"].get(name, "")
        profile_stats = record_play_day(save)
        response["data"].update(profile_stats)
        with save.lock:
            response["dataTokens"].update(
                {t: save.state["tokens"][t] for t in profile_stats}
            )
        with save.lock:
            before = copy.deepcopy(save.state["tables"].get("UserLottery", []))
        gacha.prepare(save)
        resources, tokens = save.resources()
        with save.lock:
            rows = save.state["tables"].get("UserLottery", [])
            if rows != before:
                response["data"]["UserLottery"] = copy.deepcopy(rows)
                response["dataTokens"]["UserLottery"] = save.state["tokens"].get(
                    "UserLottery", ""
                )
        response.setdefault("operations", []).extend(account_unlocks.pending(save))
        response["operations"].extend(save.pending_adventures())
        box_operation = event_box.pending(save)
        if box_operation:
            response["operations"].append(box_operation)
        box_data, box_tokens = event_box.recovery(save)
        response["data"].update(box_data)
        response["dataTokens"].update(box_tokens)
        starter = tutorial_starter.pending(save)
        if starter:
            response.setdefault("operations", []).append(starter)
        response["data"].update(resources)
        response["dataTokens"].update(tokens)
        return "application/json", json.dumps(response, separators=(",", ":")).encode()
    if action == "user_data/confirm":
        gacha.prepare(save)
        save.resources()
        with save.lock:
            tokens = dict(save.state["tokens"])
            # Ask the client to pull the recovered rows once, rather than
            # declaring that its already-rejected cache is synchronized.
            for table, rows in save.state["tables"].items():
                if rows and os.environ.get("DANMACHI_RESYNC") == "1":
                    tokens[table] = hashlib.md5(
                        (
                            "recovered-v1:" + table + json.dumps(rows, sort_keys=True)
                        ).encode()
                    ).hexdigest()
        tokens.setdefault("UserCommunicationCharacter", backend.HOME_CHARACTER_TOKEN)
        return (
            "application/json",
            json.dumps(
                {
                    "code": 0,
                    "dataTokens": tokens,
                    "migrators": [],
                    "operations": [
                        o
                        for o in (
                            tutorial_starter.pending(save),
                            gacha.pending(save),
                            event_box.pending(save),
                        )
                        if o
                    ]
                    + account_unlocks.pending(save)
                    + save.pending_adventures(),
                },
                separators=(",", ":"),
            ).encode(),
        )
    if action == "user_data/pull":
        value = backend.decode_request(request_body)
        tables = value.get("tables")
        if (
            not isinstance(tables, list)
            or not tables
            or len(tables) > 256
            or not all(isinstance(t, str) for t in tables)
        ):
            raise ValueError("Unsupported table pull")
        with save.lock:
            known = all(t in save.state["tables"] for t in tables)
        if known:
            from save_store import pack, wire_tables

            resources, resource_tokens = save.resources()
            with save.lock:
                data = {t: save.state["tables"][t] for t in tables}
                tokens = {
                    t: (
                        hashlib.md5(
                            (
                                "recovered-v1:"
                                + t
                                + json.dumps(data[t], sort_keys=True)
                            ).encode()
                        ).hexdigest()
                        if data[t] and os.environ.get("DANMACHI_RESYNC") == "1"
                        else save.state["tokens"].get(t, "")
                    )
                    for t in tables
                }
            data.update(resources)
            tokens.update(resource_tokens)
            return "application/x-msgpack", pack(
                {"data": wire_tables(data), "dataTokens": tokens, "recovery": False}
            )
        if any(t in save.state["tables"] for t in tables):
            raise ValueError(
                "Mixed saved and unknown tables cannot be safely reconstructed"
            )
    return original_api_response(action, request_body)


backend.api_response = persistent_api_response


class CheckedHandler(backend.LocalHandler):
    """
    Add local assets, lifecycle routes and checked POST handling to the baseline
    HTTP handler.
    """

    def _post_with_migration(self):
        """Wrap baseline POST handling with local save and migration behavior."""
        gacha_request.key = hashlib.sha256(
            (
                self.headers.get("X-ARGO-REQUEST-ID", "")
                + ":"
                + self.headers.get("X-ARGO-REQUEST-SEQUENCE", "")
            ).encode()
        ).hexdigest()
        path = urlsplit(self.path).path
        if path == "/offline/save-checkpoint":
            if self.headers.get("Content-Length", "0") != "0":
                self.send_error(400)
                return
            save.checkpoint()
            body = b'{"saved":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            print("Local save checkpoint completed.", flush=True)
            return
        if path in ("/billing/v1.0/migration/user/token", "/billing/v1.0/migration"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400)
                return
            if not 0 <= length <= 1024 * 1024:
                self.send_error(413)
                return
            self.record(self.rfile.read(length))
            # The inspected GREE Core$b adapter reads migration_token at the
            # response root. Core/internal/e accepts result=OK on completion.
            # This local account's tables stay intact when Android is rebuilt.
            response = {"result": "OK"}
            if path.endswith("/user/token"):
                response["migration_token"] = backend.LOCAL_TOKEN
            body = json.dumps(response, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_POST()

    def do_GET(self):
        route = urlsplit(self.path)
        if route.path.startswith("/zip-reader/"):
            from zip_reader import index_bytes, asset, record_read, statistics

            if route.path == "/zip-reader/stats":
                body = json.dumps(statistics()).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if route.path == "/zip-reader/index":
                body = index_bytes()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if route.path == "/zip-reader/file":
                values = parse_qs(route.query).get("path", [])
                source = asset(values[0]) if len(values) == 1 else None
                if source is None:
                    self.send_error(404)
                    return
                from asset_cache import small_asset

                cached = small_asset(source)
                if cached is not None:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(cached)))
                    self.end_headers()
                    self.wfile.write(cached)
                    record_read(values[0], len(cached))
                    return
                with source.open() as stream:
                    self.send_response(200)
                    self.send_header("Content-Length", str(source.stat().st_size))
                    self.end_headers()
                    for chunk in iter(lambda: stream.read(65536), b""):
                        self.wfile.write(chunk)
                record_read(values[0], source.stat().st_size)
                return
            self.send_error(404)
            return
        if urlsplit(self.path).path == "/billing/v1.0/payment/balance":
            with save.lock:
                gem = next(
                    (
                        r
                        for r in save.state["tables"].get("UserCurrency", [])
                        if r["currencyId"] == 205000001
                    ),
                    {},
                )
                free = max(
                    0,
                    gem.get("cumulativeAmount", 0)
                    - save.state.get("localIrisSpent", 0),
                )
            body = json.dumps(
                {
                    "result": "OK",
                    "entry": {
                        "balance_charge_gem": 0,
                        "balance_free_gem": free,
                        "balance_total_gem": free,
                    },
                },
                separators=(",", ":"),
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        from menu_pages import page as menu_page

        body = menu_page(route.path, route.query)
        if body is not None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if urlsplit(self.path).path == "/api/asset/notice/index":
            from web_pages import document

            body = document(
                "<h1>Local offline game</h1><p>Your progress is saved on this Mac. Online announcements and purchases are unavailable.</p><p>Use the close button to return to the game.</p>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/health":
            consume_reset()
            body = b'{"status":"ok","localAccountReset":1}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):
        try:
            self._post_with_migration()
        except (ValueError, KeyError, TypeError) as error:
            print("Rejected incomplete local save request: " + str(error), flush=True)
            self.unknown()


backend.LocalHandler = CheckedHandler


# Manifest and logical content resolution
@functools.lru_cache(maxsize=8)
def local_manifest(phase):
    """Serve a local manifest matching the available archived or generated assets."""
    source = backend.CONTENTS / phase
    manifest = json.loads((source / "project.manifest").read_text())
    available = {}
    for relative, metadata in manifest["assets"].items():
        path = resolve_asset(phase, relative, metadata)
        if path is None:
            continue
        item = dict(metadata)
        item["size"] = path.stat().st_size
        if isinstance(path, Path):
            item["md5"] = hashlib.md5(path.read_bytes()).hexdigest()
        available[relative] = item
    manifest["assets"] = available
    return MemoryAsset(json.dumps(manifest, separators=(",", ":")).encode())


class ContentPaths(dict):
    # The two original URL prefixes share one index, rather than retaining
    # two long URL strings for every asset. Response bytes remain unchanged.
    """Resolve manifest paths lazily instead of eagerly extracting archived assets."""

    def get(self, key, default=None):
        for prefix in ("/api/", "/content/"):
            if key.startswith(prefix):
                return super().get(key[len(prefix) :], default)
        return default


@functools.lru_cache(maxsize=1)
def asset_paths():
    """Build the allowed logical asset path set for local request handling."""
    result = ContentPaths()
    for phase in "12345678":
        root = backend.CONTENTS / phase
        manifest = root / "project.manifest"
        if not manifest.is_file():
            continue
        for relative, metadata in json.loads(manifest.read_text())["assets"].items():
            path = resolve_asset(phase, relative, metadata)
            if path is None:
                continue
            result[metadata["path"]] = path
    return result


backend.local_project_manifest = local_manifest
backend.asset_paths = asset_paths
from archive_assets import recover as recover_archived_media

original_content_path = backend.content_path


def content_path(request_path):
    """Resolve a content request within the project asset layout."""
    from local_downloads import manifest_asset

    manifest = manifest_asset(request_path)
    if manifest is not None:
        return manifest
    indexed = asset_paths().get(unquote(urlsplit(request_path).path))
    if indexed is not None and indexed.is_file():
        return indexed
    candidate = original_content_path(request_path)
    if candidate is not None and candidate.is_file():
        return candidate
    return recover_archived_media(request_path)


backend.content_path = content_path

if __name__ == "__main__":
    print("Persistent save server listening on Mac loopback port 28766.", flush=True)
    # Prepare immutable generated tables before health announces readiness.
    # The native ZIP reader's first index request has a 20-second timeout.
    from zip_reader import index_bytes

    index_bytes()
    backend.serve()
