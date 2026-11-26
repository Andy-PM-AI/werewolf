"""AudienceLib sampling, persona compaction and the 93-question MBTI interview."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import llm
import mbti
import questionnaires
import store
from audiencelib_client import AudienceLib

_HERE = os.path.dirname(os.path.abspath(__file__))

COUNTRY_NAMES = {"CN": "中国", "US": "美国", "GB": "英国", "DE": "德国", "FR": "法国"}
_GENDER_ALIASES = {
    "male": ("male", "m", "男", "男性"),
    "female": ("female", "f", "女", "女性"),
    "男": ("男", "male", "男性"),
    "女": ("女", "female", "女性"),
}

_CATALOG = {"stamp": 0.0, "value": None}
_CATALOG_LOCK = threading.Lock()


def _settings():
    return llm.CONFIG.data


def audiencelib_client():
    key = str(_settings().get("audiencelib_api_key") or "")
    if not key or key == "replace-me":
        raise RuntimeError("AudienceLib API Key 未配置")
    return AudienceLib(key, _settings().get("audiencelib_base_url", "https://audiencelib.lifecontext.ai"))


def catalog(max_age=120):
    """Authorised populations and their filter facets, cached briefly."""
    with _CATALOG_LOCK:
        if _CATALOG["value"] is not None and time.time() - _CATALOG["stamp"] < max_age:
            return _CATALOG["value"]
        client = audiencelib_client()
        countries = {}
        errors = []
        for code in COUNTRY_NAMES:
            try:
                raw = client.populations(code)
            except Exception as exc:  # a country may simply not be authorised
                errors.append({"country": code, "error": str(exc)[:200]})
                continue
            items = []
            for release in raw.get("items") or []:
                if not isinstance(release, dict):
                    continue
                facets = (release.get("manifest") or {}).get("facets") or {}
                items.append({
                    "id": release.get("id"),
                    "name": release.get("name"),
                    "count": release.get("count") or 0,
                    "country_code": str(release.get("country_code") or code).upper(),
                    "facets": {k: v for k, v in facets.items() if isinstance(v, list)},
                })
            if items:
                countries[code] = {
                    "code": code,
                    "name": COUNTRY_NAMES.get(code, code),
                    "default_release_id": raw.get("default_release_id"),
                    "sampling_quota": raw.get("sampling_quota"),
                    "limits": raw.get("limits"),
                    "items": items,
                }
        value = {"countries": countries, "errors": errors, "fetched_at": store.now_iso()}
        _CATALOG.update({"stamp": time.time(), "value": value})
        return value


def _map_gender(value, facet=None):
    text = str(value or "").strip().lower()
    if text in ("", "any", "all"):
        return ""
    candidates = _GENDER_ALIASES.get(text, (text,))
    if facet:
        for candidate in facet:
            if str(candidate).strip().lower() in candidates:
                return str(candidate)
        return ""
    return {"male": "male", "female": "female", "男": "男", "女": "女"}.get(text, text)


def _pick_release(country):
    cat = catalog()
    entry = cat["countries"].get(country)
    if not entry or not entry["items"]:
        raise RuntimeError("AudienceLib 没有 %s 的授权人口版本" % COUNTRY_NAMES.get(country, country))
    default = entry.get("default_release_id")
    return next((r for r in entry["items"] if r["id"] == default), entry["items"][0])


def _text(value):
    if isinstance(value, (list, tuple)):
        return " · ".join(str(x).strip() for x in value if str(x).strip())
    return "" if value is None else str(value).strip()


def _first(source, keys, default=None):
    for key in keys:
        value = source.get(key) if isinstance(source, dict) else None
        if value not in (None, ""):
            return value
    return default


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def normalize_person(raw, country):
    raw = dict(raw) if isinstance(raw, dict) else {}
    snapshot = raw.get("snapshot") if isinstance(raw.get("snapshot"), dict) else {}
    profile = snapshot.get("profile") if isinstance(snapshot.get("profile"), dict) else {}
    mind = snapshot.get("mind") if isinstance(snapshot.get("mind"), dict) else {}
    source = {**profile, **raw}

    person_id = _text(_first(source, ("person_id", "id")))
    name = _text(_first(source, ("name", "姓名(虚构)", "display_name"))) or "无名"
    age = _int(_first(source, ("age", "年龄")))
    gender = _text(_first(source, ("gender", "sex", "性别")))
    province = _text(_first(source, ("province", "region_name", "所在省份", "region")))
    city = _text(_first(source, ("city", "居住地类型", "region_name")))
    urbanicity = _text(_first(source, ("urbanicity", "城乡")))
    education = _text(_first(source, ("education", "学历")))
    occupation = _text(_first(source, ("occupation", "具体职业", "employment", "job")))
    occupation_group = _text(_first(source, ("occupation_group", "职业大类")))
    income = _int(_first(source, ("income", "个人月收入(元)", "income_decile")))
    marital = _text(_first(source, ("marital", "marital_status", "婚姻状况")))
    interests = _first(source, ("interests", "兴趣爱好"), [])
    if isinstance(interests, str):
        interests = re.split(r"[、,，;；/]", interests)
    interests = [str(x).strip() for x in interests if str(x).strip()]

    big_five = {
        "外向性": _first(profile, ("外向性",)),
        "宜人性": _first(profile, ("宜人性",)),
        "尽责性": _first(profile, ("尽责性",)),
        "开放性": _first(profile, ("开放性",)),
        "神经质": _first(profile, ("神经质",)),
    }
    big_five = {k: v for k, v in big_five.items() if v not in (None, "")}
    life_story = _text(_first(mind, ("life_story", "life_experience")))
    speech = _text(_first(mind, ("speech",)))
    beliefs = mind.get("beliefs") if isinstance(mind.get("beliefs"), list) else []
    system_prompt = _text(_first(snapshot, ("system_prompt",))) or _text(_first(raw, ("system_prompt",)))
    risk_pref = _first(profile, ("风险偏好(1-5)",))

    persona = _compact_persona({
        "name": name, "age": age, "gender": gender, "province": province,
        "urbanicity": urbanicity, "education": education, "occupation": occupation,
        "income": income, "marital": marital, "life_story": life_story,
        "speech": speech, "beliefs": beliefs, "big_five": big_five,
        "risk_pref": risk_pref,
    })
    return {
        "id": "pl_" + (person_id.replace("per_", "") if person_id else uuid.uuid4().hex),
        "person_id": person_id,
        "name": name,
        "age": age,
        "gender": gender,
        "country": country,
        "province": province,
        "city": city,
        "urbanicity": urbanicity,
        "education": education,
        "occupation": occupation,
        "occupation_group": occupation_group,
        "income": income,
        "marital": marital,
        "interests": interests[:12],
        "persona": persona,
        "system_prompt": system_prompt,
        "profile_json": {"big_five": big_five, "risk_preference": risk_pref,
                         "speech": speech, "beliefs": beliefs, "life_story": life_story},
        "raw_json": raw,
        "source": "audiencelib",
        "created_at": store.now_iso(),
    }


def _compact_persona(p):
    bits = []
    identity = "，".join(str(x) for x in [
        p.get("name"), ("%s岁" % p["age"]) if p.get("age") else "",
        p.get("gender"), p.get("province"), p.get("urbanicity"),
        p.get("education"), p.get("occupation"),
        ("月收入约%s元" % p["income"]) if p.get("income") else "",
        p.get("marital"),
    ] if x)
    bits.append(identity + "。")
    if p.get("life_story"):
        bits.append("经历：" + p["life_story"][:260])
    if p.get("speech"):
        bits.append("说话习惯：" + p["speech"])
    if p.get("beliefs"):
        bits.append("在意的事：" + "；".join(str(x) for x in p["beliefs"][:3]))
    bf = p.get("big_five") or {}
    if bf:
        bits.append("心理测量：" + "、".join("%s%s" % (k, v) for k, v in bf.items()) + "（0–100）。")
    if p.get("risk_pref") not in (None, ""):
        bits.append("风险偏好：%s/5。" % p["risk_pref"])
    return "\n".join(bits)


def _question_block():
    lines = []
    for i, q in enumerate(mbti.QUESTIONS, 1):
        lines.append("%d. %s\nA. %s\nB. %s" % (i, q[0], q[1], q[2]))
    return "\n".join(lines)


_QUESTION_BLOCK = _question_block()


def _letter(item):
    text = str(item or "").strip().upper()
    if text in ("A", "A.", "1", "选项A"):
        return "A"
    if text in ("B", "B.", "2", "选项B"):
        return "B"
    return ""


def _extract_answers(obj):
    """Return {1-based question number: 'A'|'B'} from a model response."""
    if not isinstance(obj, dict):
        return {}
    payload = obj.get("answers") or obj.get("responses") or obj.get("choices")
    out = {}
    if isinstance(payload, str):
        # Some models return one long "AABB..." string instead of a list.
        letters = [ch for ch in payload.upper() if ch in ("A", "B")]
        for index, letter in enumerate(letters[:93], 1):
            out[index] = letter
    elif isinstance(payload, list):
        for index, item in enumerate(payload, 1):
            if isinstance(item, dict):
                item = item.get("answer") or item.get("choice") or item.get("value")
            letter = _letter(item)
            if letter:
                out[index] = letter
    elif isinstance(payload, dict):
        for key, item in payload.items():
            try:
                index = int(str(key).strip().strip("第题：:"))
            except (TypeError, ValueError):
                continue
            if 1 <= index <= 93:
                if isinstance(item, dict):
                    item = item.get("answer") or item.get("choice") or item.get("value")
                letter = _letter(item)
                if letter:
                    out[index] = letter
    return out


def _fallback_answers(player, indices):
    """Last-resort A/B pattern derived from the persona, clearly flagged as fallback."""
    seed = hashlib.sha256(
        (str(player.get("person_id")) + str(player.get("name"))).encode("utf-8")
    ).digest()
    out = {}
    for n in indices:
        out[n] = "A" if seed[(n - 1) % len(seed)] % 2 == 0 else "B"
    return out


def _bf_value(bf, key):
    try:
        return float(bf.get(key))
    except (TypeError, ValueError):
        return None


def _calibration(bf):
    """Turn the library's Big Five profile into dimension-level answering hints.

    Without this the model tends to role-play the persona's *questionnaire
    habits* ("题多就不耐烦") and every older or practical persona lands on ISTJ.
    The hint keeps the 93-item scoring standard while anchoring the answers to
    the person's measured traits.
    """
    if not bf:
        return ""
    lines = []
    e = _bf_value(bf, "外向性")
    o = _bf_value(bf, "开放性")
    a = _bf_value(bf, "宜人性")
    c = _bf_value(bf, "尽责性")
    if e is not None:
        lines.append("外向性 %.0f → %s" % (e, "偏 E（外倾）" if e >= 55 else "偏 I（内倾）" if e <= 45 else "中间，按题目判断"))
    if o is not None:
        lines.append("开放性 %.0f → %s" % (o, "偏 N（直觉）" if o >= 55 else "偏 S（感觉）" if o <= 45 else "中间，按题目判断"))
    if a is not None:
        lines.append("宜人性 %.0f → %s" % (a, "偏 F（情感）" if a >= 55 else "偏 T（思维）" if a <= 45 else "中间，按题目判断"))
    if c is not None:
        lines.append("尽责性 %.0f → %s" % (c, "偏 J（判断）" if c >= 55 else "偏 P（知觉）" if c <= 45 else "中间，按题目判断"))
    if not lines:
        return ""
    return (
        "【作答校准】这个人物的人口库心理测量档案如下。请让作答与这些倾向大体一致，"
        "但不要机械地全选同一侧；具体题目仍按这个人的经历和第一感觉判断：\n"
        + "\n".join(lines)
    )


def run_mbti_test(player):
    """Backward-compatible wrapper for the built-in MBTI questionnaire."""
    definition = questionnaires.builtin_definition()
    definition["_id"] = questionnaires.BUILTIN_ID
    return questionnaires.run_test(player, definition)


# --------------------------------------------------------------------------
# sampling jobs
# --------------------------------------------------------------------------
JOBS = {}
_JOBS_LOCK = threading.RLock()


def _job_view(job):
    with _JOBS_LOCK:
        data = {k: v for k, v in job.items() if k != "people_raw"}
        people = list(job.get("people") or [])
        added = list(job.get("added") or [])
        # Large batches must not serialize thousands of rows every poll.
        # Keep the counters exact but only send the most recent window.
        data["people"] = people[-200:]
        data["people_total"] = len(people)
        data["added"] = added[-200:]
        data["added_count"] = len(added)
        counts = {}
        for item in added:
            counts[item.get("mbti") or "—"] = counts.get(item.get("mbti") or "—", 0) + 1
        data["added_counts"] = counts
        data["errors"] = list(job.get("errors") or [])[-50:]
        data["errors_total"] = len(job.get("errors") or [])
        return json.loads(json.dumps(data, ensure_ascii=False))


def get_job(job_id):
    with _JOBS_LOCK:
        job = JOBS.get(job_id)
        return _job_view(job) if job else None


def start_sample_job(payload):
    qid = store.get_active_questionnaire_id() or questionnaires.BUILTIN_ID
    definition = questionnaires.get_definition(qid)
    count = _int(payload.get("count"))
    if not count or count < 1 or count > 10000:
        raise ValueError("单次抽取样本量必须在 1–10000 之间")
    country = str(payload.get("country") or "CN").upper()
    if country not in COUNTRY_NAMES:
        raise ValueError("不支持的国家")
    age_min = _int(payload.get("age_min"))
    age_max = _int(payload.get("age_max"))
    if age_min is not None and age_max is not None and age_min > age_max:
        raise ValueError("最低年龄不能高于最高年龄")
    job = {
        "id": "job_" + uuid.uuid4().hex[:12],
        "status": "queued",
        "phase": "queued",
        "requested": count,
        "tested": 0,
        "sampled": 0,
        "failed": 0,
        "added": [],
        "people": [],
        "errors": [],
        "message": "排队中",
        "started_at": store.now_iso(),
        "finished_at": None,
        "request": {"country": country, "age_min": age_min, "age_max": age_max,
                    "gender": payload.get("gender") or "", "count": count,
                    "questionnaire_id": qid, "questionnaire_name": definition.get("name"),
                    "education": payload.get("education") or [],
                    "occupation_group": payload.get("occupation_group") or [],
                    "urbanicity": payload.get("urbanicity") or "",
                    "consumption_style": payload.get("consumption_style") or []},
    }
    with _JOBS_LOCK:
        JOBS[job["id"]] = job
        # Keep the registry small.
        if len(JOBS) > 30:
            for key in list(JOBS)[:len(JOBS) - 30]:
                JOBS.pop(key, None)
    thread = threading.Thread(target=_run_sample_job, args=(job,), daemon=True)
    thread.start()
    return job["id"]


def _run_sample_job(job):
    try:
        _set(job, status="running", phase="sampling", message="正在从 AudienceLib 抽取人口样本…")
        people = sample_people(job["request"])
        qid = job["request"].get("questionnaire_id") or store.get_active_questionnaire_id() or questionnaires.BUILTIN_ID
        definition = questionnaires.get_definition(qid)
        definition["_id"] = qid
        _set(job, phase="testing", sampled=len(people),
             message="样本已到达，正在用《%s》逐一测验…" % definition.get("name"))
        with _JOBS_LOCK:
            job["people"] = [
                {"name": p.get("name"), "age": p.get("age"), "gender": p.get("gender"),
                 "province": p.get("province"), "occupation": p.get("occupation"),
                 "status": "pending", "mbti": None}
                for p in people
            ]
        completed = 0
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(questionnaires.run_test, p, definition): (i, p) for i, p in enumerate(people)}
            for future in as_completed(futures):
                index, base = futures[future]
                try:
                    tested = future.result()
                    store.add_player(tested)
                    store.upsert_questionnaire_result(tested["id"], qid, tested)
                    with _JOBS_LOCK:
                        job["added"].append({
                            "id": tested["id"], "name": tested["name"],
                            "age": tested.get("age"), "gender": tested.get("gender"),
                            "mbti": tested["mbti"], "type_name": tested.get("type_name") or mbti.type_name(tested["mbti"]),
                            "fallback": bool(tested.get("test_fallback")),
                        })
                        job["people"][index]["status"] = "done"
                        job["people"][index]["mbti"] = tested["mbti"]
                except Exception as exc:
                    with _JOBS_LOCK:
                        job["failed"] += 1
                        job["errors"].append({"name": base.get("name"), "error": str(exc)[:300]})
                        job["people"][index]["status"] = "failed"
                completed += 1
                _set(job, tested=completed, message="问卷测验 %d / %d" % (completed, len(people)),
                     phase="testing")
        _set(job, status="done" if job["added"] else "error",
             phase="done" if job["added"] else "error",
             message=("已加入 %d 位玩家" % len(job["added"])) if job["added"] else "没有成功加入任何玩家",
             finished_at=store.now_iso())
    except Exception as exc:
        _set(job, status="error", phase="error", message=str(exc)[:500],
             errors=job["errors"] + [{"error": str(exc)[:500]}], finished_at=store.now_iso())


def _set(job, **fields):
    with _JOBS_LOCK:
        job.update(fields)


def sample_people(request):
    country = request["country"]
    release = _pick_release(country)
    count = int(request["count"])
    facets = release.get("facets") or {}
    filters = {}
    age_min, age_max = request.get("age_min"), request.get("age_max")
    if age_min is not None or age_max is not None:
        age = {}
        if age_min is not None:
            age["gte"] = max(0, min(int(age_min), 120))
        if age_max is not None:
            age["lte"] = max(0, min(int(age_max), 120))
        filters["age"] = age
    gender = _map_gender(request.get("gender"), facets.get("gender"))
    if gender:
        filters["gender"] = gender
    for key in ("education", "occupation_group", "consumption_style"):
        values = request.get(key) or []
        allowed = facets.get(key)
        if not isinstance(values, list) or not values:
            continue
        if allowed:
            kept = [v for v in values if v in allowed]
            if kept:
                filters[key] = kept
        else:
            filters[key] = values
    urbanicity = str(request.get("urbanicity") or "").strip()
    allowed_urban = facets.get("urbanicity")
    if urbanicity and (not allowed_urban or urbanicity in allowed_urban):
        filters["urbanicity"] = urbanicity
    client = audiencelib_client()
    body = {
        "name": "狼人杀人格实验室 · %s" % store.now_iso()[:10],
        "population_release_id": release["id"],
        "size": count,
        "filters": filters,
        "sampling": {"method": "random"},
    }
    created = client.create_audience(body, idempotency_key=str(uuid.uuid4()))
    audience_id = str(created.get("audience_id") or "")
    if not audience_id:
        raise RuntimeError("AudienceLib 未返回人群 ID")
    audience = client.audience(audience_id)
    people = [p for p in client.people(audience_id) if isinstance(p, dict)]
    if len(people) != count:
        raise RuntimeError("AudienceLib 返回 %d 人，请求 %d 人" % (len(people), count))
    return [normalize_person(p, country) for p in people]
