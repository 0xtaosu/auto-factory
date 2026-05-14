import {
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  FileSpreadsheet,
  Gauge,
  Loader2,
  RefreshCw,
  TrendingUp,
  Upload,
} from 'lucide-react';
import React from 'react';
import { useMemo, useState } from 'react';
import { createJob, getDetail, getJob, getOverview } from './api.js';

const indicatorMeta = {
  total_value: { icon: TrendingUp, accent: 'blue' },
  stagnant_ratio: { icon: AlertTriangle, accent: 'amber' },
  balance: { icon: Gauge, accent: 'green' },
  anomalies: { icon: BarChart3, accent: 'red' },
};

const lightLabels = {
  green: '正常',
  yellow: '关注',
  red: '警戒',
};

export default function App() {
  const [job, setJob] = useState(null);
  const [overview, setOverview] = useState(null);
  const [activeIndicator, setActiveIndicator] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleUpload(file) {
    if (!file) return;
    setLoading(true);
    setError(null);
    setActiveIndicator(null);
    setDetail(null);
    setOverview(null);
    try {
      const created = await createJob(file);
      const nextJob = await getJob(created.job_id);
      setJob(nextJob);
      if (nextJob.status === 'failed') {
        setError(nextJob.error || { message: '分析失败', details: [] });
        return;
      }
      const nextOverview = await getOverview(created.job_id);
      setOverview(nextOverview);
    } catch (err) {
      setError({ message: '系统繁忙，请稍后再试', details: [err.message] });
    } finally {
      setLoading(false);
    }
  }

  async function openDetail(indicatorId) {
    if (!job) return;
    setLoading(true);
    setError(null);
    try {
      const nextDetail = await getDetail(job.job_id, indicatorId);
      setActiveIndicator(indicatorId);
      setDetail(nextDetail);
    } catch (err) {
      setError({ message: '详情加载失败', details: [err.message] });
    } finally {
      setLoading(false);
    }
  }

  function resetDemo() {
    setJob(null);
    setOverview(null);
    setActiveIndicator(null);
    setDetail(null);
    setError(null);
  }

  return (
    <main className="app-shell">
      <Header job={job} onReset={resetDemo} />
      {error && <ErrorPanel error={error} />}
      {!overview && <UploadPanel loading={loading} onUpload={handleUpload} />}
      {overview && !activeIndicator && (
        <OverviewScreen overview={overview} job={job} loading={loading} onOpenDetail={openDetail} />
      )}
      {overview && activeIndicator && detail && (
        <DetailScreen
          detail={detail}
          indicatorId={activeIndicator}
          loading={loading}
          onBack={() => {
            setActiveIndicator(null);
            setDetail(null);
          }}
        />
      )}
    </main>
  );
}

function Header({ job, onReset }) {
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark">
          <FileSpreadsheet size={21} />
        </div>
        <div>
          <h1>库存健康度分析报告</h1>
          <p>{job?.filename || '上传 ERP 进出库明细，生成老板一眼看懂的报告'}</p>
        </div>
      </div>
      {job && (
        <button className="icon-text-btn" onClick={onReset} type="button">
          <RefreshCw size={16} />
          重新上传
        </button>
      )}
    </header>
  );
}

function UploadPanel({ loading, onUpload }) {
  return (
    <section className="upload-band">
      <label className="upload-drop">
        <input
          type="file"
          accept=".xlsx,.xls"
          disabled={loading}
          onChange={(event) => onUpload(event.target.files?.[0])}
        />
        <span className="upload-icon">
          {loading ? <Loader2 className="spin" size={32} /> : <Upload size={32} />}
        </span>
        <strong>{loading ? '正在分析 Excel' : '上传库存进出库 Excel'}</strong>
        <span>支持 PRD 中的 7 个必须字段，系统会自动识别库存明细 sheet</span>
      </label>
    </section>
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
            {error.details.slice(0, 6).map((detail) => (
              <li key={detail}>{detail}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function OverviewScreen({ overview, job, loading, onOpenDetail }) {
  const quality = overview.data_quality;
  return (
    <section className="dashboard">
      <div className={`conclusion ${overview.overall_health.grade}`}>
        <div>
          <span className="eyebrow">一句话结论</span>
          <h2>“{overview.overall_health.summary}”</h2>
        </div>
        <div className="score-pill">
          <span>{overview.overall_health.score}</span>
          <small>{lightLabels[overview.overall_health.grade]}</small>
        </div>
      </div>

      <div className="meta-row">
        <Metric label="数据范围" value={`${quality?.date_range?.start_date || '--'} 至 ${quality?.date_range?.end_date || '--'}`} />
        <Metric label="有效记录" value={`${quality?.valid_records ?? '--'} / ${quality?.total_records ?? '--'}`} />
        <Metric label="物料种类" value={`${quality?.material_count ?? '--'} 种`} />
        <Metric label="任务状态" value={job?.status === 'completed' ? '已完成' : '处理中'} />
      </div>

      <div className="indicator-grid">
        {overview.indicators.map((indicator) => (
          <IndicatorCard
            key={indicator.id}
            indicator={indicator}
            disabled={loading}
            onClick={() => onOpenDetail(indicator.id)}
          />
        ))}
      </div>

      <div className="suggestion-band">
        {overview.overall_health.action_suggestions.map((suggestion) => (
          <div key={suggestion}>
            <CheckCircle2 size={16} />
            <span>{suggestion}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function IndicatorCard({ indicator, disabled, onClick }) {
  const meta = indicatorMeta[indicator.id] || indicatorMeta.total_value;
  const Icon = meta.icon;
  return (
    <button className={`indicator-card ${indicator.traffic_light}`} disabled={disabled} onClick={onClick} type="button">
      <span className={`card-icon ${meta.accent}`}>
        <Icon size={20} />
      </span>
      <span className="traffic-dot">{lightLabels[indicator.traffic_light]}</span>
      <span className="indicator-name">{indicator.name}</span>
      <strong>{indicator.display_value}</strong>
      <span className="indicator-summary">{indicator.summary}</span>
      <span className="drill-copy">点击下钻</span>
    </button>
  );
}

function DetailScreen({ detail, indicatorId, loading, onBack }) {
  return (
    <section className="detail-view">
      <button className="back-btn" onClick={onBack} type="button">
        <ArrowLeft size={16} />
        返回概览
      </button>
      <div className={`detail-heading ${detail.traffic_light || 'green'}`}>
        <span>{lightLabels[detail.traffic_light] || '详情'}</span>
        <h2>{detail.title}</h2>
        <p>{detail.trend_analysis || detail.summary || detail.analysis || detail.note}</p>
      </div>
      {loading && <Loader2 className="spin" size={20} />}
      {indicatorId === 'total_value' && <TotalValueDetail detail={detail} />}
      {indicatorId === 'stagnant_ratio' && <StagnantDetail detail={detail} />}
      {indicatorId === 'balance' && <BalanceDetail detail={detail} />}
      {indicatorId === 'anomalies' && <AnomalyDetail detail={detail} />}
    </section>
  );
}

function TotalValueDetail({ detail }) {
  return (
    <>
      <div className="meta-row">
        <Metric label="当前库存总资金" value={detail.display_value} />
        <Metric label="累计入库" value={formatMoney(detail.total_in)} />
        <Metric label="累计出库" value={formatMoney(detail.total_out)} />
        <Metric label="趋势判断" value={detail.trend_direction} />
      </div>
      <MonthlyBars rows={detail.monthly} mode="net" />
    </>
  );
}

function StagnantDetail({ detail }) {
  return (
    <>
      <div className="meta-row">
        <Metric label="呆滞占比" value={detail.display_value} />
        <Metric label="呆滞金额" value={detail.display_amount} />
        <Metric label="呆滞物料" value={`${detail.count} 种`} />
        <Metric label="阈值" value={`${detail.config.stagnant_days} 天`} />
      </div>
      <DataTable
        columns={['排名', '物料', '最后出库', '未出库天数', '金额']}
        rows={detail.top_list.map((item) => [
          item.rank,
          `${item.material_code} ${item.material_name}`,
          item.last_out_date || '无出库',
          item.days_since_last_out ?? '--',
          item.display_amount,
        ])}
      />
    </>
  );
}

function BalanceDetail({ detail }) {
  return (
    <>
      <div className="meta-row">
        <Metric label="最近6个月出入比" value={detail.display_value} />
        <Metric label="判断" value={detail.judgment} />
      </div>
      <MonthlyBars rows={detail.monthly} mode="ratio" />
    </>
  );
}

function AnomalyDetail({ detail }) {
  const breakdown = useMemo(
    () => [
      ['单价异常', detail.breakdown.price_spike],
      ['采购量异常', detail.breakdown.qty_spike],
      ['长期不出库', detail.breakdown.no_outbound],
      ['频率异常', detail.breakdown.freq_change],
    ],
    [detail],
  );
  return (
    <>
      <div className="meta-row">
        <Metric label="异常物料" value={`${detail.total} 种`} />
        <Metric label="涉及金额" value={detail.display_amount} />
        {breakdown.map(([label, value]) => (
          <Metric key={label} label={label} value={`${value} 种`} />
        ))}
      </div>
      <DataTable
        columns={['物料', '异常类型', '说明', '金额']}
        rows={detail.top_list.map((item) => [
          `${item.material_code} ${item.material_name}`,
          anomalyLabel(item.anomaly_type),
          item.anomaly_desc,
          item.display_amount,
        ])}
      />
    </>
  );
}

function MonthlyBars({ rows, mode }) {
  const maxValue = Math.max(
    1,
    ...rows.map((row) => {
      if (mode === 'ratio') return row.ratio || 0;
      return Math.abs(row.net_change || 0);
    }),
  );
  return (
    <div className="chart-panel">
      {rows.map((row) => {
        const value = mode === 'ratio' ? row.ratio || 0 : row.net_change || 0;
        const width = Math.max(4, Math.abs(value) / maxValue * 100);
        return (
          <div className="bar-row" key={row.month}>
            <span>{row.month}</span>
            <div className="bar-track">
              <i className={value < 0 ? 'negative' : ''} style={{ width: `${width}%` }} />
            </div>
            <strong>{mode === 'ratio' ? (row.ratio ? row.ratio.toFixed(2) : '--') : formatMoney(value)}</strong>
          </div>
        );
      })}
    </div>
  );
}

function DataTable({ columns, rows }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length}>暂无数据</td>
            </tr>
          ) : (
            rows.map((row, index) => (
              <tr key={`${row[0]}-${index}`}>
                {row.map((cell, cellIndex) => (
                  <td key={`${cell}-${cellIndex}`}>{cell}</td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
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

function formatMoney(value) {
  const abs = Math.abs(value || 0);
  const sign = value < 0 ? '-' : '';
  if (abs >= 100000000) return `${sign}${(abs / 100000000).toFixed(2)}亿`;
  if (abs >= 10000) return `${sign}${(abs / 10000).toFixed(1)}万`;
  return `${sign}${abs.toFixed(0)}元`;
}

function anomalyLabel(type) {
  return {
    price_spike: '单价异常',
    qty_spike: '采购量异常',
    no_outbound: '长期不出库',
    freq_change: '频率异常',
  }[type] || type;
}
