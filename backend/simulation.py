"""Simulation setup validation, the background runner, and aggregate analysis."""
from __future__ import annotations

import random
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import llm
import questionnaires
import store
from engine import (BOARD_SIZES, GameEngine, GameStopped, MAX_ROUNDS, ROLE_DEFS,
                    ROLE_ORDER, role_totals)
import mbti as mbti_mod

_RUNNERS = {}
_LOCK = threading.RLock()


class Runner:
    """Runs a simulation batch, optionally with several games in flight.

    Each game is independent (its own engine, RNG seed and player copies), so a
    small worker pool can overlap the sequential speech loops. SQLite writes and
    progress counters stay behind a lock; pause/stop are shared checkpoints.
    """
    def __init__(self, sim_id):
        self.sim_id = sim_id
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.thread = None
        self.live = []
        self.live_lock = threading.Lock()
        self.progress_lock = threading.Lock()
        self.current_game = 0
        self.current_round = 0
        self.error = None
        self.status = "created"
        self.live_by_game = {}
        self.token_lock = threading.Lock()
        self.failed = 0
        self.failures = []
        self.concurrency = 1

    def start(self):
        sim = store.get_simulation(self.sim_id)
        if not sim:
            raise ValueError("模拟不存在")
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.pause_event.clear()
        self.error = None
        with self.token_lock:
            self.live_by_game = {}
        self.status = "running"
        store.update_simulation(
            self.sim_id, status="running",
            started_at=sim.get("started_at") or store.now_iso(),
            finished_at=None, error=None,
        )
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def pause(self):
        if self.status != "running":
            return
        self.pause_event.set()
        self.status = "paused"
        store.update_simulation(self.sim_id, status="paused")

    def resume(self):
        if self.status not in ("paused", "stopped"):
            return
        if self.status == "stopped":
            self.stop_event.clear()
        self.pause_event.clear()
        self.error = None
        with self.token_lock:
            self.live_by_game = {}
        self.status = "running"
        store.update_simulation(self.sim_id, status="running", error=None)
        if not (self.thread and self.thread.is_alive()):
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.pause_event.clear()
        if self.status in ("running", "paused", "created"):
            self.status = "stopping"
            store.update_simulation(self.sim_id, status="stopping")

    def checkpoint(self):
        if self.stop_event.is_set():
            raise GameStopped("用户停止")
        while self.pause_event.is_set():
            if self.stop_event.is_set():
                raise GameStopped("用户停止")
            time.sleep(0.2)
        if self.stop_event.is_set():
            raise GameStopped("用户停止")

    def _on_event(self, game_no, event):
        if event.get("round"):
            self.current_round = event["round"]
        tokens = int(event.get("tokens") or 0)
        if event.get("type") == "dawn":
            tokens += sum(int(choice.get("tokens") or 0)
                          for choice in (event.get("wolf_choices") or []))
        if event.get("type") == "vote":
            tokens += sum(int(vote.get("tokens") or 0)
                          for vote in (event.get("votes") or []))
        if tokens:
            with self.token_lock:
                self.live_by_game[game_no] = self.live_by_game.get(game_no, 0) + tokens
        text = event.get("public")
        if not text:
            return
        with self.live_lock:
            self.live.append({
                "seq": len(self.live) + 1,
                "round": event.get("round") or 0,
                "type": event.get("type"),
                "text": "第%d局 · %s" % (game_no, text),
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            if len(self.live) > 80:
                self.live = self.live[-80:]

    def _log(self, text, kind="run"):
        with self.live_lock:
            self.live.append({
                "seq": len(self.live) + 1, "round": self.current_round,
                "type": kind, "text": text,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            if len(self.live) > 80:
                self.live = self.live[-80:]

    def _run_one(self, game_no, variable_type, seed, variable_roles, fixed_by_role,
                 fixed_players, fixed_ids, all_players, eligible, variable_slots):
        self.checkpoint()
        with self.progress_lock:
            self.current_game = max(self.current_game, game_no)
            self.current_round = 1
        game_rng = random.Random(seed * 7919 + game_no * 104729)
        pool = [p for p in all_players
                if p["mbti"] == variable_type and p["id"] not in fixed_ids]
        # A player deleted mid-run can shrink the pool; fall back to any eligible
        # type rather than aborting the whole batch.
        if len(pool) < variable_slots:
            for alt in eligible:
                alt_pool = [p for p in all_players
                            if p["mbti"] == alt and p["id"] not in fixed_ids]
                if len(alt_pool) >= variable_slots:
                    variable_type, pool = alt, alt_pool
                    break
            else:
                raise RuntimeError("可用玩家不足，无法填满变量角色")
        game_rng.shuffle(pool)
        variable_players = pool[:variable_slots]

        players_by_role = {}
        cursor = 0
        for role in ROLE_ORDER:
            count = int(variable_roles.get(role) or 0)
            chosen = []
            for player in variable_players[cursor:cursor + count]:
                item = dict(player)
                item["_is_variable"] = True
                chosen.append(item)
            cursor += count
            for assignment in fixed_by_role.get(role, []):
                player = fixed_players.get(assignment["player_id"])
                if not player:
                    raise RuntimeError("固定玩家已被删除：%s" % assignment.get("name", ""))
                item = dict(player)
                # The fixed seat's personality is part of the locked
                # configuration. A later retest must not silently change the
                # role the user selected.
                item["mbti"] = assignment.get("mbti") or player["mbti"]
                item["params"] = mbti_mod.params_for(item["mbti"])
                item["_is_variable"] = False
                chosen.append(item)
            players_by_role[role] = chosen

        game_seed = (seed * 1000003 + game_no * 7919) % (2 ** 31 - 1)
        self._log("第 %d 局开始 · 变量性格 %s（%s）" % (
            game_no, variable_type, mbti_mod.type_name(variable_type)))
        engine = GameEngine(
            players_by_role, variable_roles, variable_type, game_seed,
            checkpoint=self.checkpoint,
            on_event=lambda event: self._on_event(game_no, event),
        )
        result = engine.run()
        result["simulation_id"] = self.sim_id
        result["game_no"] = game_no
        store.add_game(result)
        return result

    def _loop(self):
        sim = store.get_simulation(self.sim_id)
        if not sim:
            return
        completed_count = int(sim.get("completed_games") or 0)
        try:
            config = sim.get("config_json") or {}
            total_games = int(sim.get("total_games") or 0)
            seed = int(sim.get("seed") or 0)
            concurrency = max(1, min(4, int(config.get("concurrency") or 1)))
            self.concurrency = concurrency
            self.failed = 0
            self.failures = []
            variable_roles = sim.get("variable_roles") or {}
            fixed = sim.get("fixed_assignments") or []
            fixed_ids = {item["player_id"] for item in fixed}
            variable_slots = sum(int(v) for v in variable_roles.values())
            fixed_by_role = {role: [] for role in ROLE_ORDER}
            for item in fixed:
                fixed_by_role.setdefault(item["role"], []).append(item)
            qid = config.get("questionnaire_id") or ""
            if qid:
                fixed_players = {p["id"]: p for p in store.get_players_for_questionnaire(list(fixed_ids), qid)}
            else:
                fixed_players = {p["id"]: p for p in store.get_players(list(fixed_ids))}

            # Resume by game number, not by "last completed": with concurrent
            # games a later number can finish before an earlier one.
            existing = store.all_game_summaries(self.sim_id)
            existing_nos = {int(g["game_no"]) for g in existing}
            completed_count = len(existing)
            tokens_total = sum(int(g.get("tokens") or 0) for g in existing)
            self.current_game = max(existing_nos) if existing_nos else 0
            todo = [n for n in range(1, total_games + 1) if n not in existing_nos]
            if not todo:
                self.status = "completed"
                store.update_simulation(
                    self.sim_id, status="completed", finished_at=store.now_iso(),
                    completed_games=completed_count, total_tokens=tokens_total)
                self._log("模拟完成 · 共 %d 局" % completed_count, kind="done")
                return

            # Recompute which types can fill every variable seat in one game.
            type_counts = {}
            if qid:
                all_players, _total = store.list_players_for_questionnaire(qid, limit=5000, tested_only=True)
            else:
                all_players, _total = store.list_players(limit=5000)
            for player in all_players:
                if player["id"] in fixed_ids:
                    continue
                type_counts[player["mbti"]] = type_counts.get(player["mbti"], 0) + 1
            eligible = sorted(t for t, n in type_counts.items() if n >= variable_slots)
            if not eligible:
                raise RuntimeError(
                    "没有一种性格能填满 %d 个变量角色（扣除已选固定玩家后）" % variable_slots)
            rng = random.Random(seed)
            schedule = []
            while len(schedule) < total_games:
                block = list(eligible)
                rng.shuffle(block)
                schedule.extend(block)
            schedule = schedule[:total_games]

            self.status = "running"
            self._log("模拟启动 · 共 %d 局 · 并发 %d · 变量角色 %d 个 · 可选性格 %d 种" % (
                total_games, concurrency, variable_slots, len(eligible)))
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {
                    pool.submit(
                        self._run_one,
                        game_no,
                        schedule[game_no - 1],
                        seed,
                        variable_roles,
                        fixed_by_role,
                        fixed_players,
                        fixed_ids,
                        all_players,
                        eligible,
                        variable_slots,
                    ): game_no
                    for game_no in todo
                }
                for future in as_completed(futures):
                    game_no = futures[future]
                    try:
                        result = future.result()
                    except GameStopped:
                        for item in futures:
                            item.cancel()
                        raise
                    except llm.LLMConfigError as exc:
                        for item in futures:
                            item.cancel()
                        raise RuntimeError("模型配置错误：%s" % exc) from exc
                    except Exception as exc:
                        with self.progress_lock:
                            self.failed += 1
                            self.failures.append((game_no, str(exc)[:240]))
                            self.live_by_game.pop(game_no, None)
                        self._log("第 %d 局失败：%s" % (game_no, str(exc)[:180]), kind="error")
                        continue
                    with self.progress_lock:
                        completed_count += 1
                        tokens_total += int(result.get("tokens") or 0)
                        self.current_game = max(self.current_game, game_no)
                        self.current_round = result["rounds"]
                        self.live_by_game.pop(game_no, None)
                        store.update_simulation(
                            self.sim_id, completed_games=completed_count,
                            current_game=self.current_game,
                            current_round=result["rounds"],
                            total_tokens=tokens_total,
                        )
                    winner_text = {"wolf": "狼人胜", "good": "好人胜", "draw": "未决"}[result["winner"]]
                    self._log("第 %d 局结束 · %s · %d 轮" % (
                        game_no, winner_text, result["rounds"]))
                    if self.stop_event.is_set():
                        for item in futures:
                            item.cancel()
                        raise GameStopped("用户停止")

            if self.failed:
                self.status = "error"
                self.error = "%d 局失败，可继续补跑。首个错误：%s" % (
                    self.failed, self.failures[0][1] if self.failures else "")
                store.update_simulation(
                    self.sim_id, status="error", finished_at=store.now_iso(),
                    error=self.error, completed_games=completed_count,
                    total_tokens=tokens_total)
                self._log("模拟结束：%s" % self.error, kind="error")
            else:
                self.status = "completed"
                store.update_simulation(
                    self.sim_id, status="completed", finished_at=store.now_iso(),
                    completed_games=completed_count, total_tokens=tokens_total)
                self._log("模拟完成 · 共 %d 局" % completed_count, kind="done")
        except GameStopped:
            self.status = "stopped"
            completed_count = store.count_games(self.sim_id)
            store.update_simulation(
                self.sim_id, status="stopped", finished_at=store.now_iso(),
                completed_games=completed_count,
                total_tokens=sum(int(g.get("tokens") or 0)
                                 for g in store.all_game_summaries(self.sim_id)),
            )
            with self.token_lock:
                self.live_by_game = {}
            self._log("模拟已停止", kind="done")
        except Exception as exc:
            self.status = "error"
            self.error = str(exc)[:600]
            completed_count = store.count_games(self.sim_id)
            store.update_simulation(
                self.sim_id, status="error", finished_at=store.now_iso(),
                error=self.error, completed_games=completed_count,
                total_tokens=sum(int(g.get("tokens") or 0)
                                 for g in store.all_game_summaries(self.sim_id)),
            )
            with self.token_lock:
                self.live_by_game = {}
            self._log("模拟出错：%s" % self.error, kind="error")

    def snapshot(self):
        sim = store.get_simulation(self.sim_id) or {}
        with self.live_lock:
            live = list(self.live[-40:])
        with self.token_lock:
            live_tokens = sum(self.live_by_game.values())
        return {
            "id": self.sim_id,
            "no": sim.get("no"),
            "status": self.status if self.status else sim.get("status"),
            "total_games": sim.get("total_games"),
            "completed_games": sim.get("completed_games") or 0,
            "current_game": self.current_game or sim.get("current_game") or 0,
            "current_round": self.current_round or sim.get("current_round") or 0,
            "max_rounds": MAX_ROUNDS,
            "concurrency": self.concurrency,
            "total_tokens": int(sim.get("total_tokens") or 0) + live_tokens,
            "started_at": sim.get("started_at"),
            "finished_at": sim.get("finished_at"),
            "error": self.error or sim.get("error"),
            "live": live,
        }

def get_runner(sim_id):
    with _LOCK:
        return _RUNNERS.get(sim_id)


def _runner_for(sim_id):
    with _LOCK:
        runner = _RUNNERS.get(sim_id)
        if not runner:
            runner = Runner(sim_id)
            _RUNNERS[sim_id] = runner
        return runner


def validate_setup(payload):
    try:
        player_count = int(payload.get("player_count") or 9)
    except (TypeError, ValueError):
        player_count = 9
    if player_count not in BOARD_SIZES:
        raise ValueError("玩家人数必须是 9 人或 10 人")
    qid = payload.get("questionnaire_id") or store.get_active_questionnaire_id()
    qitem = store.get_questionnaire(qid) if qid else None
    if qid and not qitem:
        raise ValueError("当前生效问卷不存在")
    totals = role_totals(player_count)
    roles = {}
    for role in ROLE_ORDER:
        try:
            count = int((payload.get("variable_roles") or {}).get(role) or 0)
        except (TypeError, ValueError):
            count = 0
        if count < 0 or count > totals[role]:
            raise ValueError("%s 变量数量必须在 0–%d 之间（%d 人局）" % (
                ROLE_DEFS[role]["name"], totals[role], player_count))
        roles[role] = count
    variable_slots = sum(roles.values())
    if variable_slots < 1:
        raise ValueError("至少要设置 1 个变量角色")
    if variable_slots > player_count:
        raise ValueError("变量角色不能超过 %d 个" % player_count)

    fixed = payload.get("fixed_assignments") or []
    if not isinstance(fixed, list):
        raise ValueError("固定角色格式错误")
    fixed_ids = []
    fixed_by_role = {role: [] for role in ROLE_ORDER}
    for item in fixed:
        if not isinstance(item, dict):
            raise ValueError("固定角色格式错误")
        role = str(item.get("role") or "")
        player_id = str(item.get("player_id") or "")
        if role not in ROLE_DEFS:
            raise ValueError("未知角色：%s" % role)
        if not player_id:
            raise ValueError("固定角色缺少玩家")
        fixed_by_role[role].append(player_id)
        fixed_ids.append(player_id)
    if len(set(fixed_ids)) != len(fixed_ids):
        raise ValueError("同一名玩家不能占据两个固定角色")
    for role in ROLE_ORDER:
        expected = totals[role] - roles[role]
        if len(fixed_by_role[role]) != expected:
            raise ValueError("%s 需要选择 %d 名固定玩家，当前 %d 名" % (
                ROLE_DEFS[role]["name"], expected, len(fixed_by_role[role])))
    if qid:
        players = store.get_players_for_questionnaire(fixed_ids, qid)
        if len(players) != len(fixed_ids):
            raise ValueError("有固定玩家已不在玩家库中")
        if any(not p.get("has_result") for p in players):
            raise ValueError("有固定玩家还没有完成当前生效问卷")
    else:
        players = store.get_players(fixed_ids)
        if len(players) != len(fixed_ids):
            raise ValueError("有固定玩家已不在玩家库中")

    total_games = int(payload.get("games") or 0)
    if total_games < 1 or total_games > 2000:
        raise ValueError("模拟局数必须在 1–2000 之间")
    try:
        concurrency = int(payload.get("concurrency") or 1)
    except (TypeError, ValueError):
        concurrency = 1
    if concurrency < 1 or concurrency > 4:
        raise ValueError("并发局数必须在 1–4 之间")
    seed = payload.get("seed")
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = random.SystemRandom().randint(1, 2 ** 30)

    # Every variable role in a game shares one personality tag. A tag is usable
    # only if it has enough distinct samples after the fixed seats are removed.
    if qid:
        all_players, _ = store.list_players_for_questionnaire(qid, limit=2000, tested_only=True)
    else:
        all_players, _ = store.list_players(limit=2000)
    fixed_set = set(fixed_ids)
    counts = {}
    for player in all_players:
        if player["id"] in fixed_set:
            continue
        counts[player["mbti"]] = counts.get(player["mbti"], 0) + 1
    eligible = sorted(t for t, n in counts.items() if n >= variable_slots)
    if not eligible:
        best = max(counts.items(), key=lambda kv: kv[1]) if counts else ("", 0)
        raise ValueError(
            "变量角色共 %d 个，需要同一性格的 %d 名不同玩家；当前最多只有 %s 性格的 %d 名可用（已扣除固定玩家）。"
            "请减少变量角色或补充玩家。" % (variable_slots, variable_slots, best[0] or "任意", best[1]))

    fixed_enriched = []
    by_id = {p["id"]: p for p in players}
    for role in ROLE_ORDER:
        for player_id in fixed_by_role[role]:
            p = by_id[player_id]
            fixed_enriched.append({
                "role": role,
                "role_name": ROLE_DEFS[role]["name"],
                "player_id": p["id"],
                "name": p["name"],
                "mbti": p["mbti"],
                "type_name": p.get("type_name") or mbti_mod.type_name(p["mbti"]),
                "age": p.get("age"),
                "gender": p.get("gender"),
                "occupation": p.get("occupation"),
                "province": p.get("province"),
            })
    return {
        "id": "sim_" + uuid.uuid4().hex[:12],
        "name": str(payload.get("name") or "").strip()[:80],
        "variable_roles": roles,
        "fixed_assignments": fixed_enriched,
        "total_games": total_games,
        "seed": seed,
        "config_json": {
            "player_count": player_count,
            "questionnaire_id": qid or "",
            "questionnaire_name": (qitem or {}).get("name") or "",
            "variable_slots": variable_slots,
            "eligible_types": eligible,
            "eligible_counts": {t: counts[t] for t in eligible},
            "concurrency": concurrency,
        },
    }


def create_simulation(payload):
    setup = validate_setup(payload)
    sim = {
        "id": setup["id"],
        "name": setup["name"],
        "created_at": store.now_iso(),
        "status": "created",
        "total_games": setup["total_games"],
        "completed_games": 0,
        "variable_roles": setup["variable_roles"],
        "fixed_assignments": setup["fixed_assignments"],
        "seed": setup["seed"],
        "current_game": 0,
        "current_round": 0,
        "total_tokens": 0,
        "config_json": setup["config_json"],
    }
    sim_id, no = store.create_simulation(sim)
    return store.get_simulation(sim_id)


def start_simulation(sim_id):
    sim = store.get_simulation(sim_id)
    if not sim:
        raise ValueError("模拟不存在")
    if sim["status"] == "completed":
        raise ValueError("本次模拟已经完成，请新建模拟")
    if int(sim.get("completed_games") or 0) >= int(sim.get("total_games") or 0):
        raise ValueError("本次模拟已经完成，请新建模拟")
    runner = _runner_for(sim_id)
    runner.start()
    return runner.snapshot()


def pause_simulation(sim_id):
    runner = get_runner(sim_id)
    if runner:
        runner.pause()
        return runner.snapshot()
    sim = store.get_simulation(sim_id)
    if not sim:
        raise ValueError("模拟不存在")
    if sim["status"] == "running":
        store.update_simulation(sim_id, status="paused")
    return simulation_snapshot(sim_id)


def resume_simulation(sim_id):
    runner = get_runner(sim_id)
    if not runner:
        sim = store.get_simulation(sim_id)
        if not sim:
            raise ValueError("模拟不存在")
        runner = _runner_for(sim_id)
    runner.resume()
    return runner.snapshot()


def stop_simulation(sim_id):
    runner = get_runner(sim_id)
    if runner:
        runner.stop()
        return runner.snapshot()
    sim = store.get_simulation(sim_id)
    if not sim:
        raise ValueError("模拟不存在")
    if sim["status"] in ("running", "paused", "stopping", "created"):
        store.update_simulation(
            sim_id, status="stopped", finished_at=store.now_iso(), error=None)
    return simulation_snapshot(sim_id)


def simulation_snapshot(sim_id):
    runner = get_runner(sim_id)
    if runner:
        return runner.snapshot()
    sim = store.get_simulation(sim_id)
    if not sim:
        return None
    return {
        "id": sim["id"], "no": sim["no"], "status": sim["status"],
        "total_games": sim["total_games"], "completed_games": sim["completed_games"],
        "current_game": sim.get("current_game") or 0,
        "current_round": sim.get("current_round") or 0,
        "max_rounds": MAX_ROUNDS,
        "concurrency": int((sim.get("config_json") or {}).get("concurrency") or 1),
        "total_tokens": sim.get("total_tokens") or 0,
        "started_at": sim.get("started_at"), "finished_at": sim.get("finished_at"),
        "error": sim.get("error"), "live": [],
    }


def public_simulation(sim):
    if not sim:
        return None
    return {
        "id": sim["id"],
        "no": sim["no"],
        "name": sim.get("name") or "",
        "created_at": sim.get("created_at"),
        "started_at": sim.get("started_at"),
        "finished_at": sim.get("finished_at"),
        "status": sim.get("status"),
        "total_games": sim.get("total_games"),
        "completed_games": sim.get("completed_games") or 0,
        "variable_roles": sim.get("variable_roles") or {},
        "fixed_assignments": sim.get("fixed_assignments") or [],
        "seed": sim.get("seed"),
        "total_tokens": sim.get("total_tokens") or 0,
        "config": sim.get("config_json") or {},
        "error": sim.get("error"),
    }


def history(limit=100):
    return [public_simulation(sim) for sim in store.list_simulations(limit)]


def _rate(wins, games):
    return round(wins / games, 4) if games else 0.0


def compute_stats(games):
    camps = {"wolf": 0, "good": 0, "draw": 0}
    by_type = {}
    timeline = []
    rounds_total = 0
    tokens = 0
    for game in games:
        winner = game.get("winner")
        if winner in camps:
            camps[winner] += 1
        rounds_total += int(game.get("rounds") or 0)
        tokens += int(game.get("tokens") or 0)
        vtype = game.get("variable_type") or "—"
        item = by_type.setdefault(vtype, {
            "type": vtype, "type_name": mbti_mod.type_name(vtype),
            "games": 0, "wolf_games": 0, "wolf_wins": 0,
            "good_games": 0, "good_wins": 0,
            "appearances": 0, "player_wins": 0,
            "rounds": 0, "tokens": 0,
        })
        camp = game.get("variable_camp_wins") or {}
        wolf = camp.get("wolf") or {}
        good = camp.get("good") or {}
        item["games"] += 1
        item["wolf_games"] += int(wolf.get("players") or 0) and 1 or 0
        item["wolf_wins"] += int(wolf.get("wins") or 0)
        item["good_games"] += int(good.get("players") or 0) and 1 or 0
        item["good_wins"] += int(good.get("wins") or 0)
        item["appearances"] += int(game.get("variable_player_count") or 0)
        item["player_wins"] += int(game.get("variable_player_wins") or 0)
        item["rounds"] += int(game.get("rounds") or 0)
        item["tokens"] += int(game.get("tokens") or 0)
        played = len(timeline) + 1
        timeline.append({
            "no": game.get("game_no"),
            "games": played,
            "wolf_wins": camps["wolf"],
            "good_wins": camps["good"],
            "draws": camps["draw"],
            "wolf_rate": _rate(camps["wolf"], played),
            "good_rate": _rate(camps["good"], played),
            "draw_rate": _rate(camps["draw"], played),
        })
    type_rows = []
    for item in by_type.values():
        item["wolf_rate"] = _rate(item["wolf_wins"], item["wolf_games"])
        item["good_rate"] = _rate(item["good_wins"], item["good_games"])
        item["player_rate"] = _rate(item["player_wins"], item["appearances"])
        item["avg_rounds"] = round(item["rounds"] / item["games"], 2) if item["games"] else 0
        type_rows.append(item)
    type_rows.sort(key=lambda x: (-x["player_rate"], -x["games"], x["type"]))
    total = len(games)
    return {
        "games": total,
        "camps": {
            "wolf": {"wins": camps["wolf"], "rate": _rate(camps["wolf"], total)},
            "good": {"wins": camps["good"], "rate": _rate(camps["good"], total)},
            "draw": {"wins": camps["draw"], "rate": _rate(camps["draw"], total)},
        },
        "by_type": type_rows,
        "timeline": timeline,
        "avg_rounds": round(rounds_total / total, 2) if total else 0,
        "tokens": tokens,
    }


def analysis(sim_id):
    sim = store.get_simulation(sim_id)
    if not sim:
        return None
    games = store.all_game_summaries(sim_id)
    return {
        "simulation": public_simulation(sim),
        "games": games,
        "stats": compute_stats(games),
        "snapshot": simulation_snapshot(sim_id),
    }
