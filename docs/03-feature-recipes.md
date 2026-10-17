# 3. Feature recipes

## Inspect or change the banner schedule

Run `python3 tools/maintain.py banners --date YYYY-MM-DD`. Dates refer to UTC rotation days.

Read [offline/gacha_rotation.py](../offline/gacha_rotation.py): `TICKET_BANNERS` identifies permanent standard ticket offers; `current_events` links scheduled episodes; `active` selects the daily lineup; `month_windows` preloads actual dates for the calendar month. The lineup has six regular Iris/free offers, two daily general offers and two daily anniversary offers, plus current-event and standard ticket banners. Empty ticket inventories can hide their matching native banners.

[offline/gacha.py](../offline/gacha.py) serves encrypted lottery dates, initializes user rows, reserves draws and returns native grant operations. It preserves original costs and pools from `gacha-catalog.json.gz`. The client caches the monthly master: leave and reenter Gacha for a daily change; reopen the game at a calendar-month change.

After editing, run `python3 tools/maintain.py test gacha`. Check today and tomorrow, dates encoded in the master, expired-offer rejection, ticket payment and durable retries. Do not regenerate the original catalog simply to alter scheduling.

## Repair an event or anniversary screen

[offline/guild_events.py](../offline/guild_events.py) controls monthly event availability. [offline/anniversary_events.py](../offline/anniversary_events.py) keeps the retained anniversary episodes, stages, shops and boxes available. These are memory-only master overlays; archived masters remain unchanged.

Grand Day's original `event_map.json` is absent from the retained collections. A guarded factory hook in [launcher/grand_day_stage_list.py](../launcher/grand_day_stage_list.py) seeds only episode `7160000101` with its original first battle, `1160000101102`, and its original Orario page `1` before the retained map-stage controller initializes. This opens the Orario location list used after battle, with its background, difficulty tabs, counters and shortcuts. Selecting a location does not start a battle or change unlocks. The ordinary stage-list dispatch experiment is removed. Back returns directly to the event lineup because the overview is absent. Original map records are preserved. The helper generates patch bytes; the installed guarded bytes and expected hash live in [launcher/compatibility-patches.json](../launcher/compatibility-patches.json). Editing the generator alone does not update the installed native library or patch record.

Test with the `events` and `native` suites, then enter Grand Day from the event lineup, check difficulty tabs and shortcuts, leave, and reopen it before entering a stage. Never substitute another event's stage IDs or rewards to make the screen appear populated.

## Repair reward-box transactions

[offline/event_box.py](../offline/event_box.py) reconstructs original box/step/content relationships, costs, reward aliases, finite quantities and weights. `show` initializes the screen and supplies current rates. `draw` reserves payment and progress atomically, then returns one native reward operation. `pending` and `recovery` support interrupted replies; `protect_pending` prevents a delayed client update from undoing a reservation.

Request fields are `eventBoxId` and `drawCount`. The native result parser consumes `chosenItems[].eventBoxContentId` and `currentStepContents` entries containing `contentId`, `rate` and `rateVariationState`. Server routes and generic user-data recovery are wired in [offline/server.py](../offline/server.py).

Run `python3 tools/maintain.py test boxes`. Native reset/next-round behavior and actual reward receipt require their own gameplay verification; temporary-save tests alone do not establish them.

## Investigate a movie

The video bridge sources are in `launcher/video/`. Deferred H.264 setup waits for SPS/PPS in queued frames; the orientation helper flips decoded movie frames vertically. Avoid changing camera textures or the user-verified window adapter.

[state/verification/2026-10-15/movie-audit.json](../state/verification/2026-10-15/movie-audit.json) records full video-stream decoding and archive MD5 checks for 172 USM assets. All 164 standard variants decoded cleanly; eight alternate `movie/mac/` variants produced demux warnings. This does not certify audio, rendering, orientation or Skip transitions in the game.

Keep media in the archives. Feed an archived stream to a diagnostic decoder through a pipe rather than extracting a persistent movie collection. Verify a representative full-screen Story movie and stage-select movie in the native runtime before claiming playback fixed.


To repeat the optional archive/decode audit with an installed `ffmpeg`, run:

```sh
python3 tools/audit_movies.py
```

It reads ZIP streams through pipes, uses two decoder workers, and writes a small dated JSON report under `state/verification/`. It does not install a decoder, edit media or modify the account.


## Event item icons

[offline/event_item_icons.py](../offline/event_item_icons.py) builds explicit virtual ZIP aliases for every original `eventItem` record, for both `_frame.png` and `_noframe.png`. Available originals always win. Missing icons use retained artwork with an identical item display name, including reruns. If none exists, they use distinct retained substitute artwork. The resolver reserves existing artwork first, then chooses different image hashes for currencies sharing an original shop or alias family, plus six neighboring item identities to cover events without retained shops. These substitutes are placeholders, not recovered historic art. Item identities, names, costs, quantities and rewards are unchanged.

The aliases are registered by [offline/zip_reader.py](../offline/zip_reader.py). No PNG is extracted or modified. To add recovered art later, register its verified original archive source; it will automatically take priority over the fallback. Run `python3 -B tools/maintain.py test events`, then restart the game because the virtual file index is cached. Check item counters and framed icons in Exchange. Coverage/evidence: `state/verification/2026-10-16/event-item-icons.json`.


## Matching ticket banners

All 261 original ticket types are covered by permanent matching choices in [offline/gacha_rotation.py](../offline/gacha_rotation.py). Ticket access is additional to the Iris/event rotation. Costs, ticket IDs, original pools and draw counts come from [offline/build_gacha.py](../offline/build_gacha.py). Preserve distinct pool choices when deduplicating historical copies. [offline/gacha_ticket_access.py](../offline/gacha_ticket_access.py) supplies native validity compatibility and fallback banner art through virtual ZIP assets. Server ticket draws have no offline expiry or per-account draw cap while tickets remain. Native validity uses its maximum positive signed duration. Reenter Gacha after receiving a ticket; restart after changing cached masters. Run `python3 -B tools/maintain.py test gacha`. Automated consumption checks cover every type; complete native verification of the expanded lineup is still pending.

## English display labels

[english_presentation.py](../offline/english_presentation.py) composes English display strings after the existing availability and ticket-validity overlays. [english-text.json](../offline/english-text.json) maps original table/row/column identities to English labels. It changes display strings only: IDs, aliases, skill effects, costs, pools, save rows, artwork and voices retain their existing sources. Some historical menu titles use descriptive English labels rather than recovered official translations.

The overlay appends encrypted replacement string vectors and changes only their relative pointers, then encrypts the native table. Existing records and scalar fields do not move. `zip_reader.py` advertises the new byte sizes and serves the same bytes. Gacha Details uses the same English names as the native master.

Edit the explicit label entries, then run:

```sh
python3 tools/maintain.py test english
python3 tools/maintain.py test gacha
python3 tools/maintain.py check
```

The generated English image cards were removed at the user's request. No English artwork replacement layer is active. Retained artwork can contain Japanese text; this text-label overlay does not translate baked-in image text, movies, or shared animation sheets. The earlier distinct event-item icon aliases remain as requested separately.
