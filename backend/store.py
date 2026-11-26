"""SQLite persistence for players, simulations and per-game transcripts."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("WEREWOLF_DB", os.path.join(_HERE, "data", "werewolf.db"))
_LOCK = threading.RLock()

_JSON_COLUMNS = {
    "players": ("dims", "params", "answers", "profile_json", "raw_json", "interests"),
    "simulations": ("variable_roles", "fixed_assignments", "config_json"),
    "games": ("variable_roles", "variable_camp_wins", "detail"),
    "questionnaires": ("definition",),
    "questionnaire_results": ("dims", "params", "answers"),
}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def _conn():
    """A short-lived connection. The context commits and always closes the fd."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with _LOCK, _conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS players (
                id TEXT PRIMARY KEY,
                person_id TEXT,
                name TEXT NOT NULL,
                age INTEGER,
                gender TEXT,
                country TEXT,
                province TEXT,
                city TEXT,
                urbanicity TEXT,
                education TEXT,
                occupation TEXT,
                occupation_group TEXT,
                income INTEGER,
                marital TEXT,
                interests TEXT,
                mbti TEXT NOT NULL,
                dims TEXT,
                params TEXT,
                answers TEXT,
                test_fallback INTEGER DEFAULT 0,
                persona TEXT,
                system_prompt TEXT,
                profile_json TEXT,
                raw_json TEXT,
                source TEXT,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_players_mbti ON players(mbti);
            CREATE INDEX IF NOT EXISTS idx_players_created ON players(created_at);

            CREATE TABLE IF NOT EXISTS simulations (
                id TEXT PRIMARY KEY,
                no INTEGER UNIQUE,
                name TEXT,
                created_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                status TEXT DEFAULT 'created',
                total_games INTEGER,
                completed_games INTEGER DEFAULT 0,
                variable_roles TEXT,
                fixed_assignments TEXT,
                seed INTEGER,
                current_game INTEGER DEFAULT 0,
                current_round INTEGER DEFAULT 0,
                error TEXT,
                total_tokens INTEGER DEFAULT 0,
                config_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_simulations_no ON simulations(no DESC);

            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                simulation_id TEXT NOT NULL,
                game_no INTEGER NOT NULL,
                seed INTEGER,
                variable_type TEXT,
                winner TEXT,
                win_reason TEXT,
                rounds INTEGER,
                variable_roles TEXT,
                variable_camp_wins TEXT,
                variable_player_wins INTEGER DEFAULT 0,
                variable_player_count INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                tokens INTEGER DEFAULT 0,
                degenerate INTEGER DEFAULT 0,
                detail TEXT,
                created_at TEXT,
                UNIQUE(simulation_id, game_no)
            );
            CREATE INDEX IF NOT EXISTS idx_games_sim ON games(simulation_id, game_no);

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                invite_code TEXT,
                created_at TEXT,
                last_login_at TEXT,
                active INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT,
                expires_at TEXT,
                last_seen_at TEXT,
                user_agent TEXT,
                ip TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

            CREATE TABLE IF NOT EXISTS auth_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                created_at TEXT,
                expires_at TEXT,
                attempts INTEGER DEFAULT 0,
                consumed INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_auth_codes_email ON auth_codes(email, id DESC);

            CREATE TABLE IF NOT EXISTS invites (
                code TEXT PRIMARY KEY,
                created_at TEXT,
                used_by TEXT,
                used_at TEXT
            );

            CREATE TABLE IF NOT EXISTS questionnaires (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT,
                description TEXT,
                question_count INTEGER,
                definition TEXT NOT NULL,
                is_builtin INTEGER DEFAULT 0,
                created_at TEXT,
                created_by TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_questionnaires_created ON questionnaires(created_at);

            CREATE TABLE IF NOT EXISTS questionnaire_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id TEXT NOT NULL,
                questionnaire_id TEXT NOT NULL,
                result TEXT,
                type_name TEXT,
                dims TEXT,
                params TEXT,
                answers TEXT,
                test_fallback INTEGER DEFAULT 0,
                test_error TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(player_id, questionnaire_id)
            );
            CREATE INDEX IF NOT EXISTS idx_qr_questionnaire ON questionnaire_results(questionnaire_id);
            CREATE INDEX IF NOT EXISTS idx_qr_player ON questionnaire_results(player_id);

            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )


def _decode_row(table, row):
    if row is None:
        return None
    out = dict(row)
    for key in _JSON_COLUMNS.get(table, ()):
        if out.get(key) in (None, ""):
            if key in ("dims", "params", "variable_roles", "fixed_assignments",
                       "variable_camp_wins", "config_json", "interests", "answers"):
                out[key] = {} if key not in ("interests", "answers") else []
            else:
                out[key] = None
            continue
        try:
            out[key] = json.loads(out[key])
        except (TypeError, json.JSONDecodeError):
            pass
    return out


def _dumps(value):
    return json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value


# --------------------------------------------------------------------------
# players
# --------------------------------------------------------------------------
PLAYER_FIELDS = (
    "id", "person_id", "name", "age", "gender", "country", "province", "city",
    "urbanicity", "education", "occupation", "occupation_group", "income",
    "marital", "interests", "mbti", "dims", "params", "answers", "test_fallback",
    "persona", "system_prompt", "profile_json", "raw_json", "source", "created_at",
)


def add_player(player):
    values = []
    for field in PLAYER_FIELDS:
        value = player.get(field)
        if field in ("dims", "params", "answers", "profile_json", "raw_json", "interests") and value is not None:
            value = _dumps(value)
        values.append(value)
    placeholders = ",".join("?" for _ in PLAYER_FIELDS)
    with _LOCK, _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO players(%s) VALUES(%s)" % (",".join(PLAYER_FIELDS), placeholders),
            values,
        )
    return player["id"]


def get_player(player_id):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
    return _decode_row("players", row)


def get_players(ids):
    ids = list(dict.fromkeys(x for x in ids if x))
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM players WHERE id IN (%s)" % marks, ids).fetchall()
    by_id = {row["id"]: _decode_row("players", row) for row in rows}
    return [by_id[x] for x in ids if x in by_id]


def list_players(mbti=None, search="", dimensions=None, limit=200, offset=0):
    clauses, values = [], []
    if mbti:
        clauses.append("mbti=?")
        values.append(mbti.upper())
    if search:
        clauses.append("(name LIKE ? OR occupation LIKE ? OR province LIKE ? OR mbti LIKE ?)")
        needle = "%" + search.strip() + "%"
        values.extend([needle, needle, needle, needle])
    for dim, letter in (dimensions or {}).items():
        if dim not in ("EI", "SN", "TF", "JP") or not letter:
            continue
        # Fixed-position letter test: EI at 0, SN at 1, TF at 2, JP at 3.
        pos = {"EI": 1, "SN": 2, "TF": 3, "JP": 4}[dim]
        clauses.append("substr(mbti,?,1)=?")
        values.extend([pos, letter.upper()])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM players" + where, values).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM players" + where + " ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            values + [int(limit), int(offset)],
        ).fetchall()
    return [_decode_row("players", row) for row in rows], total


def player_type_counts():
    with _conn() as conn:
        rows = conn.execute(
            "SELECT mbti, COUNT(*) AS n FROM players GROUP BY mbti ORDER BY mbti"
        ).fetchall()
    return {row["mbti"]: row["n"] for row in rows}


def player_dimension_counts():
    types = player_type_counts()
    out = {"EI": {"E": 0, "I": 0}, "SN": {"S": 0, "N": 0},
           "TF": {"T": 0, "F": 0}, "JP": {"J": 0, "P": 0}}
    for mbti, n in types.items():
        for key, pos in (("EI", 0), ("SN", 1), ("TF", 2), ("JP", 3)):
            if len(mbti) == 4:
                out[key][mbti[pos]] = out[key].get(mbti[pos], 0) + n
    return out


def player_stats():
    types = player_type_counts()
    total = sum(types.values())
    fallback = 0
    with _conn() as conn:
        last = conn.execute("SELECT created_at FROM players ORDER BY created_at DESC LIMIT 1").fetchone()
        fallback = conn.execute("SELECT COUNT(*) FROM players WHERE test_fallback=1").fetchone()[0]
    return {
        "total": total,
        "types": types,
        "type_count": sum(1 for n in types.values() if n > 0),
        "dimensions": player_dimension_counts(),
        "fallback": fallback,
        "last_created": last["created_at"] if last else None,
    }


def delete_players(ids):
    ids = [x for x in ids if x]
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    with _LOCK, _conn() as conn:
        conn.execute("DELETE FROM questionnaire_results WHERE player_id IN (%s)" % marks, ids)
        cur = conn.execute("DELETE FROM players WHERE id IN (%s)" % marks, ids)
        return cur.rowcount



# --------------------------------------------------------------------------
# questionnaires and per-player results
# --------------------------------------------------------------------------
def _json_load(value, fallback):
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _questionnaire_row(row):
    out = _decode_row("questionnaires", row)
    if out and out.get("definition") is None:
        out["definition"] = {}
    return out


def create_questionnaire(item):
    with _LOCK, _conn() as conn:
        conn.execute(
            "INSERT INTO questionnaires(id,name,version,description,question_count,"
            "definition,is_builtin,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
            (item["id"], item["name"], item.get("version") or "", item.get("description") or "",
             int(item.get("question_count") or 0), _dumps(item.get("definition") or {}),
             1 if item.get("is_builtin") else 0, item.get("created_at") or now_iso(),
             item.get("created_by") or "system"),
        )
    return get_questionnaire(item["id"])


def upsert_questionnaire(item):
    """Insert the built-in questionnaire or refresh its definition."""
    existing = get_questionnaire(item["id"])
    if not existing:
        return create_questionnaire(item)
    with _LOCK, _conn() as conn:
        conn.execute(
            "UPDATE questionnaires SET name=?,version=?,description=?,question_count=?,"
            "definition=?,is_builtin=? WHERE id=?",
            (item["name"], item.get("version") or "", item.get("description") or "",
             int(item.get("question_count") or 0), _dumps(item.get("definition") or {}),
             1 if item.get("is_builtin") else 0, item["id"]),
        )
    return get_questionnaire(item["id"])


def get_questionnaire(qid):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM questionnaires WHERE id=?", (qid,)).fetchone()
    return _questionnaire_row(row)


def list_questionnaires():
    active = get_active_questionnaire_id()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT q.*, COUNT(r.id) AS tested FROM questionnaires q "
            "LEFT JOIN questionnaire_results r ON r.questionnaire_id=q.id "
            "GROUP BY q.id ORDER BY q.is_builtin DESC, q.created_at ASC"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    out = []
    for row in rows:
        item = _questionnaire_row(row)
        tested = int(row["tested"] or 0)
        item["tested"] = tested
        item["total"] = int(total or 0)
        item["coverage"] = round(tested / total, 4) if total else 0.0
        item["is_active"] = item["id"] == active
        out.append(item)
    return out


def delete_questionnaire(qid):
    with _LOCK, _conn() as conn:
        conn.execute("DELETE FROM questionnaire_results WHERE questionnaire_id=?", (qid,))
        cur = conn.execute("DELETE FROM questionnaires WHERE id=? AND is_builtin=0", (qid,))
        return cur.rowcount


def get_meta(key):
    with _conn() as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(key, value):
    with _LOCK, _conn() as conn:
        conn.execute(
            "INSERT INTO app_meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def get_active_questionnaire_id():
    return get_meta("active_questionnaire_id")


def set_active_questionnaire(qid):
    if not get_questionnaire(qid):
        raise ValueError("问卷不存在")
    set_meta("active_questionnaire_id", qid)


def upsert_questionnaire_result(player_id, qid, tested):
    now = now_iso()
    values = (
        tested.get("mbti") or tested.get("result") or "",
        tested.get("type_name") or "",
        _dumps(tested.get("dims") or {}),
        _dumps(tested.get("params") or {}),
        _dumps(tested.get("answers") or []),
        1 if tested.get("test_fallback") else 0,
        tested.get("test_error") or None,
        now,
    )
    with _LOCK, _conn() as conn:
        conn.execute(
            "INSERT INTO questionnaire_results(player_id,questionnaire_id,result,type_name,"
            "dims,params,answers,test_fallback,test_error,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(player_id,questionnaire_id) DO UPDATE SET "
            "result=excluded.result,type_name=excluded.type_name,dims=excluded.dims,"
            "params=excluded.params,answers=excluded.answers,test_fallback=excluded.test_fallback,"
            "test_error=excluded.test_error,updated_at=excluded.updated_at",
            (player_id, qid, values[0], values[1], values[2], values[3], values[4],
             values[5], values[6], now, now),
        )
    return get_questionnaire_result(player_id, qid)


def get_questionnaire_result(player_id, qid):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM questionnaire_results WHERE player_id=? AND questionnaire_id=?",
            (player_id, qid),
        ).fetchone()
    return _decode_row("questionnaire_results", row)


def _player_with_result(row, qid):
    out = _decode_row("players", row)
    # The q_* columns are joined aliases, not part of the players table.
    q_result = out.pop("q_result", None)
    q_type_name = out.pop("q_type_name", None)
    q_dims = out.pop("q_dims", None)
    q_params = out.pop("q_params", None)
    q_answers = out.pop("q_answers", None)
    q_fallback = out.pop("q_fallback", None)
    q_created = out.pop("q_created_at", None)
    out["questionnaire_id"] = qid
    out["has_result"] = bool(q_result)
    out["result_created_at"] = q_created
    out["type_name"] = q_type_name or ""
    if q_result:
        out["mbti"] = q_result
        out["dims"] = _json_load(q_dims, {})
        out["params"] = _json_load(q_params, {})
        out["answers"] = _json_load(q_answers, [])
        out["test_fallback"] = int(q_fallback or 0)
    else:
        # Do not silently show another questionnaire's result as the active one.
        out["mbti"] = ""
        out["dims"] = {}
        out["params"] = {}
        out["answers"] = []
        out["test_fallback"] = 0
    return out


def _player_result_query(qid, tested_only=False):
    sql = (
        "SELECT p.*, r.result AS q_result, r.type_name AS q_type_name, "
        "r.dims AS q_dims, r.params AS q_params, r.answers AS q_answers, "
        "r.test_fallback AS q_fallback, r.created_at AS q_created_at "
        "FROM players p LEFT JOIN questionnaire_results r "
        "ON r.player_id=p.id AND r.questionnaire_id=?"
    )
    if tested_only:
        sql += " WHERE r.id IS NOT NULL"
    return sql


def list_players_for_questionnaire(qid, mbti=None, search="", dimensions=None,
                                   limit=200, offset=0, tested_only=False):
    clauses, values = [], []
    if tested_only:
        clauses.append("r.id IS NOT NULL")
    if mbti:
        clauses.append("r.result=?")
        values.append(mbti.upper())
    if search:
        clauses.append("(p.name LIKE ? OR p.occupation LIKE ? OR p.province LIKE ? OR r.result LIKE ?)")
        needle = "%" + search.strip() + "%"
        values.extend([needle, needle, needle, needle])
    for dim, letter in (dimensions or {}).items():
        if dim not in ("EI", "SN", "TF", "JP") or not letter:
            continue
        pos = {"EI": 1, "SN": 2, "TF": 3, "JP": 4}[dim]
        clauses.append("substr(r.result,?,1)=?")
        values.extend([pos, letter.upper()])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    base = _player_result_query(qid, tested_only=False)
    with _conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM (" + base + where + ")", [qid] + values
        ).fetchone()[0]
        rows = conn.execute(
            base + where + " ORDER BY p.created_at DESC, p.rowid DESC LIMIT ? OFFSET ?",
            [qid] + values + [int(limit), int(offset)],
        ).fetchall()
    return [_player_with_result(row, qid) for row in rows], total


def get_player_for_questionnaire(player_id, qid):
    items = get_players_for_questionnaire([player_id], qid)
    return items[0] if items else None


def get_players_for_questionnaire(ids, qid):
    ids = list(dict.fromkeys(x for x in ids if x))
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    with _conn() as conn:
        rows = conn.execute(
            _player_result_query(qid) + " WHERE p.id IN (%s)" % marks,
            [qid] + ids,
        ).fetchall()
    by_id = {row["id"]: _player_with_result(row, qid) for row in rows}
    return [by_id[x] for x in ids if x in by_id]


def players_without_questionnaire_result(qid):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT p.* FROM players p LEFT JOIN questionnaire_results r "
            "ON r.player_id=p.id AND r.questionnaire_id=? WHERE r.id IS NULL "
            "ORDER BY p.created_at ASC, p.rowid ASC",
            (qid,),
        ).fetchall()
    return [_decode_row("players", row) for row in rows]


def questionnaire_result_rows(qid):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT p.id,p.name,p.age,p.gender,p.province,p.occupation,"
            "r.result,r.type_name,r.created_at AS result_created_at "
            "FROM questionnaire_results r JOIN players p ON p.id=r.player_id "
            "WHERE r.questionnaire_id=? ORDER BY p.name",
            (qid,),
        ).fetchall()
    return [dict(row) for row in rows]


def questionnaire_comparison(left_id, right_id):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT p.id,p.name,p.age,p.gender,p.province,p.occupation,"
            "l.result AS left_result,l.type_name AS left_type,"
            "r.result AS right_result,r.type_name AS right_type "
            "FROM questionnaire_results l "
            "JOIN questionnaire_results r ON r.player_id=l.player_id AND r.questionnaire_id=? "
            "JOIN players p ON p.id=l.player_id "
            "WHERE l.questionnaire_id=? ORDER BY p.name",
            (right_id, left_id),
        ).fetchall()
    return [dict(row) for row in rows]


def player_type_counts_for_questionnaire(qid):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT result, COUNT(*) AS n FROM questionnaire_results "
            "WHERE questionnaire_id=? AND result<>'' GROUP BY result ORDER BY result",
            (qid,),
        ).fetchall()
    return {row["result"]: row["n"] for row in rows}


def player_dimension_counts_for_questionnaire(qid):
    types = player_type_counts_for_questionnaire(qid)
    out = {"EI": {"E": 0, "I": 0}, "SN": {"S": 0, "N": 0},
           "TF": {"T": 0, "F": 0}, "JP": {"J": 0, "P": 0}}
    for result, n in types.items():
        for key, pos in (("EI", 0), ("SN", 1), ("TF", 2), ("JP", 3)):
            if len(result) > pos:
                letter = result[pos]
                if letter in out[key]:
                    out[key][letter] += n
    return out


def player_stats_for_questionnaire(qid):
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        tested = conn.execute(
            "SELECT COUNT(*) FROM questionnaire_results WHERE questionnaire_id=? AND result<>''",
            (qid,),
        ).fetchone()[0]
        fallback = conn.execute(
            "SELECT COUNT(*) FROM questionnaire_results WHERE questionnaire_id=? AND test_fallback=1",
            (qid,),
        ).fetchone()[0]
        last = conn.execute("SELECT created_at FROM players ORDER BY created_at DESC LIMIT 1").fetchone()
    types = player_type_counts_for_questionnaire(qid)
    return {
        "total": int(total or 0),
        "tested": int(tested or 0),
        "coverage": round((tested or 0) / total, 4) if total else 0.0,
        "types": types,
        "type_count": sum(1 for n in types.values() if n > 0),
        "dimensions": player_dimension_counts_for_questionnaire(qid),
        "fallback": int(fallback or 0),
        "last_created": last["created_at"] if last else None,
        "questionnaire_id": qid,
    }


def backfill_builtin_results(qid):
    now = now_iso()
    with _LOCK, _conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO questionnaire_results(player_id,questionnaire_id,result,"
            "type_name,dims,params,answers,test_fallback,created_at,updated_at) "
            "SELECT id,?,mbti,'',dims,params,answers,test_fallback,created_at,? FROM players",
            (qid, now),
        )
        return cur.rowcount

# --------------------------------------------------------------------------
# simulations
# --------------------------------------------------------------------------
SIM_FIELDS = (
    "id", "no", "name", "created_at", "started_at", "finished_at", "status",
    "total_games", "completed_games", "variable_roles", "fixed_assignments",
    "seed", "current_game", "current_round", "error", "total_tokens", "config_json",
)


def mark_interrupted():
    """A restart cannot keep an in-memory game loop alive; park its batch as paused."""
    with _LOCK, _conn() as conn:
        conn.execute(
            "UPDATE simulations SET status='paused', "
            "error='服务重启，模拟已暂停。打开本次模拟点击继续，会从下一局恢复。' "
            "WHERE status IN ('running','stopping')"
        )


def create_simulation(sim):
    with _LOCK, _conn() as conn:
        no = (conn.execute("SELECT COALESCE(MAX(no),0) FROM simulations").fetchone()[0] or 0) + 1
        sim = dict(sim)
        sim["no"] = no
        sim.setdefault("created_at", now_iso())
        sim.setdefault("status", "created")
        values = []
        for field in SIM_FIELDS:
            value = sim.get(field)
            if field in ("variable_roles", "fixed_assignments", "config_json") and value is not None:
                value = _dumps(value)
            values.append(value)
        conn.execute(
            "INSERT INTO simulations(%s) VALUES(%s)" % (
                ",".join(SIM_FIELDS), ",".join("?" for _ in SIM_FIELDS)),
            values,
        )
    return sim["id"], no


def update_simulation(sim_id, **fields):
    if not fields:
        return
    values, assignments = [], []
    for key, value in fields.items():
        if key not in SIM_FIELDS:
            continue
        if key in ("variable_roles", "fixed_assignments", "config_json") and value is not None:
            value = _dumps(value)
        assignments.append(key + "=?")
        values.append(value)
    if not assignments:
        return
    values.append(sim_id)
    with _LOCK, _conn() as conn:
        conn.execute("UPDATE simulations SET " + ",".join(assignments) + " WHERE id=?", values)


def get_simulation(sim_id):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM simulations WHERE id=?", (sim_id,)).fetchone()
    return _decode_row("simulations", row)


def get_simulation_by_no(no):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM simulations WHERE no=?", (int(no),)).fetchone()
    return _decode_row("simulations", row)


def list_simulations(limit=100):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM simulations ORDER BY no DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [_decode_row("simulations", row) for row in rows]


# --------------------------------------------------------------------------
# games
# --------------------------------------------------------------------------
GAME_FIELDS = (
    "simulation_id", "game_no", "seed", "variable_type", "winner", "win_reason",
    "rounds", "variable_roles", "variable_camp_wins", "variable_player_wins",
    "variable_player_count", "duration_ms", "tokens", "degenerate", "detail", "created_at",
)

GAME_SUMMARY_FIELDS = (
    "simulation_id", "game_no", "seed", "variable_type", "winner", "win_reason",
    "rounds", "variable_roles", "variable_camp_wins", "variable_player_wins",
    "variable_player_count", "duration_ms", "tokens", "degenerate", "created_at",
)


def add_game(game):
    game = dict(game)
    game.setdefault("created_at", now_iso())
    values = []
    for field in GAME_FIELDS:
        value = game.get(field)
        if field in ("variable_roles", "variable_camp_wins", "detail") and value is not None:
            value = _dumps(value)
        values.append(value)
    with _LOCK, _conn() as conn:
        cur = conn.execute(
            "INSERT OR REPLACE INTO games(%s) VALUES(%s)" % (
                ",".join(GAME_FIELDS), ",".join("?" for _ in GAME_FIELDS)),
            values,
        )
        return cur.lastrowid


def list_games(sim_id, limit=50, offset=0, order="desc"):
    direction = "DESC" if order.lower() != "asc" else "ASC"
    with _conn() as conn:
        rows = conn.execute(
            "SELECT %s FROM games WHERE simulation_id=? ORDER BY game_no %s LIMIT ? OFFSET ?" % (
                ",".join(GAME_SUMMARY_FIELDS), direction),
            (sim_id, int(limit), int(offset)),
        ).fetchall()
    return [_decode_row("games", row) for row in rows]


def all_game_summaries(sim_id):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT %s FROM games WHERE simulation_id=? ORDER BY game_no ASC" % ",".join(GAME_SUMMARY_FIELDS),
            (sim_id,),
        ).fetchall()
    return [_decode_row("games", row) for row in rows]


def get_game(sim_id, game_no):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM games WHERE simulation_id=? AND game_no=?", (sim_id, int(game_no))
        ).fetchone()
    return _decode_row("games", row)


def count_games(sim_id):
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM games WHERE simulation_id=?", (sim_id,)).fetchone()[0]


def delete_simulation(sim_id):
    with _LOCK, _conn() as conn:
        conn.execute("DELETE FROM games WHERE simulation_id=?", (sim_id,))
        conn.execute("DELETE FROM simulations WHERE id=?", (sim_id,))


# --------------------------------------------------------------------------
# auth: users, sessions, verification codes (invite codes are reusable)
# --------------------------------------------------------------------------
def get_user_by_email(email):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE LOWER(email)=?", (str(email).strip().lower(),)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def create_user(email, invite_code):
    import uuid
    email = str(email).strip().lower()
    user_id = "usr_" + uuid.uuid4().hex[:16]
    stamp = now_iso()
    with _LOCK, _conn() as conn:
        try:
            conn.execute(
                "INSERT INTO users(id,email,invite_code,created_at,last_login_at,active) "
                "VALUES(?,?,?,?,?,1)",
                (user_id, email, invite_code or "", stamp, stamp),
            )
        except sqlite3.IntegrityError:
            return None
    return get_user_by_id(user_id)


def touch_user_login(user_id):
    with _LOCK, _conn() as conn:
        conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now_iso(), user_id))




def register_user(email, invite_code):
    """Create a user. Invite codes are reusable, so the code is stored on the
    user for audit but never consumed. If the email already exists (race
    between two verifies), the existing user is returned so the caller can
    simply log in.
    """
    import uuid
    email = str(email).strip().lower()
    with _LOCK, _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if row:
            return dict(row)
        user_id = "usr_" + uuid.uuid4().hex[:16]
        stamp = now_iso()
        try:
            conn.execute(
                "INSERT INTO users(id,email,invite_code,created_at,last_login_at,active) "
                "VALUES(?,?,?,?,?,1)",
                (user_id, email, invite_code or "", stamp, stamp),
            )
        except sqlite3.IntegrityError:
            row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            return dict(row) if row else None
    return get_user_by_id(user_id)


def create_auth_code(email, code_hash, expires_at):
    email = str(email).strip().lower()
    with _LOCK, _conn() as conn:
        conn.execute("UPDATE auth_codes SET consumed=1 WHERE email=? AND consumed=0", (email,))
        cur = conn.execute(
            "INSERT INTO auth_codes(email,code_hash,created_at,expires_at,attempts,consumed) "
            "VALUES(?,?,?,?,0,0)",
            (email, code_hash, now_iso(), expires_at),
        )
        return cur.lastrowid


def latest_auth_code(email):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM auth_codes WHERE email=? AND consumed=0 ORDER BY id DESC LIMIT 1",
            (str(email).strip().lower(),),
        ).fetchone()
    return dict(row) if row else None


def bump_auth_code(code_id):
    with _LOCK, _conn() as conn:
        conn.execute("UPDATE auth_codes SET attempts=attempts+1 WHERE id=?", (code_id,))
        row = conn.execute("SELECT attempts FROM auth_codes WHERE id=?", (code_id,)).fetchone()
    return int(row["attempts"]) if row else 0


def consume_auth_code(code_id):
    with _LOCK, _conn() as conn:
        conn.execute("UPDATE auth_codes SET consumed=1 WHERE id=?", (code_id,))


def invalidate_auth_codes(email):
    with _LOCK, _conn() as conn:
        conn.execute("UPDATE auth_codes SET consumed=1 WHERE email=? AND consumed=0",
                     (str(email).strip().lower(),))


def create_session(token_hash, user_id, expires_at, user_agent="", ip=""):
    with _LOCK, _conn() as conn:
        conn.execute(
            "INSERT INTO sessions(token_hash,user_id,created_at,expires_at,last_seen_at,user_agent,ip) "
            "VALUES(?,?,?,?,?,?,?)",
            (token_hash, user_id, now_iso(), expires_at, now_iso(), user_agent[:300], ip[:80]),
        )


def get_session(token_hash):
    with _conn() as conn:
        row = conn.execute(
            "SELECT s.*, u.email, u.created_at AS user_created_at, "
            "u.last_login_at AS user_last_login, u.active "
            "FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",
            (token_hash, now_iso()),
        ).fetchone()
    return dict(row) if row else None


def touch_session(token_hash):
    with _LOCK, _conn() as conn:
        conn.execute("UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (now_iso(), token_hash))


def delete_session(token_hash):
    with _LOCK, _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))


def delete_expired_sessions():
    with _LOCK, _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at<=?", (now_iso(),))
        conn.execute("DELETE FROM auth_codes WHERE expires_at<=? AND consumed=1", (now_iso(),))
