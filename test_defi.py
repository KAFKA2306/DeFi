import tempfile
import unittest
from pathlib import Path

from build_raw_evidence_view import build as build_raw_evidence_view, build_locators
from defi import AAVE_EVENT_SIGNATURES, EvidenceStore, aave_daily, canonical_json, decode_int256, load_raw_ref, sha256, uniswap_daily


class DefiEvidenceTests(unittest.TestCase):
    def test_decode_signed_int256(self):
        self.assertEqual(decode_int256("0" * 63 + "a"), 10)
        self.assertEqual(decode_int256("f" * 64), -1)

    def test_aave_daily_counts_protocol_events_without_mixing_amounts(self):
        topics = {f"aave_{name}": "0x" + f"{index:064x}" for index, name in enumerate(AAVE_EVENT_SIGNATURES, start=1)}
        reserve = "0x" + "11" * 20
        debt = "0x" + "22" * 20
        logs = [
            {"topics": [topics["aave_supply"], "0x" + reserve[2:].rjust(64, "0")]},
            {"topics": [topics["aave_borrow"], "0x" + reserve[2:].rjust(64, "0")]},
            {"topics": [topics["aave_liquidation"], "0x" + reserve[2:].rjust(64, "0"), "0x" + debt[2:].rjust(64, "0")]},
        ]
        row = aave_daily(logs, topics, "2026-01-01")
        self.assertEqual(row["event_count"], 3)
        self.assertEqual(row["event_counts"]["supply"], 1)
        self.assertEqual(row["event_counts"]["borrow"], 1)
        self.assertEqual(row["event_counts"]["liquidation"], 1)
        self.assertEqual(row["reserve_count"], 2)

    def test_uniswap_swap_aggregates_absolute_token_deltas(self):
        def word(value: int) -> str:
            if value < 0:
                value = (1 << 256) + value
            return f"{value:064x}"

        logs = [
            {"data": "0x" + word(2_000_000) + word(-10**18) + word(1) + word(2) + word(3)},
            {"data": "0x" + word(-3_000_000) + word(2 * 10**18) + word(1) + word(2) + word(3)},
        ]
        contracts = {"uniswap_v3": {"pool": "0xpool", "fee": 3000, "token0": "0xusdc", "token1": "0xweth", "token0_decimals": 6, "token1_decimals": 18}}
        row = uniswap_daily(logs, contracts, "2026-01-01")
        self.assertEqual(row["swap_count"], 2)
        self.assertEqual(row["gross_token0"], 5.0)
        self.assertEqual(row["gross_token1"], 3.0)

    def test_evidence_store_reuses_only_matching_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = EvidenceStore(root)
            raw = canonical_json({"jsonrpc": "2.0", "id": 1, "result": []})
            request = {"jsonrpc": "2.0", "id": 1, "method": "eth_test", "params": []}

            first_ref = store.save(raw, "https://example.invalid", request)
            path = root / first_ref["path"]
            self.assertEqual(first_ref["sha256"], sha256(raw))
            self.assertEqual(path.read_bytes(), raw)

            first_mtime_ns = path.stat().st_mtime_ns
            second_ref = store.save(raw, "https://example.invalid", request)
            self.assertEqual(second_ref, first_ref)
            self.assertEqual(path.stat().st_mtime_ns, first_mtime_ns)
            self.assertEqual(path.read_bytes(), raw)

            corrupted = b"{}"
            path.write_bytes(corrupted)
            with self.assertRaisesRegex(ValueError, "raw evidence hash mismatch"):
                store.save(raw, "https://example.invalid", request)
            self.assertEqual(path.read_bytes(), corrupted)

    def test_raw_reference_hash_is_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_dir = root / "raw" / "objects"
            raw_dir.mkdir(parents=True)
            raw = canonical_json({"jsonrpc": "2.0", "id": 1, "result": []})
            digest = sha256(raw)
            path = raw_dir / f"{digest}.json"
            path.write_bytes(raw)
            ref = {"path": path.relative_to(root).as_posix(), "sha256": digest, "source_url": "https://example.invalid"}
            self.assertEqual(load_raw_ref(root, ref), [])
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "raw evidence hash mismatch"):
                load_raw_ref(root, ref)

    def test_standard_raw_evidence_view_preserves_source_hash_and_path(self):
        ref = {
            "path": "raw/objects/" + "a" * 64 + ".json",
            "sha256": "a" * 64,
            "source_url": "https://eth.drpc.org",
        }
        provenance = {
            "chain_id": 1,
            "contract_history": {"schema_version": 1, "changes": []},
            "contract_raw_refs": [ref],
            "dates": {
                "2026-01-01": {
                    "from_block": 100,
                    "to_block": 199,
                    "aave_log_count": 3,
                    "aave_raw_refs": [ref],
                    "uniswap_log_count": 2,
                    "uniswap_raw_refs": [ref],
                    "start_boundary": {"block_number": 99, "block_hash": "0xstart", "block_timestamp": "2025-12-31T23:59:59+00:00", "raw_ref": ref},
                    "end_boundary": {"block_number": 199, "block_hash": "0xend", "block_timestamp": "2026-01-01T23:59:59+00:00", "raw_ref": ref},
                }
            },
        }
        view = build_raw_evidence_view(provenance)
        self.assertEqual(view["record_count"], 1)
        self.assertEqual(
            view["records"],
            [{"source_evidence_path": ref["path"], "source_sha256": ref["sha256"], "source_url": ref["source_url"]}],
        )

        locators = build_locators(provenance)
        self.assertEqual(locators["chain_id"], 1)
        self.assertEqual(locators["record_count"], 1)
        day = locators["records"][0]
        self.assertEqual((day["from_block"], day["to_block"]), (100, 199))
        self.assertEqual(day["start_boundary"]["block_hash"], "0xstart")
        self.assertEqual(day["end_boundary"]["block_hash"], "0xend")
        self.assertEqual(day["aave"]["raw_refs"][0]["source_sha256"], "a" * 64)
        self.assertEqual(day["uniswap"]["raw_refs"][0]["source_evidence_path"], ref["path"])


if __name__ == "__main__":
    unittest.main()
