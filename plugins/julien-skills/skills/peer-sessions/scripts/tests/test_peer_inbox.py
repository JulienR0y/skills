from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(
    os.environ.get("PEER_SCRIPTS_DIR", Path(__file__).resolve().parents[1])
)
MODULE_PATH = Path(os.environ.get("PEER_INBOX_PATH", SCRIPTS / "peer-inbox.py"))
TRANSCRIPT = Path(__file__).with_name("peer-events.jsonl")
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("peer_inbox_under_test", MODULE_PATH)
peer_inbox = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(peer_inbox)


class PeerInboxTests(unittest.TestCase):
    def test_reads_utf8_peer_transcript(self) -> None:
        messages = peer_inbox.peer_messages(TRANSCRIPT, msg_id="msg-utf8")

        self.assertEqual(messages[0]["body"], "STATUS: ❝ready❞")
        self.assertEqual(messages[0]["verifiedPeerPid"], 4312)

    def test_accepts_missing_pid_when_unique_live_registry_pipe_matches(self) -> None:
        pipe = r"\\.\pipe\LOCAL\cc-msg-worker"
        records = [{"pid": 4312, "name": "worker", "messagingSocketPath": pipe}]

        messages = peer_inbox.peer_messages(
            TRANSCRIPT,
            sender="worker",
            msg_id="msg-fallback",
            verified_records=records,
        )

        self.assertEqual(messages[0]["verifiedPeerPid"], 4312)
        self.assertEqual(messages[0]["verification"], "registry_pipe")

    def test_rejects_missing_pid_when_pipe_match_is_ambiguous(self) -> None:
        pipe = r"\\.\pipe\LOCAL\cc-msg-worker"
        records = [
            {"pid": 4312, "name": "worker", "messagingSocketPath": pipe},
            {"pid": 8754, "name": "worker", "messagingSocketPath": pipe},
        ]

        messages = peer_inbox.peer_messages(
            TRANSCRIPT, msg_id="msg-fallback", verified_records=records
        )

        self.assertEqual(messages, [])

    def test_rejects_missing_pid_when_registry_name_conflicts(self) -> None:
        pipe = r"\\.\pipe\LOCAL\cc-msg-worker"
        records = [{"pid": 4312, "name": "worker", "messagingSocketPath": pipe}]

        messages = peer_inbox.peer_messages(
            TRANSCRIPT, msg_id="msg-name", verified_records=records
        )

        self.assertEqual(messages, [])


if __name__ == "__main__":
    unittest.main()
