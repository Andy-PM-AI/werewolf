"""Core rule tests: MBTI scoring, engine win checks, validation and stats.

Run with: PYTHONPATH=backend python3 -m unittest discover -s tests
"""
import os
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

import engine  # noqa: E402
import mbti  # noqa: E402
import simulation  # noqa: E402
import store  # noqa: E402


def player(index, mbti_type="INTJ", variable=False):
    return {
        "id": "p%d" % index,
        "name": "玩家%d" % index,
        "age": 30,
        "gender": "女",
        "province": "北京",
        "occupation": "职员",
        "mbti": mbti_type,
        "params": mbti.params_for(mbti_type),
        "persona": "玩家%d的人物" % index,
        "_is_variable": variable,
    }


def roster(variable_wolves=3, villagers=None):
    by_role = {"wolf": [], "villager": [], "seer": [], "witch": [], "hunter": []}
    types = {
        "wolf": ["INTJ"] * 3,
        "villager": villagers or ["ENFP", "ISTJ", "ESFP"],
        "seer": ["INFJ"],
        "witch": ["ESTP"],
        "hunter": ["ISFJ"],
    }
    index = 0
    for role, role_types in types.items():
        for type_code in role_types:
            index += 1
            by_role[role].append(player(index, type_code, role == "wolf" and index <= variable_wolves))
    return by_role


def seats_in(prompt, marker):
    match = re.search(marker + r"[：:]\s*([^\n。]+)", prompt)
    if not match:
        return []
    return [int(x) for x in re.findall(r"(\d+)号", match.group(1))]


def fake_chat(system, user, **kwargs):
    if '"speech"' in user:
        seats = seats_in(user, "存活玩家")
        target = seats[0] if seats else 1
        return {"speech": "我怀疑%d号，今天先出他。" % target}, {"total_tokens": 80}
    if "投票阶段" in user:
        seats = seats_in(user, "存活玩家")
        me = re.search(r"你是 (\d+) 号", user)
        my_seat = int(me.group(1)) if me else 0
        options = [s for s in seats if s != my_seat] or seats
        return {"target": options[0]}, {"total_tokens": 20}
    if "狼人商议刀人" in user:
        seats = seats_in(user, "存活好人")
        return {"target": seats[0]}, {"total_tokens": 20}
    if "今晚被狼人刀的是" in user:
        return {"save": False, "poison": None}, {"total_tokens": 20}
    if "选择一名存活玩家查验" in user:
        seats = seats_in(user, "候选")
        me = re.search(r"你是 (\d+) 号", user)
        my_seat = int(me.group(1)) if me else 0
        options = [s for s in seats if s != my_seat] or seats
        return {"target": options[0]}, {"total_tokens": 20}
    if "可以开枪" in user:
        seats = seats_in(user, "存活")
        me = re.search(r"你是 (\d+) 号", user)
        my_seat = int(me.group(1)) if me else 0
        options = [s for s in seats if s != my_seat] or seats
        return {"target": options[0]}, {"total_tokens": 20}
    return {"target": 1}, {"total_tokens": 10}


class MBTITests(unittest.TestCase):
    def test_question_pool_is_complete(self):
        self.assertEqual(len(mbti.QUESTIONS), 93)
        self.assertEqual(len(mbti.DIMS["EI_A"]) + len(mbti.DIMS["EI_B"]), 21)
        self.assertEqual(len(mbti.DIMS["SN_A"]) + len(mbti.DIMS["SN_B"]), 26)
        self.assertEqual(len(mbti.DIMS["TF_A"]) + len(mbti.DIMS["TF_B"]), 24)
        self.assertEqual(len(mbti.DIMS["JP_A"]) + len(mbti.DIMS["JP_B"]), 22)
        used = [n for values in mbti.DIMS.values() for n in values]
        self.assertEqual(sorted(used), list(range(1, 94)))

    def test_all_a_and_all_b(self):
        self.assertEqual(mbti.score(["A"] * 93)["mbti"], "ESTJ")
        self.assertEqual(mbti.score(["B"] * 93)["mbti"], "ISFJ")

    def test_params(self):
        intj = mbti.params_for("INTJ")
        enfp = mbti.params_for("ENFP")
        self.assertEqual(intj["verbosity"], 0.2)
        self.assertEqual(intj["risk"], 0.2)
        self.assertEqual(enfp["verbosity"], 0.8)
        self.assertEqual(enfp["risk"], 0.8)
        self.assertEqual(enfp["evidence"], 0.2)


class EngineTests(unittest.TestCase):
    def test_full_game_runs_and_records_rules(self):
        with patch("llm.chat_json", side_effect=fake_chat):
            game = engine.GameEngine(roster(), {"wolf": 3}, "INTJ", 12345)
            result = game.run()
        self.assertIn(result["winner"], ("wolf", "good", "draw"))
        self.assertEqual(len(result["detail"]["players"]), 9)
        self.assertLessEqual(result["rounds"], 8)
        self.assertEqual(result["variable_player_count"], 3)
        self.assertEqual(result["variable_camp_wins"]["good"]["players"], 0)
        types = [event["type"] for event in result["detail"]["events"]]
        self.assertIn("night", types)
        self.assertIn("dawn", types)
        self.assertIn("vote", types)
        self.assertIn("win", types)

    def test_win_conditions(self):
        with patch("llm.chat_json", side_effect=fake_chat):
            good_win = engine.GameEngine(roster(), {"wolf": 3}, "INTJ", 1)
            for agent in good_win.agents:
                if agent.camp == "wolf":
                    good_win._kill(agent, "test", 1)
            self.assertTrue(good_win._check_win("test"))
            self.assertEqual(good_win.winner, "good")

            god_win = engine.GameEngine(roster(), {"wolf": 3}, "INTJ", 2)
            for agent in god_win.agents:
                if agent.role in engine.GOD_ROLES:
                    god_win._kill(agent, "test", 1)
            self.assertTrue(god_win._check_win("test"))
            self.assertEqual(god_win.winner, "wolf")
            self.assertIn("三神", god_win.win_reason)

            villager_win = engine.GameEngine(roster(), {"wolf": 3}, "INTJ", 3)
            for agent in villager_win.agents:
                if agent.role == "villager":
                    villager_win._kill(agent, "test", 1)
            self.assertTrue(villager_win._check_win("test"))
            self.assertEqual(villager_win.winner, "wolf")
            self.assertIn("三民", villager_win.win_reason)

    def test_hunter_can_decline_shot(self):
        def declining_chat(system, user, **kwargs):
            if "可以开枪" in user:
                return {"target": None}, {"total_tokens": 10}
            return fake_chat(system, user, **kwargs)

        with patch("llm.chat_json", side_effect=declining_chat):
            game = engine.GameEngine(roster(), {"wolf": 3}, "INTJ", 5)
            hunter = next(a for a in game.agents if a.role == "hunter")
            before_alive = sum(1 for a in game.agents if a.alive)
            game._hunter_shot(hunter, "vote")
            self.assertEqual(sum(1 for a in game.agents if a.alive), before_alive)
            event = game.events[-1]
            self.assertEqual(event["type"], "hunter_shot")
            self.assertIsNone(event["target"])

    def test_poisoned_hunter_cannot_shoot(self):
        with patch("llm.chat_json", side_effect=fake_chat):
            game = engine.GameEngine(roster(), {"wolf": 3}, "INTJ", 4)
            hunter = next(a for a in game.agents if a.role == "hunter")
            game._kill(hunter, "poison", 1)
            before = len(game.events)
            game._hunter_shot(hunter, "poison")
            self.assertEqual(len(game.events), before)


class BehaviorBoundaryTests(unittest.TestCase):
    def test_dead_reference_and_flip_claim_are_detected(self):
        with patch("llm.chat_json", side_effect=fake_chat):
            game = engine.GameEngine(roster(), {"wolf": 3}, "INTJ", 11)
        speaker = game.agents[0]
        game._kill(game.seat_map[3], "wolf", 1)
        self.assertEqual(game._parse_accusations(speaker, "1号跳得挺干脆，2号被查杀光喊悍跳。我票先挂2号"), [2])
        self.assertEqual(game._parse_accusations(speaker, "别投2号，2号不像狼"), [])
        self.assertIsNone(game._parse_claim("1号跳预言家"))
        self.assertEqual(game._parse_claim("我跳预言家"), "预言家")
        for text in ("我也跳预言家", "我才是预言家", "我直接跳预言家", "我4号，预言家",
                     "我9号，也跳个预言家", "我5号说一句，我这儿是预言家", "我9号还是预言家"):
            self.assertEqual(game._parse_claim(text), "预言家", text)
        self.assertIsNone(game._parse_claim("我4号不是预言家"))
        self.assertEqual(game._parse_accusations(speaker, "后面谁踩8号我肯定不跟"), [])
        self.assertEqual(game._parse_positive(speaker, "我昨晚验了8号，是好人"), [8])
        self.assertTrue(game._speech_violations(speaker, "3号今晚验谁？"))
        self.assertTrue(game._speech_violations(speaker, "3号翻牌是民"))
        self.assertTrue(game._speech_violations(speaker, "3号是好人"))
        self.assertFalse(game._speech_violations(speaker, "昨天3号被刀了，今天听1号。"))

    def test_wolf_night_chat_produces_shared_plan_and_vote_reasons(self):
        with patch("llm.chat_json", side_effect=fake_chat):
            game = engine.GameEngine(roster(), {"wolf": 3}, "INTJ", 12)
            result = game.run()
        chats = [event for event in result["detail"]["events"] if event["type"] == "wolf_chat"]
        self.assertTrue(chats)
        self.assertIn(chats[0]["target"], {a.seat for a in game.agents if a.camp == "good"})
        wolves = [a for a in game.agents if a.camp == "wolf"]
        self.assertTrue(all(w.plan for w in wolves))
        # A wolf that died on an earlier night keeps the plan from its last
        # living night; only currently alive wolves must share the final plan.
        alive_wolves = [w for w in wolves if w.alive] or wolves
        self.assertTrue(all(w.plan["target"] == game.wolf_plan["target"] for w in alive_wolves))
        votes = [event for event in result["detail"]["events"] if event["type"] == "vote"]
        self.assertTrue(votes)
        self.assertTrue(all(v.get("reason") for v in votes[0]["votes"]))

    def test_seat_parser_accepts_chinese_suffix(self):
        self.assertEqual(engine._seat_int("5号"), 5)
        self.assertEqual(engine._seat_int("四号"), 4)
        self.assertEqual(engine._seat_int(" 10 "), 10)
        self.assertIsNone(engine._seat_int("不投"))


class TenPlayerTests(unittest.TestCase):
    def test_ten_player_board_has_four_villagers_and_four_villager_loss(self):
        by_role = roster(villagers=["ENFP", "ISTJ", "ESFP", "ENTJ"])
        with patch("llm.chat_json", side_effect=fake_chat):
            game = engine.GameEngine(by_role, {"wolf": 3}, "INTJ", 21)
            self.assertEqual(len(game.agents), 10)
            self.assertEqual(sum(1 for a in game.agents if a.role == "villager"), 4)
            for agent in game.agents:
                if agent.role == "villager":
                    game._kill(agent, "test", 1)
            self.assertTrue(game._check_win("test"))
            self.assertEqual(game.winner, "wolf")
            self.assertIn("四民", game.win_reason)

    def test_ten_player_validation_accepts_four_fixed_villagers(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = store.DB_PATH
            store.DB_PATH = os.path.join(tmp, "ten.db")
            try:
                store.init_db()
                types = ["INTJ", "INTJ", "INTJ", "ENFP", "ENFP", "ISTJ", "ESFP", "INFJ", "ESTP", "ENTJ"]
                for index, type_code in enumerate(types):
                    store.add_player({
                        "id": "p%d" % index, "person_id": "per_%d" % index,
                        "name": "玩家%d" % index, "mbti": type_code, "dims": {},
                        "params": mbti.params_for(type_code), "created_at": store.now_iso(),
                    })
                setup = simulation.validate_setup({
                    "player_count": 10,
                    "variable_roles": {"wolf": 1},
                    "fixed_assignments": [
                        {"role": "wolf", "player_id": "p1"},
                        {"role": "wolf", "player_id": "p2"},
                        {"role": "villager", "player_id": "p4"},
                        {"role": "villager", "player_id": "p5"},
                        {"role": "villager", "player_id": "p6"},
                        {"role": "villager", "player_id": "p9"},
                        {"role": "seer", "player_id": "p7"},
                        {"role": "witch", "player_id": "p8"},
                        {"role": "hunter", "player_id": "p3"},
                    ],
                    "games": 1,
                })
                self.assertEqual(setup["config_json"]["player_count"], 10)
            finally:
                store.DB_PATH = old


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = store.DB_PATH
        store.DB_PATH = os.path.join(self.tmp.name, "test.db")
        store.init_db()
        for index, type_code in enumerate(
            ["INTJ", "INTJ", "INTJ", "ENFP", "ENFP", "ISTJ", "ESFP", "INFJ", "ESTP"]
        ):
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
        store.DB_PATH = self.old_path
        self.tmp.cleanup()

    def test_three_variable_wolves_need_three_same_type(self):
        setup = simulation.validate_setup({
            "variable_roles": {"wolf": 3},
            "fixed_assignments": [
                {"role": "villager", "player_id": "p4"},
                {"role": "villager", "player_id": "p5"},
                {"role": "villager", "player_id": "p6"},
                {"role": "seer", "player_id": "p7"},
                {"role": "witch", "player_id": "p8"},
                {"role": "hunter", "player_id": "p3"},
            ],
            "games": 3,
        })
        self.assertEqual(setup["variable_roles"]["wolf"], 3)
        self.assertIn("INTJ", setup["config_json"]["eligible_types"])

    def test_rejects_impossible_variable_block(self):
        with self.assertRaises(ValueError):
            simulation.validate_setup({
                "variable_roles": {"wolf": 3, "villager": 3, "seer": 1, "witch": 1, "hunter": 1},
                "fixed_assignments": [],
                "games": 1,
            })

    def test_rejects_more_than_2000_games(self):
        with self.assertRaises(ValueError):
            simulation.validate_setup({
                "variable_roles": {"wolf": 3},
                "fixed_assignments": [
                    {"role": "villager", "player_id": "p4"},
                    {"role": "villager", "player_id": "p5"},
                    {"role": "villager", "player_id": "p6"},
                    {"role": "seer", "player_id": "p7"},
                    {"role": "witch", "player_id": "p8"},
                    {"role": "hunter", "player_id": "p3"},
                ],
                "games": 2001,
            })

    def test_rejects_missing_fixed_slot(self):
        with self.assertRaises(ValueError):
            simulation.validate_setup({
                "variable_roles": {"wolf": 1},
                "fixed_assignments": [],
                "games": 1,
            })


class PromptIsolationTests(unittest.TestCase):
    def test_private_prompts_do_not_contain_other_roles(self):
        prompts = []

        def capture(system, user, **kwargs):
            prompts.append((system, user))
            return fake_chat(system, user, **kwargs)

        with patch("llm.chat_json", side_effect=capture):
            game = engine.GameEngine(roster(), {"wolf": 3}, "INTJ", 777)
            game.run()
        self.assertTrue(prompts)
        seen_roles = set()
        for system, user in prompts:
            # The only role block in an agent prompt is the agent's own seat.
            self.assertEqual(user.count("身份是【"), 1)
            match = re.search(r"身份是【(狼人|平民|预言家|女巫|猎人)】", user)
            self.assertIsNotNone(match)
            role = match.group(1)
            seen_roles.add(role)
            if role != "狼人":
                self.assertNotIn("你的狼队友", user)
            if role != "预言家":
                self.assertNotIn("你的验人记录", user)
            if role != "女巫":
                self.assertNotIn("解药：", user)
                self.assertNotIn("毒药：", user)
            if role != "猎人":
                self.assertNotIn("被狼人刀死或被投票出局时可以开枪", user)
            self.assertNotIn("role_name", user)
            self.assertNotIn("player_id", user)
        self.assertIn("狼人", seen_roles)
        self.assertIn("平民", seen_roles)
        self.assertIn("预言家", seen_roles)
        self.assertIn("女巫", seen_roles)
        self.assertIn("猎人", seen_roles)


class StatsTests(unittest.TestCase):
    def test_compute_stats(self):
        games = [
            {
                "game_no": 1, "winner": "wolf", "rounds": 3, "tokens": 100,
                "variable_type": "INTJ",
                "variable_camp_wins": {"wolf": {"players": 1, "wins": 1}, "good": {"players": 0, "wins": 0}},
                "variable_player_count": 1, "variable_player_wins": 1,
            },
            {
                "game_no": 2, "winner": "good", "rounds": 5, "tokens": 200,
                "variable_type": "INTJ",
                "variable_camp_wins": {"wolf": {"players": 1, "wins": 0}, "good": {"players": 0, "wins": 0}},
                "variable_player_count": 1, "variable_player_wins": 0,
            },
            {
                "game_no": 3, "winner": "draw", "rounds": 8, "tokens": 300,
                "variable_type": "ENFP",
                "variable_camp_wins": {"wolf": {"players": 0, "wins": 0}, "good": {"players": 1, "wins": 0}},
                "variable_player_count": 1, "variable_player_wins": 0,
            },
        ]
        stats = simulation.compute_stats(games)
        self.assertEqual(stats["games"], 3)
        self.assertEqual(stats["camps"]["wolf"]["wins"], 1)
        self.assertEqual(stats["camps"]["good"]["wins"], 1)
        self.assertEqual(stats["camps"]["draw"]["wins"], 1)
        self.assertEqual(len(stats["timeline"]), 3)
        intj = next(row for row in stats["by_type"] if row["type"] == "INTJ")
        self.assertEqual(intj["games"], 2)
        self.assertEqual(intj["wolf_games"], 2)
        self.assertEqual(intj["wolf_wins"], 1)
        self.assertEqual(intj["player_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
