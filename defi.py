#!/usr/bin/env python3
"""Collect finalized Ethereum DeFi evidence for Aave V3 and Uniswap V3."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any

CHAIN_ID = 1
DEFAULT_RPC_URL = "https://eth.drpc.org"
DEFAULT_DATA_ROOT = Path("data/defi")
DEFAULT_API_DIR = Path("api/v1/defi")
HISTORY_DAYS = 92

AAVE_PROVIDER = "0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e"
AAVE_POOL_EXPECTED = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
AAVE_SOURCE = "https://github.com/aave-dao/aave-address-book/blob/main/src/AaveV3Ethereum.sol"

UNISWAP_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
UNISWAP_SOURCE = "https://github.com/Uniswap/v3-periphery/blob/main/deploys.md"
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
UNISWAP_FEE = 3000

AAVE_EVENT_SIGNATURES = {
    "supply": "Supply(address,address,address,uint256,uint16)",
    "withdraw": "Withdraw(address,address,address,uint256)",
    "borrow": "Borrow(address,address,address,uint256,uint8,uint256,uint16)",
    "repay": "Repay(address,address,address,uint256,bool)",
    "liquidation": "LiquidationCall(address,address,address,uint256,uint256,address,bool)",
}
UNISWAP_SWAP_SIGNATURE = "Swap(address,address,int256,int256,uint160,uint128,int24)"

SELECTORS = {
    "aave_get_pool": "0x026b1d5f",
    "uniswap_get_pool": "0x1698ee82",
    "token0": "0x0dfe1681",
    "token1": "0xd21220a7",
    "decimals": "0x313ce567",
}
AAVE_EVENT_TOPICS = {
    "supply": "0x2b627736bca15cd5381dcf80b0bf11fd197d01a037c52b927a881a10fb73ba61",
    "withdraw": "0x3115d1449a7b732c986cba18244e897a450f61e1bb8d589cd2e69e6c8924f9f7",
    "borrow": "0xb3d084820fb1a9decffb176436bd02558d15fac9b0ddfed8c465bc7359d7dce0",
    "repay": "0xa534c8dbe71f871f9f3530e97a74601fea17b426cae02e1c5aee42c96c784051",
    "liquidation": "0xe413a321e8681d831f4dbccbca790d2952b56f977908e45be37335533e005286",
}
UNISWAP_SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def hex_address(value: str) -> str:
    return "0x" + value[-40:].lower()


def encode_address(value: str) -> str:
    return value.removeprefix("0x").lower().rjust(64, "0")


def encode_uint(value: int) -> str:
    return hex(value)[2:].rjust(64, "0")


def decode_address(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x") or len(value) < 42:
        raise ValueError(f"invalid ABI address result: {value!r}")
    return "0x" + value[-40:]


def decode_uint(value: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ValueError(f"invalid ABI uint result: {value!r}")
    return int(value, 16)


def decode_int256(word: str) -> int:
    value = int(word, 16)
    return value - (1 << 256) if value >= (1 << 255) else value


class EvidenceStore:
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.objects = data_root / "raw" / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)

    def save(self, raw: bytes, source_url: str, request_body: object) -> dict[str, Any]:
        digest = sha256(raw)
        path = self.objects / f"{digest}.json"
        if path.exists():
            if sha256(path.read_bytes()) != digest:
                raise ValueError(f"raw evidence hash mismatch: {path}")
        else:
            path.write_bytes(raw)
            if sha256(path.read_bytes()) != digest:
                raise ValueError(f"raw evidence hash mismatch after write: {path}")
        return {
            "source_url": source_url,
            "sha256": digest,
            "path": path.relative_to(self.data_root).as_posix(),
            "request": request_body,
            "size_bytes": len(raw),
        }


class EthereumRPC:
    def __init__(self, url: str, store: EvidenceStore):
        self.url = url
        self.store = store
        self.request_id = 0

    def _send(self, method: str, params: list[Any], store: bool) -> tuple[Any, dict[str, Any] | None]:
        self.request_id += 1
        body = {"jsonrpc": "2.0", "id": self.request_id, "method": method, "params": params}
        raw_body = json.dumps(body, separators=(",", ":")).encode()
        request = urllib.request.Request(
            self.url,
            data=raw_body,
            headers={"Content-Type": "application/json", "User-Agent": "KAFKA2306/defi-primary-evidence"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read()
        ref = self.store.save(raw, self.url, body) if store else None
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError(f"{method}: unexpected JSON-RPC response")
        if payload.get("error"):
            raise RuntimeError(f"{method}: {payload['error']}")
        if "result" not in payload:
            raise ValueError(f"{method}: missing result")
        return payload["result"], ref

    def call_with_ref(self, method: str, params: list[Any]) -> tuple[Any, dict[str, Any]]:
        result, ref = self._send(method, params, store=True)
        assert ref is not None
        return result, ref

    def call(self, method: str, params: list[Any]) -> Any:
        return self._send(method, params, store=False)[0]


def eth_call(rpc: EthereumRPC, to: str, data: str, block_tag: str) -> tuple[str, dict[str, Any]]:
    value, ref = rpc.call_with_ref("eth_call", [{"to": to, "data": data}, block_tag])
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ValueError(f"invalid eth_call result from {to}")
    return value, ref


def block_timestamp(block: dict[str, Any]) -> int:
    return int(str(block["timestamp"]), 16)


def block_number(block: dict[str, Any]) -> int:
    return int(str(block["number"]), 16)


def block_at(rpc: EthereumRPC, number: int, store_ref: bool = False) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if store_ref:
        value, ref = rpc.call_with_ref("eth_getBlockByNumber", [hex(number), False])
    else:
        value = rpc.call("eth_getBlockByNumber", [hex(number), False])
        ref = None
    if not value:
        raise ValueError(f"missing Ethereum block {number}")
    if int(value["number"], 16) != number or not value.get("hash"):
        raise ValueError(f"invalid Ethereum block response {number}")
    return value, ref


def find_last_before(rpc: EthereumRPC, target_ts: int, guess: int, final_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = max(1, min(final_number, guess))
    for _ in range(6):
        block, _ = block_at(rpc, candidate)
        delta = target_ts - block_timestamp(block)
        if -24 <= delta <= 24:
            break
        step = int(delta / 12)
        if step == 0:
            step = 1 if delta > 0 else -1
        candidate = max(1, min(final_number, candidate + step))

    block, _ = block_at(rpc, candidate)
    if block_timestamp(block) < target_ts:
        low = candidate
        high = min(final_number, candidate + 128)
        high_block, _ = block_at(rpc, high)
        while high < final_number and block_timestamp(high_block) < target_ts:
            low = high
            high = min(final_number, high + 256)
            high_block, _ = block_at(rpc, high)
    else:
        high = candidate
        low = max(1, candidate - 128)
        low_block, _ = block_at(rpc, low)
        while low > 1 and block_timestamp(low_block) >= target_ts:
            high = low
            low = max(1, low - 256)
            low_block, _ = block_at(rpc, low)

    best = low
    best_block, _ = block_at(rpc, best)
    if block_timestamp(best_block) >= target_ts:
        raise ValueError(f"failed to bracket Ethereum timestamp {target_ts}")
    while low <= high:
        mid = (low + high) // 2
        current, _ = block_at(rpc, mid)
        if block_timestamp(current) < target_ts:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    final_block, final_ref = block_at(rpc, best, store_ref=True)
    if block_timestamp(final_block) >= target_ts or final_ref is None:
        raise ValueError("boundary block is not strictly before target")
    return final_block, final_ref


def resolve_boundaries(rpc: EthereumRPC, finalized: dict[str, Any], boundary_dates: list[date]) -> dict[str, dict[str, Any]]:
    final_number = block_number(finalized)
    final_ts = block_timestamp(finalized)
    needed = sorted(set(boundary_dates))
    result: dict[str, dict[str, Any]] = {}
    previous_number: int | None = None
    for current_date in needed:
        target_dt = datetime.combine(current_date, dt_time.min, tzinfo=UTC)
        target_ts = int(target_dt.timestamp())
        if previous_number is None:
            guess = final_number - round((final_ts - target_ts) / 12)
        else:
            guess = previous_number + 7200
        block, ref = find_last_before(rpc, target_ts, guess, final_number)
        previous_number = block_number(block)
        result[current_date.isoformat()] = {
            "target_time": target_dt.isoformat(),
            "block_number": previous_number,
            "block_hash": block["hash"],
            "block_timestamp": datetime.fromtimestamp(block_timestamp(block), UTC).isoformat(),
            "raw_ref": ref,
        }
    return result


def get_logs_chunked(rpc: EthereumRPC, address: str, from_block: int, to_block: int, topics: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    params = [{"address": address, "fromBlock": hex(from_block), "toBlock": hex(to_block), "topics": topics}]
    try:
        rows, ref = rpc.call_with_ref("eth_getLogs", params)
        if not isinstance(rows, list):
            raise ValueError("eth_getLogs returned non-list")
        return rows, [ref]
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError):
        if to_block - from_block < 128:
            raise
        midpoint = (from_block + to_block) // 2
        left, left_refs = get_logs_chunked(rpc, address, from_block, midpoint, topics)
        time.sleep(0.02)
        right, right_refs = get_logs_chunked(rpc, address, midpoint + 1, to_block, topics)
        return left + right, left_refs + right_refs


def verify_code(rpc: EthereumRPC, address: str, block_tag: str) -> tuple[str, dict[str, Any]]:
    code, ref = rpc.call_with_ref("eth_getCode", [address, block_tag])
    if not isinstance(code, str) or code in {"0x", "0x0"}:
        raise ValueError(f"contract has no code at {block_tag}: {address}")
    return sha256(bytes.fromhex(code.removeprefix("0x"))), ref


def resolve_contracts(rpc: EthereumRPC, finalized: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
    refs: list[dict[str, Any]] = []
    block_tag = hex(block_number(finalized))
    chain_id, ref = rpc.call_with_ref("eth_chainId", [])
    refs.append(ref)
    if int(chain_id, 16) != CHAIN_ID:
        raise ValueError(f"expected Ethereum chain_id 1, got {chain_id}")

    aave_pool_raw, ref = eth_call(rpc, AAVE_PROVIDER, SELECTORS["aave_get_pool"], block_tag)
    refs.append(ref)
    aave_pool = decode_address(aave_pool_raw)
    if aave_pool.lower() != AAVE_POOL_EXPECTED.lower():
        raise ValueError(f"Aave provider resolved unexpected pool {aave_pool}")

    calldata = SELECTORS["uniswap_get_pool"] + encode_address(USDC) + encode_address(WETH) + encode_uint(UNISWAP_FEE)
    pool_raw, ref = eth_call(rpc, UNISWAP_FACTORY, calldata, block_tag)
    refs.append(ref)
    uniswap_pool = decode_address(pool_raw)
    if int(uniswap_pool, 16) == 0:
        raise ValueError("Uniswap factory returned zero pool")

    token0_raw, ref = eth_call(rpc, uniswap_pool, SELECTORS["token0"], block_tag)
    refs.append(ref)
    token1_raw, ref = eth_call(rpc, uniswap_pool, SELECTORS["token1"], block_tag)
    refs.append(ref)
    token0 = decode_address(token0_raw)
    token1 = decode_address(token1_raw)
    if {token0.lower(), token1.lower()} != {USDC.lower(), WETH.lower()}:
        raise ValueError(f"unexpected Uniswap pool token pair {token0}/{token1}")
    decimals0_raw, ref = eth_call(rpc, token0, SELECTORS["decimals"], block_tag)
    refs.append(ref)
    decimals1_raw, ref = eth_call(rpc, token1, SELECTORS["decimals"], block_tag)
    refs.append(ref)
    decimals0 = decode_uint(decimals0_raw)
    decimals1 = decode_uint(decimals1_raw)
    if not (0 <= decimals0 <= 36 and 0 <= decimals1 <= 36):
        raise ValueError("unreasonable token decimals")

    contracts: dict[str, Any] = {
        "observed_at": datetime.fromtimestamp(block_timestamp(finalized), UTC).isoformat(),
        "block_number": block_number(finalized),
        "block_hash": finalized["hash"],
        "aave_v3": {"addresses_provider": AAVE_PROVIDER, "pool": aave_pool, "source_url": AAVE_SOURCE},
        "uniswap_v3": {
            "factory": UNISWAP_FACTORY,
            "pool": uniswap_pool,
            "fee": UNISWAP_FEE,
            "token0": token0,
            "token1": token1,
            "token0_decimals": decimals0,
            "token1_decimals": decimals1,
            "source_url": UNISWAP_SOURCE,
        },
    }
    for protocol, address in (("aave_provider", AAVE_PROVIDER), ("aave_pool", aave_pool), ("uniswap_factory", UNISWAP_FACTORY), ("uniswap_pool", uniswap_pool)):
        code_hash, ref = verify_code(rpc, address, block_tag)
        refs.append(ref)
        contracts.setdefault("code_sha256", {})[protocol] = code_hash

    topics = {f"aave_{name}": topic for name, topic in AAVE_EVENT_TOPICS.items()}
    topics["uniswap_swap"] = UNISWAP_SWAP_TOPIC
    return contracts, topics, refs


def load_raw_ref(data_root: Path, ref: dict[str, Any]) -> object:
    path = data_root / str(ref["path"])
    raw = path.read_bytes()
    if sha256(raw) != ref["sha256"]:
        raise ValueError(f"raw evidence hash mismatch: {path}")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError(f"invalid raw JSON-RPC evidence: {path}")
    return payload.get("result")


def aave_daily(logs: list[dict[str, Any]], topics: dict[str, str], day: str) -> dict[str, Any]:
    reverse = {value: key.removeprefix("aave_") for key, value in topics.items() if key.startswith("aave_")}
    counts = {name: 0 for name in AAVE_EVENT_SIGNATURES}
    reserves: set[str] = set()
    for log in logs:
        log_topics = log.get("topics") or []
        if not log_topics:
            raise ValueError("Aave log missing topics")
        name = reverse.get(str(log_topics[0]).lower())
        if name is None:
            raise ValueError(f"unknown Aave event topic {log_topics[0]}")
        counts[name] += 1
        if len(log_topics) > 1:
            reserves.add(hex_address(str(log_topics[1])))
        if name == "liquidation" and len(log_topics) > 2:
            reserves.add(hex_address(str(log_topics[2])))
    return {"date": day, "protocol": "aave_v3", "event_count": sum(counts.values()), "event_counts": counts, "reserve_addresses": sorted(reserves), "reserve_count": len(reserves)}


def uniswap_daily(logs: list[dict[str, Any]], contracts: dict[str, Any], day: str) -> dict[str, Any]:
    info = contracts["uniswap_v3"]
    gross0_raw = 0
    gross1_raw = 0
    for log in logs:
        data = str(log.get("data") or "").removeprefix("0x")
        if len(data) < 64 * 5:
            raise ValueError("Uniswap Swap log data is too short")
        words = [data[i : i + 64] for i in range(0, len(data), 64)]
        gross0_raw += abs(decode_int256(words[0]))
        gross1_raw += abs(decode_int256(words[1]))
    dec0 = int(info["token0_decimals"])
    dec1 = int(info["token1_decimals"])
    return {
        "date": day,
        "protocol": "uniswap_v3",
        "pool": info["pool"],
        "fee": info["fee"],
        "token0": info["token0"],
        "token1": info["token1"],
        "swap_count": len(logs),
        "gross_token0_raw": gross0_raw,
        "gross_token1_raw": gross1_raw,
        "gross_token0": gross0_raw / (10 ** dec0),
        "gross_token1": gross1_raw / (10 ** dec1),
        "token0_decimals": dec0,
        "token1_decimals": dec1,
    }


def collect_raw_refs(index: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    refs.extend(index.get("contract_raw_refs", []))
    for day in index.get("dates", {}).values():
        refs.append(day["start_boundary"]["raw_ref"])
        refs.append(day["end_boundary"]["raw_ref"])
        refs.extend(day.get("aave_raw_refs", []))
        refs.extend(day.get("uniswap_raw_refs", []))
    unique: dict[str, dict[str, Any]] = {}
    for ref in refs:
        unique[str(ref["sha256"])] = ref
    return list(unique.values())


def update_contract_history(data_root: Path, contracts: dict[str, Any]) -> dict[str, Any]:
    path = data_root / "contract-history.json"
    history = json.loads(path.read_text()) if path.exists() else {"schema_version": 1, "changes": []}
    fingerprint_payload = {"aave_v3": contracts["aave_v3"], "uniswap_v3": contracts["uniswap_v3"], "code_sha256": contracts["code_sha256"]}
    fingerprint = sha256(canonical_json(fingerprint_payload))
    if not history["changes"] or history["changes"][-1]["fingerprint_sha256"] != fingerprint:
        history["changes"].append({"valid_from_observed_at": contracts["observed_at"], "block_number": contracts["block_number"], "block_hash": contracts["block_hash"], "fingerprint_sha256": fingerprint, **fingerprint_payload})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(history))
    return history


def complete_dates(finalized: dict[str, Any], history_days: int) -> list[date]:
    if history_days < 90:
        raise ValueError("history-days must be at least 90")
    final_date = datetime.fromtimestamp(block_timestamp(finalized), UTC).date()
    last_complete = final_date - timedelta(days=1)
    first = last_complete - timedelta(days=history_days - 1)
    return [first + timedelta(days=offset) for offset in range(history_days)]


def live_collect(data_root: Path, rpc_url: str, history_days: int) -> dict[str, Any]:
    store = EvidenceStore(data_root)
    rpc = EthereumRPC(rpc_url, store)
    finalized, finalized_ref = rpc.call_with_ref("eth_getBlockByNumber", ["finalized", False])
    if not finalized or not finalized.get("hash"):
        raise ValueError("Ethereum finalized block unavailable")
    contracts, topics, contract_refs = resolve_contracts(rpc, finalized)
    contract_refs.append(finalized_ref)

    existing_path = data_root / "evidence-index.json"
    existing = json.loads(existing_path.read_text()) if existing_path.exists() else None
    dates_map: dict[str, Any] = dict(existing.get("dates", {})) if existing else {}
    target_dates = complete_dates(finalized, history_days)
    refresh = {day.isoformat() for day in target_dates[-2:]}
    missing = [day for day in target_dates if day.isoformat() not in dates_map or day.isoformat() in refresh]
    if missing:
        required_boundary_dates = sorted(set(missing + [day + timedelta(days=1) for day in missing]))
        boundaries = resolve_boundaries(rpc, finalized, required_boundary_dates)
        for day in missing:
            day_key = day.isoformat()
            next_key = (day + timedelta(days=1)).isoformat()
            start = boundaries[day_key]
            end = boundaries[next_key]
            from_block = int(start["block_number"]) + 1
            to_block = int(end["block_number"])
            if to_block < from_block:
                raise ValueError(f"invalid day block range {day_key}")
            aave_topics = [[topics[f"aave_{name}"] for name in AAVE_EVENT_SIGNATURES]]
            aave_logs, aave_refs = get_logs_chunked(rpc, contracts["aave_v3"]["pool"], from_block, to_block, aave_topics)
            uniswap_logs, uniswap_refs = get_logs_chunked(rpc, contracts["uniswap_v3"]["pool"], from_block, to_block, [topics["uniswap_swap"]])
            if any(str(row.get("blockHash") or "") == "" for row in aave_logs + uniswap_logs):
                raise ValueError(f"log without block hash on {day_key}")
            dates_map[day_key] = {
                "start_boundary": start,
                "end_boundary": end,
                "from_block": from_block,
                "to_block": to_block,
                "aave_log_count": len(aave_logs),
                "uniswap_log_count": len(uniswap_logs),
                "aave_raw_refs": aave_refs,
                "uniswap_raw_refs": uniswap_refs,
            }

    history = update_contract_history(data_root, contracts)
    index = {
        "schema_version": 1,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "chain_id": CHAIN_ID,
        "finalized": {"block_number": block_number(finalized), "block_hash": finalized["hash"], "block_timestamp": datetime.fromtimestamp(block_timestamp(finalized), UTC).isoformat(), "raw_ref": finalized_ref},
        "contracts": contracts,
        "event_topics": topics,
        "contract_raw_refs": contract_refs,
        "contract_history": history,
        "dates": dict(sorted(dates_map.items())),
    }
    data_root.mkdir(parents=True, exist_ok=True)
    existing_path.write_bytes(canonical_json(index))
    return index


def load_index(data_root: Path) -> dict[str, Any]:
    index = json.loads((data_root / "evidence-index.json").read_text())
    if index.get("chain_id") != CHAIN_ID:
        raise ValueError("evidence index is not Ethereum mainnet")
    for ref in collect_raw_refs(index):
        load_raw_ref(data_root, ref)
    return index


def build_api(index: dict[str, Any], data_root: Path, api_dir: Path) -> dict[str, Any]:
    aave_rows = []
    uniswap_rows = []
    for day, evidence in sorted(index["dates"].items()):
        aave_logs: list[dict[str, Any]] = []
        for ref in evidence["aave_raw_refs"]:
            result = load_raw_ref(data_root, ref)
            if not isinstance(result, list):
                raise ValueError("Aave raw log evidence is not a list")
            aave_logs.extend(result)
        uniswap_logs: list[dict[str, Any]] = []
        for ref in evidence["uniswap_raw_refs"]:
            result = load_raw_ref(data_root, ref)
            if not isinstance(result, list):
                raise ValueError("Uniswap raw log evidence is not a list")
            uniswap_logs.extend(result)
        aave_rows.append(aave_daily(aave_logs, index["event_topics"], day))
        uniswap_rows.append(uniswap_daily(uniswap_logs, index["contracts"], day))

    if not aave_rows or not uniswap_rows:
        raise ValueError("DeFi evidence index has no daily rows")
    dates = sorted({row["date"] for row in aave_rows} & {row["date"] for row in uniswap_rows})
    raw_refs = collect_raw_refs(index)
    coverage = {
        "first_date": dates[0],
        "last_date": dates[-1],
        "day_count": len(dates),
        "span_days": (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days,
        "protocol_count": 2,
        "aave_event_count": sum(row["event_count"] for row in aave_rows),
        "aave_liquidation_count": sum(row["event_counts"]["liquidation"] for row in aave_rows),
        "uniswap_swap_count": sum(row["swap_count"] for row in uniswap_rows),
        "raw_evidence_count": len(raw_refs),
        "contract_change_count": len(index.get("contract_history", {}).get("changes", [])),
    }
    if coverage["day_count"] < 90 or coverage["span_days"] < 89:
        raise ValueError(f"DeFi history is shorter than 90 days: {coverage}")

    api_dir.mkdir(parents=True, exist_ok=True)
    (api_dir / "aave-daily.json").write_bytes(canonical_json({"schema_version": 1, "records": aave_rows}))
    (api_dir / "uniswap-daily.json").write_bytes(canonical_json({"schema_version": 1, "records": uniswap_rows}))
    (api_dir / "contracts.json").write_bytes(canonical_json({"schema_version": 1, "current": index["contracts"], "history": index.get("contract_history", {"schema_version": 1, "changes": []})}))
    (api_dir / "provenance.json").write_bytes(canonical_json(index))
    aave_by_date = {row["date"]: row for row in aave_rows}
    uniswap_by_date = {row["date"]: row for row in uniswap_rows}
    combined = [{"date": day, "aave_event_count": aave_by_date[day]["event_count"], "aave_liquidation_count": aave_by_date[day]["event_counts"]["liquidation"], "uniswap_swap_count": uniswap_by_date[day]["swap_count"]} for day in dates]
    (api_dir / "daily.json").write_bytes(canonical_json({"schema_version": 1, "records": combined}))

    def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    write_csv(api_dir / "aave-daily.csv", [{"date": row["date"], "event_count": row["event_count"], "supply": row["event_counts"]["supply"], "withdraw": row["event_counts"]["withdraw"], "borrow": row["event_counts"]["borrow"], "repay": row["event_counts"]["repay"], "liquidation": row["event_counts"]["liquidation"], "reserve_count": row["reserve_count"]} for row in aave_rows], ["date", "event_count", "supply", "withdraw", "borrow", "repay", "liquidation", "reserve_count"])
    write_csv(api_dir / "uniswap-daily.csv", uniswap_rows, ["date", "pool", "fee", "token0", "token1", "swap_count", "gross_token0", "gross_token1", "token0_decimals", "token1_decimals"])

    output = {
        "schema_version": 1,
        "dataset": "Ethereum DeFi primary evidence",
        "retrieved_at": index["retrieved_at"],
        "coverage": coverage,
        "protocols": {
            "aave_v3": {"source_url": AAVE_SOURCE, "pool": index["contracts"]["aave_v3"]["pool"], "events": list(AAVE_EVENT_SIGNATURES)},
            "uniswap_v3": {"source_url": UNISWAP_SOURCE, "factory": index["contracts"]["uniswap_v3"]["factory"], "pool": index["contracts"]["uniswap_v3"]["pool"], "fee": index["contracts"]["uniswap_v3"]["fee"]},
        },
        "views": {"daily": "daily.json", "aave_daily": "aave-daily.json", "aave_daily_csv": "aave-daily.csv", "uniswap_daily": "uniswap-daily.json", "uniswap_daily_csv": "uniswap-daily.csv", "contracts": "contracts.json", "provenance": "provenance.json"},
        "rules": [
            "only complete UTC days whose end boundary is below the finalized Ethereum block are published",
            "Aave and Uniswap observations are decoded from canonical contract logs, not aggregator metrics",
            "asset-denominated Aave amounts are not summed across reserves with different units",
            "Uniswap gross token deltas are token amounts and are not labeled as USD volume",
            "contract resolution is checked against official Aave/Uniswap registries and Ethereum bytecode",
            "contract-history fingerprints record future address/code changes instead of silently merging migrations",
            "raw JSON-RPC responses are content-addressed with SHA-256 and required for offline rebuild",
        ],
    }
    (api_dir / "index.json").write_bytes(canonical_json(output))
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--api-dir", type=Path, default=DEFAULT_API_DIR)
    parser.add_argument("--rpc-url", default=os.environ.get("ETH_RPC_URL", DEFAULT_RPC_URL))
    parser.add_argument("--history-days", type=int, default=HISTORY_DAYS)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    index = load_index(args.data_root) if args.offline else live_collect(args.data_root, args.rpc_url, args.history_days)
    output = build_api(index, args.data_root, args.api_dir)
    print(json.dumps(output["coverage"], sort_keys=True))


if __name__ == "__main__":
    main()
