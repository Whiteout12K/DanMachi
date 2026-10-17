# 1. Project map

## Runtime flow

```text
Launch DanMachi.command
  → launcher/game.py
      → checks native compatibility and containment
      → starts offline/server.py on 127.0.0.1:28766
      → starts the local Mac.apk runtime and retained APK
          → native game requests API data from the local server
          → virtual assets are read from retained ZIP archives
          → native client commits gameplay updates to the local save
```

## Folder responsibilities

| Folder or file | Purpose | Normal editing policy |
| --- | --- | --- |
| `launcher/` | Startup, containment, native compatibility, Java helpers and host adapters | Edit source; rebuild only the affected helper |
| `offline/` | Local APIs, persistence, master overlays and feature tests | Main location for gameplay-service repairs |
| `docs/` | Learning guide and maintenance workflow | Keep current with behavior |
| `tools/` | Read-only inspection and focused verification entry point | No player-balance changes |
| [state/offline/player-state.json](../state/offline/player-state.json) | Server-side account tables, tokens and operation reservations | Back up with the account tools; do not hand-edit for testing |
| `state/native-client/` | Writable native account files and caches | Part of the account; close game before copying |
| `state/logs/` | Bounded launcher/server/runtime diagnostics | Generated each launch |
| `state/verification/` | Evidence reports from maintenance checks | Generated, separate from player progress |
| `assets/`, `contents/`, `offline/apks/` | Retained media, manifests and original APK inputs | Preserve originals; serve overlays in memory |
| `runtime/`, `DanMachi MF.app` | Runtime and installed app packaging | Preserve dependencies and internal links |
| `User Data/` | Export/import/delete-account tools | Use these for account lifecycle operations |

## Source entry points

| Area | Read first | Related files |
| --- | --- | --- |
| Startup | [launcher/game.py](../launcher/game.py) | [check_bundle.py](../launcher/check_bundle.py), [compatibility.py](../launcher/compatibility.py), [save_exit.py](../launcher/save_exit.py) |
| Requests | [offline/server.py](../offline/server.py) | `reference/offline_client.py` supplies baseline protocol handling |
| Saves | [offline/save_store.py](../offline/save_store.py) | [test_save_updates.py](../offline/test_save_updates.py), [test_inventory_transactions.py](../offline/test_inventory_transactions.py) |
| Banners and tickets | [offline/gacha_rotation.py](../offline/gacha_rotation.py) | [gacha.py](../offline/gacha.py), [build_gacha.py](../offline/build_gacha.py), `test_gacha*.py` |
| Monthly events | [offline/guild_events.py](../offline/guild_events.py) | [guild_quests.py](../offline/guild_quests.py) |
| Event item artwork | [offline/event_item_icons.py](../offline/event_item_icons.py) | [offline/test_event_item_icons.py](../offline/test_event_item_icons.py) |
| Anniversary stories | [offline/anniversary_events.py](../offline/anniversary_events.py) | [launcher/grand_day_stage_list.py](../launcher/grand_day_stage_list.py) |
| Anniversary reward boxes | [offline/event_box.py](../offline/event_box.py) | [test_event_box.py](../offline/test_event_box.py) |
| Archived assets | [offline/asset_store.py](../offline/asset_store.py) | [zip_reader.py](../offline/zip_reader.py), [archive_catalog.py](../offline/archive_catalog.py), [asset_cache.py](../offline/asset_cache.py) |
| Original master decoding | [offline/rebuild_master.py](../offline/rebuild_master.py) | `build_gacha.value` reads variable-width encrypted scalars |
| Video and typing | [launcher/video/MovieAgent.java](../launcher/video/MovieAgent.java) | [MovieDeferred.java](../launcher/video/MovieDeferred.java), [MovieOrientation.java](../launcher/video/MovieOrientation.java), [KeyboardSupport.java](../launcher/video/KeyboardSupport.java) |
| Mouse/window rendering | [launcher/window_fit.m](../launcher/window_fit.m) | Keep the user-verified mapping intact |
| Native patches | [launcher/compatibility-patches.json](../launcher/compatibility-patches.json) | Each change must retain exact original/replacement bytes and full-file hashes |

A file in `reference/` describes historical protocol behavior. A compiled `.jar`, `.dylib`, `.so` or catalog is an output/dependency; locate its source before editing it.
