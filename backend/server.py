#!/usr/bin/env python3
"""HTTP API and static host for the MBTI werewolf lab."""
from __future__ import annotations

import faulthandler
import json
import os
import posixpath
import re
import signal
import sys
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import auth
import llm
import mbti
import profiler
import questionnaires
import simulation
import store

PORT = int(os.environ.get("WEREWOLF_PORT", "8791"))
DIST = os.path.join(_ROOT, "frontend", "dist")
ALLOWED_ORIGINS = {
    item.strip().rstrip("/")
    for item in (os.environ.get("WEREWOLF_ALLOWED_ORIGINS")
                 or "http://127.0.0.1:8791,http://localhost:8791,"
                    "http://127.0.0.1:5179,http://localhost:5179").split(",")
    if item.strip()
}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def _json_ready(value):
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    return value


def public_player(player):
    """Strip the heavy prompt/answer/raw snapshot from list payloads."""
    if not player:
        return player
    out = dict(player)
    out.pop("raw_json", None)
    out.pop("system_prompt", None)
    answers = out.pop("answers", None) or []
    out["answer_count"] = len(answers)
    return out


def public_questionnaire(item, include_definition=False):
    if not item:
        return item
    out = dict(item)
    definition = out.get("definition") or {}
    out["response_type"] = definition.get("response_type") or "binary"
    out["scoring_mode"] = (definition.get("scoring") or {}).get("mode") or "pole_majority"
    if not include_definition:
        out.pop("definition", None)
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "WerewolfLab/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------------------------ utils
    def _cors(self):
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
            self.send_header("Access-Control-Allow-Credentials", "true")

    def _send(self, status, payload, content_type="application/json; charset=utf-8", headers=None):
        body = payload
        if not isinstance(payload, (bytes, bytearray)):
            if content_type.startswith("application/json"):
                body = json.dumps(_json_ready(payload), ensure_ascii=False).encode("utf-8")
            else:
                body = str(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _error(self, status, message, code=None):
        payload = {"error": str(message)}
        if code:
            payload["code"] = code
        self._send(status, payload)

    def _client_ip(self):
        direct = self.client_address[0] if self.client_address else ""
        if direct in ("127.0.0.1", "::1"):
            forwarded = (self.headers.get("X-Real-IP") or self.headers.get("X-Forwarded-For") or "")
            if forwarded:
                return forwarded.split(",")[0].strip()[:80]
        return direct

    def _require_user(self, path):
        if path.startswith("/api/") and not auth.is_public_api(path):
            user = auth.current_user(self)
            if not user:
                self._error(401, "请先登录", "UNAUTHORIZED")
                return None
            return user
        return True

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 2_000_000:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("请求体不是合法 JSON")
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def _path(self):
        parsed = urlparse(self.path)
        return parsed.path, parse_qs(parsed.query)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        try:
            path, query = self._path()
            if path.startswith("/api/"):
                if self._require_user(path) is None:
                    return
                return self._api_get(path, query)
            return self._static(path)
        except auth.AuthError as exc:
            self._error(exc.status, exc.message, exc.code)
        except Exception as exc:
            traceback.print_exc()
            self._error(500, exc)

    def do_POST(self):
        try:
            path, query = self._path()
            if not path.startswith("/api/"):
                return self._error(404, "Not found")
            if self._require_user(path) is None:
                return
            body = self._body()
            return self._api_post(path, body)
        except auth.AuthError as exc:
            self._error(exc.status, exc.message, exc.code)
        except ValueError as exc:
            self._error(400, exc)
        except Exception as exc:
            traceback.print_exc()
            self._error(500, exc)

    def do_DELETE(self):
        try:
            path, query = self._path()
            if not path.startswith("/api/"):
                return self._error(404, "Not found")
            if self._require_user(path) is None:
                return
            return self._api_delete(path)
        except auth.AuthError as exc:
            self._error(exc.status, exc.message, exc.code)
        except ValueError as exc:
            self._error(400, exc)
        except Exception as exc:
            traceback.print_exc()
            self._error(500, exc)

    # ------------------------------------------------------------------ static
    def _static(self, path):
        rel = posixpath.normpath(unquote(path)).lstrip("/")
        if rel in ("", "."):
            rel = "index.html"
        target = os.path.join(DIST, rel)
        if not os.path.abspath(target).startswith(os.path.abspath(DIST)):
            return self._error(403, "Forbidden")
        if not os.path.isfile(target):
            # SPA fallback for hash-less routes.
            target = os.path.join(DIST, "index.html")
            if not os.path.isfile(target):
                return self._send(503, "前端尚未构建。请运行 ./build.sh 或 npm run build。",
                                  "text/plain; charset=utf-8")
        ext = os.path.splitext(target)[1].lower()
        content_type = MIME.get(ext, "application/octet-stream")
        with open(target, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if ext == ".html":
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ------------------------------------------------------------------ routes
    def _api_get(self, path, query):
        if path == "/api/auth/me":
            user = auth.current_user(self)
            if not user:
                return self._error(401, "请先登录", "UNAUTHORIZED")
            return self._send(200, {"user": user})

        if path == "/api/health":
            caps = {
                "deepseek_configured": llm.configured(),
                "audiencelib_configured": bool(
                    str(llm.CONFIG.data.get("audiencelib_api_key") or "").startswith("al_")),
                "model": llm.CONFIG.model,
                "db": os.path.relpath(store.DB_PATH, _ROOT),
            }
            try:
                stats = store.player_stats()
            except Exception:
                stats = {"total": 0}
            return self._send(200, {"ok": True, "service": "werewolf-lab", "capabilities": caps,
                                    "players": stats.get("total", 0)})

        if path == "/api/catalog":
            country = (query.get("country") or [""])[0].upper()
            cat = profiler.catalog()
            if country:
                cat = dict(cat)
                cat["countries"] = {country: cat["countries"][country]} if country in cat["countries"] else {}
            return self._send(200, cat)

        if path == "/api/players/stats":
            qid = store.get_active_questionnaire_id() or questionnaires.BUILTIN_ID
            stats = store.player_stats_for_questionnaire(qid)
            q = store.get_questionnaire(qid) or {}
            definition = q.get("definition") or {}
            stats["questionnaire"] = {"id": qid, "name": q.get("name") or "",
                                      "kind": definition.get("kind") or "generic"}
            return self._send(200, stats)

        if path == "/api/players":
            dimensions = {}
            for key, letters in (("EI", "EI"), ("SN", "SN"), ("TF", "TF"), ("JP", "JP")):
                value = (query.get(key) or [""])[0].upper()
                if value in letters:
                    dimensions[key] = value
            limit = max(1, min(int((query.get("limit") or [200])[0] or 200), 500))
            offset = max(0, int((query.get("offset") or [0])[0] or 0))
            qid = (query.get("questionnaire_id") or [""])[0] or store.get_active_questionnaire_id() or questionnaires.BUILTIN_ID
            tested_only = (query.get("tested") or [""])[0] in ("1", "true", "yes")
            players, total = store.list_players_for_questionnaire(
                qid,
                mbti=(query.get("type") or [""])[0].upper() or None,
                search=(query.get("q") or [""])[0],
                dimensions=dimensions, limit=limit, offset=offset,
                tested_only=tested_only,
            )
            return self._send(200, {"players": [public_player(p) for p in players],
                                    "total": total,
                                    "questionnaire_id": qid,
                                    "types": store.player_type_counts_for_questionnaire(qid)})

        match = re.fullmatch(r"/api/players/sample/([^/]+)", path)
        if match:
            job = profiler.get_job(match.group(1))
            if not job:
                return self._error(404, "抽样任务不存在")
            return self._send(200, job)

        if path == "/api/questionnaires":
            return self._send(200, {
                "items": [public_questionnaire(item) for item in store.list_questionnaires()],
                "active_id": store.get_active_questionnaire_id() or questionnaires.BUILTIN_ID,
            })

        if path == "/api/questionnaires/template":
            return self._send(200, {"definition": questionnaires.builtin_definition()})

        if path == "/api/questionnaires/conversion-prompt":
            prompt_path = os.path.join(_ROOT, "docs", "questionnaire-conversion-prompt.md")
            if not os.path.isfile(prompt_path):
                return self._error(404, "转换 Prompt 文档不存在")
            with open(prompt_path, encoding="utf-8") as fh:
                content = fh.read()
            return self._send(200, {
                "filename": "questionnaire-conversion-prompt.md",
                "content": content,
            })

        if path == "/api/questionnaires/compare":
            left = (query.get("left") or [""])[0]
            right = (query.get("right") or [""])[0]
            if not left or not right:
                raise ValueError("请提供 left 和 right 两个问卷 id")
            return self._send(200, questionnaires.compare(left, right))

        match = re.fullmatch(r"/api/questionnaires/jobs/([^/]+)", path)
        if match:
            job = questionnaires.get_job(match.group(1))
            if not job:
                return self._error(404, "问卷测试任务不存在")
            return self._send(200, job)

        match = re.fullmatch(r"/api/questionnaires/([^/]+)", path)
        if match:
            item = store.get_questionnaire(match.group(1))
            if not item:
                return self._error(404, "问卷不存在")
            return self._send(200, {"questionnaire": public_questionnaire(item)})

        match = re.fullmatch(r"/api/simulations/([^/]+)", path)
        if match:
            sim = store.get_simulation(match.group(1))
            if not sim:
                return self._error(404, "模拟不存在")
            return self._send(200, {"simulation": simulation.public_simulation(sim),
                                    "snapshot": simulation.simulation_snapshot(sim["id"])})

        match = re.fullmatch(r"/api/simulations/([^/]+)/live", path)
        if match:
            snap = simulation.simulation_snapshot(match.group(1))
            if not snap:
                return self._error(404, "模拟不存在")
            return self._send(200, snap)

        match = re.fullmatch(r"/api/simulations/([^/]+)/games", path)
        if match:
            sim_id = match.group(1)
            limit = max(1, min(int((query.get("limit") or [50])[0] or 50), 500))
            offset = max(0, int((query.get("offset") or [0])[0] or 0))
            order = (query.get("order") or ["desc"])[0]
            games = store.list_games(sim_id, limit=limit, offset=offset, order=order)
            return self._send(200, {"games": games, "total": store.count_games(sim_id)})

        match = re.fullmatch(r"/api/simulations/([^/]+)/games/(\d+)", path)
        if match:
            game = store.get_game(match.group(1), int(match.group(2)))
            if not game:
                return self._error(404, "该局不存在")
            return self._send(200, game)

        match = re.fullmatch(r"/api/simulations/([^/]+)/analysis", path)
        if match:
            data = simulation.analysis(match.group(1))
            if not data:
                return self._error(404, "模拟不存在")
            return self._send(200, data)

        if path == "/api/history":
            return self._send(200, {"items": simulation.history()})

        return self._error(404, "Not found")

    def _api_post(self, path, body):
        if path == "/api/auth/lookup":
            result = auth.lookup(body.get("email"), self._client_ip())
            return self._send(200, result)

        if path == "/api/auth/request-code":
            result = auth.request_code(
                body.get("email"), body.get("invite_code") or "", self._client_ip())
            return self._send(200, result)

        if path == "/api/auth/verify":
            user, token, registered = auth.verify_code(
                body.get("email"), body.get("code"),
                body.get("invite_code") or "", self._client_ip(),
                self.headers.get("User-Agent") or "",
            )
            return self._send(
                200, {"ok": True, "user": user, "registered": registered},
                headers={"Set-Cookie": auth.session_cookie(token, self)},
            )

        if path == "/api/auth/logout":
            auth.logout(self)
            return self._send(200, {"ok": True},
                              headers={"Set-Cookie": auth.clear_cookie()})

        if path == "/api/players/sample":
            job_id = profiler.start_sample_job(body)
            return self._send(200, {"job_id": job_id})

        if path == "/api/players/delete":
            ids = body.get("ids") or []
            if not isinstance(ids, list):
                raise ValueError("ids 必须是数组")
            removed = store.delete_players(ids)
            return self._send(200, {"removed": removed})

        match = re.fullmatch(r"/api/players/([^/]+)/retest", path)
        if match:
            player = store.get_player(match.group(1))
            if not player:
                return self._error(404, "玩家不存在")
            qid = store.get_active_questionnaire_id() or questionnaires.BUILTIN_ID
            definition = questionnaires.get_definition(qid)
            definition["_id"] = qid
            tested = questionnaires.run_test(player, definition)
            store.upsert_questionnaire_result(player["id"], qid, tested)
            if qid == questionnaires.BUILTIN_ID:
                store.add_player(tested)
            active = store.get_player_for_questionnaire(player["id"], qid) or store.get_player(player["id"])
            return self._send(200, {"player": public_player(active)})

        if path == "/api/questionnaires":
            user = auth.current_user(self) or {}
            definition = questionnaires.normalize_definition(
                body.get("definition") or body, body.get("name"))
            qid = "qn_" + uuid.uuid4().hex[:12]
            item = store.create_questionnaire({
                "id": qid, "name": definition["name"], "version": definition["version"],
                "description": definition["description"],
                "question_count": questionnaires.question_count(definition),
                "definition": definition, "is_builtin": 0,
                "created_by": user.get("email") or "unknown",
            })
            return self._send(200, {"questionnaire": public_questionnaire(item)})

        match = re.fullmatch(r"/api/questionnaires/([^/]+)/activate", path)
        if match:
            store.set_active_questionnaire(match.group(1))
            return self._send(200, {"ok": True, "active_id": match.group(1)})

        match = re.fullmatch(r"/api/questionnaires/([^/]+)/test-all", path)
        if match:
            job_id = questionnaires.start_test_job(match.group(1))
            return self._send(200, {"job_id": job_id})

        if path == "/api/simulations":
            sim = simulation.create_simulation(body)
            return self._send(200, {"simulation": simulation.public_simulation(sim)})

        match = re.fullmatch(r"/api/simulations/([^/]+)/(start|pause|resume|stop)", path)
        if match:
            sim_id, action = match.group(1), match.group(2)
            if action == "start":
                snap = simulation.start_simulation(sim_id)
            elif action == "pause":
                snap = simulation.pause_simulation(sim_id)
            elif action == "resume":
                snap = simulation.resume_simulation(sim_id)
            else:
                snap = simulation.stop_simulation(sim_id)
            return self._send(200, {"snapshot": snap})

        return self._error(404, "Not found")

    def _api_delete(self, path):
        match = re.fullmatch(r"/api/questionnaires/([^/]+)", path)
        if match:
            qid = match.group(1)
            item = store.get_questionnaire(qid)
            if not item:
                return self._error(404, "问卷不存在")
            if item.get("is_builtin"):
                raise ValueError("第一版内置问卷不能删除")
            if store.get_active_questionnaire_id() == qid:
                store.set_active_questionnaire(questionnaires.BUILTIN_ID)
            store.delete_questionnaire(qid)
            return self._send(200, {"deleted": True})
        match = re.fullmatch(r"/api/players/([^/]+)", path)
        if match:
            removed = store.delete_players([match.group(1)])
            return self._send(200, {"removed": removed})
        match = re.fullmatch(r"/api/simulations/([^/]+)", path)
        if match:
            store.delete_simulation(match.group(1))
            return self._send(200, {"deleted": True})
        return self._error(404, "Not found")


def main():
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    store.init_db()
    questionnaires.ensure_seed()
    store.mark_interrupted()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Werewolf lab API: http://127.0.0.1:%d" % PORT, flush=True)
    print("Static root: %s" % DIST, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
