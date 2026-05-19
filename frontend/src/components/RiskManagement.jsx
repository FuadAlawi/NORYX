import React, { useState, useEffect } from 'react';

const API = 'http://localhost:8000';

export default function RiskManagement() {
  const [risks, setRisks] = useState([]);
  const [showAdd, setShowAdd] = useState(false);
  const [newRisk, setNewRisk] = useState({
    title: '', description: '', control_id: '',
    impact: 'Medium', likelihood: 'Medium',
    mitigation_strategy: '', owner: 'Admin', status: 'Open'
  });

  const fetchRisks = () => {
    fetch(`${API}/risks/`)
      .then(r => r.ok ? r.json() : [])
      .then(data => Array.isArray(data) ? setRisks(data) : setRisks([]))
      .catch(()=>{});
  };

  useEffect(() => { fetchRisks(); }, []);

  const handleAdd = async () => {
    if(!newRisk.title) return;
    await fetch(`${API}/risks/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...newRisk, control_id: parseInt(newRisk.control_id) || 1 })
    });
    setShowAdd(false);
    fetchRisks();
  };

  const handleUpdateStatus = async (id, status) => {
    await fetch(`${API}/risks/${id}?status=${status}`, { method: 'PATCH' });
    fetchRisks();
  };

  const levels = ['Low', 'Medium', 'High', 'Critical'];
  const getSeverityColor = (impact, likelihood) => {
    const i = levels.indexOf(impact);
    const l = levels.indexOf(likelihood);
    if (i + l >= 4) return 'var(--red)';
    if (i + l >= 2) return 'var(--yellow)';
    return 'var(--green)';
  };

  const openRisks = risks.filter(r => r.status === 'Open').length;
  const mitRisks = risks.filter(r => r.status === 'Mitigating').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      
      {/* Header KPI Row */}
      <div className="g4">
        <div className="card card-sm">
          <div className="card-label">Total Risks</div>
          <div className="font-outfit card-value">{risks.length}</div>
        </div>
        <div className="card card-sm" style={{ borderLeft: '4px solid var(--red)' }}>
          <div className="card-label">Open</div>
          <div className="font-outfit card-value" style={{ color: 'var(--red)' }}>{openRisks}</div>
        </div>
        <div className="card card-sm" style={{ borderLeft: '4px solid var(--yellow)' }}>
          <div className="card-label">Mitigating</div>
          <div className="font-outfit card-value" style={{ color: 'var(--yellow)' }}>{mitRisks}</div>
        </div>
        <div className="card card-sm" style={{ borderLeft: '4px solid var(--green)' }}>
          <div className="card-label">Resolved</div>
          <div className="font-outfit card-value" style={{ color: 'var(--green)' }}>{risks.length - openRisks - mitRisks}</div>
        </div>
      </div>

      <div className="g2-wide">
        {/* Risk Matrix Visualization */}
        <div className="card">
          <div className="sec-head">
            <div className="sec-title">Risk Heatmap (4×4)</div>
            <span className="tag">Likelihood × Impact</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', padding: '20px 0' }}>
            {(() => {
              const mappedLvl = { 'Low': 1, 'Medium': 2, 'High': 3, 'Critical': 4, 'Very High': 4 };
              const activeRisks = risks.filter(r => r.status === 'Open' || r.status === 'Mitigating');
              const rowLabels = ['V.High', 'High', 'Medium', 'Low'];
              const colLabels = ['Low', 'Medium', 'High', 'Critical'];
              const labelStyle = { display: 'flex', alignItems: 'center', justifyContent: 'flex-end', paddingRight: '6px', fontSize: '10px', color: 'var(--text-secondary)', fontWeight: 500, whiteSpace: 'nowrap' };

              return (
                <div className="risk-matrix">
                  {/* Y-axis label */}
                  <div style={{ gridRow: '1 / span 4', gridColumn: 1, writingMode: 'vertical-rl', transform: 'rotate(180deg)', textAlign: 'center', fontSize: '11px', color: 'var(--text-secondary)', fontWeight: 600, letterSpacing: '0.1em' }}>LIKELIHOOD</div>

                  {/* Row labels (top = Very High, bottom = Low) */}
                  {rowLabels.map((label, i) => (
                    <div key={label} style={{ gridRow: i + 1, gridColumn: 2, ...labelStyle }}>{label}</div>
                  ))}

                  {/* 4×4 cells — y=3 is Very High (row 1), y=0 is Low (row 4) */}
                  {[3, 2, 1, 0].map((y) =>
                    [0, 1, 2, 3].map((x) => {
                      const score = (x + 1) * (y + 1);
                      const bg     = score >= 9 ? 'rgba(239, 68, 68, 0.2)'   : score >= 4 ? 'rgba(245, 158, 11, 0.2)' : 'rgba(34, 197, 94, 0.2)';
                      const border = score >= 9 ? 'var(--red-border)'         : score >= 4 ? 'var(--yellow-border)'    : 'var(--green-border)';
                      const cellRisks = activeRisks.filter(r => (mappedLvl[r.likelihood] || 2) === (y + 1) && (mappedLvl[r.impact] || 2) === (x + 1));
                      return (
                        <div key={`${x}-${y}`} className="risk-matrix-cell" style={{ gridRow: 4 - y, gridColumn: x + 3, background: bg, border: `1px solid ${border}` }}>
                          {cellRisks.length > 0 && <div style={{ width: '24px', height: '24px', borderRadius: '50%', background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: 700, color: '#fff', boxShadow: '0 0 8px rgba(0,0,0,0.4)' }}>{cellRisks.length}</div>}
                        </div>
                      );
                    })
                  )}

                  {/* Column labels */}
                  {colLabels.map((label, i) => (
                    <div key={label} style={{ gridRow: 5, gridColumn: i + 3, textAlign: 'center', fontSize: '10px', color: 'var(--text-secondary)', fontWeight: 500, paddingTop: '4px' }}>{label}</div>
                  ))}

                  {/* X-axis label */}
                  <div style={{ gridRow: 6, gridColumn: '3 / span 4', textAlign: 'center', fontSize: '11px', color: 'var(--text-secondary)', fontWeight: 600, letterSpacing: '0.1em', paddingTop: '2px' }}>IMPACT</div>
                </div>
              );
            })()}
          </div>
        </div>

        {/* Add Risk Form */}
        <div className="card">
          <div className="sec-head">
            <div className="sec-title">Log New Risk</div>
            <button className="btn btn-primary" onClick={() => setShowAdd(!showAdd)}>
              {showAdd ? 'Cancel' : '+ New Risk'}
            </button>
          </div>
          
          {showAdd ? (
            <div className="slide-in" style={{ display: 'flex', flexDirection: 'column', gap: '12px', background: 'var(--surface-2)', padding: '16px', borderRadius: 'var(--radius)' }}>
              <input placeholder="Risk Title" value={newRisk.title} onChange={e => setNewRisk({...newRisk, title: e.target.value})} />
              <textarea placeholder="Detailed description..." value={newRisk.description} onChange={e => setNewRisk({...newRisk, description: e.target.value})} rows={2} />
              
              <div className="g2">
                <select value={newRisk.impact} onChange={e => setNewRisk({...newRisk, impact: e.target.value})}>
                  <option>Low</option><option>Medium</option><option>High</option><option>Critical</option>
                </select>
                <select value={newRisk.likelihood} onChange={e => setNewRisk({...newRisk, likelihood: e.target.value})}>
                  <option>Low</option><option>Medium</option><option>High</option><option>Very High</option>
                </select>
              </div>

              <div className="g2">
                <input placeholder="Control ID (e.g. 1)" value={newRisk.control_id} onChange={e => setNewRisk({...newRisk, control_id: e.target.value})} />
                <input placeholder="Mitigation Strategy" value={newRisk.mitigation_strategy} onChange={e => setNewRisk({...newRisk, mitigation_strategy: e.target.value})} />
              </div>
              
              <button className="btn btn-primary btn-full" onClick={handleAdd}>Save Risk Entry</button>
            </div>
          ) : (
            <div className="empty" style={{ padding: '40px 0' }}>
              <div className="empty-sub">Identify and document compliance vulnerabilities to proactively manage security posture.</div>
            </div>
          )}
        </div>
      </div>

      {/* Risk Register Table */}
      <div className="card">
        <div className="sec-head">
          <div className="sec-title">Risk Register</div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Title & Description</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {risks.length === 0 ? (
                <tr><td colSpan="5" className="empty-sub" style={{ textAlign: 'center', padding: '20px' }}>No risks logged</td></tr>
              ) : risks.map(r => {
                const color = getSeverityColor(r.impact, r.likelihood);
                return (
                  <tr key={r.id}>
                    <td style={{ verticalAlign: 'top' }}><span className="tag font-outfit">RSK-{r.id}</span></td>
                    <td>
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>{r.title}</div>
                      <div style={{ fontSize: '12px', color: 'var(--text-secondary)', maxWidth: '400px' }}>{r.description || 'No description provided.'}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '6px' }}>Mitigation: {r.mitigation_strategy || 'None'}</div>
                    </td>
                    <td style={{ verticalAlign: 'top' }}>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', background: `color-mix(in srgb, ${color} 15%, transparent)`, padding: '4px 8px', borderRadius: '4px', border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`, color }}>
                        <div style={{ width: 6, height: 6, borderRadius: '50%', background: color }} />
                        <span style={{ fontSize: '11px', fontWeight: 600 }}>{r.impact} × {r.likelihood}</span>
                      </div>
                    </td>
                    <td style={{ verticalAlign: 'top' }}>
                      <span className="badge" style={{ 
                        background: r.status === 'Resolved' ? 'var(--green-dim)' : r.status === 'Mitigating' ? 'var(--yellow-dim)' : 'var(--surface-3)',
                        color: r.status === 'Resolved' ? 'var(--green)' : r.status === 'Mitigating' ? 'var(--yellow)' : 'var(--text-secondary)'
                      }}>{r.status}</span>
                    </td>
                    <td style={{ verticalAlign: 'top' }}>
                      {r.status === 'Open' && <button className="btn btn-secondary" style={{ fontSize: '11px', padding: '4px 8px' }} onClick={() => handleUpdateStatus(r.id, 'Mitigating')}>Start Mitigating</button>}
                      {r.status === 'Mitigating' && <button className="btn btn-secondary" style={{ fontSize: '11px', padding: '4px 8px', color: 'var(--green)', borderColor: 'var(--green-border)' }} onClick={() => handleUpdateStatus(r.id, 'Resolved')}>Mark Resolved</button>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
