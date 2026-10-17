# 5. Reading and editing the source

Start with the [project map](01-project-map.md), then use this index to find a file.
Files stay in their original folders because launch scripts, relative imports and
bundle checks depend on those paths.

## How to read a file

Each active Python module starts with a short purpose and a **Reading guide**,
**Editing notes**, and **Checks** comment. These explain its place in the game,
what to preserve, and which checks exercise it. Important functions have short
docstrings describing their input/output role or side effects. Native sources
have equivalent file headers and comments at compatibility decisions.

Read a feature in this order: its original definition reader, its in-memory
availability/asset overlay, its request handler, then its tests. A banner appearing
in the UI and a draw committing a reward are separate behaviors.

## Terms used in comments

| Term | Meaning here |
| --- | --- |
| Master | Original game definitions, such as item IDs, stage costs and unit pools. |
| Overlay | Changed bytes served in memory while the original input remains intact. |
| Native | The retained game client, which owns UI, combat and many inventory commits. |
| Row/table | One saved record / a collection of records of the same kind. |
| Token | Hash used by the client/server to detect a changed table. Field order can matter. |
| Pending operation | A reserved reward the native client still needs to acknowledge. |
| Idempotent retry | Repeating the same request returns its earlier reservation rather than charging or rewarding twice. |
| ZIP alias | Another logical path pointing to an existing archive member; no image extraction or copying. |

## Active Python and maintenance tools

Check commands below are suggestions for investigation, not commands to execute
by importing every module. In particular, importing `server.py` initializes the
live server save. Historical build/storage/account tools can write files when run.

| File | Purpose and edit boundary | Relevant checks |
| --- | --- | --- |
| [launcher/game.py](../launcher/game.py) | Startup coordinator: main() checks the bundle, owns the launch lock, starts the local server, and supervises the Mac.apk process. Window options and containment rules are near the top; process cleanup is inside main(). Keep shutdown/checkpoint ordering intact. | `launcher tests and tools/maintain.py test native` |
| [launcher/check_bundle.py](../launcher/check_bundle.py) | Bundle integrity checks: host compatibility, original input hashes, and folder-local links. Update inventories only for deliberate packaging changes; do not change expected hashes to hide an unexplained mismatch. | `tools/maintain.py check` |
| [launcher/compatibility.py](../launcher/compatibility.py) | Native patch installer: ensure() accepts only the recorded original or patched library hash. Patch definitions belong in compatibility-patches.json and their generators. Byte lengths and output hashes must agree before a write. | `tools/maintain.py test native` |
| [launcher/grand_day_stage_list.py](../launcher/grand_day_stage_list.py) | Grand Day entry repair: branch() encodes ARM64 jumps; patches() emits guarded native replacements. Episode, stage, page and offsets belong to the retained game build. Preserve the guard so other events keep their original behavior. | `tools/maintain.py test native` |
| [launcher/save_exit.py](../launcher/save_exit.py) | Shutdown handshake: request a local checkpoint and finish native save handling before the launcher exits. Keep timeouts bounded so a stopped server cannot trap the app on close. | `launcher/tests/test_save_exit.py` |
| [launcher/tutorial_setup.py](../launcher/tutorial_setup.py) | First-account startup observer: recognize the missing starter grant and request one bounded reload. Do not turn this into an unconditional restart loop; existing accounts should pass through. | `launcher/tests/test_tutorial_setup.py` |
| [offline/server.py](../offline/server.py) | Request coordinator: persistent_api_response() adds local gameplay services to the baseline protocol. Asset routes are below the API dispatch. The baseline module is loaded at startup; importing this file initializes the live save. Inspect it without importing during maintenance. | `tools/maintain.py test all` |
| [offline/save_store.py](../offline/save_store.py) | Save authority: MessagePack helpers define wire bytes; SaveStore merges native deltas and persists pending reward operations. Keep locks, copy-before-change, token calculation and atomic writes together. A pending operation is a reserved grant awaiting native acknowledgment, not permission to grant it twice. | `tools/maintain.py test saves and offline/test_save_store.py` |
| [offline/user_data.py](../offline/user_data.py) | Account lifecycle: validate exports first, stop this game, then copy both server and native account data. Import/delete keep rollback snapshots and release the launch lock in finally blocks. Keep game assets outside account exports. | `offline/test_user_data.py` |
| [offline/gacha.py](../offline/gacha.py) | Draw service: in-memory master overlays come first, followed by banner state, atomic draws and Details HTML. Selection reserves payment and a native grant together. Retried requests must return the reserved operation; preserve original pools, ticket IDs and draw counts. | `tools/maintain.py test gacha` |
| [offline/gacha_rotation.py](../offline/gacha_rotation.py) | Banner calendar: title matching links event offers; active() chooses the lineup; month_windows() preloads native dates. Ten Iris/free offers are independent of ticket ownership. Current events and permanent matching ticket offers are additional. Daily rotation uses UTC days. | `tools/maintain.py test gacha` |
| [offline/gacha_ticket_access.py](../offline/gacha_ticket_access.py) | Ticket compatibility: master_asset() changes native validity; art_aliases() supplies explicit missing banner images. Keep original ticket identities and pools. Zero native validity means expired; the server separately treats owned tickets as non-expiring. | `tools/maintain.py test gacha` |
| [offline/build_gacha.py](../offline/build_gacha.py) | Catalog builder: decode original tables and compact repeated unit pools into gacha-catalog.json.gz. This is a regeneration tool, not the live draw handler. Changing source logic requires rebuilding the catalog and checking retained pool/count invariants. | `tools/maintain.py test gacha` |
| [offline/event_box.py](../offline/event_box.py) | Reward boxes: show() initializes screens, draw() reserves currency and prizes, recovery() replays pending native grants. Finite prize counts and reset-prize requirements come from original masters. Payment/progress and request replay must stay atomic. | `tools/maintain.py test boxes` |
| [offline/event_item_icons.py](../offline/event_item_icons.py) | Event images: items()/groups() describe original currencies; resolutions() chooses explicit ZIP-backed image aliases. Original art wins. Missing art gets a different retained image from sibling currencies; substitutes are not recovered historical art. No player balances are touched. | `tools/maintain.py test events` |
| [offline/anniversary_events.py](../offline/anniversary_events.py) | Anniversary overlays: open retained story, stage, exchange and box records in memory. Patch only documented availability fields. Keep original identities, prerequisites and rewards; Grand Day native entry repair lives in launcher/. | `tools/maintain.py test events` |
| [offline/guild_events.py](../offline/guild_events.py) | Event calendar: link retained event episodes to rotating Guild goals and native availability. Keep episode matching separate from date changes so a scheduled quest still points to its original story. | `tools/maintain.py test events` |
| [offline/guild_quests.py](../offline/guild_quests.py) | Guild availability: derive month windows and rewrite retained limited/monthly date fields. These overlays expose goals; they must not fabricate completion or claim rewards. | `offline/test_guild_quests.py` |
| [offline/familia.py](../offline/familia.py) | Local Familia protocol: build the current player/member response and handle supported menu actions. There are no remote members or rankings to synthesize. Persist local changes through the SaveStore lock. | `offline/test_familia.py` |
| [offline/shooting.py](../offline/shooting.py) | Ais WAR protocol replies: provide playable IDs and acknowledge native minigame requests. The native client owns scores, coins and unlocks. Do not grant a second reward on completion. | `offline/test_shooting.py` |
| [offline/play_days.py](../offline/play_days.py) | Local attendance: record observed calendar days and update matching monthly login goals. A login records the day actually observed; reopening repeatedly must not count extra days. | `offline/test_play_days.py` |
| [offline/rebuild_master.py](../offline/rebuild_master.py) | Binary master reader/builder: decrypt original tables, locate rows/fields, then build compact server definitions. Offsets and encryption keys are tied to the retained APK. Regeneration writes definitions, not the real player save. | `tools/maintain.py check and the affected feature suite` |
| [offline/asset_store.py](../offline/asset_store.py) | Asset abstraction: ArchivedAsset reads original ZIP members; MemoryAsset serves generated bytes with the same interface. Resolve logical paths safely and validate indexed ZIP size/CRC before use. Keep media archive-backed. | `offline/test_asset_store.py` |
| [offline/zip_reader.py](../offline/zip_reader.py) | Virtual filesystem: catalog() assembles logical paths, index_bytes() serializes them, asset() serves the correct overlay or ZIP member. Overlay sizes must match served bytes. Phase aliases must preserve explicitly retained files; never turn missing unknown IDs into broad catch-all assets. | `offline/test_zip_reader.py` |
| [offline/archive_catalog.py](../offline/archive_catalog.py) | Shared ZIP catalog: resolve logical members whose identical bytes live in another retained archive part. Keep logical names stable and validate shared source metadata before exposing entries. | `offline/test_archive_deduplication.py` |
| [offline/asset_cache.py](../offline/asset_cache.py) | Small-asset cache: keep bounded immutable payloads in RAM to avoid repeating ZIP reads. Large media remains streamed from archives; do not add a persistent extracted cache. | `offline/test_asset_cache.py` |
| [offline/archive_assets.py](../offline/archive_assets.py) | Archive recovery: locate manifest-matching retained ZIP members for requested logical assets. Recovery must verify the source rather than silently substituting unrelated bytes. | `offline/test_asset_layout.py` |
| [offline/android_archive.py](../offline/android_archive.py) | Historical TAR installer using the retired ADB transport. Not the current Mac path; do not run it for maintenance. | `offline/test_android_archive.py` |
| [offline/local_downloads.py](../offline/local_downloads.py) | Native download metadata: voice_markers() exposes tiny completion records for voices already present in archives. Markers live in memory and require retained voice content; they do not download or fabricate missing audio. | `offline/test_local_downloads.py` |
| [offline/audio_profile.py](../offline/audio_profile.py) | Audio profile compatibility: reconcile original hashes with the optional smaller installed Ogg representation. Keep profile updates tied to verified source metadata, not arbitrary file replacements. | `offline/test_audio_profile.py` |
| [offline/menu_pages.py](../offline/menu_pages.py) | Local menu content: provide policies/help pages and the retained support layout. These pages are read-only UI content. Shared HTML styling lives in web_pages.py. | `offline/test_menu_pages.py` |
| [offline/web_pages.py](../offline/web_pages.py) | Shared HTML document wrapper for pages opened inside the native game menus. Edit layout here when multiple local pages need the same presentation. Callers supply the body content. | `offline/test_menu_pages.py` |
| [offline/sync_album.py](../offline/sync_album.py) | Album asset planning: compare original hashes, prepare only needed artwork, and install the local payload. Keep portrait availability separate from unit ownership. Do not unpack unrelated archives for an Album request. | `offline/test_album_assets.py` |
| [offline/sync_unit.py](../offline/sync_unit.py) | Unit artwork availability: expose retained assets for native units, costumes and communication portraits. This prepares media only; it must not grant ownership or change character progress. | `offline/test_inventory_transactions.py` |
| [offline/sync_voice.py](../offline/sync_voice.py) | Episode voice installation: copy only requested original voice content from checked retained archives. Do not infer that missing original audio has been recovered. Preserve original episode identities. | `offline/test_local_downloads.py` |
| [offline/sync_master.py](../offline/sync_master.py) | Historical table installation utility retained for reference. This contains an old ADB workflow and is not part of the current Mac launch path. Current maintenance must use the folder-local Mac setup; do not run this legacy installer. | `launcher/CURRENT_SETUP.md` |
| [offline/build.py](../offline/build.py) | Historical client build tool: apply reviewed service, DEX, native and manifest edits to a separate research APK. Not a normal launch step. Preserve original APK inputs and regenerate only an explicitly intended output. | `offline/test_bundle_check.py` |
| [offline/import_assets.py](../offline/import_assets.py) | Asset import utility: verify manifest identities before accepting asset payloads or shared collections. Importing media is separate from importing a player account; account tools live in user_data.py. | `offline/test_asset_store.py` |
| [offline/index_asset_archives.py](../offline/index_asset_archives.py) | Archive index maintenance: verify retained sources and build the logical asset lookup. This can remove extracted copies after verification. Review CURRENT_SETUP.md before running; normal play uses the existing index. | `offline/test_asset_layout.py` |
| [offline/deduplicate_assets.py](../offline/deduplicate_assets.py) | Optional storage maintenance: plan and repack byte-identical ZIP members while preserving logical names. The command can rewrite archive outputs. Review the plan and integrity checks before using it; it is not a startup dependency. | `offline/test_archive_deduplication.py` |
| [offline/recompress_assets.py](../offline/recompress_assets.py) | Optional ZIP repacker: retain every member payload while changing compression. This rewrites archives after verification. Do not run it as a routine readability or gameplay repair. | `offline/test_storage_maintenance.py` |
| [offline/compress_audio.py](../offline/compress_audio.py) | Optional audio conversion tool: preserve Ogg comments and update conversion metadata. This changes audio representation and is not required to launch. Inspect conversion inputs/outputs before use. | `offline/test_audio_profile.py` |
| [offline/prune_archive_exports.py](../offline/prune_archive_exports.py) | Retired cleanup command kept as a safe compatibility entry point. It must not export or discard retained assets; use the supported storage workflow. | `offline/test_storage_maintenance.py` |
| [offline/reset_account.py](../offline/reset_account.py) | Compatibility entry point for the explicit account deletion utility. Running this is an account lifecycle action, not a repair or test. Use User Data tools and their confirmation flow. | `offline/test_user_data.py` |
| [offline/account_unlocks.py](../offline/account_unlocks.py) | Native unlock recovery: return requested character grants through native operations. Keep pending grants separate from already committed ownership to avoid duplicate rewards. | `offline/test_inventory_transactions.py` |
| [offline/tutorial_banner.py](../offline/tutorial_banner.py) | Beginner-banner visibility: keep the original offer available while its tutorial grant is incomplete. Do not use this tutorial gate for permanent standard ticket banners. | `offline/test_tutorial_banner.py` |
| [offline/tutorial_starter.py](../offline/tutorial_starter.py) | First-unit recovery: prepare the original Bell starter operation when initial setup was interrupted. Keep the repair idempotent and scoped to the starter; it must not refill an existing account. | `offline/test_tutorial_starter.py` |
| [offline/tutorial_weights.py](../offline/tutorial_weights.py) | Beginner pool compatibility: generate equal weights for the retained tutorial choices. This applies only to the beginner tutorial pool; standard Gacha pools keep their original weights. | `offline/test_tutorial_weights.py` |
| [tools/maintain.py](../tools/maintain.py) | Maintenance entry point: inspect account/banner summaries, validate packaging, or run focused test groups. SUITES defines the supported feature checks. Test subprocesses use a full Python installation and temporary fixtures, not the bundled minimal runtime. | `python3 tools/maintain.py test all` |
| [tools/audit_movies.py](../tools/audit_movies.py) | Retained movie audit: stream archived USM data through diagnostics and collect decode evidence. This checks retained media without replacing the native movie player. Codec success alone does not prove in-game audio, orientation or Skip behavior. | `docs/04-verification.md` |

## English label maintenance

- [english_presentation.py](../offline/english_presentation.py): English display lookups, encrypted native string-vector overlays and matching virtual-file sizes. It does not replace artwork.
- [english-text.json](../offline/english-text.json): explicit English display strings; preserve row IDs and field numbers.
- [test_english_presentation.py](../offline/test_english_presentation.py): display-pointer isolation, playable-unit labels/skills, unchanged draw definitions, native sizes, artwork and voice preservation.

See [the English label recipe](03-feature-recipes.md#english-display-labels) for the workflow and retained-artwork limits. The new generated English texture cards and their tools were removed at the user's request; earlier event-item icon aliases remain.

## Native adapters and Java helpers

These are editable source files. Their `.dylib`, `.jar`, and executable counterparts
are separate build outputs. A formatting/comment change does not require rebuilding
them. A logic change does: consult [CURRENT_SETUP.md](../launcher/CURRENT_SETUP.md)
for the exact retained build before compiling. Do not invent a generic rebuild
command or update compatibility hashes to accept an unknown binary.

| File | Where to look |
| --- | --- |
| [app_launcher.m](../launcher/app_launcher.m) | Finder entry point, clean Python environment, logs and launch error dialog. |
| [window_fit.m](../launcher/window_fit.m) | Visible viewport/scissor fit, mouse coordinate reversal, framebuffer restoration and keyboard JNI geometry. |
| [stencil_support.c](../launcher/stencil_support.c) | EGL stencil configuration fallback and actual framebuffer diagnostics. |
| [web_sections.m](../launcher/web_sections.m) | Embedded local web views and native navigation. |
| [mac_zip_reader.c](../launcher/mac_zip_reader.c) | macOS file interposition and loopback-backed disposable asset descriptors. |
| [zip_reader.c](../offline/native/zip_reader.c) | Retained Linux/Android counterpart; not the current Mac launcher adapter. |
| [MovieAgent.java](../launcher/video/MovieAgent.java) | Exact runtime class/method guards and injected bytecode hooks. |
| [MovieDeferred.java](../launcher/video/MovieDeferred.java) | Find queued H.264 SPS/PPS data before opening the video decoder. |
| [MovieOrientation.java](../launcher/video/MovieOrientation.java) | Vertical video texture transform. |
| [KeyboardSupport.java](../launcher/video/KeyboardSupport.java) | Cocos text focus and watcher notifications. |
| [AisWarKeyboard.java](../launcher/video/AisWarKeyboard.java) | W/S held movement profile and text-entry suppression. |

The sync modules retain old device-install branches for reference. The current
`external_assets` mode exposes assets through the virtual ZIP reader and bypasses
those branches. Do not run historical ADB helpers.

The [baseline protocol](../offline/reference/offline_client.py) is a reference
implementation used by the active service. Begin gameplay edits in
[server.py](../offline/server.py); consult the baseline for existing response formats.

## Launch and account scripts

[Launch DanMachi.command](../Launch%20DanMachi.command) starts the Python coordinator.
The [Export](../User%20Data/Export%20User.command),
[Import](../User%20Data/Import%20User.command), and
[Delete](../User%20Data/Delete%20User.command) scripts delegate to
[user_data.py](../offline/user_data.py). Import and delete are real account actions;
they are not test setup commands.

## Regression files

Test names describe the scenario; assertions describe the protected result.
Temporary directories and patched paths keep synthetic fixtures separate from
Averies. Most tests can run with `python3 -B -m unittest discover -s offline -p
'<filename>'`. For launcher-only tests use `PYTHONPATH=launcher` and
`-s launcher/tests`. Prefer the focused commands in the root README when a matching
suite exists. Tests that compare source spelling can need updates after formatting;
check behavior before changing an assertion.

### offline

- [test_album_assets.py](../offline/test_album_assets.py): album includes both thumbnail formats splash and legacy atlas; verified source is reused with a relative visible link; identical art has one physical payload and original paths; wrong payload cannot write success receipt; existing visible copy does not form a link cycle; hash reader drops errors and unsafe paths.
- [test_android_archive.py](../offline/test_android_archive.py): invalid paths and links rejected before android is touched; archive streams directly without allocating a guest copy.
- [test_anniversary_events.py](../offline/test_anniversary_events.py): original map records are unchanged; anniversary box dates match books and preserve contents; all six are open and other tables fields are unchanged; stage dates match episodes without changing unlocks or rewards; anniversary shops and products have no dates only; encrypted catalog and final story script are readable.
- [test_archive_deduplication.py](../offline/test_archive_deduplication.py): virtual paths recover identical media from another phase; catalog cannot reference an external archive.
- [test_asset_cache.py](../offline/test_asset_cache.py): repeat read and eviction preserve bytes; generated asset not cached.
- [test_asset_layout.py](../offline/test_asset_layout.py): extracted copy is reported; only manifests and metadata are allowed.
- [test_asset_store.py](../offline/test_asset_store.py): verified archive read range and changed source rejected.
- [test_audio_profile.py](../offline/test_audio_profile.py): original audio url resolves only to its bound replacement; ordinary assets have no checksum override.
- [test_audio_volume.py](../offline/test_audio_volume.py): full volume requires no key events; low volume uses normal media keys and verifies result; failed or muted volume is not reported as full; no input is sent until game window has focus.
- [test_bundle_check.py](../offline/test_bundle_check.py): non macos host is rejected; non arm host is rejected; older macos is rejected; missing macos service is reported; internal symlink is allowed; external symlink is rejected; broken symlink is rejected.
- [test_connection_release.py](../offline/test_connection_release.py): shutdown waits for connection to disappear; idle connection daemon is released; live device keeps connection daemon; stop also cleans helpers when android is already gone.
- [test_disk_guard.py](../offline/test_disk_guard.py): missing or wrong version never starts android; matching marker allows profile preparation.
- [test_event_box.py](../offline/test_event_box.py): show preserves progress and does not duplicate native box; anniversary draw payment counts rewards retry and restart; invalid and unaffordable draws are atomic; stale client cannot refund payment or undo count and ack finishes recovery; limited prize is never selected after its quantity; original reset prizes gate next round without charging or granting.
- [test_event_item_icons.py](../offline/test_event_item_icons.py): every original event item has both variants; grand day uses its identical rerun art; substitutes are distinct from all neighboring currencies; every shop currency has distinct art.
- [test_familia.py](../offline/test_familia.py): entry search and invitations are valid without remote players; create retry settings and persistence preserve player; messages are local bounded and retry protected; leave rejoin and break are consistent; bad requests and foreign family do not change save.
- [test_gacha.py](../offline/test_gacha.py): retry is durable and charges once; invalid and unaffordable draws leave save unchanged; daily rotation retains standard ticket access; owned result issues original bond; reply separates native grants from result data; ticket charge is durable before native grant; owned historical ticket remains usable offline; retired scratch controls are disabled without asset copies; master contains only current rotation; free limit and token survive stale client push; daily reset preserves one time limits; used free banner hidden until a later rotation returns it; details use original names and actual pool rates; encryption round trip for all scalar widths.
- [test_gacha_balances.py](../offline/test_gacha_balances.py): every retained free offer without iris or tickets; missing iris paid offer rejected without mutation; missing ticket rejected without mutation.
- [test_gacha_bonds.py](../offline/test_gacha_bonds.py): different banners accumulate bonds and preserve spent history.
- [test_gacha_repeat.py](../offline/test_gacha_repeat.py): consumed free repeat replays same operation without mutation.
- [test_gacha_rotation.py](../offline/test_gacha_rotation.py): ten banners with permanent tickets and daily pairs; standard four star ticket draw consumes once and guarantees rarity; used free offer stays hidden same cycle and can return later; tutorial available for new account and not in random rotation; every day in month has matching native dates and two rotating pairs; running session accepts tomorrows offer and rejects expired offer.
- [test_gacha_ticket_access.py](../offline/test_gacha_ticket_access.py): every original ticket has a permanent matching choice; all ticket forms charge only their own ticket and retry once; ticket validity master only changes expiration; every permanent banner has native background and valid pool; start dash can use additional tickets after an earlier draw; native ticket button limits are removed without other record changes.
- [test_game_reopen.py](../offline/test_game_reopen.py): stopped game home is resolved after explicit launch; existing home needs no extra launch; verified persistent profile skips system package changes; locked profile restores support and starts direct boot activity; healthy profile does not start fallback activity; boot retries recovery after android service restart.
- [test_game_window.py](../offline/test_game_window.py): launcher uses windowed landscape that fits game aspect.
- [test_guild_events.py](../offline/test_guild_events.py): current quests have matching available episodes and stages; objectives and event fields outside dates are preserved; all overridden assets are generated and indexed; ais reward box is available with its episode.
- [test_guild_quests.py](../offline/test_guild_quests.py): only monthly and limited dates change; schedule has all categories across year and month rollover; generated assets round trip and catalog sizes; monthly reward claim can repeat next month but not twice same completion; limited batches are bounded and rotate at year boundary.
- [test_inventory_transactions.py](../offline/test_inventory_transactions.py): all inventory types keep other items and spent lifetime totals; stamina and ticket spend commit together and retry; all missions bonus is issued once after last mission; normal and skip rewards aggregate drops and preserve skip cost instruction; interrupted completion recovers once and new skips can reuse token; normal battle reused token uses new entry checkpoint.
- [test_local_downloads.py](../offline/test_local_downloads.py): completion requires original manifest and retained episode; retained manifests and markers are readable without extraction; original voice download list is preserved; boost and event shared image catalogs are retained.
- [test_local_migration.py](../offline/test_local_migration.py): quest support refresh is read only and registered; both original asset urls return the same asset; android rebuild migrates without resetting player.
- [test_menu_pages.py](../offline/test_menu_pages.py): support guards preserve native bindings and other controls; original help route and close guidance; policy index and all documents are local; external urls cannot fetch remote content or inject html; retained policy urls choose the right local document.
- [test_monthly_memoria.py](../offline/test_monthly_memoria.py): memoria claim and legacy retry use memoria channel; all retained memoria rewards and mixed items.
- [test_offline_network.py](../offline/test_offline_network.py): local connection allowed external connections denied.
- [test_play_days.py](../offline/test_play_days.py): days restart gap and backward clock; uninitialized player not created; monthly days include today once and reset next month.
- [test_profile_repack.py](../offline/test_profile_repack.py): duplicate assets share bytes but player files stay independent.
- [test_save_store.py](../offline/test_save_store.py): bootstrap costume repair preserves progress and existing outfits; bootstrap costume repair does not unlock other or locked characters; shop read state merges and persists without losing other products; inventory merges separate falna rewards without losing items; backfill delivered once through native stage completion; achievement rewards are native persistent and idempotent; stamina mission does not display or grant iris; legacy attack repair preserves training and does not repeat; familia quest notification persists without fake rewards; town refresh deletes old conversation and keeps replacement; stage completion uses native operation once per session; reward backfill is native persistent and not reissued; story completion without combat checkpoint; consumed resources are replaced and persisted; friendship milestones persist without duplicate claims; pc checksum matches observed original client; tutorial draw is persistent and once per account; area identity retains other areas; episode difficulty updates keep other episodes and survive reopen; exp item rewards merge by account item and survive reopen; stage updates preserve other stages; wire singletons and collections; unsigned large ids; restart and reset.
- [test_save_updates.py](../offline/test_save_updates.py): invalid request preserves disk and prior snapshot; duplicate request skips disk write and preserves progress; day resources and banner updates do not change previous snapshot.
- [test_session_shutdown.py](../offline/test_session_shutdown.py): new window wins; client stops and flushes before backend; late audio failure recovers display and keeps game; unhealthy android still stops backend.
- [test_shooting.py](../offline/test_shooting.py): completion validates original playable characters without extra grants; native score coin unlock updates persist without duplicate rows.
- [test_startup_cache.py](../offline/test_startup_cache.py): costume changes require assets but training does not; source and roster changes invalidate; broken receipt reverifies.
- [test_storage_maintenance.py](../offline/test_storage_maintenance.py): only named diagnostics and cache are touched; only oversized compilation cache is cleared; small cache stays intact; temporary cleanup preserves unknown files and symlink targets; symlinked temporary folder is not cleaned.
- [test_tutorial_banner.py](../offline/test_tutorial_banner.py): reservation and restart are not completion; row remains until native ack and is not duplicated.
- [test_tutorial_starter.py](../offline/test_tutorial_starter.py): native grant is stable and does not mutate save; owned character or completed tutorial never granted; requires expected party and stops after ack.
- [test_tutorial_weights.py](../offline/test_tutorial_weights.py): exact beginner group positive weight; encrypted virtual asset round trip.
- [test_user_data.py](../offline/test_user_data.py): round trip and asset path rejection; modified payload rejected before pausing current player; archive links rejected; short safe name and collision; named export contains checked summary and is importable; roundtrip delete and failed import rollback.
- [test_zip_reader.py](../offline/test_zip_reader.py): paths reject traversal and unrelated files; alias priority index size and unmodified stream; changed archive metadata is rejected; missing dialogue cutout is read from zip with phase alias.
### launcher/tests

- [test_grand_day_dispatch.py](../launcher/tests/test_grand_day_dispatch.py): entry stage belongs to original orario page; guarded original flow and complete native reversal.
- [test_monthly_pass.py](../launcher/tests/test_monthly_pass.py): monthly gate patch preserves the guarded native build.
- [test_runtime_logs.py](../launcher/tests/test_runtime_logs.py): split error survives large backtrace and logs stay bounded.
- [test_save_exit.py](../launcher/tests/test_save_exit.py): checkpoint preserves latest progress and pending operations; close requires server confirmation and preserves client files.
- [test_title_return.py](../launcher/tests/test_title_return.py): confirm callback exits to launcher without teardown.
- [test_tutorial_setup.py](../launcher/tests/test_tutorial_setup.py): first account reload is delayed once and preserves state; existing account never reloads; normal native grant cancels reload.

Native diagnostic sources (separate from live adapters):

- [keyboard_geometry.m](../launcher/tests/keyboard_geometry.m)
- [web_sections.m](../launcher/tests/web_sections.m)
- [stencil_buffer.c](../launcher/tests/stencil_buffer.c)
- [AisWarProbe.java](../launcher/tests/AisWarProbe.java)

## Historical test limits

Full `unittest discover -s offline` also collects older checks outside the current
focused Mac suites. The following files expect retired device controls or missing
helper modules; their headers now explain the dependency:

- [test_asset_layout.py](../offline/test_asset_layout.py): expects the removed loose_asset_problems bundle-check helper.
- [test_audio_volume.py](../offline/test_audio_volume.py): depends on the retired launcher/audio.py device helper.
- [test_connection_release.py](../offline/test_connection_release.py): expects the retired device/ADB process controls in launcher/game.py.
- [test_disk_guard.py](../offline/test_disk_guard.py): expects the retired emulator AVD profile controls.
- [test_game_reopen.py](../offline/test_game_reopen.py): expects retired device activity/boot controls rather than the Mac launcher.
- [test_profile_repack.py](../offline/test_profile_repack.py): depends on the removed repack_profile module.
- [test_session_shutdown.py](../offline/test_session_shutdown.py): depends on the retired session module.
- [test_startup_cache.py](../offline/test_startup_cache.py): depends on the retired startup_cache module.
- [test_storage_maintenance.py](../offline/test_storage_maintenance.py): depends on the removed launcher/storage.py utility.

Two cases in [test_save_store.py](../offline/test_save_store.py) require the absent
`offline/compatibility_assets/native-pc-checksum-fixture.json`. Existing source was
preserved; no checksum fixture was invented. These limits mean broad discovery is
not currently a clean all-green gate. Use the focused Mac checks for current
features, and keep missing historical coverage visible when investigating bugs.

## Consistent formatting

Python uses Black with the Python 3.10 target and 88-character lines, recorded in
[pyproject.toml](../pyproject.toml). C, Objective-C and Java use
[.clang-format](../.clang-format), with four-space indentation, 88-character lines,
and include/import order preserved. Formatters are optional development tools;
the bundled game Python does not depend on them.

With those tools installed in a separate development environment:

```sh
black --check offline launcher tools
clang-format --dry-run --Werror launcher/*.m launcher/*.c launcher/video/*.java offline/native/*.c
```

Use `black <changed-file.py>` or `clang-format -i <changed-file>` to apply formatting.
Keep comments about *why* a rule exists, what data it reads/writes, and what callers
must preserve. Avoid comments that merely repeat a statement. Update the reading
guide when a module gains a new responsibility, and the feature recipe when behavior
changes. Keep generated catalogs, original APKs, archives, runtime libraries and
player saves outside formatting passes.
