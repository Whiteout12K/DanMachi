# Local player data

In User Data/, double-click Export User.command, Import User.command or Delete User.command.

Export closes the game and writes a small ZIP to User Data/Exports, then reveals it in Finder. It includes host player progress and client account files, with a readable username/rank summary and verified file hashes. It excludes game assets, runtime files and graphics adapters.

Import opens a Mac file picker, validates the export and shows its player name/rank. Type IMPORT to replace the current player. Delete requires DELETE and clears the local player; the next launch starts fresh. Export first if you want to keep that player. Cancel either operation without typing the confirmation word.

Reopen Launch DanMachi.command after any operation. Tools use the native Mac game’s account files directly and require no Android emulator. Account paths are files/ldb, files/kwlt, files/commit_list.dat, shared_prefs, databases and no_backup; settings stored inside those account paths travel with an import and are reset by deletion. Media archives and contents remain intact.

The export format matches the original Drive tools for the same game build. Native-to-native round trips are tested; cross-runtime Drive imports have not been checked in actual gameplay. Unknown builds, modified hashes, unsafe paths, links and non-account files are rejected. Import/deletion failures restore the previous account files and host state.
