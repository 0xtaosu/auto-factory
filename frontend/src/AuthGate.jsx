import { AlertTriangle, Eye, EyeOff, Loader2, LogIn } from 'lucide-react';
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { getSession, isUnauthorized, login, logoutSession } from './api.js';

const AuthContext = createContext(null);

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used within AuthGate');
  return value;
}

function validSession(value) {
  return Boolean(value) && value.role === 'admin' && typeof value.expires_at === 'string' && value.expires_at;
}

export default function AuthGate({ children }) {
  const [session, setSession] = useState(null);
  const [phase, setPhase] = useState('checking');
  const [expired, setExpired] = useState(false);
  const [bootError, setBootError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [logoutError, setLogoutError] = useState(null);
  const [logoutArmed, setLogoutArmed] = useState(false);
  const secretHeldRef = useRef(false);
  const logoutLock = useRef(false);

  const setSecretHeld = useCallback((held) => {
    secretHeldRef.current = Boolean(held);
  }, []);

  const finishLogout = useCallback(() => {
    secretHeldRef.current = false;
    setLogoutArmed(false);
    setLogoutError(null);
    setExpired(false);
    setSession(null);
    setPhase('anonymous');
  }, []);

  const performLogout = useCallback(async (force = false) => {
    if (!force && secretHeldRef.current) {
      setLogoutArmed(true);
      return;
    }
    if (logoutLock.current) return;
    logoutLock.current = true;
    setLogoutError(null);
    try {
      await logoutSession();
      finishLogout();
    } catch (error) {
      if (isUnauthorized(error)) {
        finishLogout();
        return;
      }
      setLogoutError(error?.message || '退出失败，登录会话可能仍然有效');
    } finally {
      logoutLock.current = false;
    }
  }, [finishLogout]);

  const logout = useCallback(async () => {
    await performLogout(false);
  }, [performLogout]);

  const notifyUnauthorized = useCallback(() => {
    secretHeldRef.current = false;
    setLogoutArmed(false);
    setLogoutError(null);
    setSession(null);
    setExpired(true);
    setPhase('anonymous');
  }, []);

  useEffect(() => {
    let cancelled = false;
    setPhase('checking');
    setBootError(null);
    getSession()
      .then((next) => {
        if (cancelled) return;
        if (!validSession(next)) {
          setSession(null);
          setBootError('登录状态响应无效');
          setPhase('error');
          return;
        }
        setSession(next);
        setExpired(false);
        setPhase('ready');
      })
      .catch((error) => {
        if (cancelled) return;
        if (isUnauthorized(error)) {
          setSession(null);
          setPhase('anonymous');
          return;
        }
        setSession(null);
        setBootError(error?.message || '无法确认登录状态');
        setPhase('error');
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const contextValue = useMemo(() => ({
    session,
    logout,
    notifyUnauthorized,
    setSecretHeld,
  }), [session, logout, notifyUnauthorized, setSecretHeld]);

  let screen = null;
  if (phase === 'checking') {
    screen = (
      <main className="app-shell">
        <section className="upload-band">
          <p className="status-line">
            <Loader2 className="spin" size={18} />
            正在确认登录状态
          </p>
        </section>
      </main>
    );
  } else if (phase === 'error') {
    screen = (
      <main className="app-shell">
        <BrandBar />
        <section className="upload-band">
          <div className="login-card">
            <h2>暂时无法确认登录</h2>
            <ErrorNote message={bootError || '无法确认登录状态'} />
            <div className="button-row">
              <button className="icon-text-btn primary-btn" type="button" onClick={() => setAttempt((value) => value + 1)}>
                重试
              </button>
              <button
                className="icon-text-btn"
                type="button"
                onClick={() => {
                  setBootError(null);
                  setSession(null);
                  setPhase('anonymous');
                }}
              >
                前往登录
              </button>
            </div>
          </div>
        </section>
      </main>
    );
  } else if (phase !== 'ready' || !session) {
    screen = (
      <LoginScreen
        expired={expired}
        onSuccess={(next) => {
          setSession(next);
          setExpired(false);
          setPhase('ready');
        }}
      />
    );
  }

  return (
    <AuthContext.Provider value={contextValue}>
      {screen || (
        <>
          {logoutError && (
            <div className="app-shell">
              <ErrorNote message={logoutError} />
            </div>
          )}
          {children}
        </>
      )}
      {logoutArmed && (
        <div className="dialog-backdrop">
          <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="leave-secret-title">
            <h2 id="leave-secret-title">完整密钥仍在页面上</h2>
            <p>退出后无法再次查看这把密钥。请先复制并保存，或确认放弃后再退出。</p>
            <div className="button-row">
              <button className="icon-text-btn" type="button" onClick={() => setLogoutArmed(false)}>
                留在页面
              </button>
              <button
                className="icon-text-btn danger-btn"
                type="button"
                onClick={() => {
                  setLogoutArmed(false);
                  void performLogout(true);
                }}
              >
                仍然退出
              </button>
            </div>
          </div>
        </div>
      )}
    </AuthContext.Provider>
  );
}

function LoginScreen({ expired, onSuccess }) {
  const [token, setToken] = useState('');
  const [showToken, setShowToken] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (submitting) return;
    const nextToken = token.trim();
    if (!nextToken) {
      setFormError('请输入管理员令牌');
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const next = await login(nextToken);
      if (!validSession(next)) {
        setFormError('登录响应无效');
        return;
      }
      setToken('');
      setShowToken(false);
      onSuccess(next);
    } catch (error) {
      setFormError(loginErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="app-shell">
      <BrandBar />
      <section className="upload-band">
        <form className="login-card" method="post" action="#" onSubmit={handleSubmit}>
          <div>
            <span className="eyebrow">管理员</span>
            <h2>登录</h2>
          </div>
          <p className="help">
            请输入本服务器本地生成的管理员密钥，或部署时配置的管理员令牌。
          </p>
          <p className="help">
            令牌只用于这一次登录请求。页面不会把它写入本地存储，也不会放进网址；登录成功后浏览器只保留服务端设置的会话 Cookie。
          </p>
          {expired && <p className="notice">登录已失效。请重新输入管理员令牌。未登录时不会显示物料数据或密钥。</p>}
          <label className="stack-field">
            管理员令牌
            <span className="secret-input">
              <input
                type={showToken ? 'text' : 'password'}
                value={token}
                autoComplete="off"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                disabled={submitting}
                autoFocus
                onChange={(event) => setToken(event.target.value)}
              />
              <button
                className="icon-text-btn ghost-btn"
                type="button"
                onClick={() => setShowToken((value) => !value)}
                aria-pressed={showToken}
              >
                {showToken ? <EyeOff size={16} /> : <Eye size={16} />}
                {showToken ? '隐藏' : '显示'}
              </button>
            </span>
          </label>
          {formError && <ErrorNote message={formError} />}
          <button className="icon-text-btn primary-btn" type="submit" disabled={submitting}>
            {submitting ? <Loader2 className="spin" size={16} /> : <LogIn size={16} />}
            {submitting ? '正在登录' : '登录'}
          </button>
        </form>
      </section>
    </main>
  );
}

function BrandBar() {
  return (
    <header className="topbar">
      <div className="brand">
        <div>
          <h1>物料活动评估</h1>
          <p>管理员登录后才能查看物料分析和密钥</p>
        </div>
      </div>
    </header>
  );
}

function ErrorNote({ message }) {
  return (
    <div className="error-panel" role="alert">
      <AlertTriangle size={20} />
      <strong>{message}</strong>
    </div>
  );
}

function loginErrorMessage(error) {
  if (isUnauthorized(error)) {
    if (error.message && !/^HTTP 401$/.test(error.message)) return error.message;
    return '管理员令牌不正确';
  }
  if (error?.status === 429) return error.message || '尝试过于频繁，请稍后再试';
  if (error?.status === 422) return error.message || '登录请求无效';
  return error?.message || '登录失败';
}
