import { AlertTriangle, Check, Copy, Loader2, Trash2 } from 'lucide-react';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  createApiKey,
  defaultMcpUrl,
  getMcpInfo,
  isUnauthorized,
  listApiKeys,
  revokeApiKey,
} from './api.js';
import { useAuth } from './AuthGate.jsx';

const READ_SCOPE = 'activity:read';
const ANALYZE_SCOPE = 'activity:analyze';
const KEY_PLACEHOLDER = '<YOUR_API_KEY>';

const STATUS_LABELS = {
  active: '有效',
  expired: '已过期',
  revoked: '已撤销',
};

export default function ApiKeys() {
  const { notifyUnauthorized, setSecretHeld } = useAuth();
  const loadGen = useRef(0);
  const copyTimer = useRef(0);
  const [items, setItems] = useState(null);
  const [listError, setListError] = useState(null);
  const [mcp, setMcp] = useState(null);
  const [mcpError, setMcpError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState('');
  const [allowAnalyze, setAllowAnalyze] = useState(false);
  const [expiry, setExpiry] = useState('');
  const [formError, setFormError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [revealed, setRevealed] = useState(null);
  const [revokeTarget, setRevokeTarget] = useState(null);
  const [revokeError, setRevokeError] = useState(null);
  const [revoking, setRevoking] = useState(false);
  const [mcpUrl, setMcpUrl] = useState(defaultMcpUrl);
  const [copied, setCopied] = useState(null);
  const [copyError, setCopyError] = useState(null);

  const refresh = useCallback(async () => {
    const gen = ++loadGen.current;
    setLoading(true);
    const [keysResult, mcpResult] = await Promise.allSettled([listApiKeys(), getMcpInfo()]);
    if (gen !== loadGen.current) return;

    if (keysResult.status === 'rejected') {
      if (isUnauthorized(keysResult.reason)) {
        notifyUnauthorized();
        return;
      }
      setListError(keysResult.reason?.message || '密钥列表加载失败');
    } else if (!keysResult.value || !Array.isArray(keysResult.value.items)) {
      setListError('密钥列表响应无效');
    } else {
      setItems(keysResult.value.items);
      setListError(null);
    }

    if (mcpResult.status === 'rejected') {
      if (isUnauthorized(mcpResult.reason)) {
        notifyUnauthorized();
        return;
      }
      setMcpError(mcpResult.reason?.message || 'MCP 信息加载失败');
    } else {
      setMcp(mcpResult.value && typeof mcpResult.value === 'object' ? mcpResult.value : null);
      setMcpError(mcpResult.value && typeof mcpResult.value === 'object' ? null : 'MCP 信息响应无效');
    }
    setLoading(false);
  }, [notifyUnauthorized]);

  useEffect(() => {
    void refresh();
    return () => {
      loadGen.current += 1;
    };
  }, [refresh]);

  useEffect(() => {
    setSecretHeld(Boolean(revealed));
    return () => setSecretHeld(false);
  }, [revealed, setSecretHeld]);

  useEffect(() => () => {
    if (copyTimer.current) window.clearTimeout(copyTimer.current);
  }, []);

  useEffect(() => {
    if (!revealed) return undefined;
    const onBeforeUnload = (event) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [revealed]);

  useEffect(() => {
    if (!revokeTarget) return undefined;
    const onKey = (event) => {
      if (event.key === 'Escape' && !revoking) setRevokeTarget(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [revokeTarget, revoking]);

  async function handleCreate(event) {
    event.preventDefault();
    if (creating) return;
    if (revealed) {
      setFormError('请先复制并关闭当前密钥，再创建下一把。');
      return;
    }
    const trimmedName = name.trim();
    if (trimmedName.length < 1 || trimmedName.length > 80) {
      setFormError('名称需要 1 到 80 个字符');
      return;
    }
    let expiresAt = null;
    if (expiry) {
      const date = new Date(expiry);
      if (Number.isNaN(date.getTime()) || date.getTime() <= Date.now()) {
        setFormError('到期时间必须晚于当前时间');
        return;
      }
      expiresAt = date.toISOString();
    }
    const scopes = [READ_SCOPE];
    if (allowAnalyze) scopes.push(ANALYZE_SCOPE);
    setCreating(true);
    setFormError(null);
    try {
      const result = await createApiKey({
        name: trimmedName,
        scopes,
        expires_at: expiresAt,
      });
      if (typeof result?.key !== 'string' || result.key.length === 0) {
        setFormError('服务端没有返回完整密钥。如果列表里出现了新记录，请撤销后重新创建。');
        await refresh();
        return;
      }
      setRevealed(result.key);
      setName('');
      setExpiry('');
      await refresh();
    } catch (error) {
      if (isUnauthorized(error)) {
        notifyUnauthorized();
        return;
      }
      setFormError(error?.message || '创建密钥失败');
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke() {
    if (!revokeTarget || revoking) return;
    setRevoking(true);
    setRevokeError(null);
    try {
      await revokeApiKey(revokeTarget.key_id);
      const revokedId = revokeTarget.key_id;
      setItems((current) => (Array.isArray(current)
        ? current.map((item) => (item.key_id === revokedId
          ? { ...item, status: 'revoked', revoked_at: item.revoked_at || new Date().toISOString() }
          : item))
        : current));
      setRevokeTarget(null);
      await refresh();
    } catch (error) {
      if (isUnauthorized(error)) {
        notifyUnauthorized();
        return;
      }
      setRevokeError(error?.message || '撤销失败');
    } finally {
      setRevoking(false);
    }
  }

  function markCopied(kind) {
    setCopied(kind);
    if (copyTimer.current) window.clearTimeout(copyTimer.current);
    copyTimer.current = window.setTimeout(() => setCopied(null), 2000);
  }

  async function copyValue(kind, value) {
    try {
      await copyText(value);
      setCopyError(null);
      markCopied(kind);
    } catch (error) {
      setCopyError(error?.message || '复制失败');
    }
  }

  const configText = mcpConfigText(mcpUrl);
  const loopback = isLoopbackUrl(mcpUrl.trim());
  const tools = Array.isArray(mcp?.tools) ? mcp.tools : [];
  const scopeInfo = Array.isArray(mcp?.scopes) ? mcp.scopes : [];

  return (
    <section className="keys-page">
      <div className="panel">
        <h2>MCP / API Keys</h2>
        <p className="help">
          在这里签发独立 API 密钥。密钥不能再签发其他密钥、创建登录会话或管理凭据。所有密钥访问的都是本项目数据，不按密钥隔离数据集。
        </p>
      </div>

      {revealed && (
        <div className="secret-reveal" role="status">
          <strong>这把密钥只显示这一次</strong>
          <p>
            关闭或离开后无法再查看完整密钥，列表里以后只有前缀。请现在复制并保存到安全的地方。页面不会把它写入本地存储或网址。
          </p>
          <input
            className="secret-value"
            readOnly
            value={revealed}
            aria-label="新创建的 API 密钥"
            autoComplete="off"
            spellCheck={false}
            onFocus={(event) => event.target.select()}
          />
          {copyError && <ErrorNote message={copyError} />}
          <div className="button-row">
            <button className="icon-text-btn primary-btn" type="button" onClick={() => void copyValue('secret', revealed)}>
              {copied === 'secret' ? <Check size={16} /> : <Copy size={16} />}
              {copied === 'secret' ? '已复制' : '复制密钥'}
            </button>
            <button className="icon-text-btn" type="button" onClick={() => setRevealed(null)}>
              我已保存，关闭
            </button>
          </div>
        </div>
      )}

      <form className="panel" method="post" action="#" onSubmit={handleCreate}>
        <h3>创建独立密钥</h3>
        <div className="form-grid">
          <label className="stack-field">
            名称
            <input
              value={name}
              maxLength={80}
              disabled={creating}
              autoComplete="off"
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：质检只读"
            />
          </label>
          <label className="stack-field">
            到期时间（可选）
            <input
              type="datetime-local"
              value={expiry}
              min={localDateTimeMin()}
              disabled={creating}
              onChange={(event) => setExpiry(event.target.value)}
              onInvalid={(event) => {
                event.preventDefault();
                setFormError('到期时间必须晚于当前时间');
              }}
            />
          </label>
        </div>
        <div className="scope-list">
          <label className="check-row">
            <input type="checkbox" checked readOnly disabled />
            <span>读取 activity:read（必需）</span>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={allowAnalyze}
              disabled={creating}
              onChange={(event) => setAllowAnalyze(event.target.checked)}
            />
            <span>分析 activity:analyze（可选）</span>
          </label>
        </div>
        <p className="help">留空到期时间表示不过期。填写时必须是未来的时间。未勾选分析时只授予读取权限。</p>
        {formError && <ErrorNote message={formError} />}
        <div className="button-row">
          <button className="icon-text-btn primary-btn" type="submit" disabled={creating}>
            {creating ? <Loader2 className="spin" size={16} /> : null}
            {creating ? '正在创建' : '创建密钥'}
          </button>
        </div>
      </form>

      <div className="table-wrap">
        <div className="section-heading">
          <h3>已签发的密钥</h3>
          {(listError || mcpError) && (
            <button className="icon-text-btn" type="button" onClick={() => void refresh()}>
              重试
            </button>
          )}
        </div>
        <p className="help">完整密钥不会出现在列表中。状态和最后使用时间以服务端记录为准。</p>
        {listError && <ErrorNote message={listError} />}
        {loading && items == null && !listError && (
          <p className="status-line">
            <Loader2 className="spin" size={16} />
            正在加载密钥
          </p>
        )}
        {Array.isArray(items) && items.length === 0 && (
          <p className="help">还没有独立密钥。</p>
        )}
        {Array.isArray(items) && items.length > 0 && (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>名称</th>
                  <th>前缀</th>
                  <th>权限</th>
                  <th>状态</th>
                  <th>最后使用</th>
                  <th>到期</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.key_id}>
                    <td>
                      <strong>{item.name}</strong>
                      <div className="muted">创建于 {formatDateTime(item.created_at)}</div>
                    </td>
                    <td className="mono">{item.prefix}</td>
                    <td>{formatScopes(item.scopes)}</td>
                    <td>
                      <span className={`badge ${statusTone(item.status)}`}>{statusLabel(item.status)}</span>
                      {item.revoked_at && <div className="muted">撤销于 {formatDateTime(item.revoked_at)}</div>}
                    </td>
                    <td>{item.last_used_at ? formatDateTime(item.last_used_at) : '从未使用'}</td>
                    <td>{item.expires_at ? formatDateTime(item.expires_at) : '不过期'}</td>
                    <td>
                      {item.status === 'revoked' ? (
                        <span className="muted">已撤销</span>
                      ) : (
                        <button
                          className="icon-text-btn danger-btn"
                          type="button"
                          onClick={() => {
                            setRevokeError(null);
                            setRevokeTarget(item);
                          }}
                        >
                          <Trash2 size={16} />
                          撤销
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel">
        <h3>连接 MCP</h3>
        {mcpError && <ErrorNote message={mcpError} />}
        <div className="meta-row mcp-meta">
          <Info label="服务端路径" value={mcp?.endpoint_path || '/mcp'} />
          <Info label="传输" value={mcp?.transport || 'streamable-http'} />
          <Info label="认证" value={mcp?.auth || 'bearer-api-key'} />
        </div>
        <p className="help">{dataAccessCopy(mcp?.data_access)}</p>
        <p className="notice">
          密钥通过请求头 Authorization: Bearer 使用，只适用于允许自定义请求头的 Streamable HTTP 客户端。只支持 OAuth 登录的客户端不能使用这些密钥。下面的 JSON 是通用示例，不表示所有 MCP 客户端都兼容。
        </p>
        {tools.length > 0 && (
          <ul className="plain-list">
            {tools.map((tool) => (
              <li key={tool.name}>
                <span className="mono">{tool.name}</span>
                {tool.description ? `：${tool.description}` : ''}
              </li>
            ))}
          </ul>
        )}
        {scopeInfo.length > 0 && (
          <ul className="plain-list">
            {scopeInfo.map((scope) => (
              <li key={scope.name}>
                <span className="mono">{scope.name}</span>
                {scope.description ? `：${scope.description}` : ''}
              </li>
            ))}
          </ul>
        )}
        <label className="stack-field">
          MCP 地址
          <input
            value={mcpUrl}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setMcpUrl(event.target.value)}
          />
        </label>
        <p className="help">
          开发环境若设置了 VITE_API_BASE，就用该地址；未配置时使用当前页面的主机名加 8000 端口，在 localhost 打开是 http://localhost:8000/mcp，在 127.0.0.1 打开是 http://127.0.0.1:8000/mcp。生产环境默认是当前网站同源的 /mcp。把配置交给远程客户端前，请改成对方能够访问的地址。页面不会把本机地址自动换成对外地址。
        </p>
        {loopback && (
          <p className="notice">
            当前地址指向本机。其他机器上的客户端不能靠这个地址访问你的电脑，除非那台机器确实能连通这里。需要远程使用时，请改成外部可访问的 URL。
          </p>
        )}
        <label className="stack-field">
          mcpServers 配置
          <textarea className="mcp-json" readOnly value={configText} spellCheck={false} />
        </label>
        <p className="help">
          {`配置中的 ${KEY_PLACEHOLDER} 是占位符。复制密钥后自行替换它，并保留 Bearer 前缀。页面不会把完整密钥写进这段 JSON。`}
        </p>
        {copyError && <ErrorNote message={copyError} />}
        <div className="button-row">
          <button
            className="icon-text-btn"
            type="button"
            disabled={!mcpUrl.trim()}
            onClick={() => void copyValue('url', mcpUrl.trim())}
          >
            {copied === 'url' ? <Check size={16} /> : <Copy size={16} />}
            {copied === 'url' ? '已复制地址' : '复制地址'}
          </button>
          <button
            className="icon-text-btn"
            type="button"
            disabled={!mcpUrl.trim()}
            onClick={() => void copyValue('json', configText)}
          >
            {copied === 'json' ? <Check size={16} /> : <Copy size={16} />}
            {copied === 'json' ? '已复制配置' : '复制连接配置'}
          </button>
        </div>
      </div>

      {revokeTarget && (
        <div
          className="dialog-backdrop"
          onMouseDown={() => {
            if (!revoking) setRevokeTarget(null);
          }}
        >
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="revoke-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <h2 id="revoke-title">撤销密钥</h2>
            <p>
              {`确认撤销「${revokeTarget.name}」（前缀 ${revokeTarget.prefix}）？撤销后使用该密钥的客户端会立即失去访问权限，而且不能恢复。`}
            </p>
            {revokeError && <ErrorNote message={revokeError} />}
            <div className="button-row">
              <button className="icon-text-btn" type="button" disabled={revoking} onClick={() => setRevokeTarget(null)} autoFocus>
                取消
              </button>
              <button className="icon-text-btn danger-btn" type="button" disabled={revoking} onClick={() => void handleRevoke()}>
                {revoking ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}
                {revoking ? '正在撤销' : '确认撤销'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
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

function Info({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className="mono">{value}</strong>
    </div>
  );
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status || '未知';
}

function statusTone(status) {
  if (status === 'active' || status === 'expired' || status === 'revoked') return status;
  return 'muted';
}

function formatScopes(scopes) {
  if (!Array.isArray(scopes) || scopes.length === 0) return '未提供';
  return scopes.map((scope) => {
    if (scope === READ_SCOPE) return '读取';
    if (scope === ANALYZE_SCOPE) return '分析';
    return scope;
  }).join('、');
}

function formatDateTime(value) {
  if (!value) return '未提供';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(date);
}

function localDateTimeMin() {
  const date = new Date();
  const pad = (part) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function dataAccessCopy(value) {
  if (!value || value === 'All keys access this project data; no per-key dataset isolation.') {
    return '所有密钥都访问本项目数据，不按密钥隔离数据集。';
  }
  return value;
}

function mcpConfigText(url) {
  return JSON.stringify({
    mcpServers: {
      'inventory-activity': {
        url: url.trim(),
        headers: {
          Authorization: `Bearer ${KEY_PLACEHOLDER}`,
        },
      },
    },
  }, null, 2);
}

function isLoopbackUrl(value) {
  if (!value) return false;
  try {
    const url = new URL(value);
    return ['localhost', '127.0.0.1', '::1', '0.0.0.0'].includes(url.hostname);
  } catch {
    return /localhost|127\.0\.0\.1|0\.0\.0\.0/i.test(value);
  }
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      /* fall through to the selection copy */
    }
  }
  const area = document.createElement('textarea');
  area.value = value;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.left = '-9999px';
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand('copy');
  area.remove();
  if (!ok) throw new Error('当前环境无法访问剪贴板');
}
