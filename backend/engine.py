"""A hard-ruled 9/10-player werewolf engine whose agents are DeepSeek personas.

The engine, not the model, owns every rule: night order, potion legality, vote
tallies, hunter shots and the win check. Model calls only choose actions and
produce speech; malformed answers fall back to a deterministic heuristic and
mark the game degenerate instead of aborting the batch.
"""
from __future__ import annotations

import random
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import llm
import mbti as mbti_mod

ROLE_DEFS = {
    "wolf": {"name": "狼人", "camp": "wolf", "total": 3, "max": 3},
    "villager": {"name": "平民", "camp": "good", "total": 3, "max": 4},
    "seer": {"name": "预言家", "camp": "good", "total": 1, "max": 1},
    "witch": {"name": "女巫", "camp": "good", "total": 1, "max": 1},
    "hunter": {"name": "猎人", "camp": "good", "total": 1, "max": 1},
}
ROLE_ORDER = ("wolf", "villager", "seer", "witch", "hunter")
BOARD_SIZES = (9, 10)
GOD_ROLES = ("seer", "witch", "hunter")
MAX_ROUNDS = 8


def role_totals(player_count):
    """Role counts for the supported 9- and 10-player boards.

    The rules are otherwise unchanged: 3 wolves, seer/witch/hunter, and the
    remaining seats are villagers. A 9-player board has 3 villagers; the
    10-player board adds one optional villager seat.
    """
    try:
        player_count = int(player_count or 9)
    except (TypeError, ValueError):
        player_count = 9
    if player_count not in BOARD_SIZES:
        raise ValueError("玩家人数只能是 9 或 10 人")
    totals = {role: int(ROLE_DEFS[role]["total"]) for role in ROLE_ORDER}
    totals["villager"] = player_count - 6
    return totals


_CLAIM_PATTERNS = (
    re.compile(
        r"(?:我是|我跳|我也跳|我才是|我直接跳|我悍跳|我抢跳|我这边是|我这里是|我这儿是|"
        r"我确实是|我就是|我是真|我起跳|我认|我报|我预言家)\s*"
        r"(?:一个|个|张|真的|真)?\s*(预言家|女巫|猎人|平民|民|狼人|狼)"
    ),
    re.compile(
        r"我\s*\d{1,2}\s*号[，,：:\s]*(?:是|跳|也跳|才是|还是|直接跳|悍跳|抢跳)?\s*"
        r"(?:一个|个|张|真的|真)?\s*(预言家|女巫|猎人|平民|民|狼人|狼)"
    ),
    re.compile(
        r"我[^。！？!?；;\n]{0,12}?(?:才是|也是|就是|真是|还是|也跳|直接跳|悍跳|抢跳)\s*"
        r"(?:一个|个|张|真的|真)?\s*(预言家|女巫|猎人|平民|民|狼人|狼)"
    ),
    re.compile(r"我(?:预言家|女巫|猎人|平民|民|狼人|狼)"),
)
_SEAT_RE = re.compile(r"(\d{1,2})\s*号")
_PAST_MARKERS = (
    "昨天", "昨晚", "之前", "生前", "遗言", "上一轮", "上一夜", "当时", "说过", "投过",
    "出局", "死了", "已死", "被刀", "被毒", "被投", "验过", "自称", "他说", "她说",
)
_DEAD_ACTION_RE = re.compile(
    r"(?:让|问|等|听|跟|看|要|叫|催|求)\s*(\d{1,2})\s*号|"
    r"(\d{1,2})\s*号[^。！？!?；;\n]{0,16}(?:今晚|今天|后面|验人|报验|发言|说句话|聊|带队|"
    r"还活着|还在|是死是活|出来|跳身份|归票|看验人|听[^。！？]{0,6}验)"
)
_FLIP_RE = re.compile(
    r"(?:翻牌|翻身份|翻民|翻村民|开出|出局身份)[^。！？!?；;\n]{0,8}(?:是|为)?[^。！？!?；;\n]{0,4}(?:民|村民|狼人|狼|预言家|女巫|猎人|好人)|"
    r"(?:出局|投出去|被投出)[^。！？!?；;\n]{0,8}(?:是|为)[^。！？!?；;\n]{0,4}(?:民|村民|狼人|狼|预言家|女巫|猎人|好人)"
)
_SELF_HIDE_RE = re.compile(r"(?:先藏着|别刀我|别急着拍|不暴露|藏一下|先不拍)")
_SELF_EXPOSE_RE = re.compile(r"(?:我|本人)\s*(?:就|是|认|真是)?\s*(?:狼人|狼)(?:[，。！？!?；;\s]|$)|我认了[^。！？!?；;]{0,6}狼")
_WAIT_RE = re.compile(r"(?:先听|别急|不站边|先过|票先攥着|再听|等预言家|先看着)")
_POTION_EMPTY_RE = re.compile(r"(?:药没了|没药了|两瓶都用完|药都用完|没有药了)")
_ACCUSE_PATTERNS = (
    re.compile(r"(?:投|票|出|归|踩|怀疑|查杀|毒|打|冲|推)[^。！？!?；;\n]{0,8}?(\d{1,2})\s*号"),
    re.compile(r"(\d{1,2})\s*号[^。！？!?；;\n]{0,6}?(?:被查杀|是狼|像狼|为狼|就是狼|肯定是狼|大概率是狼|狼坑)"),
    re.compile(r"(\d{1,2})\s*号[^。！？!?；;\n]{0,6}?(?:有问题|可疑|狼面|狼味|不对劲)"),
    re.compile(r"(?:不信|不认|不站|不保)\s*(\d{1,2})\s*号"),
)
_POSITIVE_PATTERNS = (
    re.compile(r"(?:金水|保|认好|认下|信任)\s*(?:给|在|到|掉)?\s*(\d{1,2})\s*号"),
    re.compile(r"(\d{1,2})\s*号\s*(?:是|为)?\s*(?:好人|金水|不像狼|不是狼|没问题|可以保)"),
)


def _clip(text, limit):
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for mark in "。！？!?；;，,":
        pos = cut.rfind(mark)
        if pos >= limit * 0.55:
            return cut[:pos + 1]
    return cut


def _seat_label(seat, name):
    return "%d号 %s" % (seat, name) if name else "%d号" % seat

_CN_SEATS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _seat_int(value):
    """Parse a model-provided seat number without rejecting “5号” strings."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    text = unicodedata.normalize("NFKC", str(value))
    match = re.search(r"\d{1,2}", text)
    if match:
        return int(match.group())
    for char in text:
        if char in _CN_SEATS:
            return _CN_SEATS[char]
    return None


class GameStopped(RuntimeError):
    """Raised at a checkpoint when the user stops the simulation mid-game."""


class Agent:
    def __init__(self, player, role, seat, is_variable):
        self.player = player
        self.role = role
        self.seat = seat
        self.name = player.get("name") or "无名"
        self.mbti = (player.get("mbti") or "ISTJ").upper()
        self.params = player.get("params") or mbti_mod.params_for(self.mbti)
        self.persona = player.get("persona") or ""
        self.camp = ROLE_DEFS[role]["camp"]
        self.is_variable = bool(is_variable)
        self.alive = True
        self.death_cause = None
        self.death_round = None
        self.checks = []
        self.potions = {"antidote": True, "poison": True}
        self.suspicion = {}
        self.tokens = 0
        self.claims = []
        self.plan = None
        self.round_speech = None
        self.last_vote_target = None

    @property
    def max_words(self):
        return mbti_mod.max_words(self.params)

    @property
    def role_name(self):
        return ROLE_DEFS[self.role]["name"]

    @property
    def camp_name(self):
        return "狼人阵营" if self.camp == "wolf" else "好人阵营"

    def card(self):
        return {
            "seat": self.seat,
            "name": self.name,
            "role": self.role,
            "role_name": self.role_name,
            "camp": self.camp,
            "mbti": self.mbti,
            "type_name": mbti_mod.type_name(self.mbti),
            "is_variable": self.is_variable,
            "age": self.player.get("age"),
            "gender": self.player.get("gender"),
            "province": self.player.get("province"),
            "occupation": self.player.get("occupation"),
            "params": self.params,
            "alive": self.alive,
            "death_cause": self.death_cause,
            "death_round": self.death_round,
            "checks": list(self.checks),
            "claims": list(self.claims),
        }


class GameEngine:
    def __init__(self, players_by_role, variable_roles, variable_type, seed,
                 checkpoint=None, on_event=None, player_count=None):
        self.players_by_role = players_by_role
        self.variable_roles = dict(variable_roles or {})
        self.variable_type = variable_type
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.checkpoint = checkpoint
        self.on_event = on_event
        supplied = sum(len(players_by_role.get(role) or []) for role in ROLE_ORDER)
        self.player_count = int(player_count or supplied or 9)
        if self.player_count not in BOARD_SIZES:
            raise ValueError("玩家人数只能是 9 或 10 人")
        self.round = 1
        self.events = []
        self.public_log = []
        self.round_summaries = []
        self.agents = []
        self.seat_map = {}
        self.tokens = 0
        self.degenerate = False
        self.errors = []
        self.winner = None
        self.win_reason = None
        self.last_death_seat = None
        self.next_start = 1
        self.last_vote_counts = {}
        self.wolf_plan = None
        self.wolf_chat = []
        self._systems = {}
        self._token_lock = threading.Lock()
        self._build()

    # ------------------------------------------------------------------ setup
    def _build(self):
        totals = role_totals(self.player_count)
        slots = []
        for role in ROLE_ORDER:
            players = list(self.players_by_role.get(role) or [])
            expected = totals[role]
            if len(players) != expected:
                raise ValueError("%s 需要 %d 名玩家，收到 %d 名" % (ROLE_DEFS[role]["name"], expected, len(players)))
            for player in players:
                slots.append((role, player))
        if len(slots) != self.player_count:
            raise ValueError("一局必须有 %d 名玩家，当前 %d 名" % (self.player_count, len(slots)))
        self.rng.shuffle(slots)
        for index, (role, player) in enumerate(slots, 1):
            is_variable = bool(player.get("_is_variable"))
            agent = Agent(player, role, index, is_variable)
            self.agents.append(agent)
            self.seat_map[index] = agent
        for agent in self.agents:
            agent.suspicion = {other.seat: 0.0 for other in self.agents if other.seat != agent.seat}
            if agent.camp == "wolf":
                for other in self.agents:
                    if other.camp == "wolf" and other.seat != agent.seat:
                        agent.suspicion[other.seat] = -10.0
        self._record({
            "type": "game_start",
            "round": 0,
            "public": "%d 名玩家入座，游戏开始。" % self.player_count,
            "players": [agent.card() for agent in self.agents],
            "variable_type": self.variable_type,
            "variable_roles": self.variable_roles,
            "player_count": self.player_count,
            "seed": self.seed,
        })

    def alive(self):
        return [a for a in self.agents if a.alive]

    def alive_by(self, camp=None, role=None, exclude=None):
        out = []
        for agent in self.agents:
            if not agent.alive:
                continue
            if camp and agent.camp != camp:
                continue
            if role and agent.role != role:
                continue
            if exclude and agent.seat == exclude:
                continue
            out.append(agent)
        return out

    def by_seat(self, seat):
        return self.seat_map.get(int(seat))

    # --------------------------------------------------------------- prompts
    def _system(self, agent):
        if agent.seat in self._systems:
            return self._systems[agent.seat]
        notes = mbti_mod.param_notes(agent.params)
        persona = agent.persona or "%s，%s岁，%s，%s。" % (
            agent.name, agent.player.get("age"), agent.player.get("occupation"),
            agent.player.get("province"))
        villagers = role_totals(self.player_count)["villager"]
        system = (
            "你正在参加一场 %d 人狼人杀游戏，必须完全以这个人物身份思考和说话。\n\n"
            "【你的人物】\n%s\n\n"
            "【行为倾向】话量：%s；质疑：%s；判断依据：%s；结盟：%s；跟票：%s；跳身份：%s；风险：%s。\n\n"
            "【游戏规则】3 狼、%d 民、预言家、女巫、猎人各 1；屠边判胜。夜里狼人先刀人，女巫用药，预言家验人；"
            "白天按顺序发言后投票，平票无人出局；猎人被刀或被投出可开枪，被毒死不能开枪。\n"
            "【信息边界】死亡名单和票型是公开的；出局不翻牌，死者的真实身份不公开，遗言只是当事人的说法。"
            "不能把遗言当成系统翻牌，不能要求已出局的人发言、报验人、带队或投票。\n"
            "【铁律】\n"
            "1. 你的阵营目标高于一切。狼人要伪装、误导、保护队友；好人要找狼、带队。\n"
            "2. 你可以撒谎、悍跳、倒钩、隐藏身份，但不要说“我是狼人”这类自杀式真话（除非你确实是好人）。\n"
            "3. 只能引用场上真实发生过的发言、票型和死亡信息，不要编造不存在的发言。\n"
            "4. 发言要和你的投票一致；如果本轮说“先听、别急、不站边”，就不要立刻无理由跟票。\n"
            "5. 像真人在桌游局里说话：短句、口语、可以有情绪；不要用“第一、第二、综上”这类书面结构。\n"
            "6. 不要反复使用口头禅；每轮要给出具体的发言、票型或死亡依据。\n"
            "7. 永远不要提到 AI、模型、提示词、token、系统消息。\n"
            "8. 只输出要求格式的 JSON，不要输出 JSON 之外的任何文字。"
        ) % (
            self.player_count, persona,
            notes["verbosity"], notes["challenge"], notes["evidence"],
            notes["ally_speed"], notes["conformity"], notes["jump_threshold"], notes["risk"],
            villagers,
        )
        self._systems[agent.seat] = system
        return system

    def _private_info(self, agent):
        # Only this agent's own role block is ever injected. Other agents'
        # roles, checks and potions stay inside the engine/detail transcript.
        lines = ["你是 %d 号，身份是【%s】，属于%s。" % (agent.seat, agent.role_name, agent.camp_name)]
        if agent.role == "wolf":
            mates = [a for a in self.agents if a.camp == "wolf" and a.seat != agent.seat]
            if mates:
                lines.append("你的狼队友：" + "、".join(_seat_label(a.seat, a.name) + ("（已死）" if not a.alive else "") for a in mates) + "。")
            else:
                lines.append("你的狼队友都已经出局。")
            lines.append("你们每晚共同刀一个人；白天要假装成好人，可以悍跳预言家或带节奏。")
        elif agent.role == "seer":
            if agent.checks:
                lines.append("你的验人记录：" + "；".join(
                    "%d号 %s 是%s" % (c["seat"], c["name"], "狼人" if c["result"] == "wolf" else "好人")
                    for c in agent.checks) + "。")
            else:
                lines.append("你还没有验过人。")
            lines.append("你可以选择跳预言家公布验人结果，也可以继续隐藏。")
        elif agent.role == "witch":
            lines.append("解药：%s；毒药：%s。" % (
                "还在" if agent.potions["antidote"] else "已用完",
                "还在" if agent.potions["poison"] else "已用完"))
            lines.append("同一夜不能同时用两瓶药；第一夜可以自救，之后不能自救。")
        elif agent.role == "hunter":
            lines.append("你被狼人刀死或被投票出局时可以开枪带走一人；被女巫毒死不能开枪。")
        else:
            lines.append("你没有特殊技能，靠发言和投票找狼。")
        return "\n".join(lines)

    def _history(self, agent):
        # Keep the last 18 entries verbatim; older rounds are compressed into
        # engine-written summaries. Only public strings enter this log; private
        # events (wolf choices, seer checks, potions) are never appended here.
        # The full transcript stays in the game detail for the post-game drawer.
        if len(self.public_log) <= 24:
            return "【场上已发生】\n" + "\n".join(self.public_log)
        parts = ["【前情摘要】"] + self.round_summaries[-5:]
        parts.append("【最近发生】")
        parts.extend(self.public_log[-18:])
        return "\n".join(parts)

    def _round_speech_digest(self):
        """A compact, structured digest of every speech in the current day.

        The raw public log is already sent to the model, but models can lose
        track of who claimed what in a long transcript. This digest is injected
        into the vote prompt so every voter sees the same current-day claims,
        accusations and stated vote intentions.
        """
        lines = []
        claims = []
        for event in self.events:
            if event.get("round") != self.round or event.get("type") != "speech":
                continue
            seat = event.get("seat")
            text = _clip(event.get("text") or "", 180)
            claimed = event.get("claimed_role")
            accused = event.get("accused") or []
            intent = event.get("vote_intent")
            tags = []
            if claimed:
                tags.append("声称%s" % claimed)
                claims.append("%d号→%s" % (seat, claimed))
            if accused:
                tags.append("指认%s" % "、".join("%d号" % s for s in accused))
            if intent:
                tags.append("倾向投%d号" % intent)
            suffix = ("（%s）" % "；".join(tags)) if tags else ""
            lines.append("%d号：%s%s" % (seat, text, suffix))
        if not lines:
            return ""
        parts = ["【本轮发言摘要（必须据此投票）】"]
        parts.extend(lines)
        if claims:
            parts.append("【本轮身份声明】" + "、".join(claims))
        return "\n".join(parts)

    def _state_block(self, agent):
        alive = self.alive()
        dead = [a for a in self.agents if not a.alive]
        alive_text = "、".join(_seat_label(a.seat, a.name) for a in alive) or "无人"
        dead_text = "、".join(
            "%s（第%d轮%s）" % (
                _seat_label(a.seat, a.name), a.death_round or 0,
                "被毒" if a.death_cause == "poison" else "被枪" if a.death_cause == "shot"
                else "被投" if a.death_cause == "vote" else "夜间出局")
            for a in dead) or "无"
        lines = [
            "【当前局面】现在是第 %d 轮，%s。" % (
                self.round, "白天发言阶段" if self._is_daytime() else "夜间行动阶段"),
            "【存活玩家】%s。" % alive_text,
            "【已出局】%s。" % dead_text,
            "【信息边界】出局不翻牌，以上出局者身份仍未知；遗言只是他们自己的说法，不是系统公开的身份。"
            "不要向出局者提问、要验人、要带队或等他们投票。",
        ]
        claims = []
        for player in self.agents:
            if player.claims:
                claim = player.claims[-1]
                claims.append("%d号第%d轮跳%s" % (player.seat, claim["round"], claim["role"]))
        if claims:
            lines.append("【公开跳身份】%s。" % "；".join(claims[-6:]))
        if self.last_vote_counts:
            vote_text = "、".join(
                "%d号%d票" % (seat, count)
                for seat, count in sorted(self.last_vote_counts.items(), key=lambda kv: (-kv[1], kv[0])))
            lines.append("【上一轮票型】%s。" % vote_text)
        return "\n".join(lines)

    def _is_daytime(self):
        # Events are appended before each action; the last phase marker is the
        # most reliable indication and avoids coupling prompts to call order.
        for event in reversed(self.events):
            if event.get("type") == "day":
                return True
            if event.get("type") == "night":
                return False
        return True

    def _wolf_plan_text(self, agent):
        if agent.role != "wolf" or not self.wolf_plan:
            return ""
        plan = self.wolf_plan
        target = plan.get("target")
        target_text = _seat_label(target, self.seat_map[target].name) if target in self.seat_map else "未定"
        lines = [
            "【狼队夜间计划】昨晚狼队决定刀 %s。" % target_text,
            "白天策略：%s" % (plan.get("plan") or "先观察，找机会带节奏。"),
        ]
        if plan.get("fake_claim"):
            lines.append("狼队安排：%s 负责悍跳 %s。你要配合，不要拆队友的台。"
                         % (plan.get("fake_claim_seat") or "一名狼队友", plan.get("fake_claim")))
        return "\n".join(lines)

    def _suspicion_text(self, agent):
        others = [a for a in self.alive() if a.seat != agent.seat]
        if not others:
            return "【你的怀疑排序】没有其他存活玩家。"
        ranked = sorted(others, key=lambda a: (-agent.suspicion.get(a.seat, 0), a.seat))
        top = ranked[:3]
        trusted = sorted(ranked, key=lambda a: (agent.suspicion.get(a.seat, 0), a.seat))[:2]
        def label(a):
            score = agent.suspicion.get(a.seat, 0)
            tag = "高" if score >= 2 else ("中" if score >= 0.5 else ("低" if score > -1 else "信任"))
            return "%s（%s）" % (_seat_label(a.seat, a.name), tag)
        text = "【你的怀疑排序】最怀疑：" + "、".join(label(a) for a in top)
        if trusted and trusted[0].seat not in [a.seat for a in top]:
            text += "；相对信任：" + "、".join(_seat_label(a.seat, a.name) for a in trusted)
        return text

    def _checkpoint(self):
        if self.checkpoint:
            self.checkpoint()

    def _call(self, agent, user, max_tokens=320, temperature=0.85):
        try:
            obj, usage = llm.chat_json(
                self._system(agent), user, max_tokens=max_tokens,
                temperature=temperature, effort="none", timeout=90, retries=1,
            )
            tokens = int(usage.get("total_tokens") or 0)
            with self._token_lock:
                agent.tokens += tokens
                self.tokens += tokens
            return obj, tokens, None
        except llm.LLMConfigError:
            raise
        except Exception as exc:
            self.errors.append({"seat": agent.seat, "error": str(exc)[:240]})
            return None, 0, exc

    # --------------------------------------------------------------- recording
    def _record(self, event, public=None):
        event = dict(event)
        event.setdefault("round", self.round)
        if public:
            event["public"] = public
            self.public_log.append(public)
        self.events.append(event)
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                pass

    def _summarize_round(self):
        deaths = []
        focus = {}
        vote_text = ""
        for event in reversed(self.events):
            if event.get("round") != self.round:
                break
            if event["type"] == "dawn":
                deaths = [d["seat"] for d in event.get("deaths") or []]
            if event["type"] == "speech":
                for seat in event.get("accused") or []:
                    focus[seat] = focus.get(seat, 0) + 1
            if event["type"] == "vote":
                vote_text = event.get("summary") or ""
        bits = ["第%d轮" % self.round]
        bits.append("夜里死亡：" + ("、".join("%d号" % s for s in deaths) if deaths else "无人"))
        if focus:
            top = sorted(focus.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
            bits.append("发言焦点：" + "、".join("%d号" % s for s, _ in top))
        if vote_text:
            bits.append(vote_text)
        self.round_summaries.append("；".join(bits) + "。")

    # ------------------------------------------------------------------ actions
    def _speak(self, agent):
        self._checkpoint()
        if agent.role == "seer":
            wolf_checks = [c for c in agent.checks if c["result"] == "wolf"]
            if wolf_checks:
                guidance = "你是预言家：你已经验到查杀，今天优先跳预言家，报清楚验人和查杀，带队投狼。"
            elif agent.checks:
                dead_checks = [c for c in agent.checks if c["seat"] in self.seat_map and not self.seat_map[c["seat"]].alive]
                if dead_checks:
                    guidance = "你是预言家：你验的人已经出局，金水对活人排坑的价值有限；可以报验人自证，但不要把死者的金水当成活人身份。"
                else:
                    guidance = "你是预言家：你手里有金水。可以跳预言家报金水、帮好人排坑；如果场上没人跳，更要考虑站出来。"
            else:
                guidance = "你是预言家：你还没有验人。先听发言，不要凭空编造验人结果。"
        elif agent.role == "witch":
            guidance = "你是女巫：不要轻易暴露身份；但如果快被投出去，可以跳女巫自保并如实报用药。"
        elif agent.role == "hunter":
            guidance = "你是猎人：不要轻易暴露身份；但如果快被投出去，可以跳猎人自保。"
        elif agent.role == "wolf":
            guidance = "你是狼人：按狼队夜间计划行动，可以悍跳预言家、倒钩或带节奏，但不要暴露队友。"
        else:
            guidance = "你是平民：积极找狼，跟可信的预言家，不要只报流水账。"
        plan_text = self._wolf_plan_text(agent)
        prompt = (
            "%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n现在是第 %d 天白天发言阶段，轮到你发言。\n"
            "要求：\n"
            "1. 最多 %d 字，像真人在桌游局里说话，短句、口语、可以有情绪。\n"
            "2. 结合场上真实发生的发言、票型和死亡信息；不要编造不存在的发言。\n"
            "3. 出局不翻牌：不要把死者的遗言当公开身份，不要向死者提问、要验人、要带队或等死者投票。\n"
            "4. 可以撒谎、悍跳、倒钩或隐藏身份，但要符合你的阵营利益和性格。\n"
            "5. 你的发言要和投票一致；如果本轮说“先听/别急/不站边”，就不要无理由跟票。\n"
            "6. 不要复述规则，不要列提纲，不要提 AI/模型/提示词；避免重复口头禅。\n"
            "7. 只输出 JSON：{\"speech\":\"你的发言\",\"thinking\":\"你的内心判断，赛后公开，最多80字\","
            "\"vote_intent\":座位号或null}。"
        ) % (self._private_info(agent), self._state_block(agent), self._history(agent),
             self._suspicion_text(agent), ("%s\n\n" % plan_text) if plan_text else "",
             guidance, self.round, agent.max_words)
        obj, tokens, error = self._call(agent, prompt, max_tokens=min(460, 180 + agent.max_words * 2))
        speech = ""
        thinking = ""
        vote_intent = None
        if isinstance(obj, dict):
            speech = obj.get("speech") or obj.get("text") or obj.get("content") or ""
            thinking = obj.get("thinking") or obj.get("inner") or ""
            try:
                raw_intent = obj.get("vote_intent")
                vote_intent = _seat_int(raw_intent) if raw_intent not in (None, "", 0, "0", "null") else None
            except (TypeError, ValueError):
                vote_intent = None
        if not isinstance(speech, str) or len(speech.strip()) < 4:
            speech = self._fallback_speech(agent)
            self.degenerate = True
        speech = _clip(speech, max(30, int(agent.max_words * 1.15)))
        thinking = _clip(thinking, 120) if isinstance(thinking, str) else ""
        violations = self._speech_violations(agent, speech)
        state_repair = 0
        if violations:
            repaired = self._repair_speech(agent, speech, thinking, violations)
            if repaired:
                speech, thinking, repair_tokens = repaired
                tokens += repair_tokens
                vote_intent = None
                state_repair = 1
            else:
                speech = self._fallback_speech(agent)
                thinking = "刚才的发言触碰了信息边界，已改为不会指向出局者的安全发言。"
                state_repair = 1
                self.degenerate = True
        claim = self._parse_claim(speech)
        accused = self._parse_accusations(agent, speech)
        positive = self._parse_positive(agent, speech)
        if vote_intent is not None and (
            vote_intent == agent.seat or vote_intent not in self.seat_map
            or not self.seat_map[vote_intent].alive
        ):
            vote_intent = None
        if vote_intent is None and accused:
            vote_intent = accused[0]
        if _WAIT_RE.search(speech) and not accused:
            vote_intent = None
        if claim:
            agent.claims.append({"round": self.round, "role": claim})
        self._update_suspicion_from_speech(agent, accused, positive, claim, speech)
        agent.round_speech = {
            "round": self.round,
            "speech": speech,
            "thinking": thinking,
            "claim": claim,
            "accused": list(accused),
            "positive": list(positive),
            "vote_intent": vote_intent,
        }
        self._record({
            "type": "speech",
            "round": self.round,
            "seat": agent.seat,
            "name": agent.name,
            "role": agent.role,
            "role_name": agent.role_name,
            "camp": agent.camp,
            "mbti": agent.mbti,
            "text": speech,
            "thinking": thinking or "本轮没有记录内心独白。",
            "claimed_role": claim,
            "accused": accused,
            "vote_intent": vote_intent,
            "state_repair": state_repair,
            "constraint_notes": violations,
            "tokens": tokens,
            "fallback": bool(error),
        }, public="第%d天 · %s：%s" % (self.round, _seat_label(agent.seat, agent.name), speech))
        return speech

    def _parse_claim(self, text):
        text = text or ""
        for pattern in _CLAIM_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            role = match.group(1) if match.groups() else match.group(0)[1:]
            prefix = text[max(0, match.start() - 6):match.start()]
            if any(word in prefix for word in ("不是", "不跳", "不认", "别")):
                continue
            return {"民": "平民", "狼": "狼人"}.get(role, role)
        return None

    def _speech_violations(self, agent, text):
        """Hard information-boundary checks that are cheap and deterministic."""
        issues = []
        clauses = re.split(r"[。！？!?；;\n]", text or "")
        dead = [a for a in self.agents if not a.alive]
        for clause in clauses:
            if not clause.strip():
                continue
            if any(marker in clause for marker in _PAST_MARKERS):
                continue
            for victim in dead:
                if ("%d号" % victim.seat) not in clause:
                    continue
                if _DEAD_ACTION_RE.search(clause):
                    issues.append("%d号已经出局，不能要求他发言/验人/带队" % victim.seat)
                    break
                role_claim = re.search(
                    r"%d\s*号[^。！？!?；;\n]{0,8}?(?:是|为|翻牌|翻身份|翻民|翻村民)"
                    r"[^。！？!?；;\n]{0,4}(?:民|村民|狼人|狼|预言家|女巫|猎人|好人)"
                    % victim.seat, clause)
                if role_claim:
                    issues.append("%d号已经出局，不能把遗言或猜测当成公开身份" % victim.seat)
                    break
        if _FLIP_RE.search(text or ""):
            issues.append("不能把出局者的遗言当成系统翻牌")
        claim = self._parse_claim(text or "")
        if claim == "狼人" or _SELF_EXPOSE_RE.search(text or ""):
            issues.append("不能自曝狼人身份")
        if claim and _SELF_HIDE_RE.search(text or ""):
            issues.append("刚报了身份又说要藏着，前后矛盾")
        if agent.role == "witch" and _POTION_EMPTY_RE.search(text or ""):
            if agent.potions.get("antidote") or agent.potions.get("poison"):
                issues.append("你还有药，不能谎报药已经用完")
        return list(dict.fromkeys(issues))

    def _repair_speech(self, agent, speech, thinking, issues):
        self._checkpoint()
        prompt = (
            "%s\n\n%s\n\n%s\n\n你刚才准备说：“%s”\n"
            "这句话违反了信息边界：%s。\n"
            "请重写这段发言，保留你的阵营策略和人物语气，但必须遵守：出局不翻牌；不要求已出局者发言/验人/带队；"
            "不自曝狼人；刚报身份就不要又说藏着；女巫报药必须和真实药水状态一致。"
            "不要解释规则，只输出 JSON：{\"speech\":\"重写后的发言\",\"thinking\":\"重写后的内心判断\","
            "\"vote_intent\":座位号或null}。"
        ) % (
            self._private_info(agent), self._state_block(agent), self._history(agent),
            speech, "；".join(issues),
        )
        obj, tokens, _error = self._call(agent, prompt, max_tokens=min(420, 180 + agent.max_words * 2))
        if not isinstance(obj, dict):
            return None
        fixed = obj.get("speech") or obj.get("text") or ""
        if not isinstance(fixed, str) or len(fixed.strip()) < 4:
            return None
        fixed = _clip(fixed, max(30, int(agent.max_words * 1.15)))
        if self._speech_violations(agent, fixed):
            return None
        fixed_thinking = obj.get("thinking") or thinking or "已按信息边界重写。"
        return fixed, _clip(str(fixed_thinking), 120), tokens

    def _fallback_speech(self, agent):
        suspects = sorted(
            [a for a in self.alive() if a.seat != agent.seat],
            key=lambda a: (-agent.suspicion.get(a.seat, 0), a.seat),
        )
        if not suspects:
            return "我没更多信息了，听大家的。"
        target = suspects[0]
        options = [
            "我先听一圈。%s刚才的说法我有点在意，等会儿重点看他。" % _seat_label(target.seat, target.name),
            "我暂时没有特别确定的人，%s的发言让我不太舒服，先记一笔。" % _seat_label(target.seat, target.name),
            "场上信息还不多，我先保留意见，%s号后面多说点。" % target.seat,
        ]
        return self.rng.choice(options)

    @staticmethod
    def _negated_verb(clause, start):
        prefix = clause[max(0, start - 5):start]
        return any(word in prefix for word in ("别", "不要", "没", "不", "保", "免"))

    def _parse_accusations(self, agent, text):
        """Extract only semantic suspicion targets, not every seat in a clause.

        The old keyword parser tagged both the subject and the object of a
        sentence when words like “悍跳” appeared. That is why a sentence about
        1号 could show “指认 1号、2号” while the actual vote was 2号. Here each
        pattern captures the grammatical object, and negated verbs are skipped.
        """
        alive_seats = {a.seat for a in self.alive()}
        accused = []
        for clause in re.split(r"[。！？!?；;\n]", text or ""):
            if not clause.strip():
                continue
            if (re.search(r"(?:谁|如果|要是|若).{0,6}(?:踩|投|出|冲|打|推)", clause)
                    and re.search(r"(?:不跟|不站|不投|不认|保)", clause)):
                continue
            for pattern in _ACCUSE_PATTERNS:
                for match in pattern.finditer(clause):
                    if self._negated_verb(clause, match.start()):
                        continue
                    seat = int(match.group(1))
                    if re.search(r"%d\s*号\s*(?:不是|不像|未必是|不一定是)" % seat, clause):
                        continue
                    if seat in alive_seats and seat != agent.seat and seat not in accused:
                        accused.append(seat)
        return accused

    def _parse_positive(self, agent, text):
        alive_seats = {a.seat for a in self.alive()}
        positive = []
        for clause in re.split(r"[。！？!?；;\n]", text or ""):
            if not clause.strip():
                continue
            for pattern in _POSITIVE_PATTERNS:
                for match in pattern.finditer(clause):
                    if self._negated_verb(clause, match.start()):
                        continue
                    seat = int(match.group(1))
                    if re.search(r"%d\s*号\s*(?:不是|不像|未必是|不一定是)" % seat, clause):
                        continue
                    if seat in alive_seats and seat != agent.seat and seat not in positive:
                        positive.append(seat)
        # "验了 8 号，是好人" can span a comma, which the clause splitter
        # otherwise separates into two fragments.
        for match in re.finditer(
                r"验(?:了|过)?\s*(\d{1,2})\s*号[^。！？!?；;\n]{0,10}(?:是|为)?\s*(?:好人|金水)",
                text or ""):
            seat = int(match.group(1))
            if seat in alive_seats and seat != agent.seat and seat not in positive:
                positive.append(seat)
        return positive

    def _update_suspicion_from_speech(self, speaker, accused, positive, claim, text):
        prior_seer_claims = [a for a in self.alive() if any(c["role"] == "预言家" for c in a.claims)]
        for listener in self.alive():
            if listener.seat == speaker.seat:
                continue
            weight = 0.35
            if listener.params.get("evidence", 0.5) >= 0.65:
                weight += 0.15
            if listener.params.get("conformity", 0.5) >= 0.65:
                weight += 0.08
            if claim == "预言家":
                weight += 0.35
            # A listener who already distrusts the speaker discounts that
            # speaker's accusations; this stops a wolf from steering the table
            # simply by naming good players.
            suspicion_of_speaker = listener.suspicion.get(speaker.seat, 0)
            credibility = max(0.3, min(1.25, 1.0 - suspicion_of_speaker / 12.0))
            weight *= credibility
            for seat in accused:
                if listener.camp == "wolf" and self.seat_map[seat].camp == "wolf":
                    continue
                listener.suspicion[seat] = min(10.0, listener.suspicion.get(seat, 0) + weight)
            for seat in positive:
                if listener.camp == "wolf" and self.seat_map[seat].camp == "wolf":
                    continue
                listener.suspicion[seat] = max(-10.0, listener.suspicion.get(seat, 0) - 0.18)
            # A second seer claim makes both claimants suspicious to onlookers.
            if claim == "预言家" and prior_seer_claims:
                for claimant in prior_seer_claims:
                    if claimant.seat != speaker.seat and claimant.camp != listener.camp:
                        listener.suspicion[claimant.seat] = min(10.0, listener.suspicion.get(claimant.seat, 0) + 0.25)
        # A claimed seer's structured kill/clear statement carries more
        # weight. Use the semantic targets instead of every seat number in the
        # clause, so a sentence about the claimant does not become a check.
        if claim == "预言家":
            for listener in self.alive():
                if listener.seat == speaker.seat:
                    continue
                for seat in accused:
                    if seat in listener.suspicion:
                        listener.suspicion[seat] = min(10.0, listener.suspicion[seat] + 2.0)
                for seat in positive:
                    if seat in listener.suspicion:
                        listener.suspicion[seat] = max(-10.0, listener.suspicion[seat] - 1.0)

    def _current_seer_claims(self):
        claims = []
        for event in self.events:
            if event.get("round") == self.round and event.get("type") == "speech":
                if event.get("claimed_role") == "预言家" and event.get("seat") not in claims:
                    claims.append(event.get("seat"))
        return claims

    def _vote(self, agent):
        self._checkpoint()
        candidates = [a for a in self.alive() if a.seat != agent.seat]
        if not candidates:
            return None, 0, False, "", "no_candidates"
        speech = agent.round_speech or {}
        stated = speech.get("vote_intent")
        if stated not in {a.seat for a in candidates}:
            stated = None
        accused = [s for s in (speech.get("accused") or []) if s in {a.seat for a in candidates}]
        if stated:
            commitment = "你本轮发言时表示要投 %d 号。" % stated
        elif accused:
            commitment = "你本轮发言中怀疑 %s；投票要与这个判断一致。" % "、".join("%d号" % s for s in accused)
        elif _WAIT_RE.search(speech.get("speech") or "") and not accused:
            commitment = "你本轮发言说先听/别急/不站边，且没有点人。你可以投 null 弃票，不要无理由立刻跟票。"
        else:
            commitment = "你本轮没有明确点人，请按自己的怀疑排序投票。"
        if agent.camp == "good":
            seer_claims = self._current_seer_claims()
            if len(seer_claims) == 1:
                role_hint = (
                    "你是好人：场上只有 %d 号声称预言家。除非他的验人/发言有明确矛盾，"
                    "首日不要仅因为“跳得早”投他；把票投给其他更可疑的人。"
                    % seer_claims[0]
                )
            elif len(seer_claims) > 1:
                role_hint = (
                    "你是好人：场上有 %s 对跳预言家。比较验人逻辑和发言，不要只因为谁先跳就投谁。"
                    % "、".join("%d号" % s for s in seer_claims)
                )
            else:
                role_hint = "你是好人：优先跟可信的预言家查杀；如果没有明确查杀，投你最怀疑的人。"
        else:
            role_hint = "你是狼人：尽量把票投给好人，必要时可以牺牲队友做身份，但不要暴露狼队。"
        prompt = (
            "%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n现在是投票阶段，存活玩家：%s。\n"
            "%s你的跟票倾向：%s。%s投给一名存活玩家，不能投自己。"
            "必须基于上面的本轮发言摘要投票，不得声称“还没听到别人发言”或忘记已经发生的发言；"
            "如果改票，必须在 reason 里说明改票理由；如果你本轮说先听且没有点人，可以输出 null 弃票。"
            "只输出 JSON：{\"target\": 座位号或null, \"reason\":\"一句话投票理由\"}。"
        ) % (
            self._private_info(agent), self._state_block(agent), self._history(agent),
            self._round_speech_digest(), self._suspicion_text(agent),
            "、".join("%d号" % a.seat for a in self.alive()),
            commitment,
            "较高，拿不准时可以跟随多数" if agent.params.get("conformity", 0.5) >= 0.65 else "较低，坚持自己的判断",
            role_hint,
        )
        obj, tokens, error = self._call(agent, prompt, max_tokens=110, temperature=0.65)
        target, has_target, reason = self._parse_vote_answer(obj, candidates)
        fallback = False
        if not has_target:
            if stated:
                target, reason = stated, "目标解析失败，按本轮承诺投票。"
            elif accused:
                target, reason = accused[0], "目标解析失败，按本轮怀疑对象投票。"
            elif _WAIT_RE.search(speech.get("speech") or ""):
                target, reason = None, "本轮说先听，选择弃票。"
            else:
                target = self._fallback_vote(agent, candidates)
                reason = "信息不足，按怀疑排序投票。"
            fallback = True
            self.degenerate = True
        elif target is not None and (target == agent.seat or target not in self.seat_map
                                     or not self.seat_map[target].alive
                                     or target not in candidates):
            # The model sometimes returns “4号”/“四号” or the wrong field. Parse
            # that above; if it still is not a live seat, ask once for a bare
            # integer before falling back to the deterministic suspicion order.
            retry_prompt = (
                "%s\n\n%s\n\n你刚才返回的投票目标无法识别为存活座位号。"
                "存活玩家：%s。请只输出一个整数座位号（不能投自己），"
                "格式：{\"target\": 整数或null,\"reason\":\"一句话理由\"}。"
            ) % (
                self._private_info(agent), self._state_block(agent),
                "、".join("%d号" % a.seat for a in candidates),
            )
            obj_r, tokens_r, error_r = self._call(agent, retry_prompt, max_tokens=90, temperature=0.4)
            tokens += tokens_r
            error = error or error_r
            target_r, has_r, reason_r = self._parse_vote_answer(obj_r, candidates)
            if has_r and (target_r is None or target_r in {a.seat for a in candidates}):
                target, reason = target_r, reason_r or "按重新确认的座位号投票。"
                fallback = False
            else:
                target = self._fallback_vote(agent, candidates)
                reason = "模型没有给出合法座位号，按怀疑排序投票。"
                fallback = True
                self.degenerate = True

        # One consistency repair: a speech that promised X should not silently
        # become Y, and an explicit “wait” should not become an unexplained
        # bandwagon. The second answer is still allowed to change its mind, but
        # it must give a reason.
        contradicted = bool(stated and target is not None and target != stated and len(reason) < 4)
        waited = bool(_WAIT_RE.search(speech.get("speech") or "") and not accused
                      and target is not None and len(reason) < 4)
        if contradicted or waited:
            retry = (
                "%s\n\n%s\n\n你本轮已经说过：“%s”\n"
                "你刚才选择了 %s，但没有给出改票理由。请重新决定：要么投回你承诺/怀疑的人，"
                "要么保留新目标并在 reason 里说明为什么改票；如果你本轮说先听且没有点人，也可以投 null。"
                "只输出 JSON：{\"target\": 座位号或null, \"reason\":\"一句话投票理由\"}。"
            ) % (
                self._private_info(agent), self._state_block(agent), speech.get("speech") or "",
                ("%d号" % target) if target is not None else "弃票",
            )
            obj2, tokens2, error2 = self._call(agent, retry, max_tokens=100, temperature=0.55)
            tokens += tokens2
            error = error or error2
            target2, has_target2, reason2 = self._parse_vote_answer(obj2, candidates)
            if has_target2:
                if target2 is None:
                    target, reason = None, reason2 or "本轮先听，选择弃票。"
                elif target2 in {a.seat for a in candidates}:
                    if stated and target2 != stated and len(reason2) < 4:
                        target, reason = stated, "改票理由未说明，按原承诺投回 %d号。" % stated
                    elif waited and len(reason2) < 4:
                        target, reason = None, "本轮说先听，选择弃票。"
                    else:
                        target, reason = target2, reason2 or "重新判断后改票。"
                else:
                    target, reason = stated or target, "改票目标不合法，按原判断投票。"
                fallback = False
        if target is not None and target not in {a.seat for a in candidates}:
            target = stated or self._fallback_vote(agent, candidates)
            reason = reason or "按原判断投票。"
        if target is not None and not reason:
            reason = "按本轮怀疑对象投票。" if not stated or target == stated else "改票：重新判断后投新目标。"
        if target is None:
            reason = reason or "本轮先听，选择弃票。"
        consistency = "consistent"
        if stated and target is not None and target != stated:
            consistency = "changed_with_reason" if len(reason) >= 4 else "inconsistent"
        elif _WAIT_RE.search(speech.get("speech") or "") and not accused and target is not None:
            consistency = "waited_then_voted"
        elif fallback:
            consistency = "fallback"
        return target, tokens, bool(error), _clip(reason, 60), consistency

    def _parse_vote_answer(self, obj, candidates):
        if not isinstance(obj, dict):
            return None, False, ""
        has_target = "target" in obj
        raw = obj.get("target")
        reason = obj.get("reason") or ""
        if raw in (None, "", "null", "None"):
            return None, has_target, str(reason)[:60]
        target = _seat_int(raw)
        if target is None:
            text = str(raw)
            for candidate in candidates:
                if candidate.name and candidate.name in text:
                    target = candidate.seat
                    break
        if target is None:
            return None, False, str(reason)[:60]
        return target, True, str(reason)[:60]

    def _fallback_vote(self, agent, candidates):
        if agent.params.get("conformity", 0.5) >= 0.65 and self.last_vote_counts:
            pool = [a for a in candidates if a.seat in self.last_vote_counts]
            if pool:
                top = max(self.last_vote_counts.get(a.seat, 0) for a in pool)
                pool = [a for a in pool if self.last_vote_counts.get(a.seat, 0) == top]
                return self.rng.choice(pool).seat
        ranked = sorted(candidates, key=lambda a: (-agent.suspicion.get(a.seat, 0), a.seat))
        best = ranked[0]
        tied = [a for a in ranked if agent.suspicion.get(a.seat, 0) == agent.suspicion.get(best.seat, 0)]
        return self.rng.choice(tied).seat

    def _wolf_plan(self, wolves, candidates):
        """One night-chat round: every wolf proposes, then a leader decides.

        The old engine had each wolf pick a target independently and took the
        plurality. That made coordinated fake claims and daytime plans
        impossible, so “等对跳” never arrived. This is still one kill, but the
        wolves now leave the night with a shared target, a fake-claim owner and
        a daytime strategy that they can execute in their speeches.
        """
        if not wolves or not candidates:
            return None
        candidate_text = "、".join(_seat_label(a.seat, a.name) for a in candidates)
        proposals = []

        def propose(wolf):
            prompt = (
                "%s\n\n%s\n\n%s\n\n现在是第 %d 夜，狼人商议刀人。存活好人：%s。\n"
                "请提出你的刀口，并给狼队一句夜间沟通：白天谁悍跳预言家、谁倒钩、是否编造查杀。"
                "只能刀存活好人，不能刀狼队友。只输出 JSON：{\"target\":座位号,"
                "\"message\":\"给狼队的一句话\",\"fake_claim\":\"预言家\"或null}。"
            ) % (
                self._private_info(wolf), self._state_block(wolf), self._history(wolf),
                self.round, candidate_text,
            )
            obj, tokens, error = self._call(wolf, prompt, max_tokens=130, temperature=0.7)
            target = None
            message = ""
            fake_claim = None
            if isinstance(obj, dict):
                target = _seat_int(obj.get("target"))
                message = str(obj.get("message") or "")[:120]
                fake_claim = obj.get("fake_claim")
                if fake_claim not in ("预言家", "女巫", "猎人", None, ""):
                    fake_claim = None
            valid = {a.seat for a in candidates}
            if target not in valid:
                ranked = sorted(candidates, key=lambda a: (-wolf.suspicion.get(a.seat, 0), a.seat))
                target = ranked[0].seat
                self.degenerate = True
            return {"seat": wolf.seat, "name": wolf.name, "target": target,
                    "message": message, "fake_claim": fake_claim or "",
                    "tokens": tokens, "fallback": bool(error)}

        with ThreadPoolExecutor(max_workers=min(3, len(wolves))) as pool:
            proposals = list(pool.map(propose, wolves))
        leader = max(wolves, key=lambda w: (
            w.params.get("challenge", 0.5) + w.params.get("risk", 0.5), -w.seat))
        proposal_text = "\n".join(
            "%d号：刀%d号；想法：%s；想骗的身份：%s" % (
                item["seat"], item["target"], item["message"] or "无", item["fake_claim"] or "无")
            for item in proposals)
        leader_prompt = (
            "%s\n\n%s\n\n%s\n\n狼队夜间讨论如下：\n%s\n\n"
            "你是狼队主心骨。请做最终决定：今晚刀谁、白天由谁悍跳什么身份、整体策略是什么。"
            "默认安排一名狼悍跳预言家并编造验人；只有你判断不跳明显更好时，才在 plan 里说明理由。"
            "注意：今晚刀的人天亮后会死，悍跳时不要把今晚刀口报成金水或查杀，金水/查杀要指向其他存活玩家。"
            "只能刀存活好人：%s。只输出 JSON：{\"target\":座位号,\"fake_claim\":\"预言家\"或null,"
            "\"fake_claim_seat\":座位号或null,\"plan\":\"一句白天策略\"}。"
        ) % (
            self._private_info(leader), self._state_block(leader), self._history(leader),
            proposal_text, candidate_text,
        )
        obj, leader_tokens, leader_error = self._call(
            leader, leader_prompt, max_tokens=150, temperature=0.55)
        target = None
        fake_claim = None
        fake_claim_seat = None
        plan = ""
        if isinstance(obj, dict):
            target = _seat_int(obj.get("target"))
            fake_claim = obj.get("fake_claim")
            if fake_claim not in ("预言家", "女巫", "猎人", None, ""):
                fake_claim = None
            fake_claim_seat = _seat_int(obj.get("fake_claim_seat"))
            plan = str(obj.get("plan") or "")[:160]
        valid = {a.seat for a in candidates}
        if target not in valid:
            tally = {}
            for item in proposals:
                tally[item["target"]] = tally.get(item["target"], 0) + 1
            top = max(tally.values())
            tied = [seat for seat, count in tally.items() if count == top]
            target = self.rng.choice(tied)
            self.degenerate = True
        if fake_claim_seat not in {w.seat for w in wolves}:
            fake_claim_seat = leader.seat if fake_claim else None
        if not plan:
            plan = "白天先观察真预言家的发言，必要时由 %d号悍跳，其他狼倒钩或冲票。" % (
                fake_claim_seat or leader.seat)
        total_tokens = sum(item["tokens"] for item in proposals) + leader_tokens
        plan_obj = {
            "target": target,
            "fake_claim": fake_claim,
            "fake_claim_seat": fake_claim_seat,
            "plan": plan,
            "leader": leader.seat,
            "proposals": proposals,
            "tokens": total_tokens,
        }
        for wolf in wolves:
            wolf.plan = plan_obj
        self.wolf_plan = plan_obj
        self._record({
            "type": "wolf_chat",
            "round": self.round,
            "proposals": proposals,
            "target": target,
            "fake_claim": fake_claim,
            "fake_claim_seat": fake_claim_seat,
            "plan": plan,
            "leader": leader.seat,
            "tokens": total_tokens,
            "fallback": bool(leader_error),
        })
        return target, plan_obj

    def _wolf_choice(self, wolf, candidates):
        self._checkpoint()
        prompt = (
            "%s\n\n%s\n\n%s\n\n现在是第 %d 夜，狼人商议刀人。存活好人：%s。\n"
            "你的风险偏好：%s。选择今晚要杀的好人，只输出 JSON：{\"target\": 座位号}。"
        ) % (
            self._private_info(wolf), self._state_block(wolf), self._history(wolf), self.round,
            "、".join("%s" % _seat_label(a.seat, a.name) for a in candidates),
            "较高，可以冒险刀关键位置" if wolf.params.get("risk", 0.5) >= 0.65 else "较低，优先稳妥目标",
        )
        obj, tokens, error = self._call(wolf, prompt, max_tokens=60, temperature=0.7)
        target = None
        if isinstance(obj, dict):
            target = _seat_int(obj.get("target"))
        valid = {a.seat for a in candidates}
        if target not in valid:
            ranked = sorted(candidates, key=lambda a: (-wolf.suspicion.get(a.seat, 0), a.seat))
            target = ranked[0].seat
            self.degenerate = True
        return target, tokens, bool(error)

    def _witch_action(self, victim):
        self._checkpoint()
        witch = next((a for a in self.alive() if a.role == "witch"), None)
        if not witch:
            return False, None
        if not witch.potions["antidote"] and not witch.potions["poison"]:
            return False, None
        victim_text = _seat_label(victim.seat, victim.name) if victim else "无人被刀"
        prompt = (
            "%s\n\n%s\n\n%s\n\n%s\n\n现在是第 %d 夜。今晚被狼人刀的是：%s。\n"
            "请决定是否用解药救他，以及是否用毒药毒一个人。规则：同一夜不能同时用两瓶药；"
            "第一夜可以自救，之后不能自救；被毒死的猎人不能开枪。\n"
            "首夜没有信息时，解药很宝贵，不要默认必救；只有你判断被刀者可能是关键神职或强好人时才救。"
            "毒药只在你有较强把握时使用，拿不准就留着，不要毒已经跳身份的好人。\n"
            "你之后报药时必须和真实药水状态一致；不想暴露可以不说，但不能谎报药已经用完。\n"
            "只输出 JSON：{\"save\": true 或 false, \"poison\": 座位号或 null}。"
        ) % (
            self._private_info(witch), self._state_block(witch), self._history(witch),
            self._suspicion_text(witch), self.round,
            victim_text + ("（就是你）" if victim and victim.seat == witch.seat else ""),
        )
        obj, tokens, error = self._call(witch, prompt, max_tokens=80, temperature=0.6)
        save = bool(obj.get("save")) if isinstance(obj, dict) else False
        poison = obj.get("poison") if isinstance(obj, dict) else None
        poison = _seat_int(poison) if poison not in (None, "", 0, "0", "null") else None
        if victim is None:
            save = False
        save_allowed = bool(
            victim and witch.potions["antidote"]
            and not (victim.seat == witch.seat and self.round > 1)
        )
        poison_allowed = bool(
            poison and witch.potions["poison"] and poison in self.seat_map
            and self.seat_map[poison].alive and poison != witch.seat
            and (not victim or poison != victim.seat)
        )
        if save and poison_allowed:
            # The rule forbids both; keep the save when it is legal, otherwise poison.
            if save_allowed:
                poison = None
            else:
                save = False
        if save and not save_allowed:
            save = False
            self.degenerate = True
        if poison is not None and not poison_allowed:
            poison = None
            self.degenerate = True
        if save:
            witch.potions["antidote"] = False
        if poison:
            witch.potions["poison"] = False
        self._record({
            "type": "witch",
            "round": self.round,
            "seat": witch.seat,
            "name": witch.name,
            "victim": victim.seat if victim else None,
            "save": save,
            "poison": poison,
            "tokens": tokens,
            "fallback": bool(error),
        })
        return save, poison

    def _seer_action(self):
        self._checkpoint()
        seer = next((a for a in self.alive() if a.role == "seer"), None)
        if not seer:
            return None
        candidates = [a for a in self.alive() if a.seat != seer.seat]
        if not candidates:
            return None
        checked = {c["seat"] for c in seer.checks}
        preferred = [a for a in candidates if a.seat not in checked] or candidates
        # Do not let a zero-information first night collapse onto 1号 every game.
        preferred.sort(key=lambda a: (-seer.suspicion.get(a.seat, 0), self.rng.random()))
        prompt = (
            "%s\n\n%s\n\n%s\n\n现在是第 %d 夜。选择一名存活玩家查验阵营（不能查自己）。\n"
            "优先查验你怀疑度最高、或发言最像狼的人；不要验你已经确定是好人的玩家。"
            "第一夜没有信息时，不要默认验 1 号，可以从候选里按直觉挑一个中后段玩家。\n"
            "候选（按你的怀疑度排序）：%s。已验过：%s。只输出 JSON：{\"target\": 座位号}。"
        ) % (
            self._private_info(seer), self._state_block(seer), self._history(seer), self.round,
            "、".join("%s" % _seat_label(a.seat, a.name) for a in preferred),
            "、".join("%d号" % c["seat"] for c in seer.checks) or "无",
        )
        obj, tokens, error = self._call(seer, prompt, max_tokens=60, temperature=0.5)
        target = None
        if isinstance(obj, dict):
            target = _seat_int(obj.get("target"))
        valid = {a.seat for a in preferred}
        if target not in valid:
            top_score = max(seer.suspicion.get(a.seat, 0) for a in preferred)
            tied = [a for a in preferred if seer.suspicion.get(a.seat, 0) == top_score]
            target = self.rng.choice(tied).seat
            self.degenerate = True
        checked_agent = self.seat_map[target]
        result = "wolf" if checked_agent.camp == "wolf" else "good"
        seer.checks.append({"round": self.round, "seat": target, "name": checked_agent.name, "result": result})
        seer.suspicion[target] = 10.0 if result == "wolf" else -10.0
        self._record({
            "type": "seer",
            "round": self.round,
            "seat": seer.seat,
            "name": seer.name,
            "target": target,
            "target_name": checked_agent.name,
            "result": result,
            "tokens": tokens,
            "fallback": bool(error),
        })
        return {"target": target, "result": result}

    def _hunter_shot(self, hunter, cause):
        self._checkpoint()
        if hunter.role != "hunter" or cause == "poison":
            return
        candidates = [a for a in self.alive() if a.seat != hunter.seat]
        if not candidates:
            return
        last = hunter.round_speech or {}
        last_text = last.get("speech") or "你本轮没有留下明确发言。"
        last_vote = hunter.last_vote_target
        prompt = (
            "%s\n\n%s\n\n%s\n\n%s\n\n你刚被%s出局，可以开枪带走一名存活玩家。\n"
            "你本轮最后说：“%s”；你最后投的是：%s。\n"
            "开枪是好人最后的手段：先看发言和票型，不要枪口对准已经跳预言家/女巫/猎人的人。"
            "优先打你公开怀疑的人；如果改枪，必须在 reason 里说明新依据。"
            "如果没有把握，可以不开枪，把决定留给活着的队友。\n"
            "存活：%s。只输出 JSON：{\"target\": 座位号或null, \"reason\":\"开枪理由\"}；"
            "不开枪输出 {\"target\": null}。"
        ) % (
            self._private_info(hunter), self._state_block(hunter), self._history(hunter),
            self._suspicion_text(hunter), "狼人刀死" if cause == "wolf" else "投票",
            last_text, ("%d号" % last_vote) if last_vote else "弃票/未投",
            "、".join("%s" % _seat_label(a.seat, a.name) for a in candidates),
        )
        obj, tokens, error = self._call(hunter, prompt, max_tokens=120, temperature=0.55)
        raw_target = obj.get("target") if isinstance(obj, dict) else None
        reason = _clip(str(obj.get("reason") or "") if isinstance(obj, dict) else "", 60)
        if raw_target in (None, "", 0, "0", "null", "pass", "不开枪"):
            self._record({
                "type": "hunter_shot",
                "round": self.round,
                "seat": hunter.seat,
                "name": hunter.name,
                "target": None,
                "target_name": None,
                "reason": reason,
                "tokens": tokens,
                "fallback": bool(error),
            }, public="猎人 %s 选择不开枪。" % _seat_label(hunter.seat, hunter.name))
            return
        target = _seat_int(raw_target)
        valid = {a.seat for a in candidates}
        if target not in valid:
            ranked = sorted(candidates, key=lambda a: (-hunter.suspicion.get(a.seat, 0), a.seat))
            target = ranked[0].seat
            reason = reason or "目标不合法，按怀疑排序开枪。"
            self.degenerate = True
        # One consistency repair when the shot contradicts the hunter's public
        # suspicion without any explanation.
        last_accused = last.get("accused") or []
        if target != hunter.seat and last_accused and target not in last_accused and len(reason) < 4:
            retry = (
                "%s\n\n%s\n\n你最后公开怀疑的是 %s，却准备枪 %d号，且没有理由。"
                "请重新决定：打回你公开怀疑的人，或保留新目标并说明为什么改枪。"
                "只输出 JSON：{\"target\":座位号或null,\"reason\":\"开枪理由\"}。"
            ) % (
                self._private_info(hunter), self._state_block(hunter),
                "、".join("%d号" % s for s in last_accused), target,
            )
            obj2, tokens2, error2 = self._call(hunter, retry, max_tokens=100, temperature=0.5)
            tokens += tokens2
            error = error or error2
            if isinstance(obj2, dict):
                raw2 = obj2.get("target")
                reason2 = _clip(str(obj2.get("reason") or ""), 60)
                if raw2 in (None, "", "null", 0, "0"):
                    target = None
                else:
                    target2 = _seat_int(raw2)
                    if target2 in valid:
                        target = target2
                        reason = reason2 or reason
        if target is None:
            self._record({
                "type": "hunter_shot",
                "round": self.round,
                "seat": hunter.seat,
                "name": hunter.name,
                "target": None,
                "target_name": None,
                "reason": reason or "改枪后仍没有把握，选择不开枪。",
                "tokens": tokens,
                "fallback": bool(error),
            }, public="猎人 %s 选择不开枪。" % _seat_label(hunter.seat, hunter.name))
            return
        if target not in valid:
            target = self._fallback_vote(hunter, candidates)
            reason = "目标不合法，按怀疑排序开枪。"
            self.degenerate = True
        victim = self.seat_map[target]
        self._kill(victim, "shot", self.round)
        self._record({
            "type": "hunter_shot",
            "round": self.round,
            "seat": hunter.seat,
            "name": hunter.name,
            "target": target,
            "target_name": victim.name,
            "target_role": victim.role,
            "target_role_name": victim.role_name,
            "reason": reason,
            "tokens": tokens,
            "fallback": bool(error),
        }, public="猎人 %s 开枪带走 %s。" % (_seat_label(hunter.seat, hunter.name), _seat_label(victim.seat, victim.name)))

    def _last_words(self, agent):
        self._checkpoint()
        prompt = (
            "%s\n\n%s\n\n%s\n\n你刚被投票出局，请留下最后一句遗言，最多 45 字。\n"
            "出局不翻牌：你的遗言只是你的说法，不是系统公开身份。可以指认、表身份、留信息。"
            "狼人必须继续为阵营服务：可以撒谎、可以假装好人，但绝不能自曝狼人、认狼或直接卖队友。"
            "好人可以报真实身份和验人；女巫报药必须和真实药水状态一致。\n"
            "只输出 JSON：{\"speech\":\"遗言\"}。"
        ) % (self._private_info(agent), self._state_block(agent), self._history(agent))
        obj, tokens, error = self._call(agent, prompt, max_tokens=140, temperature=0.8)
        speech = obj.get("speech") if isinstance(obj, dict) else ""
        if not isinstance(speech, str) or len(speech.strip()) < 2:
            speech = self._fallback_last_words(agent)
            self.degenerate = True
        speech = _clip(speech, 50)
        violations = self._speech_violations(agent, speech)
        state_repair = 0
        if violations:
            repaired = self._repair_speech(agent, speech, "", violations)
            if repaired:
                speech, _thinking, repair_tokens = repaired
                tokens += repair_tokens
            else:
                speech = self._fallback_last_words(agent)
                self.degenerate = True
            state_repair = 1
        self._record({
            "type": "last_words",
            "round": self.round,
            "seat": agent.seat,
            "name": agent.name,
            "text": speech,
            "state_repair": state_repair,
            "constraint_notes": violations,
            "tokens": tokens,
            "fallback": bool(error),
        }, public="%s 遗言：%s" % (_seat_label(agent.seat, agent.name), speech))

    def _fallback_last_words(self, agent):
        suspects = sorted(
            [a for a in self.alive() if a.seat != agent.seat],
            key=lambda a: (-agent.suspicion.get(a.seat, 0), a.seat),
        )
        target = suspects[0] if suspects else None
        if agent.camp == "wolf":
            return ("我真是民，票我的里面有问题，%d号像狼。" % target.seat) if target else "好人别被带偏。"
        if target:
            return "我先把票留在这儿，%s号有问题。" % target.seat
        return "好人加油。"

    def _kill(self, agent, cause, round_no):
        if not agent.alive:
            return False
        agent.alive = False
        agent.death_cause = cause
        agent.death_round = round_no
        self.last_death_seat = agent.seat
        return True

    # -------------------------------------------------------------------- flow
    def _speaking_order(self):
        n = len(self.agents)
        if self.round == 1:
            start = 1
        elif self.last_death_seat:
            start = self.last_death_seat % n + 1
        else:
            start = self.next_start
        order = list(range(start, n + 1)) + list(range(1, start))
        return [self.seat_map[s] for s in order if self.seat_map[s].alive]

    def _night(self):
        self._checkpoint()
        self._record({
            "type": "night",
            "round": self.round,
            "public": "第%d夜，天黑请闭眼。" % self.round,
        })
        good_targets = self.alive_by(camp="good")
        wolves = self.alive_by(camp="wolf")
        victim = None
        wolf_choices = []
        if wolves and good_targets:
            coordinated = self._wolf_plan(wolves, good_targets)
            if coordinated:
                final, _plan = coordinated
                victim = self.seat_map[final]
                wolf_choices = [{
                    "seat": item["seat"], "name": item["name"], "target": item["target"],
                    "tokens": 0, "fallback": item["fallback"],
                } for item in _plan["proposals"]]
            else:
                with ThreadPoolExecutor(max_workers=min(3, len(wolves))) as pool:
                    results = list(pool.map(lambda w: self._wolf_choice(w, good_targets), wolves))
                tally = {}
                for wolf, (target, tokens, fallback) in zip(wolves, results):
                    wolf_choices.append({"seat": wolf.seat, "name": wolf.name, "target": target,
                                         "tokens": tokens, "fallback": fallback})
                    tally[target] = tally.get(target, 0) + 1
                top = max(tally.values())
                tied = [seat for seat, count in tally.items() if count == top]
                final = self.rng.choice(tied)
                victim = self.seat_map[final]
        # Witch and seer actions are independent once the wolf victim is known;
        # overlap their model calls instead of paying both latencies in series.
        with ThreadPoolExecutor(max_workers=2) as pool:
            witch_future = pool.submit(self._witch_action, victim)
            seer_future = pool.submit(self._seer_action)
            save, poison = witch_future.result()
            check = seer_future.result()
        causes = {}
        if victim and not save:
            causes.setdefault(victim.seat, set()).add("wolf")
        if poison:
            causes.setdefault(poison, set()).add("poison")
        deaths = []
        for seat, cause_set in causes.items():
            agent = self.seat_map[seat]
            cause = "poison" if "poison" in cause_set else "wolf"
            if self._kill(agent, cause, self.round):
                deaths.append({"seat": agent.seat, "name": agent.name, "role": agent.role,
                               "role_name": agent.role_name, "cause": cause})
        if deaths:
            # Multiple night deaths: the next day's speech starts after the
            # lowest-numbered victim, a deterministic reading of the rule.
            self.last_death_seat = min(d["seat"] for d in deaths)
            text = "第%d天，天亮了。昨夜死亡：%s。" % (
                self.round, "、".join(_seat_label(d["seat"], d["name"]) for d in deaths))
        else:
            text = "第%d天，天亮了。昨夜是平安夜。" % self.round
        self._record({
            "type": "dawn",
            "round": self.round,
            "deaths": deaths,
            "wolf_target": victim.seat if victim else None,
            "wolf_choices": wolf_choices,
            "saved": bool(save),
            "poisoned": poison,
            "seer_check": check,
            "public": text,
        })
        for death in deaths:
            agent = self.seat_map[death["seat"]]
            if agent.role == "hunter":
                self._hunter_shot(agent, death["cause"])
                break
        self._check_win("第%d夜" % self.round)

    def _day(self):
        self._checkpoint()
        self._record({
            "type": "day",
            "round": self.round,
            "public": "第%d天，开始发言。" % self.round,
        })
        order = self._speaking_order()
        start_seat = order[0].seat if order else None
        for agent in order:
            if not agent.alive:
                continue
            self._speak(agent)
        voters = self.alive()
        with ThreadPoolExecutor(max_workers=min(6, max(1, len(voters)))) as pool:
            results = list(pool.map(self._vote, voters))
        votes = []
        tally = {}
        for voter, result in zip(voters, results):
            target, tokens, fallback, reason, consistency = result
            if target is None:
                votes.append({"voter": voter.seat, "voter_name": voter.name,
                              "target": None, "target_name": None,
                              "reason": reason, "consistency": consistency,
                              "tokens": tokens, "fallback": fallback})
                continue
            votes.append({"voter": voter.seat, "voter_name": voter.name,
                          "target": target, "target_name": self.seat_map[target].name,
                          "reason": reason, "consistency": consistency,
                          "tokens": tokens, "fallback": fallback})
            tally[target] = tally.get(target, 0) + 1
        self.last_vote_counts = tally
        for voter, result in zip(voters, results):
            target = result[0]
            if target is None:
                continue
            voter.last_vote_target = target
            for listener in self.alive():
                if listener.seat == voter.seat:
                    continue
                if listener.camp == "wolf" and self.seat_map[target].camp == "wolf":
                    continue
                listener.suspicion[target] = min(10.0, listener.suspicion.get(target, 0) + 0.25)
            voter.suspicion[target] = min(10.0, voter.suspicion.get(target, 0) + 0.5)
        eliminated = None
        tie = False
        summary = ""
        if tally:
            top = max(tally.values())
            leaders = [seat for seat, count in tally.items() if count == top]
            if len(leaders) > 1:
                tie = True
                summary = "%s 各得 %d 票，平票，无人出局。" % (
                    "、".join("%d号" % s for s in sorted(leaders)), top)
            else:
                eliminated = self.seat_map[leaders[0]]
                summary = "%d号得 %d 票，被投出。" % (eliminated.seat, top)
        else:
            summary = "无人投票。"
        vote_link = "；".join(
            "%d号→%s" % (v["voter"], ("%d号" % v["target"]) if v["target"] is not None else "弃票")
            for v in votes)
        public = "第%d天投票：%s。%s" % (self.round, vote_link or "无人投票", summary)
        self._record({
            "type": "vote",
            "round": self.round,
            "votes": votes,
            "tally": tally,
            "tie": tie,
            "eliminated": eliminated.seat if eliminated else None,
            "eliminated_name": eliminated.name if eliminated else None,
            "summary": summary,
        }, public=public)
        if eliminated:
            self._kill(eliminated, "vote", self.round)
            self._last_words(eliminated)
            if eliminated.role == "hunter":
                self._hunter_shot(eliminated, "vote")
        else:
            # No death this round: next day's speech starts after this round's start.
            self.next_start = (start_seat % len(self.agents) + 1) if start_seat else 1
        self._summarize_round()
        self._check_win("第%d天" % self.round)

    def _check_win(self, phase):
        wolves_alive = [a for a in self.agents if a.alive and a.camp == "wolf"]
        gods_alive = [a for a in self.agents if a.alive and a.role in GOD_ROLES]
        villagers_alive = [a for a in self.agents if a.alive and a.role == "villager"]
        villager_total = role_totals(self.player_count)["villager"]
        if not wolves_alive:
            self.winner, self.win_reason = "good", "狼人全部出局"
        elif not gods_alive:
            self.winner, self.win_reason = "wolf", "三神全部出局"
        elif not villagers_alive:
            self.winner, self.win_reason = "wolf", "%s民全部出局" % (
                "三" if villager_total == 3 else "四")
        else:
            return False
        who = "好人阵营" if self.winner == "good" else "狼人阵营"
        self._record({
            "type": "win",
            "round": self.round,
            "phase": phase,
            "winner": self.winner,
            "reason": self.win_reason,
            "public": "游戏结束：%s获胜（%s）。" % (who, self.win_reason),
        })
        return True

    def run(self):
        started = time.time()
        while self.round <= MAX_ROUNDS and not self.winner:
            self._night()
            if self.winner:
                break
            self._day()
            if not self.winner:
                self.round += 1
        if not self.winner:
            self.winner = "draw"
            self.win_reason = "%d轮未分胜负" % MAX_ROUNDS
            self._record({
                "type": "win",
                "round": MAX_ROUNDS,
                "phase": "limit",
                "winner": "draw",
                "reason": self.win_reason,
                "public": "游戏结束：%d轮仍未分胜负，判为未决。" % MAX_ROUNDS,
            })
        self._finalize()
        duration_ms = int((time.time() - started) * 1000)
        variable_agents = [a for a in self.agents if a.is_variable]
        camp_wins = {"wolf": {"players": 0, "wins": 0}, "good": {"players": 0, "wins": 0}}
        player_wins = 0
        for agent in variable_agents:
            camp_wins[agent.camp]["players"] += 1
            if self.winner == agent.camp:
                camp_wins[agent.camp]["wins"] += 1
                player_wins += 1
        detail = {
            "seed": self.seed,
            "variable_type": self.variable_type,
            "variable_roles": self.variable_roles,
            "winner": self.winner,
            "win_reason": self.win_reason,
            "rounds": self.round if self.winner != "draw" else MAX_ROUNDS,
            "players": [a.card() for a in self.agents],
            "events": self.events,
            "public_log": self.public_log,
            "round_summaries": self.round_summaries,
            "tokens": self.tokens,
            "degenerate": 1 if self.degenerate else 0,
            "errors": self.errors[:30],
            "duration_ms": duration_ms,
        }
        return {
            "simulation_id": None,
            "game_no": None,
            "seed": self.seed,
            "variable_type": self.variable_type,
            "winner": self.winner,
            "win_reason": self.win_reason,
            "rounds": detail["rounds"],
            "variable_roles": self.variable_roles,
            "variable_camp_wins": camp_wins,
            "variable_player_wins": player_wins,
            "variable_player_count": len(variable_agents),
            "duration_ms": duration_ms,
            "tokens": self.tokens,
            "degenerate": 1 if self.degenerate else 0,
            "detail": detail,
        }

    def _finalize(self):
        if self.winner != "draw":
            self._record({
                "type": "final_players",
                "round": self.round,
                "players": [a.card() for a in self.agents],
            })
