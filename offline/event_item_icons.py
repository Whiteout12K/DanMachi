"""Resolve missing event icons without changing original archives or item data.

Prefer an item's own art, then retained artwork for an identical display name
(e.g. an event rerun). Missing art uses distinct retained substitute icons.
Substitutes are not a claim to recover missing historical artwork.
"""

# Reading guide: Event images: items()/groups() describe original currencies;
# resolutions() chooses explicit ZIP-backed image aliases.
# Editing notes: Original art wins. Missing art gets a different retained image from
# sibling currencies; substitutes are not recovered historical art. No player balances
# are touched.
# Checks: tools/maintain.py test events.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import functools

PREFIX = "1/files/icon/event_item/"
VARIANTS = ("frame", "noframe")
# Different silhouettes: shard, crystal cluster, medal, scroll and quill.
PREFERRED = (290000773, 290000755, 290000753, 290000760, 290000762, 290000783)


@functools.lru_cache(maxsize=1)
def items():
    """Read original event item identities and display names once per process."""
    import rebuild_master as master
    from build_gacha import value

    data = master.table("eventItem")
    return tuple(
        (value(data, row, 0), master.text(data, row, 2)) for row in master.rows(data)
    )


@functools.lru_cache(maxsize=1)
def groups():
    """Original shop currencies plus conservative neighboring-item coverage.

    Older event aliases identify families; later numbered aliases do not. Cover
    nearby IDs too, so currencies without a retained shop remain distinguishable.
    """
    import re
    import rebuild_master as master
    from build_gacha import value

    data = master.table("eventItem")
    aliases = {}
    families = {}
    for row in master.rows(data):
        identity = value(data, row, 0)
        alias = master.text(data, row, 1)
        aliases[alias] = identity
        family = re.sub(r"_\d+(?=(_rev)?$)", "", alias)
        families.setdefault(family, []).append(identity)
    result = {tuple(sorted(g)) for g in families.values() if len(g) > 1}
    shop = master.table("shop")
    for row in master.rows(shop):
        group = tuple(
            sorted(
                {
                    aliases[master.text(shop, row, c)]
                    for c in (6, 7, 8, 9, 11, 12)
                    if master.text(shop, row, c) in aliases
                }
            )
        )
        if len(group) > 1:
            result.add(group)
    # Six consecutive identities also cover the older six-currency events.
    ordered = sorted(identity for identity, name in items())
    for pos in range(len(ordered)):
        result.add(tuple(ordered[pos : pos + 6]))
    return tuple(sorted(result))


def resolutions(sources):
    """Keep original art and assign substitutes distinct from nearby currencies."""
    names = {}
    retained = []
    for identity, name in items():
        if all(f"{PREFIX}{identity}_{v}.png" in sources for v in VARIANTS):
            retained.append(identity)
            if name:
                names.setdefault(name, identity)
    palette = list(dict.fromkeys([n for n in PREFERRED if n in retained] + retained))
    if not palette:
        raise ValueError("Required retained event icon artwork is unavailable")

    def fingerprints(identity):
        """Compare actual artwork hashes in both framed and unframed forms."""
        return tuple(sources[f"{PREFIX}{identity}_{v}.png"]["md5"] for v in VARIANTS)

    neighbors = {identity: set() for identity, name in items()}
    for group in groups():
        for identity in group:
            neighbors[identity].update(set(group) - {identity})
    assigned = {}
    kinds = {}
    # Reserve all recovered art before choosing any substitutes.
    for identity, name in items():
        if identity in retained:
            assigned[identity] = identity
        elif name in names:
            assigned[identity] = names[name]
            kinds[identity] = "same-name"
    for identity, name in sorted(items()):
        if identity in assigned:
            continue
        used = [fingerprints(assigned[n]) for n in neighbors[identity] if n in assigned]
        donor = next(
            (
                n
                for n in palette
                if all(
                    all(a != b for a, b in zip(fingerprints(n), other))
                    for other in used
                )
            ),
            None,
        )
        if donor is None:
            raise ValueError(f"No distinct retained icon for event item {identity}")
        assigned[identity] = donor
        kinds[identity] = "distinct-fallback"
    result = {}
    for identity, name in items():
        for variant in VARIANTS:
            target = f"{PREFIX}{identity}_{variant}.png"
            if target not in sources:
                result[target] = (
                    f"{PREFIX}{assigned[identity]}_{variant}.png",
                    kinds[identity],
                )
    return result


def aliases(sources):
    """Map each missing logical image path to its chosen original ZIP record."""
    return {
        target: sources[source]
        for target, (source, kind) in resolutions(sources).items()
    }
