# DanMachi MF — local Mac game

Start the game with **Launch DanMachi.command**. Close it with Settings → To Title to save and exit.

## Learn and edit

Start with [the project guide](docs/README.md). It explains how the original game, Mac compatibility layer and local server fit together, where to make changes, and how to verify them.

- [1. Project map](docs/01-project-map.md) — folders, responsibilities and source entry points.
- [2. Maintenance workflow](docs/02-maintenance-workflow.md) — investigate, edit, test and verify.
- [3. Feature recipes](docs/03-feature-recipes.md) — banners, events, rewards, native patches and movies.
- [4. Verification and known limits](docs/04-verification.md) — what is tested and what still needs native gameplay checks.
- [5. Source reading and editing guide](docs/05-source-guide.md) — file-by-file purposes, edit boundaries, tests and formatting.
- [Current setup and change history](launcher/CURRENT_SETUP.md) — detailed technical record; later dated entries supersede earlier experiments.

## Maintenance commands

Run these from this folder using a Python 3 installation with its standard library:

```sh
python3 tools/maintain.py status
python3 tools/maintain.py banners
python3 tools/maintain.py banners --date 2026-10-17
python3 tools/maintain.py check
python3 tools/maintain.py test gacha
python3 tools/maintain.py test boxes
python3 tools/maintain.py test events
python3 tools/maintain.py test native
```

The inspection commands do not edit saves. Tests use temporary saves. The bundled game Python is intentionally minimal and lacks `unittest`; it is used for launching and integrity checks, while maintenance tests use a full Python 3 installation.

Use the commands in **User Data/** to export or import your account. Keep the whole folder together when moving the game. Original APKs, media archives, installed app files and runtime files are preserved dependencies, not editable source.
