"""Concurrent runner test: games overlap, all are saved, progress is counted."""
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

import mbti  # noqa: E402
import simulation  # noqa: E402
import store  # noqa: E402


class FakeEngine:
    def __init__(self, *args, **kwargs):
        self.on_event = kwargs.get("on_event")
        self.seed = args[3] if len(args) > 3 else 0
        self.variable_type = args[2] if len(args) > 2 else "INTJ"

    def run(self):
        time.sleep(0.15)
        if self.on_event:
            self.on_event({"type": "speech", "round": 1, "public": "测试发言", "tokens": 10})
        return {
            "seed": self.seed,
            "variable_type": self.variable_type,
            "winner": "good",
            "win_reason": "测试",
            "rounds": 1,
            "variable_roles": {"wolf": 1},
            "variable_camp_wins": {"wolf": {"players": 1, "wins": 0},
                                   "good": {"players": 0, "wins": 0}},
            "variable_player_wins": 0,
            "variable_player_count": 1,
            "duration_ms": 150,
            "tokens": 10,
            "degenerate": 0,
            "detail": {"events": [], "players": [], "public_log": [],
                       "round_summaries": [], "errors": []},
        }


class ConcurrentRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = store.DB_PATH
        store.DB_PATH = os.path.join(self.tmp.name, "runner.db")
        store.init_db()
        types = ["INTJ", "ENFP", "ISTJ", "ESFP", "INFJ", "ESTP", "ISFJ", "ENTJ", "ISTP"]
        for index, type_code in enumerate(types, 1):
            store.add_player({
                "id": "p%d" % index,
                "person_id": "per_%d" % index,
                "name": "玩家%d" % index,
                "mbti": type_code,
                "dims": {},
                "params": mbti.params_for(type_code),
                "created_at": store.now_iso(),
            })

    def tearDown(self):
        store.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_concurrent_games_complete_and_are_counted(self):
        body = {
            "variable_roles": {"wolf": 1, "villager": 0, "seer": 0, "witch": 0, "hunter": 0},
            "fixed_assignments": [
                {"role": "wolf", "player_id": "p2"},
                {"role": "wolf", "player_id": "p3"},
                {"role": "villager", "player_id": "p4"},
                {"role": "villager", "player_id": "p5"},
                {"role": "villager", "player_id": "p6"},
                {"role": "seer", "player_id": "p7"},
                {"role": "witch", "player_id": "p8"},
                {"role": "hunter", "player_id": "p9"},
            ],
            "games": 3,
            "concurrency": 2,
        }
        with patch("simulation.GameEngine", FakeEngine):
            sim = simulation.create_simulation(body)
            self.assertEqual(sim["config_json"]["concurrency"], 2)
            simulation.start_simulation(sim["id"])
            deadline = time.time() + 5
            snap = None
            while time.time() < deadline:
                snap = simulation.simulation_snapshot(sim["id"])
                if snap and snap["status"] in ("completed", "error", "stopped"):
                    break
                time.sleep(0.05)
        self.assertIsNotNone(snap)
        self.assertEqual(snap["status"], "completed", snap)
        self.assertEqual(snap["completed_games"], 3)
        self.assertEqual(store.count_games(sim["id"]), 3)
        self.assertEqual(snap.get("concurrency"), 2)
        self.assertTrue(all("第" in item["text"] for item in snap["live"] if item["type"] == "speech"))


if __name__ == "__main__":
    unittest.main()
