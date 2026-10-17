"""Retired cleanup entry point: never export or discard game assets."""

# Reading guide: Retired cleanup command kept as a safe compatibility entry point.
# Editing notes: It must not export or discard retained assets; use the supported
# storage workflow.
# Checks: offline/test_storage_maintenance.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.


def main():
    """Report that the destructive historical cleanup workflow is retired."""
    raise RuntimeError(
        "Archive pruning is retired. Shared assets must remain intact; "
        "no files were moved, deleted, or exported outside DanMachi."
    )


if __name__ == "__main__":
    main()
