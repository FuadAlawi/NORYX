import React, { useState, useEffect, useCallback } from 'react';

const API = 'http://localhost:8000';

function ProgressBar({ value, color = 'var(--green)' }) {
  return (
    <div className="progress">
      <div className="progress-fill" style={{ width: `${value}%`, background: color }} />
    </div>
  );
}

function RingGauge({ pct }) {
  const r = 52, circ = 2 * Math.PI * r;
  const offset = circ - (pct / 100) * circ;
  const color = pct >= 70 ? 'var(--green)' : pct >= 40 ? 'var(--yellow)' : 'var(--red)';
  return (
    <div style={{ position: 'relative', width: 140, height: 140 }}>
      <svg width="140" height="140" viewBox="0 0 140 140">
        <circle cx="70" cy="70" r={r} fill="none" stroke="var(--surface-3)" strokeWidth="10"/>
        <circle cx="70" cy="70" r={r} fill="none" stroke={color} strokeWidth="10"
          strokeDasharray={circ} strokeDashoffset={offset}
          strokeLinecap="round" transform="rotate(-90 70 70)"
          style={{ transition: 'stroke-dashoffset 1s ease' }}
        />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ fontSize: '22px', fontWeight: 700, color, letterSpacing: 0 }}>{pct}%</span>
        <span style={{ fontSize: '10px', color: 'var(--text-tertiary)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Compliance</span>
      </div>
    </div>
  );
}

export default function AdminDashboard({ departments }) {
  const [stats, setStats] = useState(null);

  const load = useCallback(() => {
    fetch(`${API}/dashboard/stats`).then(r=>r.json()).then(setStats).catch(()=>{});
  }, []);

  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, [load]);

  // ═══════════════════════════════════════════════════════════════════════════
  // CHANGE 1 — Improved loading state with a spinner instead of plain text.
  //
  // OLD CODE:
  //   if (!stats) return (
  //     <div style={{ textAlign: 'center', padding: '48px', color: 'var(--text-tertiary)', fontSize: '13px' }}>
  //       Loading dashboard…
  //     </div>
  //   );
  //
  // WHY THE NEW ONE IS BETTER:
  //   A spinning indicator gives the user clear visual feedback that something
  //   is actively loading, rather than static text which can look like an error
  //   or a broken page. It feels more polished and professional.
  // ═══════════════════════════════════════════════════════════════════════════
  if (!stats) return (
    <div style={{ textAlign: 'center', padding: '64px', color: 'var(--text-tertiary)' }}>
      <div style={{
        width: 36, height: 36, margin: '0 auto 14px',
        border: '3px solid var(--surface-3)',
        borderTop: '3px solid var(--accent, #6366f1)',
        borderRadius: '50%',
        animation: 'spin 0.8s linear infinite',
      }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <div style={{ fontSize: '13px' }}>Loading dashboard…</div>
    </div>
  );

  const total  = stats.total_evidence || 0;
  const passed = stats.total_pass     || 0;
  const failed = stats.total_fail     || 0;
  const review = stats.total_review   || 0;
  const pct    = stats.overall_compliance ?? (total > 0 ? Math.round((passed / total) * 100) : 0);
  const complianceColor = pct >= 70 ? 'var(--green)' : pct >= 40 ? 'var(--yellow)' : 'var(--red)';
  const kpis  = [
    { label: 'Overall Compliance', value: `${pct}%`, color: complianceColor,          accent: pct >= 70 ? 'kpi-card-green' : pct >= 40 ? 'kpi-card-yellow' : 'kpi-card-red' },
    { label: 'Total Evidence',     value: total,     color: 'var(--text-primary)',     accent: 'kpi-card-accent' },
    { label: 'Passed',             value: passed,    color: 'var(--green)',            accent: 'kpi-card-green' },
    { label: 'Failed',             value: failed,    color: 'var(--red)',              accent: 'kpi-card-red'   },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>

      {/* KPI Row */}
      {/* ═══════════════════════════════════════════════════════════════════════
          CHANGE 2 — KPI cards now show a small trend arrow icon next to value.
          
          OLD CODE:
            <div className="card-value" style={{ color: k.color }}>{k.value}</div>
          
          WHY THE NEW ONE IS BETTER:
            A static number alone gives no directional context. The arrow icon
            (▲ for compliance/passed, ▼ for failed) gives instant visual meaning
            at a glance without adding any extra data or API calls. It makes the
            dashboard feel like a real analytics tool.
          ═══════════════════════════════════════════════════════════════════════ */}
      <div className="g4">
        {kpis.map(k => {
          const arrow = k.label === 'Failed'
            ? <span style={{ fontSize: '13px', marginLeft: '4px', opacity: 0.7 }}>▼</span>
            : k.label === 'Total Evidence'
            ? null
            : <span style={{ fontSize: '13px', marginLeft: '4px', opacity: 0.7 }}>▲</span>;
          return (
            <div className={`card card-sm kpi-card ${k.accent}`} key={k.label}>
              <div className="card-label">{k.label}</div>
              <div className="card-value" style={{ color: k.color, display: 'flex', alignItems: 'baseline' }}>
                {k.value}{arrow}
              </div>
            </div>
          );
        })}
      </div>

      {/* Compliance ring + breakdown */}
      <div className="g2-wide">
        <div className="card" style={{ display: 'flex', alignItems: 'center', gap: '28px' }}>
          <RingGauge pct={pct} />
          <div style={{ flex: 1 }}>
            <div className="sec-title" style={{ marginBottom: '14px' }}>Breakdown</div>
            {[
              { label: 'Passed',      n: passed, color: 'var(--green)'  },
              { label: 'Failed',      n: failed, color: 'var(--red)'    },
              { label: 'Need Review', n: review, color: 'var(--yellow)' },
            ].map(r => (
              <div key={r.label} style={{ marginBottom: '12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
                  <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{r.label}</span>
                  <span style={{ fontSize: '12px', fontWeight: 600, color: r.color }}>{r.n}</span>
                </div>
                <ProgressBar value={total ? (r.n / total) * 100 : 0} color={r.color} />
              </div>
            ))}
          </div>
        </div>

        {/* Heatmap */}
        <div className="card">
          <div className="sec-head">
            <div className="sec-title">Department Heatmap</div>
            <span className="tag">Compliance %</span>
          </div>
          {stats.department_stats?.length ? (
            <div className="heatmap-grid">
              {stats.department_stats.map((d, i) => {
                const p = d.total > 0 ? Math.round((d.passed / d.total) * 100) : 0;
                const cls = d.total === 0 ? 'hm-none' : p >= 70 ? 'hm-high' : p >= 40 ? 'hm-medium' : 'hm-low';
                return (
                  <div key={`${d.department || 'department'}-${i}`} className={`hm-cell ${cls}`}>
                    <span className="hm-pct">{d.total === 0 ? '—' : `${p}%`}</span>
                    <span className="hm-name">{d.department}</span>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="empty">
              <div className="empty-title">No submissions yet</div>
              <div className="empty-sub">Heatmap will populate as evidence is uploaded</div>
            </div>
          )}
        </div>
      </div>

      {/* Bottom row */}
      <div className="g2">

        {/* Top failing controls */}
        <div className="card">
          <div className="sec-head">
            <div className="sec-title">Top Failing Controls</div>
          </div>
          {stats.top_failing_controls?.length ? (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '0 0 8px', color: 'var(--text-tertiary)', fontWeight: 600, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Control</th>
                  <th style={{ textAlign: 'right', padding: '0 0 8px', color: 'var(--text-tertiary)', fontWeight: 600, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Failures</th>
                </tr>
              </thead>
              <tbody>
                {stats.top_failing_controls.map((c, i) => (
                  <tr key={i}>
                    <td style={{ padding: '7px 0', color: 'var(--text-primary)', borderTop: i > 0 ? '1px solid var(--border)' : 'none' }}>{c.control}</td>
                    <td style={{ textAlign: 'right', padding: '7px 0', borderTop: i > 0 ? '1px solid var(--border)' : 'none' }}>
                      <span className="badge badge-fail">{c.fails}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty">
              <div className="empty-title" style={{ color: 'var(--green)' }}>No failures recorded</div>
              <div className="empty-sub">Great compliance posture</div>
            </div>
          )}
        </div>

        {/* Department summary */}
        {/* ═══════════════════════════════════════════════════════════════════
            CHANGE 3 — Department rows now show a small % badge on the right
                       instead of just a fraction like "3/10".
            
            OLD CODE:
              <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                {ds?.total ? `${ds.passed}/${ds.total}` : 'No submissions'}
              </span>
            
            WHY THE NEW ONE IS BETTER:
              A percentage is faster to read and compare across departments than
              a raw fraction. The colored dot next to the department name also
              gives instant red/yellow/green status at a glance without needing
              to read the progress bar below it.
            ═══════════════════════════════════════════════════════════════════ */}
        <div className="card">
          <div className="sec-head">
            <div className="sec-title">Department Summary</div>
          </div>
          {departments.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {departments.map(d => {
                const ds = stats.department_stats?.find(s => s.department === d.name);
                const p  = ds?.total ? Math.round((ds.passed / ds.total) * 100) : 0;
                const dotColor = !ds?.total ? 'var(--text-tertiary)' : p >= 70 ? 'var(--green)' : p >= 40 ? 'var(--yellow)' : 'var(--red)';
                return (
                  <div key={d.id}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '5px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
                        {/* colored status dot */}
                        <span style={{ width: 7, height: 7, borderRadius: '50%', background: dotColor, display: 'inline-block', flexShrink: 0 }} />
                        <span style={{ fontSize: '12px', color: 'var(--text-primary)', fontWeight: 500 }}>{d.name}</span>
                      </div>
                      {/* percentage badge instead of raw fraction */}
                      <span style={{
                        fontSize: '11px', fontWeight: 600,
                        color: dotColor,
                        background: ds?.total ? `${dotColor}18` : 'transparent',
                        padding: '1px 7px', borderRadius: '999px',
                      }}>
                        {ds?.total ? `${p}%` : 'No data'}
                      </span>
                    </div>
                    <ProgressBar
                      value={p}
                      color={p >= 70 ? 'var(--green)' : p >= 40 ? 'var(--yellow)' : 'var(--red)'}
                    />
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="empty">
              <div className="empty-sub">No departments created yet</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
