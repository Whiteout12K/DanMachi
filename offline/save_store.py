"""Persist the client's actual table deltas; never invent game progress."""

# Reading guide: Save authority: MessagePack helpers define wire bytes; SaveStore merges
# native deltas and persists pending reward operations.
# Editing notes: Keep locks, copy-before-change, token calculation and atomic writes
# together. A pending operation is a reserved grant awaiting native acknowledgment, not
# permission to grant it twice.
# Checks: tools/maintain.py test saves and offline/test_save_store.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import copy
import json
import os
import struct
import threading
import secrets
import hashlib
import functools
from pathlib import Path


# State copying and original reward routing
def copy_state(state, tables=(), metadata=()):
    """Copy only mutable update targets; unchanged records stay shared/read-only."""
    result = dict(state)
    result["tables"] = dict(state["tables"])
    result["tokens"] = dict(state.get("tokens", {}))
    for table in tables:
        if table in state["tables"]:
            result["tables"][table] = copy.deepcopy(state["tables"][table])
    for key in metadata:
        if key in state:
            result[key] = copy.deepcopy(state[key])
    return result


REWARD_DEFINITIONS = json.loads(
    Path(__file__).with_name("master-rewards.json").read_text()
)["stages"]
PC_ATTACK_DEFINITIONS = json.loads(
    Path(__file__).with_name("master-pc-attacks.json").read_text()
)["pcs"]
ACHIEVEMENT_REWARDS = json.loads(
    Path(__file__).with_name("master-achievement-rewards.json").read_text()
)["achievements"]


def aggregate_items(items):
    """Combine repeated item rewards so one native grant contains each item total."""
    totals = {}
    for row in items:
        totals[row["itemId"]] = totals.get(row["itemId"], 0) + row["amount"]
    return [{"itemId": item, "amount": amount} for item, amount in totals.items()]


@functools.lru_cache(maxsize=1)
def memoria_reward_ids():
    """Identify original Memoria reward IDs used when routing native rewards."""
    import rebuild_master as m
    from build_gacha import value

    b = m.table("memoria")
    return frozenset(value(b, r, 0) for r in m.rows(b))


def route_achievement_rewards(parameters):
    """Native Memoria rewards use their own channel, not DomainItem IDs."""
    items = []
    memorias = [
        {"memoriaId": r["memoriaId"], "level": r.get("level", r.get("amount", 1))}
        for r in parameters.get("receivedMemorias", [])
    ]
    for reward in parameters.get("receivedItems", []):
        if reward["itemId"] in memoria_reward_ids():
            memorias.append({"memoriaId": reward["itemId"], "level": reward["amount"]})
        else:
            items.append(reward)
    parameters["receivedItems"] = aggregate_items(items)
    parameters["receivedMemorias"] = memorias


TABLE_IDENTITIES = {
    "UserAlarmVoiceItem": ("userId", "alarmVoiceItemId"),
    "UserDpItem": ("userId", "dpItemId"),
    "UserLockAbilityItem": ("userId", "lockAbilityId"),
    "UserPCTicket": ("userId", "pcTicketId"),
    "UserQrCodeItem": ("userId", "qrCodeItemId"),
    "UserSerialPvpSpTicketItem": ("userId", "ticketId"),
    "UserSubscriptionTicket": ("userId", "subscriptionTicketId"),
    "UserTicket": ("userId", "ticketId"),
    "UserUnderPvpRevengeTicket": ("userId", "underPvpRevengeTicketId"),
    "UserUnderPvpStaminaTicket": ("userId", "underPvpStaminaTicketId"),
    "UserUnionRaidBossSpTicketItem": ("userId", "ticketId"),
    "UserUnionRaidNormalSpTicketItem": ("userId", "ticketId"),
    "UserUnionRaidMedal": ("userId", "medalId"),
    "UserVoteItem": ("userId", "voteItemId"),
    "UserStaminaTicket": ("userId", "staminaTicketId"),
    "UserEventItem": ("userId", "eventItemId"),
    "UserKeyItem": ("userId", "keyItemId"),
    "UserHeroSublimateItem": ("userId", "heroSublimateItemId"),
    "UserHeroSublimateUnlockItem": ("userId", "heroSublimateUnlockItemId"),
    "UserCpItem": ("userId", "cpItemId"),
    "UserEquipmentEvolveItem": ("userId", "evolveItemId"),
    "UserEquipmentEnhanceItem": ("userId", "enhanceItemId"),
    "UserFamiliaDonationItem": ("userId", "familiaDonationItemId"),
    "UserTakarakujiItem": ("userId", "takarakujiItemId"),
    "UserMemoriaExpItem": ("userId", "memoriaExpItemId"),
    "UserGeneralLimitBreakItem": ("userId", "limitBreakItemId"),
    "UserMemoria": ("userId", "memoriaId"),
    "UserEventBox": ("userId", "eventBoxId"),
    "UserEventBoxStep": ("userId", "eventBoxStepId"),
    "UserEventBoxContent": ("userId", "eventBoxContentId"),
    "UserLottery": ("userId", "lotteryId"),
    "UserWritableLotteryData": ("userId", "lotteryId"),
    "UserGachaTicket": ("userId", "gachaTicketId"),
    "UserLimitBreakItem": ("userId", "limitBreakItemId"),
    "UserExpItem": ("userId", "expItemId"),
    "UserShopProduct": ("userId", "shopProductId"),
    "UserStatusBoardItem": ("userId", "statusBoardItemId"),
    "UserTownCommunication": ("userId", "characterId", "createdAt"),
    "UserAdventureTicket": ("userId", "adventureTicketId"),
    "UserSkipTicket": ("userId", "skipTicketId"),
    "UserCurrency": ("userId", "currencyId"),
    "UserCharacter": ("userId", "characterId"),
    "UserShootingGame": ("userId", "shootingGameInfoId"),
    "UserCharacterCostume": ("userId", "costumeId"),
    "UserCommunicationCharacter": ("userId", "characterId", "costumeId"),
    "UserCommunicationVoice": ("userId", "voiceId"),
    "UserParty": ("userId", "id"),
    "UserPC": ("userId", "pcId"),
    "UserArea": ("userId", "areaId"),
    "UserLocation": ("userId", "locationId"),
    "UserItemToken": ("userId", "signature"),
    "UserRandomSeed": ("userId", "signature"),
    "UserAdventureStage": ("userId", "adventureStageId"),
    "UserEpisodeDifficulty": ("userId", "episodeId"),
    "UserTutorial": ("userId", "tutorialId"),
    "UserAchievement": ("userId", "achievementId"),
    "UserSystemFlag": ("userId", "systemFlagId"),
    "UserAlarmVoice": ("userId", "voiceId"),
}

PC_FIELD_ORDER = "userId pcId totalExp hp mp destinyPoint variableChantLevel currentJobIndex jobs jobSlots skillSlots abilityPoint bookEntryState signature entryState joiningState limitbreakCount ownerType equippedWeaponIndex equippedArmorIndex attackPattern heroSublimateLevel isUnlockedHeroSublimate battlePlayCount currentDP".split()


# Native field order and wire serialization
def canonical_pcs(rows):
    """Restore native character field order before hashing or sending rows."""
    result = []
    for row in rows:
        value = {k: row[k] for k in PC_FIELD_ORDER}
        value["skillSlots"] = [
            {
                k: slot[k]
                for k in ("skillSlotNumber", "slotSkillType", "skillId", "signature")
            }
            for slot in row["skillSlots"]
        ]
        result.append(value)
    return result


def unpack(data):
    """Decode the supported MessagePack types and reject trailing bytes."""

    def read(at):
        tag = data[at]
        at += 1
        if tag < 128:
            return tag, at
        if tag >= 224:
            return tag - 256, at
        if tag in (192, 194, 195):
            return {192: None, 194: False, 195: True}[tag], at
        if 160 <= tag <= 191:
            n = tag - 160
            return data[at : at + n].decode(), at + n
        if tag in (217, 218, 219):
            width = {217: 1, 218: 2, 219: 4}[tag]
            n = int.from_bytes(data[at : at + width], "big")
            at += width
            return data[at : at + n].decode(), at + n
        if tag in (204, 205, 206, 207, 208, 209, 210, 211):
            width = {204: 1, 205: 2, 206: 4, 207: 8, 208: 1, 209: 2, 210: 4, 211: 8}[
                tag
            ]
            return (
                int.from_bytes(data[at : at + width], "big", signed=tag >= 208),
                at + width,
            )
        if tag == 202:
            return struct.unpack_from(">f", data, at)[0], at + 4
        if tag == 203:
            return struct.unpack_from(">d", data, at)[0], at + 8
        if 128 <= tag <= 159:
            mapping = tag < 144
            n = tag - (128 if mapping else 144)
        elif tag in (220, 221, 222, 223):
            mapping = tag in (222, 223)
            width = 2 if tag in (220, 222) else 4
            n = int.from_bytes(data[at : at + width], "big")
            at += width
        else:
            raise ValueError("Unsupported MessagePack tag")
        result = {} if mapping else []
        for i in range(n):
            key, at = read(at)
            if mapping:
                value, at = read(at)
                result[key] = value
            else:
                result.append(key)
        return result, at

    result, at = read(0)
    if at != len(data):
        raise ValueError("Trailing MessagePack bytes")
    return result


def pack(value):
    """Encode values in the exact MessagePack representation used for save tokens."""
    if value is None:
        return b"\xc0"
    if isinstance(value, bool):
        return b"\xc3" if value else b"\xc2"
    if isinstance(value, int):
        if 0 <= value < 128:
            return bytes([value])
        if -32 <= value < 0:
            return bytes([value & 255])
        if 0 <= value <= 0xFFFFFFFF:
            return b"\xce" + struct.pack(">I", value)
        if 0 <= value <= 0xFFFFFFFFFFFFFFFF:
            return b"\xcf" + struct.pack(">Q", value)
        return b"\xd3" + struct.pack(">q", value)
    if isinstance(value, float):
        return b"\xcb" + struct.pack(">d", value)
    if isinstance(value, str):
        data = value.encode()
        n = len(data)
        return (
            bytes([0xA0 + n])
            if n < 32
            else (
                b"\xd9" + bytes([n])
                if n < 256
                else (
                    b"\xda" + struct.pack(">H", n)
                    if n < 65536
                    else b"\xdb" + struct.pack(">I", n)
                )
            )
        ) + data
    if isinstance(value, list):
        n = len(value)
        return (
            bytes([0x90 + n])
            if n < 16
            else (
                b"\xdc" + struct.pack(">H", n)
                if n < 65536
                else b"\xdd" + struct.pack(">I", n)
            )
        ) + b"".join(pack(x) for x in value)
    if isinstance(value, dict):
        n = len(value)
        return (
            bytes([0x80 + n])
            if n < 16
            else (
                b"\xde" + struct.pack(">H", n)
                if n < 65536
                else b"\xdf" + struct.pack(">I", n)
            )
        ) + b"".join(pack(k) + pack(v) for k, v in value.items())
    raise ValueError("Unsupported saved value")


# Verified from the original ARM64 client singleton-table dispatch.
SINGLETON_TABLES = frozenset(
    (
        "UserInfo",
        "UserStatus",
        "UserAdventureState",
        "UserPvPParty",
        "UserProfile",
        "UserExplorerMember",
        "UserAlarmSetting",
        "UserPvBParty",
        "UserPvBHighScoreParty",
        "UserCasinoState",
        "UserPokerState",
        "UserExpeditionInfo",
        "UserGvEParty",
        "UserAdventureLevelInfo",
        "UserSerialPvpInfo",
        "UserGuildRaidState",
        "UserGuildEventStaminas",
        "UserShootingGameRankingReward",
        "UserUnderPvPInfo",
    )
)


def wire_tables(tables):
    """Send native singleton tables as objects and ordinary tables as lists."""
    result = {}
    for table, rows in tables.items():
        if table in SINGLETON_TABLES and rows:
            if len(rows) != 1:
                raise ValueError("Multiple singleton records: " + table)
            result[table] = rows[0]
        else:
            result[table] = rows
    return result


# Persistent account operations and reward acknowledgment
class SaveStore:
    """Own saved tables, synchronization tokens and pending native reward operations."""

    def repair_bootstrap_costume(self):
        """Complete the original offline Hestia bootstrap, without granting outfits."""
        with self.lock:
            state = copy.deepcopy(self.state)
            home = next(
                (
                    r
                    for r in state["tables"].get("UserCommunicationCharacter", [])
                    if r.get("characterId") == 100000005
                    and r.get("costumeId") == 1022027000
                    and r.get("characterState") in (2, 3)
                ),
                None,
            )
            if home is None:
                return False
            rows = state["tables"].get("UserCharacterCostume", [])
            if any(
                r.get("userId") == home["userId"] and r.get("costumeId") == 1022027000
                for r in rows
            ):
                return False
            rows = rows + [
                {"userId": home["userId"], "costumeId": 1022027000, "costumeState": 2}
            ]
            state["tables"]["UserCharacterCostume"] = rows
            state["tokens"]["UserCharacterCostume"] = hashlib.md5(
                pack(rows)
            ).hexdigest()
            self._write(state)
            return True

    def achievement_complete(self, request):
        """Let native operation 6000 grant rewards and advance completed missions."""
        requested = request.get("achievementIds")
        if not isinstance(requested, list) or not requested or len(requested) > 1000:
            raise ValueError("Invalid achievement claim")
        if any(
            not isinstance(r, dict)
            or type(r.get("achievementId")) is not int
            or type(r.get("completedAt")) is not int
            for r in requested
        ):
            raise ValueError("Invalid achievement identity")
        identities = sorted((r["achievementId"], r["completedAt"]) for r in requested)
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate achievement claim")
        key = json.dumps(identities, separators=(",", ":"))
        with self.lock:
            state = copy.deepcopy(self.state)
            claims = state.setdefault("achievementClaims", {})
            if key not in claims:
                rows = []
                items = []
                stamina = 0
                for aid, completed in identities:
                    row = next(
                        (
                            r
                            for r in state["tables"].get("UserAchievement", [])
                            if r["achievementId"] == aid
                            and r.get("completedAt") == completed
                        ),
                        None,
                    )
                    if row is None or row.get("state") != 3:
                        raise ValueError("Achievement is not completed")
                    if any(
                        any(
                            r["achievementId"] == aid and r["completedAt"] == completed
                            for r in c["parameters"]["UserAchievement"]
                        )
                        for c in claims.values()
                    ):
                        raise ValueError("Achievement reward already issued")
                    reward = ACHIEVEMENT_REWARDS.get(str(aid))
                    if reward is None:
                        raise ValueError("Achievement reward not reconstructed")
                    rows.append(copy.deepcopy(row))
                    if "stamina" in reward:
                        stamina += reward["stamina"]
                    else:
                        items.append(copy.deepcopy(reward))
                sequence = 300000001 + len(claims)
                claims[key] = {
                    "id": sequence,
                    "signature": sequence,
                    "token": "",
                    "type": 6000,
                    "parameters": {
                        "issueAmount": sum(
                            r["amount"] for r in items if r["itemId"] == 205000001
                        ),
                        "issueStamina": stamina,
                        "receivedCostumes": [],
                        "receivedItems": items,
                        "receivedPCs": [],
                        "receivedMemorias": [],
                        "issueCasinoMedal": 0,
                        "UserUnionRaidMedal": [],
                        "UserAchievement": rows,
                    },
                }
                self._write(state)
            operation = claims[key]
            before = copy.deepcopy(operation["parameters"])
            route_achievement_rewards(operation["parameters"])
            if before != operation["parameters"]:
                self._write(state)
            if (
                "token" not in operation
                or type(operation["parameters"].get("issueCasinoMedal")) is bool
            ):
                operation["token"] = ""
                operation["parameters"]["issueCasinoMedal"] = 0
                self._write(state)
            return (
                {"code": 0}
                if str(operation["id"]) in state.get("acknowledgedOperations", {})
                else {"code": 0, "operation": operation}
            )

    def repair_legacy_tutorial_attack(self):
        """Repair only the old Bell-template draw, preserving levels and jobs."""
        with self.lock:
            state = copy.deepcopy(self.state)
            pc_id = state.get("tutorialDraw", {}).get("pcId")
            definition = PC_ATTACK_DEFINITIONS.get(str(pc_id))
            pc = next(
                (r for r in state["tables"].get("UserPC", []) if r["pcId"] == pc_id),
                None,
            )
            if not definition or not pc or pc_id == 1011001001:
                return False
            slots = {r["skillSlotNumber"]: r for r in pc["skillSlots"]}
            if any(slots.get(n, {}).get("skillId") != 109001001 for n in (1, 8)) or any(
                slots.get(n, {}).get("skillId", 0) for n in range(2, 8)
            ):
                return False
            slots[1]["skillId"] = definition["attack"]
            slots[8]["skillId"] = definition["counter"]
            state["tables"]["UserPC"] = canonical_pcs(state["tables"]["UserPC"])
            state["tokens"]["UserPC"] = hashlib.md5(
                pack(state["tables"]["UserPC"])
            ).hexdigest()
            state["legacyAttackRepair"] = {"pcId": pc_id, **definition}
            self._write(state)
            return True

    def _claim_stage_rewards(self, state, stage_id, first, task_ids):
        definitions = REWARD_DEFINITIONS.get(str(stage_id), {})
        claim = state.setdefault("stageRewardClaims", {}).setdefault(
            str(stage_id), {"first": False, "tasks": []}
        )
        items = []
        if first and not claim["first"] and "first" in definitions:
            items.append(copy.deepcopy(definitions["first"]))
            claim["first"] = True
        for task in task_ids:
            if task not in claim["tasks"]:
                if "task" in definitions:
                    items.append(copy.deepcopy(definitions["task"]))
                claim["tasks"].append(task)
        required = definitions.get("taskIds", [])
        if (
            required
            and "allTasks" in definitions
            and not claim.get("allTasks")
            and set(required).issubset(claim["tasks"])
        ):
            items.append(copy.deepcopy(definitions["allTasks"]))
            claim["allTasks"] = True
        return items

    def prepare_reward_backfill(self):
        """Queue native item grants for verified clears that predate reward support."""
        with self.lock:
            state = copy.deepcopy(self.state)
            items = []
            for stage in state["tables"].get("UserAdventureStage", []):
                if stage.get("state") == 4:
                    items.extend(
                        self._claim_stage_rewards(
                            state,
                            stage["adventureStageId"],
                            True,
                            [
                                t["adventureStageTaskId"]
                                for t in stage.get("tasks", [])
                                if t.get("state", 0) > 0
                            ],
                        )
                    )
            if items:
                totals = {}
                for row in items:
                    totals[row["itemId"]] = totals.get(row["itemId"], 0) + row["amount"]
                sequence = 200000001 + len(state.get("rewardBackfills", []))
                operation = {
                    "id": sequence,
                    "type": 2000,
                    "signature": sequence,
                    "token": "",
                    "parameters": {
                        "receivedPCs": [],
                        "receivedExPCs": [],
                        "receivedEquipments": [],
                        "receivedItems": [
                            {"itemId": item, "amount": amount}
                            for item, amount in totals.items()
                        ],
                        "receivedCostumes": [],
                        "issueCasinoMedal": 0,
                        "UserUnionRaidMedal": [],
                        "UserCommunicationCharacter": [],
                        "UserGift": [],
                    },
                }
                state.setdefault("rewardBackfills", []).append(operation)
            self._write(state)

    def pending_rewards(self):
        with self.lock:
            return next(
                (
                    copy.deepcopy(o)
                    for o in self.state.get("rewardBackfills", [])
                    if not o.get("completionId")
                    and str(o["id"]) not in self.state.get("acknowledgedOperations", {})
                ),
                None,
            )

    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.state = (
            json.loads(path.read_text())
            if path.exists()
            else {"tables": {}, "tokens": {}}
        )

    def _write(self, state):
        """Persist a complete candidate state before publishing it as the live state."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w") as file:
            json.dump(state, file, separators=(",", ":"))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, self.path)
        self.state = state

    def checkpoint(self):
        """Durably finish the current local save before the server exits."""
        with self.lock:
            self._write(self.state)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def reset(self, initial):
        """Replace the account atomically without retaining deleted player data."""
        with self.lock:
            state = {
                "tables": copy.deepcopy(initial["data"]),
                "tokens": copy.deepcopy(initial["dataTokens"]),
                "generation": self.state.get("generation", 0) + 1,
            }
            self._write(state)

    def apply(self, value):
        """
        Merge native table deltas while protecting reserved rewards from stale
        pushes.
        """
        with self.lock:
            state = copy_state(self.state, metadata=("acknowledgedOperations",))
            for delta in value["deltas"]:
                for table, rows in delta["putItems"].items():
                    if not rows:
                        state["tables"].setdefault(table, [])
                        continue
                    # Identity rules are not yet known for all game tables. A
                    # full bootstrap may be stored; ambiguous later merges fail.
                    previous = state["tables"].get(table, [])
                    identity = TABLE_IDENTITIES.get(table)
                    if identity:

                        def row_key(row):
                            """
                            Use the table-specific primary
                            key to match native row updates
                            and deletions.
                            """
                            return tuple(row[k] for k in identity)

                        for batch in (previous, rows):
                            if len({row_key(r) for r in batch}) != len(batch):
                                raise ValueError("Duplicate table identity: " + table)
                        merged = {row_key(r): r for r in previous}
                        merged.update({row_key(r): r for r in rows})
                        rows = list(merged.values())
                    elif previous and previous != rows:
                        keys = [
                            k
                            for k in ("id", "partyId", "pcId", "characterId", "userId")
                            if all(k in r for r in rows + previous)
                        ]
                        key = next(
                            (
                                k
                                for k in keys
                                if len({r[k] for r in rows}) == len(rows)
                                and len({r[k] for r in previous}) == len(previous)
                            ),
                            None,
                        )
                        if key is None:
                            raise ValueError("Unknown table identity: " + table)
                        merged = {r[key]: r for r in previous}
                        merged.update({r[key]: r for r in rows})
                        rows = list(merged.values())
                    state["tables"][table] = copy.deepcopy(rows)
                for table, rows in delta["deleteItems"].items():
                    if not rows:
                        continue
                    identity = TABLE_IDENTITIES.get(table)
                    if not identity:
                        raise ValueError(
                            "Deletion identity not reconstructed: " + table
                        )
                    deleted = {tuple(r[k] for k in identity) for r in rows}
                    state["tables"][table] = [
                        r
                        for r in state["tables"].get(table, [])
                        if tuple(r[k] for k in identity) not in deleted
                    ]
            # Keep the server-reserved bond totals when native operation 1001
            # constructs its inventory rows. Correct only this unacknowledged
            # grant's matching signatures; later training/spending is untouched.
            draw = self.state.get("offlineGacha", {}).get("lastDraw", {})
            grant_id = draw.get("response", {}).get("operation", {}).get("id")
            targets = draw.get("bondTargets", {})
            touched = set()
            if targets and str(grant_id) not in self.state.get(
                "acknowledgedOperations", {}
            ):
                touched = {
                    r["limitBreakItemId"]
                    for d in value["deltas"]
                    for r in d["putItems"].get("UserLimitBreakItem", [])
                }
                if touched:
                    rows = copy.deepcopy(state["tables"].get("UserLimitBreakItem", []))
                    for row in rows:
                        target = targets.get(str(row["limitBreakItemId"]))
                        if (
                            target
                            and row["limitBreakItemId"] in touched
                            and row.get("signature") == grant_id
                        ):
                            row["amount"] = target["amount"]
                            row["cumulativeAmount"] = target["cumulativeAmount"]
                    state["tables"]["UserLimitBreakItem"] = rows
                    state["tokens"]["UserLimitBreakItem"] = hashlib.md5(
                        pack(rows)
                    ).hexdigest()
            import event_box

            for operation in value.get("operations", []):
                if (
                    isinstance(operation, dict)
                    and type(operation.get("id")) is int
                    and isinstance(operation.get("verifier"), str)
                    and operation["verifier"]
                ):
                    state.setdefault("acknowledgedOperations", {})[
                        str(operation["id"])
                    ] = operation["verifier"]
            state["tokens"].update(value["checksums"]["after"])
            event_box.protect_pending(state, self.state)
            if targets and touched:
                state["tokens"]["UserLimitBreakItem"] = hashlib.md5(
                    pack(state["tables"]["UserLimitBreakItem"])
                ).hexdigest()
            if state != self.state:
                self._write(state)

    def pending_adventures(self):
        """Recover interrupted native completions only for their current session."""
        with self.lock:
            stages = {
                r["adventureStageId"]: r
                for r in self.state["tables"].get("UserAdventureStage", [])
            }
            latest = {}
            for operation in self.state.get("adventureCompletions", {}).values():
                sid = operation["parameters"]["UserAdventureStage"][0][
                    "adventureStageId"
                ]
                latest[sid] = operation
            return [
                copy.deepcopy(o)
                for sid, o in latest.items()
                if str(o["id"]) not in self.state.get("acknowledgedOperations", {})
                and stages.get(sid, {}).get("token") == o["token"]
            ]

    def adventure_complete(self, request, request_key=None):
        """Return the native completion operation, keyed by the client's stage token."""
        import time

        stage_id = request.get("adventureStageId")
        token = request.get("token")
        skip_count = request.get("skipCount", 0)
        if type(skip_count) is not int or not 0 <= skip_count <= 1000:
            raise ValueError("Invalid adventure skip count")
        if type(stage_id) is not int or not isinstance(token, str) or not token:
            raise ValueError("Invalid adventure completion identity")
        with self.lock:
            state = copy.deepcopy(self.state)
            stage = next(
                (
                    r
                    for r in state["tables"].get("UserAdventureStage", [])
                    if r["adventureStageId"] == stage_id
                ),
                None,
            )
            claims = state.setdefault("adventureCompletions", {})
            key = str(stage_id) + ":" + token
            if skip_count and request_key:
                key += ":skip:" + request_key
            elif stage and stage.get("lastTryDateTime"):
                key += ":start:" + str(stage["lastTryDateTime"])
            elif request_key:
                key += ":request:" + request_key
            # A retry can arrive with a new transport identity after an
            # interrupted reply. Finish the existing unacknowledged operation.
            if key not in claims:
                for previous_key, previous in reversed(list(claims.items())):
                    if (
                        previous["token"] == token
                        and previous["parameters"]["UserAdventureStage"][0][
                            "adventureStageId"
                        ]
                        == stage_id
                        and str(previous["id"])
                        not in state.get("acknowledgedOperations", {})
                    ):
                        key = previous_key
                        break
            if key not in claims:
                if skip_count:
                    tickets = sum(
                        r.get("amount", 0)
                        for r in state["tables"].get("UserSkipTicket", [])
                        if r.get("skipTicketId") in (288000001, 288000002)
                        and r.get("userId") == (stage or {}).get("userId")
                    )
                    if tickets < skip_count:
                        raise ValueError("Insufficient skip tickets")
                record = request.get("adventureRecord", {})
                # Story-only stages have no start checkpoint or combat token
                # table update. Accept their zero-action local completion.
                novel = (
                    stage is not None
                    and not stage.get("tasks")
                    and stage.get("state") in (1, 4)
                    and not request.get("adventureGainedItems")
                    and isinstance(record, dict)
                    and record
                    and all(type(v) is int and v == 0 for v in record.values())
                    and token.startswith(str(stage["userId"]) + "-")
                )
                if stage is None or (stage.get("token") != token and not novel):
                    raise ValueError("Unknown adventure session")
                items = request.get("adventureGainedItems", [])
                if (
                    not isinstance(items, list)
                    or len(items) > 1000
                    or any(
                        not isinstance(r, dict)
                        or type(r.get("itemId")) is not int
                        or type(r.get("amount")) is not int
                        or not 0 <= r["amount"] <= 100000000
                        for r in items
                    )
                ):
                    raise ValueError("Invalid adventure drops")
                sequence = 100000002 + len(claims)
                task_ids = request.get("adventureStageTaskIds", [])
                known_tasks = {
                    t["adventureStageTaskId"] for t in stage.get("tasks", [])
                }
                if not isinstance(task_ids, list) or any(
                    type(t) is not int or t not in known_tasks for t in task_ids
                ):
                    raise ValueError("Unknown adventure task")
                rewards = self._claim_stage_rewards(
                    state, stage_id, not stage.get("firstCompleteDateTime"), task_ids
                )
                # The native synchronization callback does not apply a singular
                # operation. Carry older rewards through the verified stage
                # completion operation, atomically with its durable claim.
                for pending in state.get("rewardBackfills", []):
                    if not pending.get("completionId") and str(
                        pending["id"]
                    ) not in state.get("acknowledgedOperations", {}):
                        rewards.extend(
                            copy.deepcopy(pending["parameters"]["receivedItems"])
                        )
                        pending["completionId"] = sequence
                claims[key] = {
                    "id": sequence,
                    "type": 5000,
                    "signature": sequence,
                    "token": token,
                    "parameters": {
                        "UserAdventureStage": [{"adventureStageId": stage_id}],
                        "skipCount": skip_count,
                        "gainedItems": aggregate_items(items + rewards),
                        "gainedPCs": [],
                        "gainedCostumes": [],
                        "friendshipStates": request.get("friendshipStates", []),
                        "adventureStageTaskIds": request.get(
                            "adventureStageTaskIds", []
                        ),
                        "secretMissionCompleted": request.get(
                            "secretMissionCompleted", False
                        ),
                        "activeTimeAvailable": False,
                        "completedAt": int(time.time()),
                    },
                }
                self._write(state)
            operation = claims[key]
            if str(operation["id"]) not in state.get("acknowledgedOperations", {}):
                parameters = operation["parameters"]
                before = copy.deepcopy(parameters)
                parameters.setdefault("skipCount", skip_count)
                parameters["gainedItems"] = aggregate_items(parameters["gainedItems"])
                if parameters != before:
                    self._write(state)
            return {
                "code": 0,
                "data": {},
                "dataTokens": {},
                "operations": [],
                "dones": [],
                **(
                    {}
                    if str(claims[key]["id"]) in state.get("acknowledgedOperations", {})
                    else {"operation": copy.deepcopy(claims[key])}
                ),
            }

    def familia_record(self, request):
        """Keep the observed quest notification locally, without online rankings."""
        if (
            request.get("recordType") != 401
            or type(request.get("recordType")) is not int
        ):
            raise ValueError("Unreconstructed Familia record type")
        with self.lock:
            state = copy.deepcopy(self.state)
            state.setdefault("familiaNotifications", {})["401"] = True
            self._write(state)
        return {"code": 0, "data": {}, "dataTokens": {}, "operations": [], "dones": []}

    def friendship_complete(self, request):
        """Acknowledge native CP milestones once; client deltas retain CP values."""
        rows = request.get("friendshipStates")
        if not isinstance(rows, list) or not rows or len(rows) > 100:
            raise ValueError("Invalid friendship milestone batch")
        with self.lock:
            state = copy.deepcopy(self.state)
            owned = {r["characterId"] for r in state["tables"].get("UserCharacter", [])}
            claims = state.setdefault("friendshipMilestones", {})
            for row in rows:
                keys = ("characterId", "friendship", "friendshipLv", "userHeroType")
                if not isinstance(row, dict) or any(
                    type(row.get(k)) is not int for k in keys
                ):
                    raise ValueError("Invalid friendship milestone")
                if (
                    row["characterId"] not in owned
                    or not 0 <= row["friendship"] <= 100000000
                    or not 1 <= row["friendshipLv"] <= 1000
                    or row["userHeroType"] not in (0, 1, 2)
                ):
                    raise ValueError("Unsupported friendship milestone")
                key = str(row["characterId"]) + ":" + str(row["userHeroType"])
                previous = claims.get(key)
                if previous is None or row["friendshipLv"] > previous["friendshipLv"]:
                    claims[key] = copy.deepcopy(row)
            self._write(state)
            return {
                "code": 0,
                "data": {},
                "dataTokens": {},
                "operations": [],
                "dones": [],
            }

    def tutorial_draw(self, request):
        """Grant the selected free tutorial unit once per local account."""
        pc_id = request.get("pcId")
        if (
            request.get("lotteryId") != 171001765
            or type(pc_id) is not int
            or not 1011000000 <= pc_id < 1020000000
        ):
            raise ValueError("Unsupported tutorial draw")
        with self.lock:
            state = copy.deepcopy(self.state)
            tables = state["tables"]
            if not tables.get("UserInfo") or not tables.get("UserPC"):
                raise ValueError("Tutorial draw requires a bootstrapped account")
            claimed = state.get("tutorialDraw")
            if claimed:
                pc_id = claimed["pcId"]
            if not claimed:
                # Native operation 1001 builds authentic stats, jobs and skills
                # from the bundled master tables and runs tutorial.gacha_end.
                # Reserve the result here; persist the native grant via its deltas.
                state["tutorialDraw"] = {
                    "lotteryId": request["lotteryId"],
                    "pcId": pc_id,
                }
                self._write(state)
                self.state = state
            return {
                "code": 0,
                "lotteryPCs": [{"pcId": pc_id, "isFirst": True}],
                "UserCommunicationCharacter": [],
                "UserHeroSublimatePCs": [],
                "data": {
                    "lotteryPCs": [{"pcId": pc_id, "isFirst": True}],
                    "UserCommunicationCharacter": [],
                    "UserHeroSublimatePCs": [],
                },
                "dataTokens": {},
                "operations": [],
                "dones": [],
                "operation": {
                    "id": 100000001,
                    "type": 1001,
                    "signature": 100001,
                    "token": "",
                    "parameters": {
                        "UserPC": [{"pcId": pc_id}],
                        "UserLimitBreakItem": [],
                        "lotteryPCs": [{"pcId": pc_id, "isFirst": True}],
                        "UserHeroSublimatePCs": [],
                        "UserCommunicationCharacter": [],
                    },
                },
            }

    def resources(self):
        """Refill the client pools using its verified six-field row formats."""
        with self.lock:
            state = copy_state(self.state, ("UserItemToken", "UserRandomSeed"))
            info = state["tables"].get("UserInfo", [])
            if not info:
                return {}, {}
            user = info[0]["userId"]
            counter = max(state.get("resourceSequence", 100000), 100000)
            changed = False
            for table in ("UserItemToken", "UserRandomSeed"):
                rows = state["tables"].setdefault(table, [])
                fields = (
                    ("userId", "signature", "consumer", "value", "context", "verifier")
                    if table == "UserItemToken"
                    else (
                        "userId",
                        "signature",
                        "seed",
                        "consumer",
                        "result",
                        "verifier",
                    )
                )
                canonical = [{k: r[k] for k in fields} for r in rows]
                changed = changed or any(
                    list(r) != list(c) for r, c in zip(rows, canonical)
                )
                rows[:] = canonical
                available = sum(r["consumer"] == 0 for r in rows)
                while available < 100:
                    counter += 1
                    if table == "UserItemToken":
                        row = {
                            "userId": user,
                            "signature": counter,
                            "consumer": 0,
                            "value": counter,
                            "context": "",
                            "verifier": "",
                        }
                    else:
                        row = {
                            "userId": user,
                            "signature": counter,
                            "seed": secrets.randbits(32) | 0x10000,
                            "consumer": 0,
                            "result": [],
                            "verifier": "",
                        }
                    rows.append(row)
                    changed = True
                    available += 1
                # Field order matches the native MessagePack serializers.
                token = hashlib.md5(pack(rows)).hexdigest()
                changed = changed or state["tokens"].get(table) != token
                state["tokens"][table] = token
            state["resourceSequence"] = counter
            if changed:
                self._write(state)
            return (
                {
                    t: copy.deepcopy(state["tables"][t])
                    for t in ("UserItemToken", "UserRandomSeed")
                },
                {t: state["tokens"][t] for t in ("UserItemToken", "UserRandomSeed")},
            )

    def pull(self, tables):
        """
        Build a requested-table response using saved data and original bootstrap
        defaults.
        """
        with self.lock:
            return pack(
                {
                    "data": wire_tables(
                        {t: self.state["tables"].get(t, []) for t in tables}
                    ),
                    "dataTokens": {t: self.state["tokens"].get(t, "") for t in tables},
                    "recovery": False,
                }
            )
