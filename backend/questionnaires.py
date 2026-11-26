"""Questionnaire definitions, scoring, uploads and bulk testing jobs.

The first supported format is an A/B questionnaire with named dimensions.
Each option scores exactly one or more dimension poles. The result is the
concatenation of the winning pole for each dimension in ``result_order``.
The built-in 93-item MBTI questionnaire is generated from
``mbti_questions.json`` and is the upload template.
"""
from __future__ import annotations

import json
import math
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import llm
import mbti
import store

BUILTIN_ID = "qn_mbti_93_v1"
SCHEMA = "werewolf-questionnaire/v1"
_JOBS = {}
_JOBS_LOCK = threading.RLock()
_DEF_CACHE = {}


def _loads(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _finite(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s 必须是数字" % label)
    if not math.isfinite(number):
        raise ValueError("%s 必须是有限数字" % label)
    return number


def _answer_letter(item):
    text = str(item or "").strip().upper()
    if text in ("A", "A.", "1", "选项A", "甲"):
        return "A"
    if text in ("B", "B.", "2", "选项B", "乙"):
        return "B"
    return ""


def _answer_value(item, response_type="binary"):
    if response_type == "likert5":
        if isinstance(item, dict):
            item = item.get("answer") or item.get("value") or item.get("choice")
        text = str(item or "").strip()
        match = re.search(r"[1-5]", text)
        return match.group(0) if match else ""
    return _answer_letter(item)


def _dimension_meta(key):
    specs = {
        "EI": ("E", "I", "外倾", "内倾"),
        "SN": ("S", "N", "感觉", "直觉"),
        "TF": ("T", "F", "思维", "情感"),
        "JP": ("J", "P", "判断", "知觉"),
    }
    left, right, left_name, right_name = specs.get(key, (key + "L", key + "R", key + "左", key + "右"))
    return {"key": key, "left": left, "right": right,
            "left_name": left_name, "right_name": right_name}


def builtin_definition():
    if "builtin" in _DEF_CACHE:
        return json.loads(json.dumps(_DEF_CACHE["builtin"], ensure_ascii=False))
    dimensions = [_dimension_meta(key) for key in ("EI", "SN", "TF", "JP")]
    by_key = {item["key"]: item for item in dimensions}
    mapping = {}
    for key in ("EI", "SN", "TF", "JP"):
        meta = by_key[key]
        for n in mbti.DIMS.get(key + "_A", []):
            mapping[n] = (key, meta["left"], meta["right"])
        for n in mbti.DIMS.get(key + "_B", []):
            mapping[n] = (key, meta["right"], meta["left"])
    questions = []
    for index, item in enumerate(mbti.QUESTIONS, 1):
        text, a_text, b_text = item
        key, a_pole, b_pole = mapping[index]
        questions.append({
            "id": index,
            "text": text,
            "options": {
                "A": {"text": a_text, "scores": {key: a_pole}},
                "B": {"text": b_text, "scores": {key: b_pole}},
            },
        })
    definition = {
        "schema": SCHEMA,
        "name": "MBTI 93 题（第一版）",
        "version": "1.0",
        "kind": "mbti",
        "response_type": "binary",
        "description": "当前系统的第一版人格问卷，共 93 题，按 E/I、S/N、T/F、J/P 四个维度计分。",
        "dimensions": dimensions,
        "questions": questions,
        "scoring": {
            "mode": "pole_majority",
            "result_order": ["EI", "SN", "TF", "JP"],
            "type_names": mbti.TYPE_NAMES,
            "params": {"mode": "mbti"},
        },
    }
    _DEF_CACHE["builtin"] = definition
    return json.loads(json.dumps(definition, ensure_ascii=False))


def _legacy_to_definition(data, name):
    """Accept a raw mbti_questions.json-shaped upload as well as the canonical format."""
    raw_questions = data.get("questions") or []
    raw_dims = data.get("dimensions") or {}
    dimensions = [_dimension_meta(key) for key in ("EI", "SN", "TF", "JP")]
    by_key = {item["key"]: item for item in dimensions}
    mapping = {}
    for key in ("EI", "SN", "TF", "JP"):
        meta = by_key[key]
        for n in raw_dims.get(key + "_A", []):
            mapping[n] = (key, meta["left"], meta["right"])
        for n in raw_dims.get(key + "_B", []):
            mapping[n] = (key, meta["right"], meta["left"])
    questions = []
    for index, item in enumerate(raw_questions, 1):
        if not isinstance(item, list) or len(item) < 3 or index not in mapping:
            raise ValueError("第 %d 题无法识别为 MBTI 格式" % index)
        key, a_pole, b_pole = mapping[index]
        questions.append({
            "id": index, "text": str(item[0]),
            "options": {
                "A": {"text": str(item[1]), "scores": {key: a_pole}},
                "B": {"text": str(item[2]), "scores": {key: b_pole}},
            },
        })
    return {
        "schema": SCHEMA, "name": name or "MBTI 问卷", "version": data.get("version") or "1.0",
        "kind": "mbti", "response_type": "binary", "description": data.get("description") or "",
        "dimensions": dimensions, "questions": questions,
        "scoring": {"mode": "pole_majority", "result_order": ["EI", "SN", "TF", "JP"],
                    "type_names": mbti.TYPE_NAMES, "params": {"mode": "mbti"}},
    }


def normalize_definition(data, name=None):
    """Validate an uploaded questionnaire and return the canonical structure."""
    if not isinstance(data, dict):
        raise ValueError("问卷必须是 JSON 对象")
    if data.get("schema") and str(data.get("schema")) != SCHEMA:
        raise ValueError("不支持的问卷 schema：%s" % data.get("schema"))
    # Allow the current mbti_questions.json to be uploaded directly as a template.
    if isinstance(data.get("dimensions"), dict) and data.get("questions"):
        data = _legacy_to_definition(data, name or data.get("name"))
    questions = data.get("questions")
    dimensions = data.get("dimensions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("questions 必须是非空数组")
    scoring_in = data.get("scoring") if isinstance(data.get("scoring"), dict) else {}
    mode = str(scoring_in.get("mode") or "pole_majority").strip().lower()
    if mode not in ("pole_majority", "dimension_bands", "total_bands", "highest_dimension"):
        raise ValueError("不支持的计分模式：%s" % mode)
    if not isinstance(dimensions, list):
        raise ValueError("dimensions 必须是数组")
    if not dimensions and mode != "total_bands":
        raise ValueError("该计分模式至少需要一个维度")
    dims = []
    keys = set()
    poles_by_key = {}
    for raw in dimensions:
        if not isinstance(raw, dict):
            raise ValueError("dimensions 每一项必须是对象")
        key = str(raw.get("key") or "").strip()
        left = str(raw.get("left") or "").strip()
        right = str(raw.get("right") or "").strip()
        if not key or not left or not right:
            raise ValueError("每个维度都需要 key、left、right")
        if key in keys:
            raise ValueError("维度 key 不能重复：%s" % key)
        keys.add(key)
        poles_by_key[key] = {left, right}
        dims.append({"key": key, "left": left, "right": right,
                     "left_name": str(raw.get("left_name") or left),
                     "right_name": str(raw.get("right_name") or right)})
    response_type = str(data.get("response_type") or "").strip().lower()
    if response_type not in ("binary", "likert5"):
        first_options = (questions[0] or {}).get("options") if isinstance(questions[0], dict) else {}
        response_type = "likert5" if isinstance(first_options, dict) and all(
            str(k) in ("1", "2", "3", "4", "5") for k in first_options) and first_options else "binary"
    option_keys = ("A", "B") if response_type == "binary" else ("1", "2", "3", "4", "5")
    normalized_questions = []
    seen_ids = set()
    for raw in questions:
        if not isinstance(raw, dict):
            raise ValueError("questions 每一项必须是对象")
        qid = raw.get("id")
        try:
            qid = int(qid)
        except (TypeError, ValueError):
            raise ValueError("题目 id 必须是整数")
        if qid in seen_ids:
            raise ValueError("题目 id 不能重复：%s" % qid)
        seen_ids.add(qid)
        options = raw.get("options")
        if not isinstance(options, dict) or any(key not in options for key in option_keys):
            if response_type == "binary":
                raise ValueError("第 %d 题必须提供 A、B 两个选项" % qid)
            raise ValueError("第 %d 题必须提供 1、2、3、4、5 五个选项" % qid)
        dimension = str(raw.get("dimension") or "").strip() or None
        if dimension and dimension not in keys:
            raise ValueError("第 %d 题引用了未知维度：%s" % (qid, dimension))
        opts = {}
        for letter in option_keys:
            option = options.get(letter)
            if isinstance(option, str):
                option = {"text": option, "scores": {}}
            if not isinstance(option, dict):
                raise ValueError("第 %d 题 %s 选项格式错误" % (qid, letter))
            scores = option.get("scores") or {}
            values = option.get("values") or {}
            if not isinstance(scores, dict):
                raise ValueError("第 %d 题 %s 选项 scores 必须是对象" % (qid, letter))
            if not isinstance(values, dict):
                raise ValueError("第 %d 题 %s 选项 values 必须是对象" % (qid, letter))
            for dim_key, pole in scores.items():
                if dim_key not in keys or str(pole) not in poles_by_key.get(dim_key, set()):
                    raise ValueError("第 %d 题 %s 选项引用了未知维度或极点" % (qid, letter))
            clean_values = {}
            for dim_key, value in values.items():
                if dim_key not in keys:
                    raise ValueError("第 %d 题 %s 选项 values 引用了未知维度" % (qid, letter))
                clean_values[str(dim_key)] = _finite(value, "第 %d 题 %s 选项 values" % (qid, letter))
            weight = _finite(option.get("weight", 1), "第 %d 题 %s 选项 weight" % (qid, letter))
            if weight <= 0:
                raise ValueError("第 %d 题 %s 选项 weight 必须大于 0" % (qid, letter))
            points = _finite(option.get("points", 0) or 0, "第 %d 题 %s 选项 points" % (qid, letter))
            opts[letter] = {"text": str(option.get("text") or ""),
                            "scores": {str(k): str(v) for k, v in scores.items()},
                            "values": clean_values, "points": points, "weight": weight}
        has_scores = any(option["scores"] for option in opts.values())
        has_values = any(option["values"] for option in opts.values())
        has_points = any(abs(option["points"]) > 1e-12 for option in opts.values())
        if mode == "pole_majority" and not has_scores:
            raise ValueError("第 %d 题没有任何维度计分，pole_majority 模式需要 scores" % qid)
        if mode in ("dimension_bands", "highest_dimension") and not (has_values or dimension):
            raise ValueError("第 %d 题没有 values 或 dimension，无法进行维度累加" % qid)
        if dimension and response_type != "likert5":
            raise ValueError("第 %d 题使用 dimension 自动累加时必须设置 response_type=likert5" % qid)
        if mode == "total_bands" and not (has_points or has_values or dimension):
            raise ValueError("第 %d 题没有 points、values 或 dimension，无法进行总分累加" % qid)
        normalized_questions.append({"id": qid, "text": str(raw.get("text") or ""),
                                     "dimension": dimension,
                                     "reverse": bool(raw.get("reverse")), "options": opts})
    normalized_questions.sort(key=lambda item: item["id"])
    if [item["id"] for item in normalized_questions] != list(range(1, len(normalized_questions) + 1)):
        raise ValueError("题目 id 必须从 1 开始连续编号")

    order = scoring_in.get("result_order")
    if order is None:
        order = [item["key"] for item in dims]
    if not isinstance(order, list):
        raise ValueError("scoring.result_order 必须是数组")
    if mode == "total_bands" and not order:
        order = []
    elif any(key not in keys for key in order):
        raise ValueError("scoring.result_order 必须引用已有维度")
    if mode != "total_bands" and not order:
        raise ValueError("scoring.result_order 不能为空（total_bands 除外）")

    def normalize_bands(value, label):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("%s 必须是数组" % label)
        out = []
        for row in value:
            if not isinstance(row, dict):
                raise ValueError("%s 每一项必须是对象" % label)
            low = _finite(row.get("min", 0), "%s.min" % label)
            high = _finite(row.get("max", 10 ** 12), "%s.max" % label)
            if high < low:
                raise ValueError("%s 存在 max < min 的区间" % label)
            label_text = str(row.get("label") or row.get("result") or "").strip()
            if not label_text:
                raise ValueError("%s 每一段都需要 label" % label)
            out.append({"min": low, "max": high, "label": label_text})
        out.sort(key=lambda row: row["min"])
        for previous, current in zip(out, out[1:]):
            if current["min"] <= previous["max"]:
                raise ValueError("%s 的区间不能重叠" % label)
        return out

    bands = {}
    raw_bands = scoring_in.get("bands") if isinstance(scoring_in.get("bands"), dict) else {}
    for dim_key, rows in raw_bands.items():
        if dim_key not in keys:
            raise ValueError("scoring.bands 引用了未知维度：%s" % dim_key)
        bands[str(dim_key)] = normalize_bands(rows, "scoring.bands.%s" % dim_key)
    total_bands = normalize_bands(scoring_in.get("total_bands"), "scoring.total_bands")
    if mode == "dimension_bands":
        for dim_key in order:
            if not bands.get(dim_key):
                raise ValueError("dimension_bands 模式需要为维度 %s 提供 bands" % dim_key)
    if mode == "total_bands" and not total_bands:
        raise ValueError("total_bands 模式需要 scoring.total_bands")
    if mode == "highest_dimension" and not dims:
        raise ValueError("highest_dimension 模式至少需要一个维度")
    type_names = scoring_in.get("type_names")
    if not isinstance(type_names, dict):
        type_names = {}
    return {
        "schema": SCHEMA,
        "name": str(name or data.get("name") or "未命名问卷").strip()[:80],
        "version": str(data.get("version") or "1.0").strip()[:30],
        "kind": str(data.get("kind") or "generic").strip()[:30],
        "response_type": response_type,
        "description": str(data.get("description") or "").strip()[:500],
        "dimensions": dims,
        "questions": normalized_questions,
        "scoring": {
            "mode": mode,
            "result_order": [str(x) for x in order],
            "type_names": {str(k): str(v) for k, v in type_names.items()},
            "bands": bands,
            "total_bands": total_bands,
            "params": scoring_in.get("params") if isinstance(scoring_in.get("params"), dict) else {},
        },
    }


def question_count(definition):
    return len(definition.get("questions") or [])


def question_block(definition):
    lines = []
    likert = definition.get("response_type") == "likert5"
    keys = ("1", "2", "3", "4", "5") if likert else ("A", "B")
    for question in definition.get("questions") or []:
        options = question.get("options") or {}
        opts = "\n".join("%s. %s" % (key, (options.get(key) or {}).get("text", "")) for key in keys)
        lines.append("%s. %s\n%s" % (question.get("id"), question.get("text"), opts))
    return "\n".join(lines)


def _bf_value(bf, key):
    try:
        return float(bf.get(key))
    except (TypeError, ValueError):
        return None


def _calibration_text(bf):
    if not bf:
        return ""
    lines = []
    for key, name, left, right in (
        ("外向性", "外向性", "E（外倾）", "I（内倾）"),
        ("开放性", "开放性", "N（直觉）", "S（感觉）"),
        ("宜人性", "宜人性", "F（情感）", "T（思维）"),
        ("尽责性", "尽责性", "J（判断）", "P（知觉）"),
    ):
        value = _bf_value(bf, key)
        if value is not None:
            side = left if value >= 55 else right if value <= 45 else "中间，按题目判断"
            lines.append("%s %.0f → %s" % (name, value, side))
    if not lines:
        return ""
    return ("【作答校准】这个人物的人口库心理测量档案如下。请让作答与这些倾向大体一致，"
            "但不要机械地全选同一侧；具体题目仍按经历和第一感觉判断：\n" + "\n".join(lines))


def _extract_answers(obj, count, response_type="binary"):
    if not isinstance(obj, dict):
        return {}
    payload = obj.get("answers") or obj.get("responses") or obj.get("choices")
    out = {}
    if isinstance(payload, str):
        chars = [ch.upper() for ch in payload if ch.upper() in ("A", "B")] if response_type == "binary" else re.findall(r"[1-5]", payload)
        for index, value in enumerate(chars[:count], 1):
            out[index] = value
    elif isinstance(payload, list):
        for index, item in enumerate(payload, 1):
            if index > count:
                break
            value = _answer_value(item, response_type)
            if value:
                out[index] = value
    elif isinstance(payload, dict):
        for key, item in payload.items():
            try:
                index = int(str(key).strip().strip("第题：:"))
            except (TypeError, ValueError):
                continue
            if 1 <= index <= count:
                value = _answer_value(item, response_type)
                if value:
                    out[index] = value
    return out


def _fallback_answers(player, indices, response_type="binary"):
    import hashlib
    seed = hashlib.sha256(
        (str(player.get("person_id")) + str(player.get("name"))).encode("utf-8")
    ).digest()
    if response_type == "likert5":
        return {n: "3" for n in indices}
    return {n: ("A" if seed[(n - 1) % len(seed)] % 2 == 0 else "B") for n in indices}


def _band_label(value, bands):
    for row in bands or []:
        if float(row["min"]) <= value <= float(row["max"]):
            return row["label"]
    return None


def score(definition, answers):
    if isinstance(answers, dict):
        values = [answers.get(n) for n in sorted(answers)]
    else:
        values = list(answers or [])
    response_type = definition.get("response_type") or "binary"
    dims = definition.get("dimensions") or []
    scoring = definition.get("scoring") or {}
    mode = scoring.get("mode") or "pole_majority"
    questions = definition.get("questions") or []
    result = ""
    total_score = 0.0
    dim_out = {}

    if mode == "pole_majority":
        counts = {item["key"]: {item["left"]: 0.0, item["right"]: 0.0} for item in dims}
        for index, question in enumerate(questions):
            if index >= len(values):
                continue
            value = _answer_value(values[index], response_type)
            if not value:
                continue
            option = (question.get("options") or {}).get(str(value)) or {}
            weight = float(option.get("weight", 1) or 1)
            for key, pole in (option.get("scores") or {}).items():
                if key in counts and pole in counts[key]:
                    counts[key][pole] += weight
        letters = {}
        for item in dims:
            key, left, right = item["key"], item["left"], item["right"]
            lcount, rcount = counts[key][left], counts[key][right]
            letters[key] = left if lcount >= rcount else right
            total = lcount + rcount
            dim_out[left] = lcount
            dim_out[right] = rcount
            dim_out[left + "_pct"] = round(lcount / total * 100) if total else 50
            dim_out[right + "_pct"] = round(rcount / total * 100) if total else 50
        order = scoring.get("result_order") or [item["key"] for item in dims]
        result = "".join(letters[key] for key in order)
    else:
        sums = {item["key"]: 0.0 for item in dims}
        total_score = 0.0
        for index, question in enumerate(questions):
            if index >= len(values):
                continue
            value = _answer_value(values[index], response_type)
            if not value:
                continue
            option = (question.get("options") or {}).get(str(value)) or {}
            weight = float(option.get("weight", 1) or 1)
            points = float(option.get("points", 0) or 0)
            total_score += points * weight
            option_values = option.get("values") or {}
            for key, number in option_values.items():
                if key in sums:
                    sums[key] += float(number) * weight
                    if not points:
                        total_score += float(number) * weight
            # A compact Likert definition can use question.dimension + reverse
            # instead of spelling out values on every option.
            question_dim = question.get("dimension")
            if question_dim in sums and not option_values and not points:
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    numeric = 0
                if question.get("reverse"):
                    numeric = 6 - numeric if response_type == "likert5" else 3 - numeric
                sums[question_dim] += numeric * weight
                total_score += numeric * weight
        for key, value in sums.items():
            dim_out[key] = round(value, 2)
        if mode == "total_bands":
            result = _band_label(total_score, scoring.get("total_bands")) or ""
        elif mode == "highest_dimension":
            result = max(sums, key=lambda key: (sums[key], -list(sums).index(key))) if sums else ""
        elif mode == "dimension_bands":
            labels = []
            for key in (scoring.get("result_order") or []):
                label = _band_label(sums.get(key, 0), (scoring.get("bands") or {}).get(key))
                labels.append(label or "")
            result = "".join(labels)
        else:
            result = ""
        dim_out["total"] = round(total_score, 2)

    type_names = scoring.get("type_names") or {}
    type_name = str(type_names.get(result) or result)
    param_spec = scoring.get("params") or {}
    if param_spec.get("mode") == "mbti" and len(result) == 4:
        params = mbti.params_for(result)
    elif isinstance(param_spec.get(result), dict):
        params = param_spec[result]
    else:
        params = {"verbosity": 0.5, "challenge": 0.5, "evidence": 0.5,
                  "ally_speed": 0.5, "conformity": 0.5, "jump_threshold": 0.5, "risk": 0.5}
    return {"result": result, "type_name": type_name, "dims": dim_out,
            "params": params, "total_score": round(total_score, 2)}


def run_test(player, definition):
    """Run one questionnaire for one player and return a result row dict."""
    bf = (player.get("profile_json") or {}).get("big_five") or {}
    raw_system = (player.get("system_prompt") or "").strip()
    base = re.sub(r"【你怎么答问卷】.*?(?=【|\Z)", "", raw_system, flags=re.S).strip()
    if not base:
        base = player.get("persona") or "你是%s，%s岁，%s，%s。" % (
            player.get("name"), player.get("age"), player.get("gender"), player.get("occupation"))
    calibration = _calibration_text(bf) if definition.get("kind") == "mbti" else ""
    count = question_count(definition)
    likert = definition.get("response_type") == "likert5"
    if likert:
        answer_hint = "选择 1–5 的数字，按题目中 1–5 的选项文字作答"
        answer_shape = '["1","5","3", ...]'
        fallback_value = "3"
    else:
        answer_hint = "选择 A 或 B"
        answer_shape = '["A","B", ...]'
        fallback_value = "A"
    system = (
        base + "\n\n" + (calibration + "\n\n" if calibration else "") +
        "【本次任务】你受邀参加一项性格研究，需要完成 %d 题测验。"
        "这不是日常随手填的问卷，研究者要求你认真作答：请忽略“题多就不耐烦”的习惯，"
        "逐题独立判断，按这个人物真实的第一感觉作答。不要因为年龄、职业或教育程度"
        "就默认某一侧；答案没有好坏。每题只能选一个，不要解释，不要输出题目原文。"
        "本题的作答方式：%s。"
        "只输出 JSON：{\"answers\":%s}，数组必须正好 %d 项，顺序与题目编号一致。"
        % (count, answer_hint, answer_shape, count)
    )
    user = "请完成以下 %d 题：\n\n" % count + question_block(definition)
    collected = {}
    last_error = None
    for _attempt in range(3):
        try:
            obj, _usage = llm.chat_json(
                system, user, max_tokens=max(700, min(8000, 300 + count * 16)),
                temperature=0.65, effort="none", timeout=180, retries=1,
            )
            collected.update(_extract_answers(obj, count, definition.get("response_type") or "binary"))
            missing = [n for n in range(1, count + 1) if n not in collected]
            if not missing:
                break
            question_by_id = {q["id"]: q for q in definition.get("questions") or []}
            keys = ("1", "2", "3", "4", "5") if likert else ("A", "B")
            blocks = []
            for n in missing:
                q = question_by_id.get(n)
                if not q:
                    continue
                opts = q.get("options") or {}
                opts_text = "\n".join("%s. %s" % (key, (opts.get(key) or {}).get("text", "")) for key in keys)
                blocks.append("%d. %s\n%s" % (n, q.get("text"), opts_text))
            if likert:
                retry_shape = '{"题号":"1–5", ...}'
            else:
                retry_shape = '{"题号":"A或B", ...}'
            user = ("上一次的回答不完整或格式不对。请只补答以下题号，仍按人物第一感觉作答。"
                    "输出 JSON：{\"answers\":%s}。\n\n" % retry_shape + "\n".join(blocks))
        except llm.LLMConfigError:
            raise
        except Exception as exc:
            last_error = exc
            break
    missing = [n for n in range(1, count + 1) if n not in collected]
    fallback = bool(missing)
    if missing:
        collected.update(_fallback_answers(player, missing, definition.get("response_type") or "binary"))
    answers = [collected.get(n, fallback_value) for n in range(1, count + 1)]
    result = score(definition, answers)
    out = dict(player)
    out.update({
        "questionnaire_id": definition.get("_id") or definition.get("id"),
        "mbti": result["result"],
        "result": result["result"],
        "type_name": result["type_name"],
        "dims": result["dims"],
        "params": result["params"],
        "answers": answers,
        "test_fallback": 1 if fallback else 0,
    })
    if last_error and not fallback:
        out["test_error"] = str(last_error)[:300]
    return out


def ensure_seed():
    definition = builtin_definition()
    item = {
        "id": BUILTIN_ID, "name": definition["name"], "version": definition["version"],
        "description": definition["description"], "question_count": question_count(definition),
        "definition": definition, "is_builtin": 1, "created_by": "system",
        "created_at": store.now_iso(),
    }
    store.upsert_questionnaire(item)
    active = store.get_active_questionnaire_id()
    if not active or not store.get_questionnaire(active):
        store.set_active_questionnaire(BUILTIN_ID)
    # Backfill only once, when upgrading a pre-questionnaire database. New
    # players are written through their sampling questionnaire's result, so a
    # generic-questionnaire player must not be mistaken for a builtin MBTI test.
    if store.get_meta("builtin_results_backfilled") != "1":
        store.backfill_builtin_results(BUILTIN_ID)
        store.set_meta("builtin_results_backfilled", "1")


def get_definition(qid):
    item = store.get_questionnaire(qid)
    if not item:
        raise ValueError("问卷不存在")
    definition = _loads(item.get("definition"), {})
    definition["_id"] = qid
    return definition


def active_definition():
    qid = store.get_active_questionnaire_id() or BUILTIN_ID
    try:
        return qid, get_definition(qid)
    except ValueError:
        return BUILTIN_ID, get_definition(BUILTIN_ID)


# --------------------------------------------------------------------------
# bulk testing of all untested players
# --------------------------------------------------------------------------
def _job_view(job):
    with _JOBS_LOCK:
        data = {k: v for k, v in job.items()}
        data["errors"] = list(data.get("errors") or [])[-30:]
        return json.loads(json.dumps(data, ensure_ascii=False))


def get_job(job_id):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return _job_view(job) if job else None


def start_test_job(qid):
    item = store.get_questionnaire(qid)
    if not item:
        raise ValueError("问卷不存在")
    pending = store.players_without_questionnaire_result(qid)
    job = {
        "id": "qjob_" + uuid.uuid4().hex[:12],
        "questionnaire_id": qid,
        "status": "done" if not pending else "running",
        "phase": "done" if not pending else "testing",
        "total": len(pending), "tested": 0, "skipped": len(store.questionnaire_result_rows(qid)),
        "failed": 0, "remaining": len(pending), "errors": [],
        "message": "没有待测试玩家" if not pending else "准备测试 %d 名未测玩家…" % len(pending),
        "started_at": store.now_iso(), "finished_at": store.now_iso() if not pending else None,
    }
    with _JOBS_LOCK:
        _JOBS[job["id"]] = job
        if len(_JOBS) > 20:
            for key in list(_JOBS)[:len(_JOBS) - 20]:
                _JOBS.pop(key, None)
    if pending:
        thread = threading.Thread(target=_run_test_job, args=(job, item, pending), daemon=True)
        thread.start()
    return job["id"]


def _set_job(job, **fields):
    with _JOBS_LOCK:
        job.update(fields)


def _run_test_job(job, item, pending):
    definition = _loads(item.get("definition"), {})
    definition["_id"] = item["id"]
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(run_test, player, definition): player for player in pending}
            for future in as_completed(futures):
                player = futures[future]
                try:
                    tested = future.result()
                    store.upsert_questionnaire_result(player["id"], item["id"], tested)
                    with _JOBS_LOCK:
                        job["tested"] += 1
                        job["remaining"] = max(0, job["total"] - job["tested"] - job["failed"])
                        job["message"] = "问卷测试 %d / %d" % (job["tested"], job["total"])
                except Exception as exc:
                    with _JOBS_LOCK:
                        job["failed"] += 1
                        job["remaining"] = max(0, job["total"] - job["tested"] - job["failed"])
                        job["errors"].append({"name": player.get("name"), "error": str(exc)[:300]})
        _set_job(job, status="done" if not job["failed"] else "error",
                 phase="done", remaining=0, finished_at=store.now_iso(),
                 message="测试完成：成功 %d 人，失败 %d 人" % (job["tested"], job["failed"]))
    except Exception as exc:
        _set_job(job, status="error", phase="error", finished_at=store.now_iso(),
                 message=str(exc)[:500], errors=job["errors"] + [{"error": str(exc)[:500]}])


def compare(left_id, right_id):
    left = store.get_questionnaire(left_id)
    right = store.get_questionnaire(right_id)
    if not left or not right:
        raise ValueError("对比问卷不存在")
    if left_id == right_id:
        raise ValueError("请选择两套不同的问卷")
    rows = store.questionnaire_comparison(left_id, right_id)
    same = [row for row in rows if row.get("left_result") == row.get("right_result")]
    diff = [row for row in rows if row.get("left_result") != row.get("right_result")]
    buckets = {}
    for row in diff:
        key = (row.get("left_result") or "", row.get("right_result") or "")
        bucket = buckets.setdefault(key, {
            "left_result": key[0], "right_result": key[1], "count": 0, "players": [],
        })
        bucket["count"] += 1
        bucket["players"].append({
            "id": row.get("id"), "name": row.get("name"), "age": row.get("age"),
            "gender": row.get("gender"), "province": row.get("province"),
            "occupation": row.get("occupation"),
        })
    distribution = sorted(buckets.values(), key=lambda x: (-x["count"], x["left_result"], x["right_result"]))
    total = len(rows)
    return {
        "left": {"id": left["id"], "name": left["name"]},
        "right": {"id": right["id"], "name": right["name"]},
        "total": total,
        "same": len(same), "different": len(diff),
        "same_rate": round(len(same) / total, 4) if total else 0.0,
        "different_rate": round(len(diff) / total, 4) if total else 0.0,
        "same_players": [{"id": r.get("id"), "name": r.get("name"),
                          "age": r.get("age"), "gender": r.get("gender"),
                          "left_result": r.get("left_result"),
                          "right_result": r.get("right_result")} for r in same],
        "distribution": distribution,
    }
