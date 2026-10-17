# DanMachi: working setup and maintenance handoff

Last updated: **12 October 2026**, America/New_York.

This is the current working baseline for future maintenance prompts. Read it before changing the game. `launcher/README.md` contains additional history, including configurations that have since been superseded. For implementation details, the current code and `offline/apks/build.json` are authoritative. Update this document after a change has been validated; distinguish verified behavior from estimates and untested features.

## Current status

- The user reports the game is working well. The final shortcut repair passed two independent cold launches through **DanMachi Offline.app**, opening the game window in **22.2 and 21.7 seconds**. Reopening while running reused the existing window in **2.1 seconds**.
- The title and Orario lobby rendered at the current smaller resolution. Gacha also rendered at that resolution. Closing the game window was verified to flush the save and stop the background runtime.
- Ten focused boot/reopen/window/shutdown tests passed after the shortcut repair. The last complete folder check verified **715 required files** and **86,858 indexed asset mappings**, with no external asset references and all disk backing files inside this folder.
- The last maintenance turn left the game window open. This is a historical observation, not a guarantee that it is currently running; inspect processes/logs when needed.
- The folder measured approximately **10.901 GB** in logical file bytes when this document was created. Asset archives account for **8.148 GB**. Sizes vary as Android writes its profile and logs; this is not a fixed storage ceiling or a measure of cloud-sync completion.

## What this application is

The retained original game runs inside a minimized, folder-local Android 11 ARM64 environment on an Apple Silicon Mac. It is **not a native Mac port**. The installed retained game reports version **15.1.0**; the earlier conversation's 5.1.0 description does not describe the currently retained APK.

The APK's original native game library remains intact. Local modifications provide offline responses, direct access to existing ZIP assets, and a Java renderer frame limit. Exact APK/member hashes and modifications are recorded in `offline/apks/build.json`; do not replace those files with an unrelated APK version.

The verified host is an M2 Pro Mac with 16 GB memory and macOS 26.6.2. The bundled backend supports Apple Silicon macOS. It has not been verified on Intel Macs, Windows or other platforms. OS services such as Apple's hypervisor, audio, graphics and `/usr/bin/sandbox-exec` remain host requirements; “folder-local” does not mean it contains macOS itself.

## Important files and folders

| Path relative to this folder | Purpose |
| --- | --- |
| `DanMachi Offline.app` | Normal double-click entry point; its executable locates the surrounding folder and invokes the bundled Python launcher. |
| `launcher/game.py` | Boot, offline bridge, installation verification, game-only policy, window/audio and explicit shutdown. |
| `launcher/session.py` | Watches the display window and stops the background runtime after it closes. |
| `launcher/offline.sb` | Offline connection guard used for the emulator and local server. |
| `launcher/storage.py` | Bounds diagnostics and clears only oversized disposable game caches. |
| `launcher/check_bundle.py`, `launcher/bundle-files.json.gz` | Required-file inventory, executable permissions, asset and disk-backing portability checks. |
| `offline/android-game-only.json` | Removed/disabled Android package policy. Current launcher policy revision: `game-policy-v8`. |
| `offline/server.py`, `offline/save_store.py` | Local game responses and persistent player state. |
| `offline/gacha.py`, `offline/gacha-catalog.json.gz` | Offline draws and the reconstructed archived-banner catalog. |
| `offline/zip_reader.py`, `offline/native/` | External ZIP lookup and native asset-reader support. |
| `offline/apks/` | All six matching, locally signed APK splits and their build record. |
| `assets/archives/` | Downloaded media are read directly from the seven ZIPs; aliases preserve shared logical paths. No extracted copies. |
| `contents/` | Sixteen required phase manifests only; these are metadata, not media copies. |
| `state/offline/player-state.json` | Host-side persistent player state; not a disposable cache. |
| `state/offline/asset-sources.json.gz` | Original asset-to-archive mappings; required for local asset lookup. |
| `state/avd/DanmachiPlay.avd/` | Persistent Android profile, base/backing disks, writable overlays and version marker. |
| `runtime/` | Bundled Python, Android emulator/system image, dedicated ADB and scrcpy display/audio bridge. |
| `User Data/` | Existing player export/import/delete tools. Use export/import rather than improvising a partial save backup. |

## Startup and shutdown sequence

1. The app runs `runtime/python/bin/python3.10 -B launcher/game.py --offline`. Logs are written inside the folder.
2. The launcher validates the backend, holds its launch lock and starts the local offline server. It updates folder-specific paths in the Android configuration so relocating the entire folder is supported.
3. It starts or reuses the `DanmachiPlay` profile and establishes the local connection bridge. Before waiting for boot completion, it restores the boot support described below.
4. It verifies the installed APKs against the folder copies. Normally no reinstall is needed. External ZIP mode skips extracting game assets into Android.
5. It applies the game-only policy, starts the original game activity and opens/reuses the scrcpy window. The launcher sets Android media volume to full so the Mac controls output volume.
6. The window watcher handles normal closure: force-stop the game, maintain bounded caches/logs, request unused-filesystem-block trimming, sync the disks, stop the emulator/server and release the dedicated ADB daemon when unused. No startup snapshots are retained.

### Critical cold-boot fix: preserve this lifecycle

The game activity is **not directBootAware**. Android can list its installed package while refusing to launch the activity until user 0 is unlocked. Permanently disabling Settings prevents its **FallbackHome** boot activity from supplying the first activity Android needs to finish booting. Symptoms include user 0 stuck in `BOOTING`, an empty `sys.boot_completed`, “Activity class … does not exist,” and a startup timeout despite the APK being installed.

`restore_boot_ui()` temporarily enables the Settings package during unfinished boot and explicitly starts `com.android.settings/.FallbackHome` **before** waiting for `sys.boot_completed`. Once Android unlocks, `game_only()` disables Settings again for play. SystemUI remains enabled for core boot support; immersive mode/status-bar flags hide its phone controls. The Google onscreen keyboard remains disabled.

**Do not remove Settings from the system image, permanently disable its boot activity, disable SystemUI indiscriminately, or move this recovery after the boot-complete wait.** Individual Settings activity disabling was rejected by this Android build, so the working solution manages the package state across boot and play. During gameplay, seeing Settings in `pm list packages -d` is expected; that alone does not mean the next boot will fail.

## Current performance configuration

| Setting | Working value |
| --- | --- |
| Android render size / density | **800 × 450 / 120** |
| Android display pacing | **24 Hz** |
| Desktop window | **1280 × 720**, scaled from the render size |
| Display-stream limit / video bitrate | **24 fps / 4 Mbps** |
| APK Java Cocos renderer maximum | **30 fps** |
| Android configured memory / CPU cores | **2048 MB / 4 cores**; these are configuration values, not measured total host memory use. |
| Graphics | **`swangle`**, ANGLE with SwiftShader software rendering; `asg` transport. |
| Emulator mode | Headless, no snapshot, no boot animation, no metrics, no SIM; Vulkan and multidisplay features disabled. |

The smaller render has about 31% fewer pixels than 960 × 540. Text/art are softer and 24 fps motion is less fluid than 60 fps. Short CPU samples were variable; no sustained temperature or exact battery-life improvement has been established. Hardware CPU acceleration is available through Apple's hypervisor, but compatible software graphics still does substantial CPU work.

**Do not switch to the lighter host graphics mode solely to reduce heat without testing Story rendering.** Earlier host graphics trials corrupted Story/video textures. Required ANGLE/SwiftShader libraries and their ICD configuration are retained for that reason. Bell Pt.2's intended layout and opening story rendering were verified in earlier work; the entire story/battle and all later scenes have not been certified under every subsequent configuration.

## Offline assets and Gacha

Assets are served from existing archives without making full extracted copies. The ZIP reader handles native path aliases and reconstructs certain missing label-only layouts in memory using retained sprite labels. Current master-data adjustments are also made in memory. Preserve the mapping catalog, manifests and original archives together.

Gacha rotates **429 supported archived banners**, showing six Iris banners and two ticket banners per day. Reopen the game to refresh the batch. Only the current batch is enabled in memory; enabling the entire history at once previously overloaded texture memory. Native free eleven-unit draws, ticket single draws and an earned-Iris single draw reached the original reveal/result screens, including duplicate bonds and ticket consumption. Not all 429 banners or special variants have been individually tested.

Original server probability weights are absent. Offline selection is uniform within the applicable retained pools, with reconstructed fixed-pick/milestone guarantees; it is not the original live-service probability distribution. Normal paid-currency draws use earned Iris. Historical daily paid discounts, scratch promotions, purchases and online events remain unavailable. Old dates/promo text printed in artwork can remain visible. Full gameplay and some Interact behavior remain incompletely verified.

For draw maintenance, preserve these tested details:

- Durable reservations, bounded progress/last-draw storage, pending native grants and retry protection must prevent double charges.
- Native results must include `lotteryPCs` in `operation.parameters`; an outer reply alone previously crashed the reveal.
- Do not put new characters/bonds in generic `data` before the native grant handler; that previously applied characters twice.
- Preserve all original `lotteryScratch` associations and Scratch master data. The working in-memory patch sets attachment `buttonType` to zero. Emptying these tables caused assertions/save errors.
- Normal master columns 20 and 30 correspond to button types 2 and 3; button type is not determined by pick count.
- Tickets use their original `dateList`, expiry and misspelled `aquiredAt` fields, not an invented amount field.

### Gacha maintenance, 12 October 2026

The catalog now stores shared member indices (33,910 bytes, previously 49,129), retaining the same 429 banners and pools. Gacha Details builds HTML in memory from the original PC master: English names/titles, base rarity (column 46), per-rarity and per-unit offline rates, eligible normal/guaranteed/milestone pools and selected-unit overrides. These are actual uniform offline rates, not recovered historical server weights. All 429 detail pages generated successfully and 14 focused tests passed. Native Details opened, and an eleven-unit test draw reached the original results screen with units and duplicate bonds.

Draw reservations now update the UserLottery token, and delayed client pushes cannot overwrite durable consumed counts. UserLottery is kept in native draw parameters rather than pre-applied generic draw data; push replies repair it only when it differs from the authoritative state. **The native menu/result screen still displays an available free pull / Draw Again after a consumed one. This UI issue remains unresolved; do not describe it as fixed.** A second distinct request is blocked by the saved draw limit; retrying the same request returns the same reservation without another charge. Daily-marked buttons reset on the JST day boundary. Consumed free banners now leave the rotation on the next full game launch, as requested by the user; their slots fill from the remaining archived banners. The launch freezes its banner list to match the native cached master, so replacement does not happen on the current result screen. Free Iris banners can return with a fresh pull after the full 26-day Iris rotation cycle; consumed counts remain authoritative within that cycle. A focused test verifies replacement, same-request retry protection and later return. The four already-used free banners (171000449–171000452) are excluded from the next launch. No live draw was made during this rotation change; player progress was untouched.

The user requested wrapping up before further native diagnosis. Test progress and Android profile changes were restored from this turn's stopped-profile backup. No asset extraction or permanent HTML copies were added. The game was left stopped for a consistent cloud copy. Recent disposable diagnostics were trimmed; the final measured folder was smaller than this turn’s 10,901,911,773-byte starting size.

### Gear-menu maintenance, 12 October 2026

The installed menu patch changes only `Cocos2dxHelper.openURL` and `Cocos2dxWebViewHelper.loadUrl` in `classes3.dex`. Other Java methods retain their semantics; the assembler omits equivalent default false/null field initializers. APK member comparisons confirm native libraries and assets are unchanged. `offline/native/offline-menu.patch` records the method edits, and `offline/apks/build.json` records the new APK/member hashes and policy-source provenance. All six matching signed splits remain together; no Android browser/app was added.

Help now serves a local guide at the original `/content` route. External browser links show an offline information dialog rather than attempting a missing browser. External native WebView URLs redirect to `/offline/page`; TOS has compact local copies of WFS Terms of Use, Privacy Policy and In-app Currency Terms retrieved on 12 October 2026. They are stripped of remote scripts/styles/media and served with a restrictive content policy; viewing does not accept a new agreement. The three policy documents occupy 17,255 compressed bytes. Local pages do not modify player data or contact outside servers. Online support/social feeds/cloud-account transfers are not recreated; use the existing User Data commands for local export/import.

In-game verification completed: Inventory, Story Digest, Profile and Change Hero screens rendered; original story locks remained; Voice Management rendered and reported no extra data to download; Settings opened with the existing sound/display preferences; News displayed the local notice; repaired Help rendered and closed cleanly. No currency was spent, no draws were made and no new hero was selected. Some first-visit tutorial overlays were dismissed. Four menu-page checks, fourteen Gacha checks and two local-migration checks passed; all six APK hashes/signatures passed and the folder checker verified 719 required files and 86,858 mappings. The Mac locked before final TOS/Contact/SNS/Import/Alarm/AIS WARS/To Title UI checks; these are still pending. Alarm Clock is gray in the retained Europe build; do not claim its alarm scheduling works. The game was left stopped while the Mac was locked. The folder measured about 10.922 GB after trimming disposable logs. The main APK decreased by 36,864 bytes, but the reinstall and Android writes increased the overall folder by about 20 MB; do not claim an overall decrease. Ordinary and compressed QCOW conversion candidates passed full-image comparison but saved too little to offset this, so neither was applied and both temporary candidates were discarded.

## Safe maintenance and verification

Prefer small, reversible changes. Preserve the user's current progress, keep all required runtime/game files in this folder, and avoid archive extraction, permanent test copies or accumulating logs. Ask before destructive player/file removal. A proposed native port or different compatibility layer is separate work, not an automatic replacement for this working setup.

Run maintenance commands **from this folder**. These are references; reading this document does not request running them.

```sh
# Explicit clean shutdown before disk maintenance or a cloud copy:
runtime/python/bin/python3.10 -B launcher/game.py --stop

# Validate the folder and original asset/backing references:
runtime/python/bin/python3.10 -B launcher/check_bundle.py

# Refresh the inventory only after intentional changes are understood:
runtime/python/bin/python3.10 -B launcher/check_bundle.py --inventory
```

Refreshing the inventory is not proof that a modified APK or runtime is correct. Preserve build hashes, run the relevant functional checks, then update the inventory. Unused bundled Python development helpers, including `unittest`, were pruned; use the host's development Python for tests, not the slim bundled runtime:

```sh
python3 -B -m unittest discover -s offline -p test_game_reopen.py
python3 -B -m unittest discover -s offline -p test_game_window.py
python3 -B -m unittest discover -s offline -p test_session_shutdown.py
```

For launch changes, test the actual `.app` shortcut through at least two clean cold launches, reopening while already running, and normal window closure. For graphics changes, additionally check Orario, Gacha, Album and Story/video rendering. Preserve the current player data when testing draws or grants; synthetic credits and test units must not remain in the user's save.

The prior broader suite passed 80 of 82 tests. Two older checks lack `offline/compatibility_assets/native-pc-checksum-fixture.json`. That fixture failure is a known historical limitation, not proof of a new runtime regression. Do not fabricate a fixture to conceal it.

## Troubleshooting and data protection

- Start with `state/logs/application.log`, `launcher.log`, `emulator.log`, `game-window.log` and `offline-server.log`. Identify the actual failure before reinstalling anything.
- Game package/activity: `com.eu.danmore/net.wrightflyer.toybox.AppActivity`. AVD: `DanmachiPlay`. Device: `emulator-5560`. Dedicated ADB port: **5038**. Emulator ports: **5560/5561**. Host offline server: **28767**; Android uses **28766** through the reverse bridge. Preserve this separation from other emulators/ADB servers.
- Android reports “Activity does not exist” while the package is installed: check boot completion and user unlock first. It can be a boot-state problem, not missing APK files.
- Keep all six APK splits together and use the existing verification/install routine. Installing only the base APK can remove required native splits. All splits must retain matching signatures.
- Preserve `qemu-version.txt` with content **`2`**. Missing/incompatible markers can make the emulator recreate disks; the launcher deliberately refuses that condition.
- Never edit, convert or replace a live Android disk. Confirm the emulator has exited first. Do not delete a QCOW2 overlay/backing image to “clean the cache.”
- Previously tested lossless compaction used the bundled `qemu-img` to convert the stopped userdata overlay, then required successful full-image comparison and disk check before replacement. Its backing file is **`userdata-qemu.img` in QCOW2 format**, referenced relatively. The bundled QEMU 2.12 converter uses `-o backing_fmt=qcow2`; its convert command does not accept `-F`. Compaction reclaimed little space in recent checks; do not promise major reductions.
- A complete player backup includes both host player state and Android private account files/databases/preferences. Backing up only `player-state.json` is not sufficient for every restore.
- Stop the game before uploading/copying the entire folder. Keep disk backings relative and inside it, include hidden/support files, wait for cloud files to be available locally, and run the folder checker on the destination Mac. Do not assume a running-disk copy is consistent or that a local size check proves successful cloud upload.

## Native Mac options: not part of the current setup

No native port or Mac.apk installation was performed. A full port would need original source or substantial compatibility/reimplementation work, including native graphics, input, audio, assets, saves and offline behavior. Exact FPS, RAM usage and minimum requirements are unmeasured; 720p at 30 fps was discussed only as an initial prototype target. Most of the retained asset storage would remain.

Mac.apk was researched as an experimental alternative that runs APKs on Apple Silicon without booting Android and uses the Mac GPU. Its published requirements include Apple Silicon and macOS 26.4 or newer. DanMachi is not listed in its tested compatibility table. Compatibility with this modified APK, external ZIP reader, local server, saves and whole-folder portability is unverified. Recheck current documentation before proposing a trial: https://github.com/kksimp/Mac.apk-Releases

## Future handoff checklist

After validated maintenance, update this document with the changed behavior/settings, preserved save, checks actually performed, remaining limitations and storage outcome. Keep historical measurements dated. Do not replace evidence with guarantees such as “every launch,” “all assets,” “exact original odds” or “fully offline forever” unless the relevant scope has actually been demonstrated.

### Generated-file containment — 2026-10-12

The app shortcut now changes to its enclosing DanMachi directory before starting Python. Both entry scripts and launcher children route TMPDIR, TMP and TEMP into state/temp, regardless of the caller’s directory or inherited temporary paths. Android homes, subprocess working directories, logs and default save exports were already folder-local. The retired archive-pruning utility now refuses without writing or deleting anything; its old implementation exported discarded assets into Downloads/danmachi-other and is no longer available. It was not invoked by normal startup and already rejected the current shared-archive layout, so it is not established as the cause of the reported loose Drive files.

Validation: ten existing reopen/window/shutdown tests passed, shell syntax passed, the retired utility refused without writes, and both cold starts through the actual app reached Android boot-complete and “Game opened.” Normal window closure flushed the save and automatically stopped the background environment, confirmed in the launcher log despite the UI observation timing out. A final explicit stop confirmed shutdown. The full bundle check passed for 719 required files and 86,858 indexed assets. No extra game files appeared beside DanMachi during these starts. No existing user files or progress were deleted. This does not prevent Google Drive itself from creating sync conflict copies; the reported filenames were unavailable and that cause remains unconfirmed. Changes replace existing code and remove approximately 4 KB of obsolete pruning code, with no new assets or runtime packages. Android startup can still update its existing writable disks.

### Startup recovery and automatic disposable cleanup — 12 October 2026

Observed failure: the previous emulator boot completed after 283 seconds, past the launcher’s 240-second startup deadline; a subsequent launch succeeded. The launcher previously checked boot support only once after Package Manager became available. It now retries direct-boot support every five seconds while boot is unfinished, tolerating transient service restart errors. Settings is still disabled during gameplay. Existing launcher locking and replacement-window protection remain in place.

Shutdown now removes known temporary products in state/temp only after the emulator, save server and dedicated ADB are stopped. Candidates are adb.*.log, .DS_Store and Python tempfile names (tmp plus eight characters); unknown files and symlinks are preserved. User Data operations use the same launcher lock. No outside-folder duplicate guessing/deletion is performed. Runtime diagnostics are bounded to 16 KiB with recent lines retained; existing Android cache thresholds remain unchanged. Saves, APKs, archive assets, backing disks and user exports are preserved. The smaller overlay was generated with compressed lossless QCOW2 conversion while stopped, verified by disk checks and full virtual-content comparison before and after replacement, with relative backing retained. It reclaimed 2,145,792 bytes. An initial comparison attempt had an unavailable relative backing in the temporary directory and automatically restored the original; the corrected conversion/verification then passed. Temporary conversion files were discarded.

Verification: 19 focused boot-recovery, disk-guard, window, shutdown, storage-boundary and offline-network tests passed. Storage tests verify preservation of unknown files and external symlink targets. Two cold starts reached rendered title screens in roughly 24 and 21 seconds; the second followed immediate close/reopen while shutdown was finishing. Reopening while running retained the existing window. A third cold start after disk compaction reached the title screen in about 22 seconds. Normal window closure flushed progress, stopped workers and left state/temp empty. The bundle check passed for 719 required files and 86,858 indexed assets. No draw, currency spend or gameplay progress change was made.

Final logical size at this measurement: 10,925,138,092 bytes (10.925 GB). Android disk writes and legitimate saves can still change this size. Cleanup bounds known disposable output, but cannot guarantee that storage never grows, that all future launches succeed, or that Google Drive never produces sync conflict copies. Large required compressed assets were not removed.

### Asset layout audit and Android panel suppression — 12 October 2026

Use the actual folder name **assets/** (plural). Downloaded phase artwork, voices, music, movies and models belong in the seven ZIPs under assets/archives/. Preserve aliases.json.gz and state/offline/asset-sources.json.gz; they allow multiple logical paths to share a single payload. Do not extract ZIPs into contents/, Android storage, the Drive parent, or a new assets copy. The 86,858 phase mappings were audited: 86,825 point into assets/archives ZIPs, and 33 required bootstrap mappings read directly from the original compressed APKs in offline/apks/ (32 in the main APK and one theme in AssetPack1.apk). The virtual archive catalog additionally covers shared media.

It would be inaccurate to say literally every asset is in assets ZIPs: the original APKs contain required bootstrap resources; small Mac display icons remain in assets/ui/ and runtime/game-window/. These are functional exceptions, not downloaded media extraction folders. The sixteen host contents/*.manifest files are required metadata. Android’s files/contents contains only startup manifests, including its generated project.manifest.temp; the installed APK copies are required by Android. These do not constitute an extracted downloaded media library. Save data, caches, generated in-memory layouts, policy documents and source code are also not duplicate media.

The only loose downloaded media found in the host contents tree was the 6,048-byte Loki voice clip voice_cl_lok_q01_st10_hes_013.ogg. Its bytes exactly matched its retained ZIP member; the loose file and empty ancestor directories were removed, and the archive reader successfully returned the clip afterward. Folder validation now reports unexpected loose files under contents and refuses indexed sources outside the retained ZIPs or the two explicit bootstrap APKs. It permits the required manifests and Finder .DS_Store metadata. This is an audit/check, not automatic deletion of unknown user files.

Maintenance documentation now lives in launcher/: CURRENT_SETUP.md, AGENTS.md, ASSETS.md, USER_DATA.md and README.md. Root AGENTS.md is a short discovery pointer so future agents find these instructions. References and relative command guidance are from the project root.

The existing primary status-bar flags persist after startup but do not disable the secondary quick-settings/notification-shade features. The existing scrcpy Android display server now holds a StatusBarManager reference and applies disable2(0x1f) before opening the display connection. The persistent Binder token disables quick settings, notification shade, status icons, power/global-actions UI and rotation suggestions for the display server’s lifetime. This uses its existing shell permission and process, adds no app or watcher, and removes no boot-critical SystemUI component. The server archive decreased from 733,930 to 719,910 bytes; all non-DEX members remained byte-identical. Source instructions and before/after hashes are in launcher/statusbar.patch. Android 11 flag definitions were checked against the AOSP StatusBarManager source. A temporary screen-pinning experiment was stopped and is not part of the final setup.

First-session validation: Android reported mDisabled2=0x1f; title and Orario lobby rendered; top-edge downward drags on both screens did not reveal a gray Android panel. Voice-from-ZIP, asset-layout checks, archive-reader tests, reopen/window tests and offline network checks passed (14 tests). Full folder validation checked 722 required files and 86,858 indexed mappings. No draw, currency spend or user export deletion was performed. Keep SystemUI for boot support; the UI functionality is disabled during play rather than physically deleting Android framework code. Do not claim this is a guarantee against every future Android overlay or failure.

Second cold-start verification: the title rendered again and Android reapplied mDisabled2=0x1f with the display-server-owned Binder token; screen pinning remained NONE. The second gesture retest was blocked by the computer-control tool’s noWindowsAvailable error despite the running window being observable; the first-session title/lobby gesture checks above remain the direct interaction evidence. The game was then explicitly stopped cleanly. Flag definitions: [Android 11 StatusBarManager](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android-11.0.0_r1/core/java/android/app/StatusBarManager.java).

Final stopped-folder measurement was approximately 10.927 GB (10,926,852,559 logical bytes before this note). The verified loose-media removal and server replacement saved 20,068 bytes in those files; Android writes during validation increased the overall folder by about 1.7 MB relative to the previous stopped measurement. No overall storage reduction is claimed for this turn. Final folder check passed for 722 required files and 86,858 mappings; contents contained exactly 16 manifests and state/temp was empty.


### Dialogue face placement — 12 October 2026

Lefiya’s normal dialogue portrait displayed its expression detached from the head in the Orario greeting. Three original positioning files were present in the retained ZIP but absent from the phase asset index because their archive MD5 differed from the manifest: lef_normal, dio_normal (Dionysus), and dem_normal (Demeter), each under character/novel_portrait. The ZIP reader now exposes these missing original cutout.plist files through its in-memory catalog, including the existing phase-one aliases. It validates the portrait name, matching indexed body, original plist fields, positive dimensions and coordinates within the body PNG; archive size and CRC verification remain in use. Existing indexed records take precedence. Original coordinates are read from the ZIP, not hardcoded or redrawn.

Verification: 13 focused ZIP-reader, asset-store, asset-layout and Album tests passed. The new regression checks both phase aliases, unchanged original bytes/body and rejection of mismatched or out-of-bounds metadata. After restarting, the live server returned all three original position files byte-for-byte. The user reopened the same Lefiya lobby greeting and visual inspection confirmed that her face now aligns correctly with her head. Story uses the same corrected dialogue portrait lookup, but a separate Story scene and the Dionysus/Demeter dialogues were not visually tested. The game was left open at the verified greeting.

No artwork was extracted or changed; no APK, persistent asset index, manifest or save was edited. Only existing reader code, its regression test and this maintenance note changed, adding a small amount of text rather than asset copies. Legitimate Android disk writes can still change the overall folder size. Refresh the bundle inventory after maintenance documentation edits.


### Hestia Interact outfit consistency — 12 October 2026

Observed Hestia’s Outfits page with a completely empty list while her basic model still rendered. The saved UserCommunicationCharacter bootstrap references her basic costume 1022027000, but UserCharacterCostume lacked that record. Among all current communication entries, only this Hestia costume was absent from ownership. All 394 characterCostume master models had both skeleton and atlas available through the ZIP reader; relevant communication UI and Hestia model manifest assets were indexed.

SaveStore.repair_bootstrap_costume completes only the original offline bootstrap’s already-selected Hestia basic costume for an unlocked Hestia entry. It preserves existing costume states and other progress, adds no alternate outfits, and updates the costume table token so the client pulls the correction. The server applies it after initial bootstrap and local reset. Twenty save tests passed, including two new tests for persistence/idempotency, preservation and refusal to unlock other/locked characters. Two older checksum tests remain unavailable due to the previously documented missing native-pc-checksum-fixture.json. The restarted server persisted the single missing basic-costume record. Visual inspection after the user reopened Outfits confirmed the Basic Outfit row, thumbnail and description now render. The user pressed Back and reported normal return; the resulting screenshot confirmed Hestia’s Interact menu and greeting rendered normally. Other characters were audited for missing current-costume ownership but not individually tested through the UI. The game was left open. No media extraction or asset copies were added; code/test/document text and the small missing save record increase bytes slightly.


### Title Support cache/download guards — 12 October 2026

The original Clear Cache confirmation offers removal of story caches and optionally other downloaded content, followed by data downloads; Full Download requests all story assets, skipping content the original downloader considers present. Neither operation is appropriate for the external ZIP layout. The ZIP reader now transforms only three small title layouts in memory: modal_support_top removes the Clear Cache and Full Download controls from the accessible display/touch area, and modal_cache_clear_confirm/modal_novelasset_dl_confirm similarly make their affirmative buttons unreachable. Required native tag nodes remain present to preserve bindings, moved to (-8192,-8192) with zero opacity. Cancel/close and all other Support controls remain unchanged. Original ZIP members, APKs and manifests are untouched; no permanent layout copies are written. The native index advertises the transformed byte size while archive reads preserve the original CRC/size.

Import Data was inspected through its Google/Facebook/Import Code choices and blank code/password form, then cancelled without entering or submitting credentials. It is the old online transfer flow, not User Data/Import User.command. Existing local billing migration responses retain host player tables; no transfer can retrieve the old publisher account. Delete Account’s retained original layout tells users to request deletion through publisher contact, with external links already intercepted by the offline-menu patch. No deletion, cache clearing or full-download action was executed. After restart, the user opened Support and visual inspection confirmed both cache/download controls absent, with the remaining controls intact. Delete Account opened its English information dialog, explicitly directing deletion requests to the publisher contact form; it was closed without activating its final button. Import Data and Delete Account were left unchanged as requested for harmless options. Their final actions were not executed; the account-delete contact behavior is supported by the retained dialog and existing external-link interception, not a destructive live test. The game was left open at the title screen. Five menu-page/guard tests and four ZIP-reader tests passed, including retained bindings, unchanged unrelated controls and correct transformed length. The running server served all three protected layouts with matching Content-Length. Text code/test/document bytes increased slightly; no assets or runtime packages were added.


### Quest team-formation Support endpoint — 12 October 2026

The original Support button requested /api/game_client/friend/support/list, which was not registered in the offline server and failed as an unknown route. The retained native DomainSupporterDataRepository identifies the root supporters field. The server now registers this read-only action and returns code 0, supporters [] and is_fullset true. This represents no remote player loan units in offline mode; it does not fabricate friend accounts, grant units or alter formation/save tables. Existing local party members remain available. This fix restores the request/menu path, not a community service or newly generated NPC helpers.

Three local migration/support tests passed, including route registration, repeated refresh and unchanged saved tables. Two requests to the restarted real server returned HTTP 200 with the native success header and valid empty-list payload. After the user reopened an Episode level’s team formation and pressed Support, visual inspection confirmed SELECT SUPPORT rendered without a server error: My Deck and three level-two adventurer/assist pairs appeared through the original client’s local choices. No invented friend records or NPC data were sent by this fix. Selecting a support and entering a battle were not tested, and no battle, stamina spend or formation change was performed by the agent. The game was left open at Select Support. Existing server/test/document files were edited; no artwork, APK or new runtime files were added. Small text edits increase bytes slightly; normal Android writes may also change disk size.


### Hover bar and modest FPS increase — 12 October 2026

The display pacing and stream limit now target 24 fps (previously 20); the APK ceiling remains 30. This prioritizes the user's clarified low-heat preference over the original 60 fps request. Render resolution, software GPU, audio and assets remain unchanged. The scrcpy --no-mouse-hover option suppresses mouse motion without clicks, preventing the Android top-edge hover trigger and avoiding those input messages; clicks and drags still work. Existing notification-panel blocks remain. Normal Mac window decorations/close controls are retained. A temporary borderless-window/SystemUI-disable experiment was reverted: disabling the package did not stop its persistent process. SystemUI is enabled; boot support remains unchanged.

Eleven existing window/reopen/shutdown tests passed. Android reported a 24 Hz display mode during the first test launch. macOS reported no recorded thermal warning, but this is not a temperature measurement or proof of cooler operation. Sustained heat and achieved gameplay FPS remain unmeasured; 24 fps can still require more rendering work than 20. No APK, asset, runtime package or permanent extracted copy was added. Ordinary Android disk writes can increase folder bytes during validation; no fixed storage ceiling is promised.

The final hover configuration cold-launched twice through the actual app (about 22 and 21 seconds to launcher readiness); the first reached a rendered title without the Android strip, and normal window closure flushed the save and stopped workers. A direct pointer-hover sweep could not be automated by the available UI API, so the hover prevention is supported by the active --no-mouse-hover option rather than a complete gesture test. The retained Mac title bar is separate from Android.

Final title rendering was also observed on the second cold launch with no Android gray strip. The game was stopped cleanly. Stopped logical size measured 10,945,824,102 bytes versus 10,945,295,202 before validation (about 0.53 MB increase from runtime writes/text); storage did not decrease. No new files were added.
