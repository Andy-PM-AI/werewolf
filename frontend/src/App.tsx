import { useCallback, useEffect, useState } from "react";
import { api } from "./lib/api";
import type { AuthUser, Catalog, PlayerStats } from "./lib/types";
import { LogoMark, Icon } from "./components/Icons";
import { Spinner, useToast } from "./components/Ui";
import { PlayersPage } from "./pages/PlayersPage";
import { SimulatePage } from "./pages/SimulatePage";
import { HistoryDetailPage, HistoryPage } from "./pages/HistoryPage";
import { LoginPage } from "./pages/LoginPage";
import { QuestionnairesPage } from "./pages/QuestionnairesPage";
import { QuestionnaireComparePage } from "./pages/QuestionnaireComparePage";

type Route =
  | { page: "players" }
  | { page: "simulate"; simId?: string }
  | { page: "history" }
  | { page: "history-detail"; simId: string }
  | { page: "questionnaires" }
  | { page: "questionnaire-compare"; left: string; right: string };

function parseRoute(hash: string): Route {
  const path = (hash || "#/players").replace(/^#/, "");
  if (path.startsWith("/simulate/")) {
    return { page: "simulate", simId: path.split("/")[2] };
  }
  if (path.startsWith("/simulate")) return { page: "simulate" };
  if (path.startsWith("/history/")) {
    return { page: "history-detail", simId: path.split("/")[2] };
  }
  if (path.startsWith("/history")) return { page: "history" };
  if (path.startsWith("/questionnaires/compare/")) {
    const parts = path.split("/");
    return { page: "questionnaire-compare", left: parts[3] || "", right: parts[4] || "" };
  }
  if (path.startsWith("/questionnaires")) return { page: "questionnaires" };
  return { page: "players" };
}

export default function App() {
  const toast = useToast();
  const [hash, setHash] = useState(() => window.location.hash || "#/players");
  const [authState, setAuthState] = useState<"checking" | "out" | "in">("checking");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [health, setHealth] = useState<{
    ok: boolean;
    capabilities: {
      deepseek_configured: boolean;
      audiencelib_configured: boolean;
      model: string;
      db: string;
    };
    players: number;
  } | null>(null);
  const [playerStats, setPlayerStats] = useState<PlayerStats | null>(null);
  const [booting, setBooting] = useState(true);

  const route = parseRoute(hash);

  const navigate = useCallback((path: string) => {
    const next = path.startsWith("#") ? path : `#${path}`;
    if (window.location.hash === next) {
      setHash(next);
    } else {
      window.location.hash = next;
    }
  }, []);

  useEffect(() => {
    const onHash = () => {
      setHash(window.location.hash || "#/players");
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.me()
      .then(({ user: me }) => {
        if (!cancelled) {
          setUser(me);
          setAuthState("in");
        }
      })
      .catch(() => {
        if (!cancelled) setAuthState("out");
      });
    const onUnauthorized = () => {
      setAuthState("out");
      setUser(null);
      setBooting(false);
      toast.push("登录已过期，请重新登录", "info");
    };
    window.addEventListener("werewolf:unauthorized", onUnauthorized);
    return () => {
      cancelled = true;
      window.removeEventListener("werewolf:unauthorized", onUnauthorized);
    };
  }, [toast]);

  useEffect(() => {
    if (authState !== "in") return;
    let cancelled = false;
    setBooting(true);
    (async () => {
      try {
        const [h, stats] = await Promise.all([api.health(), api.playerStats()]);
        if (!cancelled) {
          setHealth(h);
          setPlayerStats(stats);
        }
      } catch (err) {
        if (!cancelled) toast.push(err instanceof Error ? err.message : "无法连接后端", "error");
      }
      try {
        const data = await api.catalog();
        if (!cancelled) setCatalog(data);
      } catch {
        // The catalog is only needed when the sampling dialog opens; keep the UI usable.
      } finally {
        if (!cancelled) setBooting(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authState, toast]);

  useEffect(() => {
    if (authState !== "in") return;
    const timer = window.setInterval(async () => {
      try {
        const [h, stats] = await Promise.all([api.health(), api.playerStats()]);
        setHealth(h);
        setPlayerStats(stats);
      } catch {
        // Keep the last known status; the page itself surfaces request errors.
      }
    }, 20000);
    return () => window.clearInterval(timer);
  }, [authState]);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // The cookie is cleared locally even if the network call fails.
    }
    setAuthState("out");
    setUser(null);
    setHash("#/players");
    window.location.hash = "#/players";
  }, []);

  const navItems = [
    { key: "players", label: "玩家库", icon: "users", path: "/players", hint: playerStats ? `${playerStats.total} 人` : "" },
    { key: "simulate", label: "游戏模拟", icon: "play", path: "/simulate", hint: "" },
    { key: "history", label: "历史记录", icon: "history", path: "/history", hint: "" },
    { key: "questionnaires", label: "问卷管理", icon: "layers", path: "/questionnaires", hint: "" },
  ];

  const activeKey = route.page === "history-detail" ? "history" : route.page === "questionnaire-compare" ? "questionnaires" : route.page;

  if (authState !== "in") {
    if (authState === "checking") {
      return (
        <div className="boot boot--full">
          <LogoMark size={46} />
          <div className="boot__text">
            <b>正在检查登录状态</b>
            <span>确认这个浏览器是否有可用的实验台会话…</span>
          </div>
          <Spinner size={24} />
        </div>
      );
    }
    return <LoginPage onSuccess={(me) => { setUser(me); setAuthState("in"); }} />;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button type="button" className="brand" onClick={() => navigate("/players")}>
          <LogoMark size={38} />
          <span className="brand__text">
            <b>人格狼人杀</b>
            <em>PERSONA WEREWOLF LAB</em>
          </span>
        </button>

        <nav className="nav">
          <div className="nav__label">实验台</div>
          {navItems.map((item) => (
            <button
              type="button"
              key={item.key}
              className={`nav__item ${activeKey === item.key ? "is-active" : ""}`}
              onClick={() => navigate(item.path)}
            >
              <span className="nav__icon"><Icon name={item.icon} size={18} /></span>
              <span className="nav__text">{item.label}</span>
              {item.hint ? <span className="nav__hint">{item.hint}</span> : null}
              {activeKey === item.key ? <span className="nav__active-bar" /> : null}
            </button>
          ))}
        </nav>

        <div className="sidebar__brief">
          <div className="sidebar__brief-head"><Icon name="moon" size={15} /> 受控实验</div>
          <p>9 / 10 人局 · 3 狼 / 3–4 民 / 预女猎，屠边判胜。每局只改变变量角色的性格标签。</p>
          <div className="sidebar__brief-stats">
            <span><b>8</b> 轮上限</span>
            <span><b>多套</b> 问卷</span>
            <span><b>7</b> 行为参数</span>
          </div>
        </div>

        <div className="sidebar__foot">
          <div className="system-status">
            <span className={`system-status__dot ${health?.capabilities.deepseek_configured ? "is-ok" : "is-bad"}`} />
            <span>DeepSeek</span>
            <em>{health?.capabilities.model || "未连接"}</em>
          </div>
          <div className="system-status">
            <span className={`system-status__dot ${health?.capabilities.audiencelib_configured ? "is-ok" : "is-bad"}`} />
            <span>AudienceLib</span>
            <em>{health?.capabilities.audiencelib_configured ? "人口库已授权" : "未配置"}</em>
          </div>
          <div className="sidebar__user">
            <span className="sidebar__user-avatar">{(user?.email || "?").slice(0, 1).toUpperCase()}</span>
            <span className="sidebar__user-text">
              <b>{user?.email || ""}</b>
              <em>已登录</em>
            </span>
            <button type="button" className="sidebar__logout" onClick={logout} title="退出登录" aria-label="退出登录">
              <Icon name="logout" size={15} />
            </button>
          </div>
          <div className="sidebar__version">v1.0 · 内部演示</div>
        </div>
      </aside>

      <main className="main">
        {booting && !health ? (
          <div className="boot">
            <LogoMark size={44} />
            <div className="boot__text">
              <b>正在连接实验台</b>
              <span>读取 DeepSeek、AudienceLib 与本地玩家库…</span>
            </div>
            <Spinner size={24} />
          </div>
        ) : null}
        {route.page === "players" ? <PlayersPage catalog={catalog} onNavigate={navigate} /> : null}
        {route.page === "simulate" ? <SimulatePage simId={route.simId} onNavigate={navigate} /> : null}
        {route.page === "history" ? <HistoryPage onNavigate={navigate} /> : null}
        {route.page === "history-detail" ? <HistoryDetailPage simId={route.simId} onNavigate={navigate} /> : null}
        {route.page === "questionnaires" ? <QuestionnairesPage onNavigate={navigate} /> : null}
        {route.page === "questionnaire-compare" ? <QuestionnaireComparePage left={route.left} right={route.right} onNavigate={navigate} /> : null}
      </main>
    </div>
  );
}
