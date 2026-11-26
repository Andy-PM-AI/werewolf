import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { AuthUser } from "../lib/types";
import { Button, useToast } from "../components/Ui";
import { Icon, LogoMark } from "../components/Icons";

type Step = "email" | "invite" | "code";

function validEmail(value: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value.trim());
}

export function LoginPage({ onSuccess }: { onSuccess: (user: AuthUser) => void }) {
  const toast = useToast();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [invite, setInvite] = useState("");
  const [code, setCode] = useState("");
  const [registered, setRegistered] = useState<boolean | null>(null);
  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [cooldown, setCooldown] = useState(0);
  const [ttl, setTtl] = useState(10);
  const codeRef = useRef<HTMLInputElement>(null);
  const inviteRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => {
      setCooldown((value) => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [cooldown]);

  useEffect(() => {
    if (step === "code") {
      window.setTimeout(() => codeRef.current?.focus(), 80);
    }
    if (step === "invite") {
      window.setTimeout(() => inviteRef.current?.focus(), 80);
    }
  }, [step]);

  const sendCode = async (inviteValue: string, existing = registered === true) => {
    setSending(true);
    setError("");
    setNotice("");
    try {
      const result = await api.requestCode(email.trim(), existing ? "" : inviteValue.trim());
      setRegistered(result.registered);
      setTtl(Math.max(1, Math.round(result.expires_in / 60)));
      setCooldown(result.resend_after || 60);
      setStep("code");
      setNotice(
        result.registered
          ? `验证码已发送至 ${email.trim()}，${Math.max(1, Math.round(result.expires_in / 60))} 分钟内有效。`
          : `注册验证码已发送至 ${email.trim()}，${Math.max(1, Math.round(result.expires_in / 60))} 分钟内有效。`,
      );
      if (result.debug_code) {
        toast.push("本地 dry-run：验证码已写入 backend/data/outbox", "info");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送验证码失败");
    } finally {
      setSending(false);
    }
  };

  const continueWithEmail = async () => {
    if (!validEmail(email)) {
      setError("请输入有效的邮箱地址");
      return;
    }
    setSending(true);
    setError("");
    setNotice("");
    try {
      const result = await api.lookup(email.trim());
      setRegistered(result.registered);
      if (result.registered) {
        await sendCode("", true);
      } else {
        setStep("invite");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "查询邮箱失败");
    } finally {
      setSending(false);
    }
  };

  const submitInvite = () => {
    if (!invite.trim()) {
      setError("请输入邀请码");
      return;
    }
    sendCode(invite, false);
  };

  const verify = async () => {
    if (!/^\d{6}$/.test(code.trim())) {
      setError("请输入 6 位数字验证码");
      return;
    }
    setVerifying(true);
    setError("");
    try {
      const result = await api.verify(email.trim(), code.trim(), registered ? "" : invite.trim());
      onSuccess(result.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "验证码验证失败");
    } finally {
      setVerifying(false);
    }
  };

  const backToEmail = () => {
    setStep("email");
    setCode("");
    setInvite("");
    setError("");
    setNotice("");
    setRegistered(null);
  };

  return (
    <div className="login-page">
      <div className="login-visual">
        <div className="login-visual__glow" />
        <div className="login-brand">
          <LogoMark size={42} />
          <div>
            <b>人格狼人杀</b>
            <span>PERSONA WEREWOLF LAB</span>
          </div>
        </div>
        <div className="login-visual__body">
          <div className="login-tag"><span /> INVITE ONLY · 受邀请制内部实验</div>
          <h1>先证明你是受邀者，<br />再进入牌桌。</h1>
          <p>
            玩家库来自 AudienceLib 人口样本，每一位玩家都要完成一套人格问卷，可上传多套问卷并对比结果；9 或 10 人局由硬编码裁判运行。
            登录只为一件事：不让陌生人替你消耗模型 Token。
          </p>
          <div className="login-features">
            <div><Icon name="users" size={17} /><span><b>人口样本</b><em>按国家、年龄、性别等维度抽取</em></span></div>
            <div><Icon name="sparkles" size={17} /><span><b>多套人格问卷</b><em>结果与玩家绑定，可按问卷对比</em></span></div>
            <div><Icon name="moon" size={17} /><span><b>受控 9 / 10 人局</b><em>每局只改变变量角色的性格</em></span></div>
          </div>
        </div>
        <div className="login-visual__foot">
          <span><Icon name="eye" size={14} /> 角色信息按座位隔离，模型不会拿到上帝视角</span>
        </div>
      </div>

      <div className="login-panel">
        <div className="login-card">
          <div className="login-card__head">
            <div className="eyebrow">SECURE ACCESS</div>
            <h2>{step === "code" ? (registered ? "输入登录验证码" : "完成注册") : "登录 / 注册"}</h2>
            <p>
              {step === "email"
                ? "同一个入口。已注册用户只需邮箱验证码，首次使用需要邀请码。"
                : step === "invite"
                  ? "这个邮箱还没有注册。输入邀请码，我们会把注册验证码发到邮箱。"
                  : registered
                    ? "验证码已发送。输入后即可进入实验台。"
                    : "验证码已发送。输入后完成注册，并直接登录。"}
            </p>
          </div>

          <div className="login-steps">
            <span className={step === "email" ? "is-active" : step === "invite" ? "is-active" : "is-done"}>
              <i>1</i> 邮箱
            </span>
            <span className="login-steps__line" />
            <span className={step === "code" ? "is-active" : ""}>
              <i>2</i> 验证码
            </span>
            <span className="login-steps__line" />
            <span className={step === "code" ? "is-next" : ""}>
              <i>3</i> 进入实验台
            </span>
          </div>

          {step === "email" ? (
            <div className="login-form">
              <label className="login-field">
                <span>邮箱</span>
                <div className="login-input">
                  <Icon name="user" size={16} />
                  <input
                    type="email"
                    autoComplete="email"
                    placeholder="you@example.com"
                    value={email}
                    autoFocus
                    onChange={(event) => setEmail(event.target.value)}
                    onKeyDown={(event) => event.key === "Enter" && continueWithEmail()}
                  />
                </div>
              </label>
              <Button
                variant="primary"
                size="lg"
                className="login-submit"
                loading={sending}
                disabled={!email.trim()}
                onClick={continueWithEmail}
              >
                继续
                <Icon name="chevronRight" size={16} />
              </Button>
              <p className="login-help">
                <Icon name="info" size={13} />
                首次注册需要邀请码；注册成功后，下次登录只需邮箱验证码。
              </p>
            </div>
          ) : null}

          {step === "invite" ? (
            <div className="login-form">
              <div className="login-email-chip">
                <Icon name="user" size={15} />
                <span>{email.trim()}</span>
                <button type="button" onClick={backToEmail}>更换</button>
              </div>
              <label className="login-field">
                <span>邀请码</span>
                <div className="login-input">
                  <Icon name="flag" size={16} />
                  <input
                    ref={inviteRef}
                    placeholder="WOLF-XXXX-XXXX"
                    value={invite}
                    autoComplete="off"
                    onChange={(event) => setInvite(event.target.value)}
                    onKeyDown={(event) => event.key === "Enter" && submitInvite()}
                  />
                </div>
              </label>
              <Button
                variant="primary"
                size="lg"
                className="login-submit"
                loading={sending}
                disabled={!invite.trim()}
                onClick={submitInvite}
              >
                注册并发送验证码
              </Button>
              <p className="login-help">
                <Icon name="info" size={13} />
                邀请码由实验负责人发放，可给多位受邀者重复使用。
              </p>
            </div>
          ) : null}

          {step === "code" ? (
            <div className="login-form">
              <div className="login-email-chip">
                <Icon name="user" size={15} />
                <span>{email.trim()}</span>
                <button type="button" onClick={backToEmail}>更换</button>
              </div>
              <label className="login-field">
                <span>6 位验证码</span>
                <div className="login-input login-input--code">
                  <Icon name="check" size={16} />
                  <input
                    ref={codeRef}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    placeholder="000000"
                    value={code}
                    onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                    onKeyDown={(event) => event.key === "Enter" && verify()}
                  />
                </div>
              </label>
              <div className="login-code-actions">
                <span>{registered ? "已注册邮箱" : "新邮箱 · 首次注册"}</span>
                <button
                  type="button"
                  className="link-btn"
                  disabled={cooldown > 0 || sending}
                  onClick={() => sendCode(invite, registered === true)}
                >
                  {cooldown > 0 ? `${cooldown}s 后可重新发送` : "重新发送验证码"}
                </button>
              </div>
              <Button
                variant="primary"
                size="lg"
                className="login-submit"
                loading={verifying}
                disabled={code.length !== 6}
                onClick={verify}
              >
                {registered ? "登录" : "注册并登录"}
              </Button>
              <p className="login-help">
                <Icon name="clock" size={13} />
                验证码 {ttl} 分钟内有效，只能使用一次。没收到请检查垃圾邮件，或重新发送。
              </p>
            </div>
          ) : null}

          {error ? (
            <div className="login-error">
              <Icon name="alert" size={15} />
              <span>{error}</span>
            </div>
          ) : null}
          {notice && !error ? (
            <div className="login-notice">
              <Icon name="check" size={15} />
              <span>{notice}</span>
            </div>
          ) : null}

          <div className="login-card__foot">
            <span><Icon name="moon" size={13} /> 验证码登录</span>
            <span>受邀请制 · 不开放公开注册</span>
          </div>
        </div>
        <p className="login-panel__note">
          这是一个内部实验工具。登录只用于访问控制，不收集你的业务数据；玩家库与模拟记录保存在本机 SQLite。
        </p>
      </div>
    </div>
  );
}
