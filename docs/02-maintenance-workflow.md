# 2. Maintenance workflow

## Establish the baseline

1. Read `launcher/AGENTS.md` and the latest entries in `launcher/CURRENT_SETUP.md`.
2. Export the account with **User Data/Export User.command** before testing changes that could affect progress. Account data includes both server JSON and native client files.
3. Run `python3 tools/maintain.py status` and `python3 tools/maintain.py check`.
4. Reproduce the smallest failing path. Note the exact menu, stage/banner/box identity, request and error. A missing asset probe followed by a successful ZIP read is normal; find the final assertion or failed request.

## Find the owning layer

- An API error belongs in `offline/server.py` and its feature module.
- Missing or expired retained content generally belongs in a virtual master overlay.
- Input, decoder or platform API failures belong in the local compatibility helpers.
- Native patches are the last step when the original UI dispatch cannot express a safe fallback through data alone.

Use `rg` to find the endpoint, table name, ID or assertion text. Compare original retained records and native consumers before assigning field meanings. IDs, aliases, field widths and enum values are not interchangeable.

## Make a small change

Change one owning module and add a focused test that exercises the original failure. For rewards or spending, also cover insufficient balance, retry, restart, stale client updates and native acknowledgment. Use a temporary `SaveStore`; never use the player account as a fixture.

Preserve original costs, prerequisites, reward identities and pools unless the requested change explicitly alters them. Do not fabricate missing media or report startup as proof of gameplay.

## Verify in order

1. Run the affected focused suite through `tools/maintain.py test`.
2. For a native patch, verify the exact input bytes, assembled branch destinations, installed output hash and complete reversal to the original APK library. Stop if any guard fails.
3. Run the bundle check after changing runtime dependencies, patches or packaging.
4. Close and reopen the game when server code, Java/native helpers or cached master data changes.
5. Exercise the exact native screen and its next transition. A visible menu is not proof of a completed reward grant or battle.
6. Inspect both saved tables and the acknowledged operation when testing a transaction.

## Record and recover

Add a dated entry to `launcher/CURRENT_SETUP.md` with the change, evidence, test results and remaining limits. Update `docs/04-verification.md` so the current status is easy to find without reading historical experiments.

Keep temporary diagnostics under `state/temp/`; keep small verification reports under `state/verification/`. Remove only disposable diagnostics after completion. Revert unsuccessful experiments rather than layering new guesses on top of them.

When reverting a native patch, restore its recorded original bytes and recompute the expected output hash after applying the remaining patches. Preserve unrelated working patches. Restart and recheck integrity before resuming gameplay.

## Test a real native transaction without spending the player’s items

For this maintenance run, a disposable APFS-cloned game was created under `state/temp/qa-game/` after checkpointing and stopping the real game. Its assets stayed in cloned ZIP archives; the clone passed its own bundle check. Only the clone's save received labeled test fixtures, and its account name was changed to **QA COPY**. The real save was hashed before and after testing.

Run only one copy at a time because the original APK uses the fixed loopback service port. Keep fixture setup under `state/temp/`, never in the live save or production launch path. Verify the window is the QA account before drawing. Afterward, stop the QA launcher, retain a small result report, remove the disposable clone, confirm the real save hash is unchanged, and reopen the real game.

A clone is a test environment, not an account export. Never import its synthetic balances into the real game.
