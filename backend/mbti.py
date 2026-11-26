"""MBTI 93-question test data, scoring and behavioural parameter derivation."""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "mbti_questions.json"), encoding="utf-8") as _fh:
    _DATA = json.load(_fh)

QUESTIONS = _DATA["questions"]
DIMS = _DATA["dimensions"]

TYPE_NAMES = {
    "ISTJ": "物流师·检查者",
    "ISFJ": "守卫者·保护者",
    "INFJ": "提倡者·劝告者",
    "INTJ": "策划者·战略家",
    "ISTP": "巧匠·鉴赏家",
    "ISFP": "艺术家·创作者",
    "INFP": "哲人·治愈者",
    "INTP": "学者·思想家",
    "ESTP": "实干家·创业者",
    "ESFP": "表演者·示范者",
    "ENFP": "奋斗者·公关者",
    "ENTP": "发明家·智多星",
    "ESTJ": "管理者·监督者",
    "ESFJ": "供应者·主人型",
    "ENFJ": "教育者·教导者",
    "ENTJ": "统帅·指挥官",
}

TYPE_DESCRIPTIONS = {
    "ISTJ": "安静、严肃、可靠，讲求实际与秩序，做事负责且有始有终，值得信赖。",
    "ISFJ": "温和、体贴、尽责，重视传统与和谐，默默为他人提供切实的支持。",
    "INFJ": "有洞察力和理想主义，关注他人成长与长远意义，做事有原则且投入。",
    "INTJ": "独立、有战略眼光，善于构建长期体系与理论，追求能力与效率。",
    "ISTP": "灵活冷静的实干者，擅长动手分析与解决具体问题，喜欢掌控工具与技术。",
    "ISFP": "敏感、温和、有审美，活在当下，用行动而非言语表达内心的价值观。",
    "INFP": "理想主义、忠诚，重视内在价值与真诚，希望自己的工作有意义、帮助他人。",
    "INTP": "喜欢分析和抽象思考，追求逻辑上的精确与理解，灵活而又有好奇心。",
    "ESTP": "精力充沛、注重行动与结果，善于在突发情境中随机应变、解决问题。",
    "ESFP": "热情、乐观、爱社交，享受当下，善于调动气氛并关心他人的感受。",
    "ENFP": "热情洋溢、想象力丰富，善于发现可能性并激励他人，重视人际连接。",
    "ENTP": "思维敏捷、爱挑战常规，善于提出新点子并推动变革，享受辩论与博弈。",
    "ESTJ": "务实、果断、有组织力，擅长制定计划与流程，以效率和结果为导向。",
    "ESFJ": "热心、合作、有责任感，重视人际和谐，乐于组织活动并照顾他人。",
    "ENFJ": "有感染力与同理心，善于发现他人潜能并引导其成长，重视和谐与责任。",
    "ENTJ": "有领导力与全局观，擅长制定长远战略并推动执行，果断且追求卓越。",
}

DIMENSION_META = [
    {"key": "EI", "left": "E", "right": "I", "left_name": "外倾", "right_name": "内倾", "total": 21},
    {"key": "SN", "left": "S", "right": "N", "left_name": "感觉", "right_name": "直觉", "total": 26},
    {"key": "TF", "left": "T", "right": "F", "left_name": "思维", "right_name": "情感", "total": 24},
    {"key": "JP", "left": "J", "right": "P", "left_name": "判断", "right_name": "知觉", "total": 22},
]


def _count(indices, answers, letter):
    return sum(1 for n in indices if str(answers[n - 1]).strip().upper() == letter)


def score(answers):
    """Score 93 A/B answers exactly as the source HTML does."""
    if len(answers) != 93:
        raise ValueError("MBTI 问卷需要 93 个答案，当前为 %d 个" % len(answers))
    E = _count(DIMS["EI_A"], answers, "A") + _count(DIMS["EI_B"], answers, "B")
    I = 21 - E
    S = _count(DIMS["SN_A"], answers, "A") + _count(DIMS["SN_B"], answers, "B")
    N = 26 - S
    T = _count(DIMS["TF_A"], answers, "A") + _count(DIMS["TF_B"], answers, "B")
    F = 24 - T
    J = _count(DIMS["JP_A"], answers, "A") + _count(DIMS["JP_B"], answers, "B")
    P = 22 - J
    letters = {
        "EI": "E" if E >= I else "I",
        "SN": "S" if S >= N else "N",
        "TF": "T" if T >= F else "F",
        "JP": "J" if J >= P else "P",
    }
    mbti = letters["EI"] + letters["SN"] + letters["TF"] + letters["JP"]
    dims = {
        "E": E, "I": I, "S": S, "N": N, "T": T, "F": F, "J": J, "P": P,
        "E_pct": round(E / 21 * 100), "I_pct": round(I / 21 * 100),
        "S_pct": round(S / 26 * 100), "N_pct": round(N / 26 * 100),
        "T_pct": round(T / 24 * 100), "F_pct": round(F / 24 * 100),
        "J_pct": round(J / 22 * 100), "P_pct": round(P / 22 * 100),
    }
    return {"mbti": mbti, "dims": dims, "letters": letters}


def params_for(mbti):
    """The parameter table in §3.2 of the design doc: baseline .5, delta .3."""
    mbti = (mbti or "").upper()
    e, s, t, j = mbti[0:1], mbti[1:2], mbti[2:3], mbti[3:4]
    return {
        "verbosity": 0.8 if e == "E" else 0.2,
        "challenge": 0.8 if e == "E" else 0.2,
        "evidence": 0.8 if s == "S" else 0.2,
        "ally_speed": 0.8 if t == "F" else 0.2,
        "conformity": 0.8 if t == "F" else 0.2,
        "jump_threshold": 0.2 if j == "J" else 0.8,
        "risk": 0.8 if j == "P" else 0.2,
    }


PARAM_LABELS = {
    "verbosity": "话量",
    "challenge": "质疑频率",
    "evidence": "证据依赖",
    "ally_speed": "结盟时机",
    "conformity": "跟票倾向",
    "jump_threshold": "跳身份阈值",
    "risk": "风险偏好",
}


def _level(value, low="低", high="高"):
    if value >= 0.65:
        return high
    if value <= 0.35:
        return low
    return "中"


def param_notes(params):
    return {
        "verbosity": _level(params["verbosity"], "话少", "话多"),
        "challenge": _level(params["challenge"], "少质疑", "常质疑"),
        "evidence": _level(params["evidence"], "凭感觉", "看证据"),
        "ally_speed": _level(params["ally_speed"], "晚结盟", "早结盟"),
        "conformity": _level(params["conformity"], "坚持己见", "容易跟票"),
        "jump_threshold": _level(params["jump_threshold"], "早跳身份", "晚跳身份"),
        "risk": _level(params["risk"], "求稳", "敢冒险"),
    }


def max_words(params):
    return int(round(40 + params.get("verbosity", 0.5) * 80))


def type_name(mbti):
    return TYPE_NAMES.get((mbti or "").upper(), "")


def all_types():
    return list(TYPE_NAMES.keys())
