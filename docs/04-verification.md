# 4. Verification and known limits

Updated 16 October 2026. This page summarizes current work; the detailed history is in `launcher/CURRENT_SETUP.md`.

## Automated checks

`python3 tools/maintain.py test all` runs 64 focused checks across Gacha, reward boxes, anniversary data, event schedules, native dispatch and monthly gates, save updates and inventory transactions. All passed after the icon distinction and readability changes. The complete launcher test directory also passes 10 checks. Tests use temporary saves.

The readability audit compares 101 Python syntax trees (production logic unchanged), 15 native/Java token streams (unchanged), and four shell scripts. Formatting and guide-link checks pass. Broad offline discovery also includes historical checks for removed device helpers and two missing checksum-fixture cases; see [the source guide](05-source-guide.md#historical-test-limits) for their scope. Final broad discovery ran 173 entries and reported 21 historical missing-helper/fixture errors; current icon and ZIP fixture checks pass within that run. It is not a clean all-green gate.

`python3 tools/maintain.py check` verifies six original APK hashes, seven retained archive sizes, required native compatibility bytes and project-local link containment. It is an integrity check, not a claim of complete gameplay coverage.

## Features under maintenance

| Area | Current behavior | Evidence and limits |
| --- | --- | --- |
| Grand Day | Enters its retained Orario map-stage controller directly | Fresh entry renders the location/background, event counters, Exchange/Gacha and Normal/Hard/Very Hard tabs. Native difficulty switching, Back/re-entry and Gacha open/return verified without another battle. Original stages, unlocks and rewards are preserved. |
| Standard 4★ tickets | Permanent retained banner 171002222 consumes ticket 296000003 | Native pull verified in an isolated QA copy: one ticket consumed, 4★ Alfrik Gulliver received, operation 400000012 acknowledged. Temporary-save retry tests also pass. Ticket ownership controls native visibility. |
| Daily Gacha rotation | Calendar-month master includes future daily pairs | Every-day date/window tests and next-day acceptance/expired-day rejection pass. Reenter Gacha after a UTC day boundary; reopen at a month boundary. Native rollover while the screen stays open is not claimed. |
| Current-event banners | Added alongside ten Iris/free offers | Event relationships and calendar windows are tested; empty ticket inventories hide ticket-only offers. |
| Event item icons | All 781 original items have framed/unframed virtual assets | 64 retain own art, 130 use identical-name rerun art, 587 use distinct retained substitute artwork. All 141 original shop currency groups are checked for unique image hashes in both variants; neighboring fallback currencies are checked too; all 60 multi-item alias families were audited without collisions. New substitute artwork has not been individually visited in every native event screen. Grand Day and Orion Saga original artwork was previously verified in-game. |
| Anniversary reward boxes | Screen rates and durable draw handler added | Native Grand Day rates and a QA draw verified: 10 medals spent, three Gnome Tickets received, operation 500000001 acknowledged. Three original anniversary boxes are covered by payment, retry, restart and finite-prize tests. Grand Day’s repeatable-round reset returns correctly; finite-box round advancement remains unverified in the native UI. |
| Movie assets | All 164 standard USM video streams decode fully | Archive MD5 checks cover all 172 variants. Eight alternate Mac variants have demux warnings; audio and in-game presentation are not certified by this audit. |

## Existing limits to keep visible

- The original Grand Day overview layout `event_map.json` is absent. Entry uses its retained Orario location list; the missing overview itself is not reconstructed.
- One earlier new-player opening-movie Skip transition caused a native shared-pointer crash. No unsafe pointer guard was added; that specific path remains unresolved.
- Multiplayer rankings, retired billing and unavailable media are not reconstructed by these fixes.
- A passing unit test, readable master or visible menu does not replace an in-game transaction and its acknowledged operation.

When reporting a new issue, record the menu path, stage/banner/box ID if known, the visible error, whether it happens after a restart, and the relevant final lines from `state/logs/macapk-errors.log` or `offline-server-errors.log`. Avoid posting full private save files when a short error and ID are sufficient.

- Expanded ticket access covers all 261 original types in automated draw checks. Complete native verification of the expanded ticket menu remains pending; the disposable QA copy was removed at the user’s request. Original save was unchanged during QA and reopened afterward.
