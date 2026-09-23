import {
  AlertTriangle,
  ArrowLeft,
  Download,
  FileSpreadsheet,
  Filter,
  KeyRound,
  Loader2,
  LogOut,
  RefreshCw,
  Search,
  Upload,
} from 'lucide-react';
import React, { useEffect, useRef, useState } from 'react';
import ApiKeys from './ApiKeys.jsx';
import { useAuth } from './AuthGate.jsx';
import {
  createJob,
  downloadResult,
  getAssessments,
  getConfig,
  getExplanation,
  getJob,
  getOverview,
  isUnauthorized,
} from './api.js';

const PAGE_SIZE = 50;
const LIMITATION_NOTICE = '当前数据不能确认存在正库存，也不能完整观测 365 天以上无交易群体。';

export default function App() {
  const [config, setConfig] = useState(null);
  const [observationDate, setObservationDate] = useState('');
  const [thresholdDays, setThresholdDays] = useState('');
  const [job, setJob] = useState(null);
  const [overview, setOverview] = useState(null);
  const [assessments, setAssessments] = useState({ total: 0, items: [] });
  const [queryInput, setQueryInput] = useState('');
  const [query, setQuery] = useState('');
  const [inactiveOnly, setInactiveOnly] = useState(false);
  const [page, setPage] = useState(0);
  const [selectedCode, setSelectedCode] = useState(null);
  const [explanation, setExplanation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState(null);
  const [listReloadToken, setListReloadToken] = useState(0);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState(null);
  const [view, setView] = useState('analysis');
  const [keysVisited, setKeysVisited] = useState(false);
  const requestGen = useRef(0);
  const { logout, notifyUnauthorized } = useAuth();

  function selectView(next) {
    if (next === 'keys') setKeysVisited(true);
    setView(next);
  }

  useEffect(() => {
    let cancelled = false;
    getConfig()
      .then((next) => {
        if (cancelled) return;
        setConfig(next);
        setObservationDate(next.observation_date || '');
        setThresholdDays(next.policy?.threshold_value == null ? '' : String(next.policy.threshold_value));
      })
      .catch((err) => {
        if (cancelled) return;
        if (isUnauthorized(err)) {
          notifyUnauthorized();
          return;
        }
        setError({ message: '无法加载默认配置', details: [err.message] });
      });
    return () => {
      cancelled = true;
    };
  }, [notifyUnauthorized]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(queryInput.trim());
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [queryInput]);

  useEffect(() => {
    if (!job || job.status !== 'completed' || selectedCode) return undefined;
    let cancelled = false;
    setListLoading(true);
    setListError(null);
    getAssessments(job.job_id, {
      q: query,
      inactiveOnly,
      offset: page * PAGE_SIZE,
      limit: PAGE_SIZE,
    })
      .then((data) => {
        if (cancelled) return;
        setAssessments(data);
      })
      .catch((err) => {
        if (cancelled) return;
        if (isUnauthorized(err)) {
          notifyUnauthorized();
          return;
        }
        setAssessments({ total: 0, items: [] });
        setListError({ message: '评估列表加载失败', details: [err.message] });
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [job, query, inactiveOnly, page, selectedCode, listReloadToken, notifyUnauthorized]);

  async function handleUpload(file) {
    if (!file) return;
    const thresholdError = validateThreshold(thresholdDays);
    const dateError = validateIsoDate(observationDate);
    if (thresholdError || dateError) {
      setError({ message: '请先修正分析参数', details: [dateError, thresholdError].filter(Boolean) });
      return;
    }
    const gen = ++requestGen.current;
    setLoading(true);
    setError(null);
    setListError(null);
    setOverview(null);
    setAssessments({ total: 0, items: [] });
    setSelectedCode(null);
    setExplanation(null);
    setPage(0);
    try {
      const created = await createJob(file, {
        observationDate: observationDate || undefined,
        thresholdDays: thresholdDays === '' ? undefined : Number(thresholdDays),
      });
      if (gen !== requestGen.current) return;
      const nextJob = await getJob(created.job_id);
      if (gen !== requestGen.current) return;
      setJob(nextJob);
      if (nextJob.status === 'failed') {
        setError(normalizeJobError(nextJob.error));
        return;
      }
      const nextOverview = await getOverview(created.job_id);
      if (gen !== requestGen.current) return;
      setOverview(nextOverview);
    } catch (err) {
      if (gen !== requestGen.current) return;
      if (isUnauthorized(err)) {
        notifyUnauthorized();
        return;
      }
      setError({ message: '分析任务失败', details: [err.message] });
    } finally {
      if (gen === requestGen.current) setLoading(false);
    }
  }

  async function openExplanation(materialCode) {
    if (!job) return;
    const gen = ++requestGen.current;
    setDetailLoading(true);
    setError(null);
    try {
      const next = await getExplanation(job.job_id, materialCode);
      if (gen !== requestGen.current) return;
      setSelectedCode(materialCode);
      setExplanation(next);
    } catch (err) {
      if (gen !== requestGen.current) return;
      if (isUnauthorized(err)) {
        notifyUnauthorized();
        return;
      }
      setError({ message: '证据详情加载失败', details: [err.message] });
    } finally {
      if (gen === requestGen.current) setDetailLoading(false);
    }
  }

  async function handleDownload(format) {
    if (!job) return;
    setError(null);
    try {
      await downloadResult(job.job_id, format);
    } catch (err) {
      if (isUnauthorized(err)) {
        notifyUnauthorized();
        return;
      }
      setError({ message: `下载 ${format} 失败`, details: [err.message] });
    }
  }

  function resetDemo() {
    requestGen.current += 1;
    setLoading(false);
    setDetailLoading(false);
    setListLoading(false);
    setJob(null);
    setOverview(null);
    setAssessments({ total: 0, items: [] });
    setQueryInput('');
    setQuery('');
    setInactiveOnly(false);
    setPage(0);
    setSelectedCode(null);
    setExplanation(null);
    setError(null);
    setListError(null);
  }

  const requestPending = loading || detailLoading;

  return (
    <main className="app-shell">
      <Header
        job={job}
        resetDisabled={requestPending}
        onReset={resetDemo}
        view={view}
        onView={selectView}
        onLogout={() => {
          void logout();
        }}
      />
      <div className={view === 'analysis' ? 'view-panel' : 'view-panel view-hidden'} inert={view === 'analysis' ? undefined : true}>
        {error && <ErrorPanel error={error} />}
        {!overview && (
          <UploadPanel
            config={config}
            loading={loading}
            observationDate={observationDate}
            thresholdDays={thresholdDays}
            onObservationDate={setObservationDate}
            onThresholdDays={setThresholdDays}
            onUpload={handleUpload}
          />
        )}
        {overview && !selectedCode && (
          <ResultScreen
            job={job}
            overview={overview}
            assessments={assessments}
            queryInput={queryInput}
            inactiveOnly={inactiveOnly}
            page={page}
            loading={loading || detailLoading}
            listLoading={listLoading}
            listError={listError}
            onQueryInput={setQueryInput}
            onInactiveOnly={(value) => {
              setInactiveOnly(value);
              setPage(0);
            }}
            onPage={setPage}
            onOpen={openExplanation}
            onDownload={handleDownload}
            onRetryList={() => setListReloadToken((token) => token + 1)}
          />
        )}
        {overview && selectedCode && (
          <DetailScreen
            explanation={explanation}
            loading={detailLoading}
            onBack={() => {
              setSelectedCode(null);
              setExplanation(null);
            }}
          />
        )}
      </div>
      {keysVisited && (
        <div className={view === 'keys' ? 'view-panel' : 'view-panel view-hidden'} inert={view === 'keys' ? undefined : true}>
          <ApiKeys />
        </div>
      )}
    </main>
  );
}

function Header({ job, resetDisabled, onReset, view, onView, onLogout }) {
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark">
          <FileSpreadsheet size={21} />
        </div>
        <div>
          <h1>物料活动评估</h1>
          <p>{job?.filename || '上传 ERP 进出库 Excel，按策略识别长期无交易物料候选'}</p>
        </div>
      </div>
      <nav className="view-nav" aria-label="功能">
        <button
          className="icon-text-btn"
          type="button"
          aria-current={view === 'analysis' ? 'page' : undefined}
          onClick={() => onView('analysis')}
        >
          物料分析
        </button>
        <button
          className="icon-text-btn"
          type="button"
          aria-current={view === 'keys' ? 'page' : undefined}
          onClick={() => onView('keys')}
        >
          <KeyRound size={16} />
          MCP / API Keys
        </button>
      </nav>
      <div className="top-actions">
        {job && view === 'analysis' && (
          <button className="icon-text-btn" disabled={resetDisabled} onClick={onReset} type="button">
            <RefreshCw size={16} />
            重新上传
          </button>
        )}
        <button className="icon-text-btn" onClick={onLogout} type="button">
          <LogOut size={16} />
          退出
        </button>
      </div>
    </header>
  );
}

function UploadPanel({
  config,
  loading,
  observationDate,
  thresholdDays,
  onObservationDate,
  onThresholdDays,
  onUpload,
}) {
  const policy = config?.policy;
  return (
    <section className="upload-band">
      <div className="upload-card">
        <p className="notice">{LIMITATION_NOTICE}</p>
        <div className="config-grid">
          <label>
            观察日
            <input
              type="date"
              value={observationDate}
              disabled={loading}
              onChange={(event) => onObservationDate(event.target.value)}
            />
          </label>
          <label>
            无交易天数阈值
            <input
              type="number"
              min="0"
              step="1"
              inputMode="numeric"
              value={thresholdDays}
              disabled={loading}
              onChange={(event) => onThresholdDays(event.target.value)}
            />
          </label>
          <Metric label="数据窗口" value={formatRange(config?.data_window_start, config?.data_window_end)} />
          <Metric
            label="默认策略"
            value={policy ? `${policy.policy_name}（>= ${displayValue(policy.threshold_value)} ${thresholdUnitLabel(policy.threshold_unit)}）` : '加载中'}
          />
        </div>
        <label className="upload-drop">
          <input
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            disabled={loading}
            onChange={(event) => {
              onUpload(event.target.files?.[0]);
              event.target.value = '';
            }}
          />
          <span className="upload-icon">
            {loading ? <Loader2 className="spin" size={32} /> : <Upload size={32} />}
          </span>
          <strong>{loading ? '正在分析 Excel' : '上传进出库 Excel'}</strong>
          <span>仅支持 .xlsx。可选填写观察日与阈值；留空则使用服务端默认配置。分析失败不会展示零值概览。</span>
        </label>
      </div>
    </section>
  );
}

function ResultScreen({
  job,
  overview,
  assessments,
  queryInput,
  inactiveOnly,
  page,
  loading,
  listLoading,
  listError,
  onQueryInput,
  onInactiveOnly,
  onPage,
  onOpen,
  onDownload,
  onRetryList,
}) {
  const counts = overview.counts || {};
  const recency = overview.days_since_last_movement || {};
  const policy = overview.policy || {};
  const totalPages = Math.max(1, Math.ceil((assessments.total || 0) / PAGE_SIZE));
  return (
    <section className="dashboard">
      <p className="notice">{LIMITATION_NOTICE}</p>
      <div className="conclusion">
        <div className="conclusion-copy">
          <span className="eyebrow">策略判定</span>
          <h2>长期无交易物料候选</h2>
          <p className="subcopy">
            {displayValue(policy.policy_name)}（{displayValue(policy.policy_id)}）：距末次交易
            {' '}{displayValue(policy.operator)} {displayValue(policy.threshold_value)} {thresholdUnitLabel(policy.threshold_unit)}
            列为候选。ActiveMaterial 仅表示未达该阈值，不是库存健康结论。失败任务不会在此显示零值。
          </p>
        </div>
        <div className="score-pill">
          <span>{displayCount(counts.inactive_candidate_count)}</span>
          <small>候选物料</small>
        </div>
      </div>

      <div className="meta-row">
        <Metric label="观察日" value={displayValue(overview.observation_date)} />
        <Metric label="数据窗口" value={formatRange(overview.data_window_start, overview.data_window_end)} />
        <Metric label="源文件" value={job?.filename || '未提供'} />
        <Metric label="任务状态" value={job?.status === 'completed' ? '已完成' : displayValue(job?.status)} />
      </div>

      <div className="indicator-grid compact">
        <CountCard label="源记录" value={counts.total_records} hint={`有效 ${displayCount(counts.valid_records)} / 无效 ${displayCount(counts.invalid_records)}`} />
        <CountCard label="物料编码" value={counts.material_count} hint={`入库 ${displayCount(counts.inbound_count)} / 出库 ${displayCount(counts.outbound_count)}`} />
        <CountCard label="长期无交易候选" value={counts.inactive_candidate_count} hint={`>=90 天 ${displayCount(counts.ge_90_count)} / >=180 天 ${displayCount(counts.ge_180_count)}`} accent="amber" />
        <CountCard label="单位冲突物料" value={counts.quantity_unavailable_count} hint={`主数据冲突 ${displayCount(counts.material_metadata_conflict_count)}`} accent="red" />
      </div>

      <div className="meta-row">
        <Metric label="距末次交易 最小" value={formatDays(recency.min)} />
        <Metric label="中位数" value={formatDays(recency.median)} />
        <Metric label="P75 / P90" value={`${formatDays(recency.p75)} / ${formatDays(recency.p90)}`} />
        <Metric label="最大" value={formatDays(recency.max)} />
      </div>

      {overview.limitations?.length > 0 && (
        <ul className="limitation-list">
          {overview.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}

      {overview.baseline_comparison?.length > 0 && (
        <div className="table-wrap">
          <h3>基线对照</h3>
          <table>
            <thead>
              <tr>
                <th>指标</th>
                <th>期望</th>
                <th>实际</th>
                <th>差额</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {overview.baseline_comparison.map((row) => (
                <tr key={row.metric}>
                  <td>{row.metric}</td>
                  <td>{displayValue(row.expected)}</td>
                  <td>{displayValue(row.actual)}</td>
                  <td>{displayValue(row.diff)}</td>
                  <td>{displayValue(row.reason)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="download-row">
        {[
          ['json', 'JSON 全量'],
          ['csv', 'CSV 评估'],
          ['ttl', 'Turtle 图谱'],
          ['report', 'Markdown 报告'],
        ].map(([format, label]) => (
          <button key={format} className="icon-text-btn" disabled={loading} onClick={() => onDownload(format)} type="button">
            <Download size={16} />
            {label}
          </button>
        ))}
      </div>

      <div className="table-wrap">
        <div className="list-toolbar">
          <label className="search-field">
            <Search size={16} />
            <input
              value={queryInput}
              placeholder="按物料编码或名称搜索"
              onChange={(event) => onQueryInput(event.target.value)}
            />
          </label>
          <label className="filter-field">
            <Filter size={16} />
            <input
              type="checkbox"
              checked={inactiveOnly}
              onChange={(event) => onInactiveOnly(event.target.checked)}
            />
            仅长期无交易候选
          </label>
          <span className="list-meta">
            {listLoading
              ? '列表加载中…'
              : listError
                ? '当前查询未加载成功'
                : `共 ${displayCount(assessments.total)} 条，第 ${page + 1} / ${totalPages} 页`}
          </span>
        </div>
        {listError ? (
          <div className="list-error">
            <ErrorPanel error={listError} />
            <button className="icon-text-btn" disabled={listLoading} onClick={onRetryList} type="button">
              <RefreshCw size={16} />
              重试当前查询
            </button>
          </div>
        ) : (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>物料</th>
                    <th>分类</th>
                    <th>距末次交易</th>
                    <th>末次日期</th>
                    <th>窗口频次</th>
                    <th>年出库数量</th>
                    <th>单位状态</th>
                  </tr>
                </thead>
                <tbody>
                  {assessments.items.length === 0 ? (
                    <tr>
                      <td colSpan={7}>{listLoading ? '正在加载评估结果' : emptyListCopy(queryInput, inactiveOnly)}</td>
                    </tr>
                  ) : (
                    assessments.items.map((item) => (
                      <tr key={item.assessment_id || item.material_code}>
                        <td>
                          <button className="link-btn" disabled={loading} onClick={() => onOpen(item.material_code)} type="button">
                            {displayValue(item.material_code)}
                          </button>
                          <div className="muted">{displayValue(item.material_name)}</div>
                        </td>
                        <td>
                          <span className={`badge ${classificationTone(item)}`}>{classificationLabel(item)}</span>
                        </td>
                        <td>{formatDays(item.days_since_last_movement)}</td>
                        <td>{displayValue(item.last_movement_date)}</td>
                        <td>{displayValue(item.movement_frequency)}</td>
                        <td>
                          <QuantityCell
                            total={item.annual_outbound_quantity}
                            byUnit={item.annual_outbound_quantity_by_unit}
                            status={item.quantity_aggregation_status}
                          />
                        </td>
                        <td>
                          <UnitStatus item={item} />
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <div className="pager">
              <button className="icon-text-btn" disabled={page <= 0 || listLoading} onClick={() => onPage(page - 1)} type="button">
                上一页
              </button>
              <button className="icon-text-btn" disabled={page + 1 >= totalPages || listLoading} onClick={() => onPage(page + 1)} type="button">
                下一页
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function DetailScreen({ explanation, loading, onBack }) {
  if (loading && !explanation) {
    return (
      <section className="detail-view">
        <button className="back-btn" onClick={onBack} type="button">
          <ArrowLeft size={16} />
          返回评估列表
        </button>
        <Loader2 className="spin" size={20} />
      </section>
    );
  }
  if (!explanation) return null;
  const assessment = explanation.assessment || {};
  const policy = explanation.policy || {};
  return (
    <section className="detail-view">
      <button className="back-btn" onClick={onBack} type="button">
        <ArrowLeft size={16} />
        返回评估列表
      </button>
      <div className={`detail-heading ${classificationTone(assessment)}`}>
        <span>{classificationLabel(assessment)}</span>
        <h2>
          {displayValue(assessment.material_code)} {displayValue(assessment.material_name, { empty: '' })}
        </h2>
        <p>{explanation.explanation}</p>
      </div>
      <p className="notice">{LIMITATION_NOTICE}</p>
      <div className="meta-row">
        <Metric label="规格" value={displayValue(assessment.material_specification)} />
        <Metric label="类别" value={displayValue(assessment.material_category)} />
        <Metric label="展示单位" value={displayValue(assessment.unit)} />
        <Metric label="策略" value={`${displayValue(policy.policy_id)} >= ${displayValue(assessment.threshold_value)} 天`} />
        <Metric label="观察日" value={displayValue(assessment.observation_date)} />
        <Metric label="末次交易日" value={displayValue(assessment.last_movement_date)} />
        <Metric label="距末次交易" value={formatDays(assessment.days_since_last_movement)} />
        <Metric label="窗口频次" value={displayValue(assessment.movement_frequency)} />
      </div>
      <UnitConflictPanel assessment={assessment} />
      {explanation.limitations?.length > 0 && (
        <ul className="limitation-list">
          {explanation.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
      <ObservationTable rows={explanation.metric_observations || []} />
      <EventTable rows={explanation.last_movement_events || []} />
      <SourceTable rows={explanation.source_records || []} />
    </section>
  );
}

function UnitConflictPanel({ assessment }) {
  const conflicts = assessment.metadata_conflicts;
  const unitConflict = assessment.quantity_aggregation_status === 'unit_conflict';
  return (
    <div className="split-panels">
      <div className={`conflict-box ${unitConflict ? 'warn' : ''}`}>
        <h3>数量合计</h3>
        {unitConflict ? (
          <p>存在单位冲突，年出库合计保持为空，不跨单位换算或相加。</p>
        ) : (
          <p>年出库合计：{displayQuantity(assessment.annual_outbound_quantity)}</p>
        )}
        <dl>
          <div>
            <dt>年出库（分单位）</dt>
            <dd>
              <UnitMap map={assessment.annual_outbound_quantity_by_unit} />
            </dd>
          </div>
          <div>
            <dt>年入库（分单位）</dt>
            <dd>
              <UnitMap map={assessment.annual_inbound_quantity_by_unit} />
            </dd>
          </div>
        </dl>
      </div>
      <div className={`conflict-box ${hasConflicts(conflicts) ? 'warn' : ''}`}>
        <h3>主数据冲突</h3>
        {hasConflicts(conflicts) ? <ValueTree value={conflicts} /> : <p>该编码未报告主数据冲突。</p>}
      </div>
    </div>
  );
}

function ObservationTable({ rows }) {
  return (
    <div className="table-wrap">
      <h3>指标观测</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>指标</th>
              <th>数值</th>
              <th>单位</th>
              <th>状态</th>
              <th>窗口</th>
              <th>不可用原因</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6}>无指标观测</td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.observation_id || `${row.metric_type}-${row.window_start}`}>
                  <td>{displayValue(row.metric_type)}</td>
                  <td>{displayQuantity(row.numeric_value)}</td>
                  <td>{displayValue(row.unit)}</td>
                  <td>{statusLabel(row.status)}</td>
                  <td>{formatRange(row.window_start, row.window_end)}</td>
                  <td>{unavailableReasonLabel(row.unavailable_reason)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EventTable({ rows }) {
  return (
    <div className="table-wrap">
      <h3>末次交易证据</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>类型</th>
              <th>数量</th>
              <th>金额</th>
              <th>部门</th>
              <th>供应商</th>
              <th>来源行</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7}>无末次交易事件</td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.movement_id}>
                  <td>{displayValue(row.transaction_date)}</td>
                  <td>{transactionLabel(row.transaction_type)}</td>
                  <td>{displayQuantity(row.quantity)}</td>
                  <td>{displayQuantity(row.amount)}</td>
                  <td>{displayValue(row.department)}</td>
                  <td>{displayValue(row.supplier)}</td>
                  <td className="mono">{displayValue(row.source_record_id)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SourceTable({ rows }) {
  return (
    <div className="table-wrap">
      <h3>源记录</h3>
      {rows.length === 0 ? (
        <p className="muted">无源记录</p>
      ) : (
        rows.map((row) => (
          <article className="source-card" key={row.source_record_id}>
            <header>
              <strong>
                {displayValue(row.source_filename)} / {displayValue(row.sheet_name)} / 第 {displayValue(row.excel_row)} 行
              </strong>
              <span className="mono">{displayValue(row.source_record_id)}</span>
            </header>
            <p className="mono muted">SHA256 {displayValue(row.source_file_sha256)}</p>
            {row.issues?.length > 0 && (
              <ul className="issue-list">
                {row.issues.map((issue) => (
                  <li key={typeof issue === 'string' ? issue : JSON.stringify(issue)}>{formatIssue(issue)}</li>
                ))}
              </ul>
            )}
            <div className="split-panels">
              <div>
                <h4>原始值</h4>
                <ValueTree value={row.raw_values} />
              </div>
              <div>
                <h4>规范化值</h4>
                <ValueTree value={row.normalized_values} />
              </div>
            </div>
          </article>
        ))
      )}
    </div>
  );
}

function QuantityCell({ total, byUnit, status }) {
  if (status === 'unit_conflict') {
    return (
      <div>
        <span className="null-value">单位冲突，合计不可用</span>
        <UnitMap map={byUnit} />
      </div>
    );
  }
  return (
    <div>
      <div>{displayQuantity(total)}</div>
      <UnitMap map={byUnit} />
    </div>
  );
}

function UnitStatus({ item }) {
  const parts = [];
  if (item.quantity_aggregation_status === 'unit_conflict') parts.push('单位冲突');
  if (hasConflicts(item.metadata_conflicts)) parts.push('主数据冲突');
  if (parts.length === 0) return <span className="muted">可合计</span>;
  return <span className="badge warn">{parts.join(' / ')}</span>;
}

function UnitMap({ map }) {
  const entries = Object.entries(map || {});
  if (entries.length === 0) return <span className="null-value">无分单位数量</span>;
  return (
    <ul className="unit-map">
      {entries.map(([unit, quantity]) => (
        <li key={unit}>
          {displayQuantity(quantity)} {displayValue(unit)}
        </li>
      ))}
    </ul>
  );
}

function ValueTree({ value }) {
  if (isMissing(value)) return <span className="null-value">未提供</span>;
  if (typeof value !== 'object') return <span>{String(value)}</span>;
  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index), item])
    : Object.entries(value);
  if (entries.length === 0) return <span className="null-value">无</span>;
  return (
    <dl className="kv-list">
      {entries.map(([key, item]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{item !== null && typeof item === 'object' ? JSON.stringify(item) : displayValue(item)}</dd>
        </div>
      ))}
    </dl>
  );
}

function CountCard({ label, value, hint, accent = 'blue' }) {
  return (
    <div className={`indicator-card static ${accent}`}>
      <span className="indicator-name">{label}</span>
      <strong>{displayCount(value)}</strong>
      <span className="indicator-summary">{hint}</span>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ErrorPanel({ error }) {
  return (
    <section className="error-panel">
      <AlertTriangle size={20} />
      <div>
        <strong>{error.message}</strong>
        {error.details?.length > 0 && (
          <ul>
            {error.details.slice(0, 8).map((detail) => (
              <li key={detail}>{detail}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function isMissing(value) {
  return value === null || value === undefined || value === '';
}

function displayValue(value, { empty = '未观测' } = {}) {
  return isMissing(value) ? empty : String(value);
}

function displayCount(value) {
  return isMissing(value) ? '未提供' : String(value);
}

function displayQuantity(value) {
  return isMissing(value) ? '不可用' : String(value);
}

function formatDays(value) {
  return isMissing(value) ? '未观测' : `${value} 天`;
}

function thresholdUnitLabel(unit) {
  if (unit === 'day') return '天';
  return displayValue(unit);
}

function formatRange(start, end) {
  if (isMissing(start) && isMissing(end)) return '未提供';
  return `${displayValue(start)} 至 ${displayValue(end)}`;
}

function classificationLabel(item) {
  if (item?.inactive_candidate === true) return '长期无交易物料候选';
  if (item?.inactive_candidate === false) return '未达阈值';
  return '未完成判断';
}

function classificationTone(item) {
  if (item?.inactive_candidate === true) return 'amber';
  if (item?.inactive_candidate === false) return 'blue';
  return 'muted';
}

function transactionLabel(type) {
  if (type === 'inbound') return '入库';
  if (type === 'outbound') return '出库';
  return displayValue(type);
}

function statusLabel(status) {
  return {
    observed: '已观测',
    unavailable: '不可用',
    partial_window: '窗口不完整',
    unit_conflict: '单位冲突',
  }[status] || displayValue(status);
}

function unavailableReasonLabel(reason) {
  return {
    unit_conflict: '单位冲突',
    missing_amount: '金额缺失',
    no_observed_movement: '窗口内无观测交易',
  }[reason] || displayValue(reason, { empty: '无' });
}

function emptyListCopy(query, inactiveOnly) {
  if (query) return `没有匹配「${query}」的物料`;
  if (inactiveOnly) return '当前筛选下没有长期无交易物料候选';
  return '没有可展示的评估结果';
}

function hasConflicts(value) {
  if (!value) return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'object') return Object.keys(value).length > 0;
  return true;
}

function formatIssue(issue) {
  if (typeof issue === 'string') return issue;
  if (issue && typeof issue === 'object') {
    return issue.message || issue.code || JSON.stringify(issue);
  }
  return String(issue);
}

function normalizeJobError(error) {
  if (!error) return { message: '分析失败', details: [] };
  if (typeof error === 'string') return { message: error, details: [] };
  return {
    message: error.message || '分析失败',
    details: Array.isArray(error.details) ? error.details : [],
  };
}

function validateIsoDate(value) {
  if (!value) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return '观察日必须为 YYYY-MM-DD';
  return null;
}

function validateThreshold(value) {
  if (value === '' || value == null) return null;
  if (!/^\d+$/.test(String(value))) return '阈值必须为非负整数';
  return null;
}
