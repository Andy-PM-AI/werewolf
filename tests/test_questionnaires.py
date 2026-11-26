"""Questionnaire uploads, per-player results, coverage and comparison tests."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

import mbti  # noqa: E402
import questionnaires  # noqa: E402
import simulation  # noqa: E402
import store  # noqa: E402


def player(index, type_code):
    return {
        "id": "p%d" % index, "person_id": "per_%d" % index,
        "name": "玩家%d" % index, "age": 30, "gender": "女",
        "province": "北京", "occupation": "职员",
        "mbti": type_code, "dims": mbti.score(["A"] * 93)["dims"] if False else {},
        "params": mbti.params_for(type_code), "answers": ["A"] * 93,
        "persona": "玩家%d" % index, "created_at": store.now_iso(),
        "profile_json": {"big_five": {"外向性": 70, "开放性": 60, "宜人性": 55, "尽责性": 65}},
    }


def two_question_definition():
    return {
        "name": "测试二问", "version": "0.1",
        "dimensions": [{"key": "AB", "left": "A", "right": "B",
                        "left_name": "甲", "right_name": "乙"}],
        "questions": [
            {"id": 1, "text": "一", "options": {"A": {"text": "甲", "scores": {"AB": "A"}},
                                                "B": {"text": "乙", "scores": {"AB": "B"}}}},
            {"id": 2, "text": "二", "options": {"A": {"text": "甲", "scores": {"AB": "A"}},
                                                "B": {"text": "乙", "scores": {"AB": "B"}}}},
        ],
        "scoring": {"result_order": ["AB"], "type_names": {"A": "甲型", "B": "乙型"}},
    }


class QuestionnaireTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = store.DB_PATH
        store.DB_PATH = os.path.join(self.tmp.name, "q.db")
        store.init_db()
        store.add_player(player(1, "ISTJ"))
        store.add_player(player(2, "ENFP"))
        questionnaires.ensure_seed()

    def tearDown(self):
        store.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_builtin_seed_backfills_and_coverage(self):
        qs = store.list_questionnaires()
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0]["id"], questionnaires.BUILTIN_ID)
        self.assertEqual(qs[0]["tested"], 2)
        self.assertEqual(qs[0]["total"], 2)
        self.assertEqual(qs[0]["coverage"], 1.0)
        self.assertEqual(store.get_questionnaire_result("p1", questionnaires.BUILTIN_ID)["result"], "ISTJ")
        self.assertEqual(store.get_player_for_questionnaire("p1", questionnaires.BUILTIN_ID)["has_result"], True)
        # Players added later through another questionnaire are not silently
        # backfilled as builtin-MBTI results on the next server start.
        store.add_player(player(3, "AAAA"))
        questionnaires.ensure_seed()
        self.assertIsNone(store.get_questionnaire_result("p3", questionnaires.BUILTIN_ID))

    def test_upload_validation_and_scoring(self):
        definition = questionnaires.normalize_definition(two_question_definition())
        self.assertEqual(questionnaires.question_count(definition), 2)
        result = questionnaires.score(definition, ["A", "B"])
        self.assertEqual(result["result"], "A")
        self.assertEqual(result["type_name"], "甲型")
        with self.assertRaises(ValueError):
            questionnaires.normalize_definition({
                **two_question_definition(),
                "questions": [
                    {"id": 1, "text": "一", "options": {"A": {"scores": {"AB": "A"}},
                                                        "B": {"scores": {"AB": "B"}}}},
                    {"id": 3, "text": "三", "options": {"A": {"scores": {"AB": "A"}},
                                                        "B": {"scores": {"AB": "B"}}}},
                ],
            })
        with self.assertRaises(ValueError):
            questionnaires.normalize_definition({
                **two_question_definition(),
                "questions": [
                    {"id": 1, "text": "一", "options": {"A": {"scores": {"AB": "Z"}},
                                                        "B": {"scores": {"AB": "B"}}}},
                    {"id": 2, "text": "二", "options": {"A": {"scores": {"AB": "A"}},
                                                        "B": {"scores": {"AB": "B"}}}},
                ],
            })

    def test_multiple_results_and_comparison(self):
        definition = two_question_definition()
        qid = "qn_test_second"
        store.create_questionnaire({
            "id": qid, "name": definition["name"], "version": "0.1",
            "question_count": 2, "definition": questionnaires.normalize_definition(definition),
            "created_by": "test",
        })
        store.upsert_questionnaire_result("p1", qid, {"mbti": "ISTJ", "dims": {}, "params": {}})
        store.upsert_questionnaire_result("p2", qid, {"mbti": "ISTJ", "dims": {}, "params": {}})
        comparison = questionnaires.compare(questionnaires.BUILTIN_ID, qid)
        self.assertEqual(comparison["total"], 2)
        self.assertEqual(comparison["same"], 1)
        self.assertEqual(comparison["different"], 1)
        self.assertEqual(comparison["distribution"][0]["left_result"], "ENFP")
        self.assertEqual(comparison["distribution"][0]["right_result"], "ISTJ")
        self.assertEqual(len(comparison["distribution"][0]["players"]), 1)
        self.assertEqual(len(store.players_without_questionnaire_result(qid)), 0)
        stats = store.player_stats_for_questionnaire(qid)
        self.assertEqual(stats["tested"], 2)
        self.assertEqual(stats["coverage"], 1.0)

    def test_test_all_job_only_tests_players_without_results(self):
        definition = two_question_definition()
        qid = "qn_test_job"
        store.create_questionnaire({
            "id": qid, "name": definition["name"], "version": "0.1",
            "question_count": 2, "definition": questionnaires.normalize_definition(definition),
            "created_by": "test",
        })
        store.upsert_questionnaire_result("p1", qid, {"mbti": "A", "dims": {}, "params": {}})
        called = []
        def fake_run(player, defn):
            called.append(player["id"])
            return {**player, "mbti": "A", "type_name": "甲型", "dims": {}, "params": {},
                    "answers": ["A", "A"], "test_fallback": 0}
        with patch("questionnaires.run_test", side_effect=fake_run):
            job_id = questionnaires.start_test_job(qid)
            import time
            deadline = time.time() + 5
            job = None
            while time.time() < deadline:
                job = questionnaires.get_job(job_id)
                if job["status"] in ("done", "error"):
                    break
                time.sleep(0.05)
        self.assertEqual(job["status"], "done")
        self.assertEqual(called, ["p2"])
        self.assertEqual(job["tested"], 1)
        self.assertEqual(store.players_without_questionnaire_result(qid), [])
        self.assertEqual(store.get_questionnaire_result("p1", qid)["result"], "A")

    def test_dimension_bands_total_bands_and_highest_dimension(self):
        dimension_def = {
            "name": "维度分段", "dimensions": [
                {"key": "O", "left": "L", "right": "H", "left_name": "低", "right_name": "高"},
            ],
            "questions": [
                {"id": 1, "text": "一", "options": {
                    "A": {"text": "低", "values": {"O": 1}},
                    "B": {"text": "高", "values": {"O": 5}},
                }},
                {"id": 2, "text": "二", "options": {
                    "A": {"text": "低", "values": {"O": 1}},
                    "B": {"text": "高", "values": {"O": 5}},
                }},
            ],
            "scoring": {
                "mode": "dimension_bands", "result_order": ["O"],
                "bands": {"O": [{"min": 0, "max": 3, "label": "L"},
                                {"min": 4, "max": 10, "label": "H"}]},
            },
        }
        normalized = questionnaires.normalize_definition(dimension_def)
        self.assertEqual(questionnaires.score(normalized, ["A", "B"])["result"], "H")

        total_def = {
            "name": "总分分段", "dimensions": [],
            "questions": [
                {"id": 1, "text": "一", "options": {
                    "A": {"text": "低", "points": 1}, "B": {"text": "高", "points": 5}}},
                {"id": 2, "text": "二", "options": {
                    "A": {"text": "低", "points": 1}, "B": {"text": "高", "points": 5}}},
            ],
            "scoring": {
                "mode": "total_bands", "result_order": [],
                "total_bands": [{"min": 0, "max": 5, "label": "L"},
                                {"min": 6, "max": 20, "label": "H"}],
            },
        }
        normalized = questionnaires.normalize_definition(total_def)
        self.assertEqual(questionnaires.score(normalized, ["B", "B"])["result"], "H")

        highest_def = {
            "name": "最高维度", "dimensions": [
                {"key": "A", "left": "L", "right": "H", "left_name": "低", "right_name": "高"},
                {"key": "B", "left": "L", "right": "H", "left_name": "低", "right_name": "高"},
            ],
            "questions": [
                {"id": 1, "text": "一", "options": {
                    "A": {"text": "A 高", "values": {"A": 5}},
                    "B": {"text": "B 高", "values": {"B": 5}},
                }},
            ],
            "scoring": {"mode": "highest_dimension", "result_order": ["A", "B"]},
        }
        normalized = questionnaires.normalize_definition(highest_def)
        self.assertEqual(questionnaires.score(normalized, ["A"])["result"], "A")

    def test_likert_dimension_reverse_scoring(self):
        defn = {
            "name": "反向题", "response_type": "likert5",
            "dimensions": [{"key": "EI", "left": "E", "right": "I",
                            "left_name": "外", "right_name": "内"}],
            "questions": [{
                "id": 1, "text": "反向题", "dimension": "EI", "reverse": True,
                "options": {str(i): {"text": str(i)} for i in range(1, 6)},
            }],
            "scoring": {"mode": "dimension_bands", "result_order": ["EI"],
                        "bands": {"EI": [{"min": 0, "max": 2, "label": "E"},
                                         {"min": 3, "max": 5, "label": "I"}]}},
        }
        normalized = questionnaires.normalize_definition(defn)
        self.assertEqual(questionnaires.score(normalized, ["5"])["result"], "E")
        self.assertEqual(questionnaires.score(normalized, ["1"])["result"], "I")

    def test_invalid_scoring_rules_are_rejected_before_save(self):
        base = {
            "name": "坏规则", "dimensions": [
                {"key": "AB", "left": "A", "right": "B", "left_name": "甲", "right_name": "乙"}],
            "questions": [{"id": 1, "text": "一", "options": {
                "A": {"text": "甲"}, "B": {"text": "乙"}}}],
            "scoring": {"mode": "pole_majority", "result_order": ["AB"]},
        }
        with self.assertRaises(ValueError):
            questionnaires.normalize_definition(base)
        with self.assertRaises(ValueError):
            questionnaires.normalize_definition({
                **base,
                "questions": [{"id": 1, "text": "一", "options": {
                    "A": {"text": "甲", "values": {"AB": 1}},
                    "B": {"text": "乙", "values": {"AB": 5}}}}],
                "scoring": {"mode": "dimension_bands", "result_order": ["AB"]},
            })
        with self.assertRaises(ValueError):
            questionnaires.normalize_definition({
                **base,
                "questions": [{"id": 1, "text": "一", "options": {
                    "A": {"text": "甲", "values": {"AB": 1}},
                    "B": {"text": "乙", "values": {"AB": 5}}}}],
                "scoring": {"mode": "dimension_bands", "result_order": ["AB"],
                            "bands": {"AB": [{"min": 0, "max": 5, "label": "L"},
                                             {"min": 4, "max": 10, "label": "H"}]}},
            })

    def test_simulation_locks_active_questionnaire(self):
        types = ["INTJ", "ENFP", "ISTJ", "ESFP", "INFJ", "ESTP", "ISFJ", "ENTJ", "ISTP"]
        for index, code in enumerate(types[2:], 3):
            store.add_player(player(index, code))
        questionnaires.ensure_seed()
        store.backfill_builtin_results(questionnaires.BUILTIN_ID)
        setup = simulation.validate_setup({
            "player_count": 9,
            "variable_roles": {"wolf": 1},
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
            "games": 1,
        })
        self.assertEqual(setup["config_json"]["questionnaire_id"], questionnaires.BUILTIN_ID)
        self.assertEqual(len(setup["fixed_assignments"]), 8)

    def test_likert_five_point_questionnaire(self):
        defn = {
            "name": "五度测试", "version": "0.1", "response_type": "likert5",
            "dimensions": [{"key": "AB", "left": "A", "right": "B",
                            "left_name": "甲", "right_name": "乙"}],
            "questions": [
                {"id": 1, "text": "一", "options": {
                    "1": {"text": "非常不同意", "scores": {"AB": "A"}},
                    "2": {"text": "不同意", "scores": {"AB": "A"}},
                    "3": {"text": "一般", "scores": {}},
                    "4": {"text": "同意", "scores": {"AB": "B"}},
                    "5": {"text": "非常同意", "scores": {"AB": "B"}},
                }},
                {"id": 2, "text": "二", "options": {
                    "1": {"text": "非常不同意", "scores": {"AB": "A"}},
                    "2": {"text": "不同意", "scores": {"AB": "A"}},
                    "3": {"text": "一般", "scores": {}},
                    "4": {"text": "同意", "scores": {"AB": "B"}},
                    "5": {"text": "非常同意", "scores": {"AB": "B"}},
                }},
            ],
            "scoring": {"result_order": ["AB"], "type_names": {"A": "甲型", "B": "乙型"}},
        }
        normalized = questionnaires.normalize_definition(defn)
        self.assertEqual(normalized["response_type"], "likert5")
        result = questionnaires.score(normalized, ["5", "5"])
        self.assertEqual(result["result"], "B")
        normalized["_id"] = "qn_test_likert"
        with patch("llm.chat_json", return_value=({"answers": [5, 5]}, {"total_tokens": 10})):
            tested = questionnaires.run_test(player(1, "ISTJ"), normalized)
        self.assertEqual(tested["mbti"], "B")
        self.assertEqual(tested["test_fallback"], 0)
        with self.assertRaises(ValueError):
            questionnaires.normalize_definition({
                **defn,
                "questions": [{
                    "id": 1, "text": "缺选项", "options": {
                        "1": {"text": "一", "scores": {}},
                        "2": {"text": "二", "scores": {}},
                    },
                }],
            })

    def test_generic_questionnaire_run_and_fallback(self):
        definition = questionnaires.normalize_definition(two_question_definition())
        definition["_id"] = "qn_test_generic"
        with patch("llm.chat_json", return_value=({"answers": ["A", "B"]}, {"total_tokens": 10})):
            result = questionnaires.run_test(player(1, "ISTJ"), definition)
        self.assertEqual(result["mbti"], "A")
        self.assertEqual(result["type_name"], "甲型")
        self.assertEqual(result["test_fallback"], 0)
        self.assertEqual(len(result["answers"]), 2)


if __name__ == "__main__":
    unittest.main()
