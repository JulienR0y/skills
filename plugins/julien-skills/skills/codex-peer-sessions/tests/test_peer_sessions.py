from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_script(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


spawn_fleet = load_script("spawn_fleet", "spawn-fleet.py")
fleet_state = load_script("fleet_state_under_test", "fleet_state.py")
fleet_events = load_script("fleet_events_under_test", "fleet_events.py")
peer_event = load_script("peer_event", "peer-event.py")
peer_send = load_script("peer_send", "peer-send.py")
peer_read = load_script("peer_read", "peer-read.py")
peer_wait = load_script("peer_wait", "peer-wait.py")
herdr_client = sys.modules["herdr_client"]


class HerdrClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.herdr_env = patch.dict(os.environ, {"HERDR_ENV": "1"})
        self.herdr_env.start()

    def tearDown(self) -> None:
        self.herdr_env.stop()
    @patch.object(herdr_client.subprocess, "run")
    def test_accepts_an_empty_success_response(self, run) -> None:
        run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")

        self.assertIsNone(
            herdr_client.call(
                "pane",
                "report-metadata",
                "w9:p1",
                "--source",
                "codex-peer-sessions",
            )
        )

    @patch.object(herdr_client.subprocess, "run")
    def test_reads_pane_process_information(self, run) -> None:
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=(
                '{"result":{"process_info":{"foreground_processes":'
                '[{"name":"codex","pid":1234}]}}}'
            ),
            stderr="",
        )

        self.assertEqual(
            herdr_client.pane_process_info("w9:p1")["foreground_processes"][0][
                "pid"
            ],
            1234,
        )

    @patch.object(herdr_client.subprocess, "run")
    def test_start_agent_reports_early_codex_exit_and_exact_pane_output(self, run) -> None:
        run.side_effect = [
            SimpleNamespace(
                returncode=1,
                stdout=(
                    '{"error":"The pane was created, but Herdr timed out waiting '
                    'for the Codex process to report ready."}'
                ),
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=(
                    '{"result":{"process_info":{"foreground_processes":'
                    '[{"name":"zsh","pid":1000}]}}}'
                ),
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=(
                    "error: the argument '--sandbox <SANDBOX_MODE>' cannot be used "
                    "with '--approve-for-me'\n"
                ),
                stderr="",
            ),
        ]

        with patch.dict(herdr_client.os.environ, {"HERDR_ENV": "1"}, clear=True):
            with self.assertRaises(herdr_client.HerdrError) as raised:
                herdr_client.start_agent(
                    "source-review",
                    "w9:p1",
                    ["codex", "-C", "/repo", "--sandbox", "workspace-write"],
                    retry_seconds=0,
                )

        message = str(raised.exception)
        self.assertIn("Codex exited before reporting ready in pane w9:p1", message)
        self.assertIn("cannot be used with '--approve-for-me'", message)
        self.assertIn("herdr pane read w9:p1", message)

    @patch.object(herdr_client, "agent_get")
    @patch.object(herdr_client, "call")
    def test_start_agent_falls_back_to_direct_run_when_shell_never_becomes_agent_capable(
        self, call_mock, agent_get
    ) -> None:
        call_mock.side_effect = [
            herdr_client.HerdrError("agent_pane_busy"),
            {"pane": {"pane_id": "w9:p1"}},
        ]
        agent_get.return_value = {
            "agent": "codex",
            "agent_status": "idle",
            "interactive_ready": True,
            "pane_id": "w9:p1",
        }

        with patch.object(herdr_client.shutil, "which", return_value="C:/bin/codex.exe"):
            result = herdr_client.start_agent(
                "source-review",
                "w9:p1",
                ["codex", "-C", "C:/repo", "--sandbox", "read-only"],
                retry_seconds=0,
            )

        self.assertEqual(result["startup_transport"], "pane-run")
        self.assertEqual(
            call_mock.call_args_list[-1],
            call("pane", "run", "w9:p1", "/c/bin/codex.exe", "-C", "/c/repo", "--sandbox", "read-only"),
        )

    @patch.object(herdr_client, "agent_get")
    @patch.object(herdr_client, "agent_visible_text", return_value="Codex ready")
    @patch.object(herdr_client, "call")
    def test_prompt_waits_for_a_real_state_change(self, call_mock, visible, agent_get) -> None:
        agent_get.side_effect = [
            {"agent_status": "idle", "interactive_ready": True, "state_change_seq": 7},
            {"agent_status": "working", "interactive_ready": True, "state_change_seq": 8},
        ]

        result = herdr_client.prompt_agent("w9:p1", "job-123", "Review this")

        self.assertEqual(result["delivery_status"], "accepted")
        self.assertEqual(result["job_id"], "job-123")
        call_mock.assert_called_once_with(
            "agent",
            "prompt",
            "w9:p1",
            "[codex-peer job job-123]\nReview this",
            "--wait",
            "--until",
            "working",
            "--timeout",
            "8000",
        )

    @patch.object(herdr_client, "agent_get")
    @patch.object(
        herdr_client,
        "agent_visible_text",
        side_effect=("Codex ready", "› [Pasted Content 42 chars]"),
    )
    @patch.object(herdr_client, "call")
    def test_prompt_recovers_only_its_new_paste_buffer(
        self, call_mock, visible, agent_get
    ) -> None:
        agent_get.side_effect = [
            {"agent_status": "idle", "interactive_ready": True, "state_change_seq": 7},
            {"agent_status": "working", "interactive_ready": True, "state_change_seq": 8},
        ]
        call_mock.side_effect = [
            herdr_client.HerdrError("agent_prompt_stalled"),
            None,
        ]

        result = herdr_client.prompt_agent("w9:p1", "job-123", "Review this")

        self.assertEqual(result["delivery_status"], "accepted")
        self.assertEqual(
            call_mock.call_args_list[1], call("pane", "send-keys", "w9:p1", "enter")
        )

    @patch.object(herdr_client, "agent_visible_text", return_value="Codex ready")
    @patch.object(
        herdr_client,
        "agent_get",
        return_value={"agent_status": "working", "interactive_ready": True},
    )
    def test_prompt_refuses_to_queue_behind_an_active_turn(self, agent_get, visible) -> None:
        with self.assertRaisesRegex(herdr_client.HerdrError, "already working"):
            herdr_client.prompt_agent("w9:p1", "job-123", "Review this")

    @patch.object(
        herdr_client,
        "agent_visible_text",
        return_value="Do you trust the contents of this directory?",
    )
    @patch.object(
        herdr_client,
        "agent_get",
        return_value={"agent_status": "idle", "interactive_ready": True},
    )
    def test_prompt_refuses_to_cross_a_repository_trust_screen(self, agent_get, visible) -> None:
        with self.assertRaisesRegex(herdr_client.HerdrError, "setup screen"):
            herdr_client.prompt_agent("w9:p1", "job-123", "Review this")


class PlacementTests(unittest.TestCase):
    def test_auto_uses_one_fleet_workspace_for_herdr(self) -> None:
        self.assertEqual(
            spawn_fleet.resolve_placement("auto", "herdr"),
            "fleet-workspace",
        )

    def test_auto_preserves_per_worker_workspaces_for_cmux(self) -> None:
        self.assertEqual(
            spawn_fleet.resolve_placement("auto", "cmux"),
            "workspace",
        )

    def test_fleet_workspace_is_rejected_for_cmux(self) -> None:
        with self.assertRaisesRegex(SystemExit, "Herdr"):
            spawn_fleet.resolve_placement("fleet-workspace", "cmux")


class WorkerCommandTests(unittest.TestCase):
    @patch.object(spawn_fleet.os, "name", "nt")
    def test_windows_pane_worker_avoids_shared_daemon(self) -> None:
        args = SimpleNamespace(
            model=None,
            sandbox="read-only",
            approve_for_me=False,
            codex_arg=[],
        )

        self.assertEqual(
            spawn_fleet.worker_command(args, "/repo"),
            ["codex", "-C", "/repo", "--sandbox", "read-only", "--no-daemon"],
        )

    @patch.object(spawn_fleet.os, "name", "posix")
    def test_non_windows_pane_worker_preserves_shared_daemon_default(self) -> None:
        args = SimpleNamespace(
            model=None,
            sandbox="read-only",
            approve_for_me=False,
            codex_arg=[],
        )

        self.assertEqual(
            spawn_fleet.worker_command(args, "/repo"),
            ["codex", "-C", "/repo", "--sandbox", "read-only"],
        )

    def test_approve_for_me_uses_its_implicit_workspace_write_sandbox(self) -> None:
        args = SimpleNamespace(
            model=None,
            sandbox="workspace-write",
            approve_for_me=True,
            codex_arg=[],
        )

        command = spawn_fleet.worker_command(args, "/repo")

        self.assertIn("--approve-for-me", command)
        self.assertNotIn("--sandbox", command)

    def test_approve_for_me_rejects_a_different_sandbox_before_launch(self) -> None:
        args = SimpleNamespace(
            model=None,
            sandbox="read-only",
            approve_for_me=True,
            codex_arg=[],
        )

        with self.assertRaisesRegex(SystemExit, "implies the workspace-write sandbox"):
            spawn_fleet.worker_command(args, "/repo")


class HerdrFleetWorkspaceTests(unittest.TestCase):
    def test_extracts_the_exact_codex_pid_from_pane_process_information(self) -> None:
        process_info = {
            "foreground_processes": [
                {"name": "zsh", "pid": 1000},
                {"name": "codex", "pid": 1234},
            ]
        }

        self.assertEqual(spawn_fleet.codex_pid(process_info), 1234)

    @patch.object(spawn_fleet, "herdr_pane_process_info")
    @patch.object(spawn_fleet, "herdr_agent_get")
    @patch.object(spawn_fleet, "herdr_agent_rename")
    @patch.object(spawn_fleet, "herdr_pane_metadata")
    @patch.object(spawn_fleet, "herdr_pane_rename")
    @patch.object(spawn_fleet, "herdr_start_agent")
    @patch.object(spawn_fleet, "herdr_pane_split")
    @patch.object(spawn_fleet, "herdr_create_workspace")
    def test_creates_one_named_workspace_with_balanced_named_workers(
        self,
        create_workspace,
        pane_split,
        start_agent,
        pane_rename,
        pane_metadata,
        agent_rename,
        agent_get,
        pane_process_info,
    ) -> None:
        create_workspace.return_value = {
            "workspace": {"workspace_id": "w9"},
            "root_pane": {"pane_id": "w9:p1"},
        }
        pane_split.side_effect = [
            {"pane_id": "w9:p2", "workspace_id": "w9"},
            {"pane_id": "w9:p3", "workspace_id": "w9"},
        ]
        start_agent.side_effect = [
            {"agent": {"pane_id": "w9:p1"}},
            {"agent": {"pane_id": "w9:p2"}},
            {"agent": {"pane_id": "w9:p3"}},
        ]
        agent_get.side_effect = [
            {"name": "source-review", "pane_id": "w9:p1"},
            {"name": "iac-review", "pane_id": "w9:p2"},
            {"name": "breakage-review", "pane_id": "w9:p3"},
        ]
        pane_process_info.side_effect = [
            {"foreground_processes": [{"name": "codex", "pid": 101}]},
            {"foreground_processes": [{"name": "codex", "pid": 102}]},
            {"foreground_processes": [{"name": "codex", "pid": 103}]},
        ]
        args = SimpleNamespace(
            fleet_label="Study Relay - S3 review",
            focus=False,
            model=None,
            sandbox="read-only",
            approve_for_me=False,
            codex_arg=[],
        )

        records = spawn_fleet.launch_herdr_fleet_workspace(
            [
                ("source-review", "/repo/backend"),
                ("iac-review", "/repo/iac"),
                ("breakage-review", "/repo/backend"),
            ],
            args,
            "study-relay-s3-review",
        )

        create_workspace.assert_called_once_with(
            "Study Relay - S3 review", "/repo/backend", False
        )
        self.assertEqual(
            pane_split.call_args_list,
            [
                call("w9:p1", "right", "/repo/iac", False),
                call("w9:p1", "down", "/repo/backend", False),
            ],
        )
        self.assertEqual(
            pane_rename.call_args_list,
            [
                call("w9:p1", "source-review"),
                call("w9:p2", "iac-review"),
                call("w9:p3", "breakage-review"),
            ],
        )
        self.assertEqual(
            agent_rename.call_args_list,
            [
                call("w9:p1", "source-review"),
                call("w9:p2", "iac-review"),
                call("w9:p3", "breakage-review"),
            ],
        )
        self.assertEqual({record["workspace_id"] for record in records}, {"w9"})
        self.assertTrue(all(record["name_verified"] for record in records))
        self.assertEqual(
            [record["pane_id"] for record in records],
            ["w9:p1", "w9:p2", "w9:p3"],
        )
        self.assertEqual([record["pid"] for record in records], [101, 102, 103])
        self.assertEqual(pane_metadata.call_count, 3)

    @patch.object(spawn_fleet, "herdr_pane_process_info")
    @patch.object(spawn_fleet, "herdr_agent_get")
    @patch.object(spawn_fleet, "herdr_agent_rename")
    @patch.object(spawn_fleet, "herdr_pane_metadata")
    @patch.object(spawn_fleet, "herdr_pane_rename")
    @patch.object(spawn_fleet, "herdr_start_agent")
    def test_rejects_a_worker_when_the_visible_name_does_not_resolve_to_its_pane(
        self,
        start_agent,
        pane_rename,
        pane_metadata,
        agent_rename,
        agent_get,
        pane_process_info,
    ) -> None:
        start_agent.return_value = {"agent": {"pane_id": "w9:p1"}}
        agent_get.return_value = {"name": "codex", "pane_id": "w9:p1"}
        pane_process_info.return_value = {
            "foreground_processes": [{"name": "codex", "pid": 1234}]
        }
        args = SimpleNamespace(
            model=None,
            sandbox="read-only",
            approve_for_me=False,
            codex_arg=[],
        )

        with self.assertRaisesRegex(
            spawn_fleet.HerdrError, "verification failed"
        ) as raised:
            spawn_fleet.start_herdr_worker(
                "source-review",
                "/repo/backend",
                "w9:p1",
                "w9",
                "fleet-workspace",
                args,
            )

        self.assertEqual(raised.exception.partial_record["pid"], 1234)
        self.assertFalse(raised.exception.partial_record["name_verified"])

    @patch.object(spawn_fleet, "herdr_pane_process_info")
    @patch.object(spawn_fleet, "herdr_start_agent")
    def test_start_failure_preserves_the_created_pane_record(
        self,
        start_agent,
        pane_process_info,
    ) -> None:
        start_agent.side_effect = spawn_fleet.HerdrError("Codex exited in pane w9:p1")
        pane_process_info.return_value = {
            "foreground_processes": [{"name": "zsh", "pid": 1000}]
        }
        args = SimpleNamespace(
            model=None,
            sandbox="read-only",
            approve_for_me=False,
            codex_arg=[],
        )

        with self.assertRaises(spawn_fleet.HerdrError) as raised:
            spawn_fleet.start_herdr_worker(
                "source-review",
                "/repo/backend",
                "w9:p1",
                "w9",
                "fleet-workspace",
                args,
            )

        self.assertEqual(raised.exception.partial_record["pane_id"], "w9:p1")
        self.assertEqual(raised.exception.partial_record["workspace_id"], "w9")
        self.assertEqual(raised.exception.partial_record["startup_status"], "failed")
        self.assertIn("Codex exited", raised.exception.partial_record["startup_error"])

    def test_failed_launch_writes_metadata_and_pane_scoped_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            error = spawn_fleet.HerdrError("Codex exited before reporting ready")
            error.cleanup_records = [
                {
                    "name": "source-review",
                    "backend": "herdr",
                    "directory": directory,
                    "placement": "fleet-workspace",
                    "pane_id": "w9:p1",
                    "workspace_id": "w9",
                    "pid": None,
                    "command": ["codex", "-C", directory, "--sandbox", "read-only"],
                    "startup_status": "failed",
                    "startup_error": str(error),
                }
            ]
            stdout = io.StringIO()
            stderr = io.StringIO()
            argv = [
                "spawn-fleet.py",
                "--backend",
                "herdr",
                "--fleet-id",
                "failed-readiness",
                "--sandbox",
                "read-only",
                f"source-review:{directory}",
            ]

            with patch.dict(
                os.environ, {"CODEX_HOME": directory, "HERDR_ENV": "1"}
            ), patch.object(
                spawn_fleet, "resolve_backend", return_value="herdr"
            ), patch.object(spawn_fleet, "herdr_caller_context"), patch.object(
                spawn_fleet,
                "launch_herdr_fleet_workspace",
                side_effect=error,
            ), patch.object(sys, "argv", argv), contextlib.redirect_stdout(
                stdout
            ), contextlib.redirect_stderr(stderr):
                self.assertEqual(spawn_fleet.main(), 1)

            metadata = Path(directory) / "peer-sessions" / "failed-readiness.json"
            self.assertTrue(metadata.is_file())
            payload = json.loads(metadata.read_text())
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["workers"][0]["pane_id"], "w9:p1")
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertIn(str(metadata), combined)
            self.assertIn(
                "herdr pane read w9:p1 --source recent-unwrapped --lines 80",
                combined,
            )
            self.assertIn("herdr workspace close w9", combined)

    def test_cleanup_prints_one_close_command_for_a_fleet_workspace(self) -> None:
        records = [
            {
                "name": "source-review",
                "placement": "fleet-workspace",
                "workspace_id": "w9",
            },
            {
                "name": "iac-review",
                "placement": "fleet-workspace",
                "workspace_id": "w9",
            },
        ]
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            spawn_fleet.print_cleanup(records, "herdr")

        self.assertEqual(output.getvalue().count("herdr workspace close w9"), 1)


class StableAddressTests(unittest.TestCase):
    def test_herdr_target_prefers_recorded_pane_id(self) -> None:
        worker = {"name": "source-review", "pane_id": "w9:p1"}

        self.assertEqual(fleet_state.herdr_target(worker), "w9:p1")

    def test_herdr_target_falls_back_to_name_for_old_metadata(self) -> None:
        worker = {"name": "source-review"}

        self.assertEqual(fleet_state.herdr_target(worker), "source-review")

    def test_event_logs_are_per_fleet_and_normalize_one_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"CODEX_HOME": directory}
        ):
            worker = {"name": "source-review"}
            payload = {"fleet_id": "fleet-a", "workers": [worker]}

            fleet_events.append_event(
                payload,
                "validation",
                "2/2 passed\nno secrets | retained",
                worker=worker,
                job_id="job-1",
                session_id="session-1",
            )

            timeline = Path(payload["timeline_log"])
            worker_log = Path(worker["event_log"])
            self.assertTrue(timeline.is_file())
            self.assertEqual(worker_log.parent.name, "workers")
            line = worker_log.read_text()
            self.assertEqual(line.count("\n"), 1)
            self.assertIn("session=session-1", line)
            self.assertIn("job=job-1", line)
            self.assertIn("no secrets \\| retained", line)

            fleet_events.append_event(
                payload,
                "Contract_Update",
                "normalized",
                worker=worker,
            )
            self.assertIn("| contract-update |", worker_log.read_text())

    def test_peer_event_appends_only_to_named_worker_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"CODEX_HOME": directory}
        ):
            metadata = Path(directory) / "peer-sessions" / "fleet-a.json"
            fleet_state.save_fleet(
                metadata,
                {"fleet_id": "fleet-a", "workers": [{"name": "source-review"}]},
            )
            with patch.object(
                sys,
                "argv",
                [
                    "peer-event.py",
                    "--fleet",
                    "fleet-a",
                    "--name",
                    "source-review",
                    "--event",
                    "blocked",
                    "--detail",
                    "waiting for test DB",
                ],
            ), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(peer_event.main(), 0)

            payload = json.loads(metadata.read_text())
            worker_log = Path(payload["workers"][0]["event_log"])
            self.assertIn("blocked", worker_log.read_text())
            self.assertIn("reported_by=worker", worker_log.read_text())
            self.assertEqual(Path(payload["timeline_log"]).read_text(), "")

    def test_event_logs_reject_path_escape_components(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"CODEX_HOME": directory}
        ):
            with self.assertRaisesRegex(ValueError, "path component"):
                fleet_events.initialize_event_logs(
                    {"fleet_id": "fleet-a", "workers": [{"name": "../other"}]}
                )

    @patch.object(peer_send, "save_fleet")
    @patch.object(peer_send, "prompt_agent", return_value={"delivery_status": "accepted"})
    @patch.object(peer_send, "load_fleet")
    def test_send_uses_recorded_pane_id(self, load_fleet, prompt_agent, save_fleet) -> None:
        load_fleet.return_value = (
            {
                "backend": "herdr",
                "workers": [{"name": "source-review", "pane_id": "w9:p1"}],
            },
            Path("fleet.json"),
        )

        with patch.object(
            sys,
            "argv",
            [
                "peer-send.py",
                "--fleet",
                "fleet",
                "--name",
                "source-review",
                "--message",
                "Continue",
            ],
        ), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(peer_send.main(), 0)

        target, job_id, message = prompt_agent.call_args.args
        self.assertEqual(target, "w9:p1")
        self.assertEqual(message, "Peer message from: coordinator\n\nContinue")
        self.assertTrue(job_id)
        saved_payload = save_fleet.call_args.args[1]
        self.assertEqual(
            saved_payload["workers"][0]["last_job"]["collection_status"],
            "pending",
        )

    def test_send_identifies_worker_sender(self) -> None:
        self.assertEqual(
            peer_send.peer_message("source-review", "Check the tests"),
            "Peer message from: source-review\n\nCheck the tests",
        )
        with self.assertRaisesRegex(ValueError, "one non-empty line"):
            peer_send.peer_message("bad\nsender", "Check the tests")

    @patch.object(peer_read, "agent_read", return_value="STATUS: done")
    @patch.object(peer_read, "load_fleet")
    def test_read_uses_recorded_pane_id(self, load_fleet, agent_read) -> None:
        load_fleet.return_value = (
            {
                "backend": "herdr",
                "workers": [{"name": "source-review", "pane_id": "w9:p1"}],
            },
            Path("fleet.json"),
        )
        output = io.StringIO()

        with patch.object(
            sys,
            "argv",
            [
                "peer-read.py",
                "--fleet",
                "fleet",
                "--name",
                "source-review",
            ],
        ), contextlib.redirect_stdout(output):
            self.assertEqual(peer_read.main(), 0)

        agent_read.assert_called_once_with("w9:p1", 120)
        self.assertIn("STATUS: done", output.getvalue())

    @patch.object(peer_wait, "save_fleet")
    @patch.object(peer_wait, "agent_read", return_value="STATUS: done")
    @patch.object(
        peer_wait,
        "agent_get",
        return_value={"agent_status": "done"},
    )
    @patch.object(peer_wait, "wait_agent")
    @patch.object(peer_wait, "load_fleet")
    def test_wait_collects_the_last_acknowledged_job(
        self, load_fleet, wait_agent_mock, agent_get, agent_read, save_fleet
    ) -> None:
        load_fleet.return_value = (
            {
                "backend": "herdr",
                "workers": [
                    {
                        "name": "source-review",
                        "pane_id": "w9:p1",
                        "last_job": {
                            "job_id": "job-123",
                            "delivery_status": "accepted",
                        },
                    }
                ],
            },
            Path("fleet.json"),
        )
        output = io.StringIO()

        with patch.object(
            sys,
            "argv",
            [
                "peer-wait.py",
                "--fleet",
                "fleet",
                "--name",
                "source-review",
                "--timeout",
                "10",
            ],
        ), contextlib.redirect_stdout(output):
            self.assertEqual(peer_wait.main(), 0)

        wait_agent_mock.assert_called_once_with("w9:p1", 10.0)
        self.assertIn('"job_id": "job-123"', output.getvalue())
        self.assertIn('"status": "done"', output.getvalue())
        saved_payload = save_fleet.call_args.args[1]
        self.assertEqual(
            saved_payload["workers"][0]["last_job"]["collection_status"],
            "collected",
        )


if __name__ == "__main__":
    unittest.main()
