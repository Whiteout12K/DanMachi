# Project guide

This is a retained Android game running through Mac.apk with a folder-local offline server. Most maintenance changes belong in the Python server or virtual master-data overlays. The original game still owns its UI, battles, inventory transactions and animations.

Read these in order:

1. [Project map](01-project-map.md)
2. [Maintenance workflow](02-maintenance-workflow.md)
3. [Feature recipes](03-feature-recipes.md)
4. [Verification and known limits](04-verification.md)
5. [Source reading and editing guide](05-source-guide.md)

Use [the root README](../README.md) for launch instructions and command examples. Read [launcher instructions](../launcher/AGENTS.md) and [CURRENT_SETUP.md](../launcher/CURRENT_SETUP.md) before maintenance. `CURRENT_SETUP.md` includes historical trials that were later reverted; check its latest dated entries before copying an old approach.

The source folders retain their existing paths so launchers, packaging checks, relative links and archive references continue to resolve. This guide provides a navigable structure over those files.
