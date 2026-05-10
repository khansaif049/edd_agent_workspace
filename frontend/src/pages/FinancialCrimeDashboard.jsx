import { useEffect, useMemo, useState } from "react";

const severityOrder = { critical: 4, high: 3, medium: 2, low: 1 };
const loadingStages = [
  "planning",
  "querying",
  "analyzing",
  "drafting",
];

function formatMoney(value) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function riskClass(level) {
  return `risk-${String(level || "low").toLowerCase()}`;
}

export default function App() {
  const [accountId, setAccountId] = useState("100428660");
  const [saveReport, setSaveReport] = useState(false);
  const [deepReview, setDeepReview] = useState(true);
  const [useLlm, setUseLlm] = useState(true);
  const [samples, setSamples] = useState([]);
  const [page, setPage] = useState("investigation");
  const [report, setReport] = useState(null);
  const [savedReports, setSavedReports] = useState([]);
  const [savedReport, setSavedReport] = useState(null);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [tmAlerts, setTmAlerts] = useState([]);
  const [tmAlert, setTmAlert] = useState(null);
  const [tmLoading, setTmLoading] = useState(false);
  const [tmRunResult, setTmRunResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeStage, setActiveStage] = useState("");

  useEffect(() => {
    fetch("/api/sample-accounts")
      .then((res) => res.json())
      .then(setSamples)
      .catch(() => setSamples([]));
  }, []);

  useEffect(() => {
    if (page === "reports") {
      loadSavedReports();
    }
    if (page === "tm") {
      loadTmAlerts();
    }
  }, [page]);

  async function loadSavedReports() {
    setReportsLoading(true);
    setError("");
    try {
      const response = await fetch("/api/reports");
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not load saved reports");
      setSavedReports(data);
      if (!savedReport && data.length) {
        loadSavedReportDetail(data[0].report_id);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setReportsLoading(false);
    }
  }

  async function loadSavedReportDetail(reportId) {
    setReportsLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/reports/${reportId}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not load report detail");
      setSavedReport(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setReportsLoading(false);
    }
  }

  async function loadTmAlerts() {
    setTmLoading(true);
    setError("");
    try {
      const response = await fetch("/api/tm/alerts");
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not load TM alerts");
      setTmAlerts(data);
      if (!tmAlert && data.length) {
        loadTmAlertDetail(data[0].alert_id);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setTmLoading(false);
    }
  }

  async function runTmScan() {
    setTmLoading(true);
    setError("");
    try {
      const response = await fetch("/api/tm/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: 25 }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not run TM scan");
      setTmRunResult(data);
      await loadTmAlerts();
    } catch (err) {
      setError(err.message);
    } finally {
      setTmLoading(false);
    }
  }

  async function loadTmAlertDetail(alertId) {
    setTmLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/tm/alerts/${alertId}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not load TM alert detail");
      setTmAlert(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setTmLoading(false);
    }
  }

  async function dispositionTmAlert(disposition) {
    if (!tmAlert) return;
    setTmLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/tm/alerts/${tmAlert.alert_id}/disposition`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ disposition, notes: `Marked ${disposition} from analyst UI` }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not disposition alert");
      setTmAlert(data);
      await loadTmAlerts();
    } catch (err) {
      setError(err.message);
    } finally {
      setTmLoading(false);
    }
  }

  async function generateReport(event) {
    event?.preventDefault();
    setLoading(true);
    setActiveStage("planning");
    setError("");
    let progressTimer;
    try {
      let stageIndex = 0;
      progressTimer = window.setInterval(() => {
        stageIndex = Math.min(stageIndex + 1, loadingStages.length - 1);
        setActiveStage(loadingStages[stageIndex]);
      }, deepReview ? 700 : 350);
      const response = await fetch("/api/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account_id: accountId,
          save: saveReport,
          deep_review: deepReview,
          use_llm: useLlm,
        }),
      });
      window.clearInterval(progressTimer);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.error || "Could not generate report");
      setActiveStage("completed");
      setReport(data);
    } catch (err) {
      setReport(null);
      setError(err.message);
    } finally {
      if (progressTimer) window.clearInterval(progressTimer);
      setLoading(false);
    }
  }

  const findings = useMemo(() => {
    return [...(report?.risk_findings || [])].sort((a, b) => {
      return (severityOrder[b.severity] || 0) - (severityOrder[a.severity] || 0);
    });
  }, [report]);

  return (
    <main className="app-shell">
      <section className="workspace">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-mark">F</div>
            <div>
              <h1>FinAgent EDD</h1>
              <p>Analyst investigation console</p>
            </div>
          </div>

          <nav className="nav-tabs">
            <button
              className={page === "investigation" ? "active" : ""}
              onClick={() => setPage("investigation")}
            >
              Investigation
            </button>
            <button
              className={page === "reports" ? "active" : ""}
              onClick={() => setPage("reports")}
            >
              Saved Reports
            </button>
            <button
              className={page === "tm" ? "active" : ""}
              onClick={() => setPage("tm")}
            >
              TM Alerts
            </button>
          </nav>

          {page === "investigation" ? (
            <>
              <form className="search-panel" onSubmit={generateReport}>
                <label htmlFor="account-id">Account ID</label>
                <input
                  id="account-id"
                  value={accountId}
                  onChange={(event) => setAccountId(event.target.value)}
                  placeholder="Enter account ID"
                />
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={saveReport}
                    onChange={(event) => setSaveReport(event.target.checked)}
                  />
                  <span>Save report to database</span>
                </label>
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={deepReview}
                    onChange={(event) => setDeepReview(event.target.checked)}
                  />
                  <span>Show deep investigation flow</span>
                </label>
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={useLlm}
                    onChange={(event) => setUseLlm(event.target.checked)}
                  />
                  <span>Use Groq LLM narrative</span>
                </label>
                <button type="submit" disabled={loading}>
                  {loading ? "Generating..." : "Generate EDD Report"}
                </button>
              </form>

              <div className="sample-list">
                <h2>Sample Accounts</h2>
                {samples.map((item) => (
                  <button
                    key={item.account_id}
                    className="sample-item"
                    onClick={() => setAccountId(item.account_id)}
                  >
                    <span>{item.account_id}</span>
                    <small>{item.entity_name} · {item.risk_rating}</small>
                  </button>
                ))}
              </div>
            </>
          ) : (
            page === "reports" ? (
            <SavedReportsList
              reports={savedReports}
              selectedId={savedReport?.report_id}
              loading={reportsLoading}
              onRefresh={loadSavedReports}
              onSelect={loadSavedReportDetail}
            />
            ) : (
              <TmAlertList
                alerts={tmAlerts}
                selectedId={tmAlert?.alert_id}
                loading={tmLoading}
                runResult={tmRunResult}
                onRun={runTmScan}
                onRefresh={loadTmAlerts}
                onSelect={loadTmAlertDetail}
              />
            )
          )}
        </aside>

        <section className="content">
          <header className="topbar">
            <div>
              <h2>{page === "investigation" ? "EDD Investigation" : page === "reports" ? "Saved EDD Reports" : "Transaction Monitoring"}</h2>
              <p>
                {page === "investigation"
                  ? "Profile, transaction behavior, screening, media, evidence, and recommendation."
                  : page === "reports"
                    ? "Review previously generated EDD reports and their saved narrative, evidence, and recommendation."
                    : "Run monitoring scenarios, triage alerts, inspect evidence, and disposition analyst outcomes."}
              </p>
            </div>
            {page === "investigation" && report && (
              <div className={`risk-badge ${riskClass(report.risk_level)}`}>
                <span>{report.risk_level}</span>
                <strong>{report.risk_score}/100</strong>
              </div>
            )}
            {page === "reports" && savedReport && (
              <div className={`risk-badge ${riskClass(savedReport.risk_level)}`}>
                <span>{savedReport.risk_level}</span>
                <strong>{savedReport.risk_score}/100</strong>
              </div>
            )}
            {page === "tm" && tmAlert && (
              <div className={`risk-badge ${riskClass(tmAlert.priority)}`}>
                <span>{tmAlert.priority}</span>
                <strong>{tmAlert.risk_score}/100</strong>
              </div>
            )}
          </header>

          {error && <div className="error">{error}</div>}
          {page === "investigation" && loading && <InvestigationProgress activeStage={activeStage} />}
          {page === "investigation" && !report && !error && !loading && <EmptyState loading={loading} />}
          {page === "investigation" && report && <ReportView report={report} findings={findings} />}
          {page === "reports" && !savedReport && !error && (
            <EmptyState loading={reportsLoading} title="No saved report selected" text="Choose a report from the sidebar to inspect its saved EDD output." />
          )}
          {page === "reports" && savedReport && <ReportView report={savedReport} findings={savedReport.risk_findings || []} />}
          {page === "tm" && !tmAlert && !error && (
            <EmptyState loading={tmLoading} title="No TM alert selected" text="Run the monitoring scan or choose an alert from the queue." />
          )}
          {page === "tm" && tmAlert && <TmAlertDetail alert={tmAlert} onDisposition={dispositionTmAlert} />}
        </section>
      </section>
    </main>
  );
}

function InvestigationProgress({ activeStage }) {
  return (
    <section className="progress-panel">
      <h3>Investigation in progress</h3>
      <div className="stage-grid">
        {loadingStages.map((stage) => {
          const activeIndex = loadingStages.indexOf(activeStage);
          const stageIndex = loadingStages.indexOf(stage);
          const state = activeStage === "completed" || stageIndex < activeIndex
            ? "done"
            : stageIndex === activeIndex
              ? "active"
              : "pending";
          return (
            <div className={`stage-item ${state}`} key={stage}>
              <span>{stage}</span>
              <small>{stageDescriptions[stage]}</small>
            </div>
          );
        })}
      </div>
    </section>
  );
}

const stageDescriptions = {
  planning: "Scope account, KYC, behavior, screening, and report objectives.",
  querying: "Load profile, transaction metrics, owners, watchlists, media, and cases.",
  analyzing: "Apply AML typology rules and calculate explainable risk score.",
  drafting: "Draft narrative, confidence note, questions, recommendation, and evidence.",
};

function SavedReportsList({ reports, selectedId, loading, onRefresh, onSelect }) {
  return (
    <div className="saved-list">
      <div className="saved-list-header">
        <h2>Saved Reports</h2>
        <button onClick={onRefresh} disabled={loading}>Refresh</button>
      </div>
      {reports.length === 0 && <p className="muted">No reports saved yet.</p>}
      {reports.map((item) => (
        <button
          key={item.report_id}
          className={`saved-item ${selectedId === item.report_id ? "active" : ""}`}
          onClick={() => onSelect(item.report_id)}
        >
          <span>Report #{item.report_id}</span>
          <strong>{item.account_id} · {item.risk_level} · {item.risk_score}/100</strong>
          <small>{item.entity_name || "Unknown entity"} · {item.created_at || "no timestamp"}</small>
        </button>
      ))}
    </div>
  );
}

function TmAlertList({ alerts, selectedId, loading, runResult, onRun, onRefresh, onSelect }) {
  return (
    <div className="saved-list">
      <div className="tm-actions">
        <button onClick={onRun} disabled={loading}>Run TM Scan</button>
        <button onClick={onRefresh} disabled={loading}>Refresh</button>
      </div>
      {runResult && (
        <div className="run-result">
          <strong>{runResult.created_alerts}</strong> created · {runResult.scanned_accounts} accounts scanned · {runResult.skipped_duplicates} duplicates skipped
        </div>
      )}
      <div className="saved-list-header">
        <h2>Alert Queue</h2>
      </div>
      {alerts.length === 0 && <p className="muted">No TM alerts yet.</p>}
      {alerts.map((item) => (
        <button
          key={item.alert_id}
          className={`saved-item ${selectedId === item.alert_id ? "active" : ""}`}
          onClick={() => onSelect(item.alert_id)}
        >
          <span>Alert #{item.alert_id}</span>
          <strong>{item.scenario_id} · {item.priority} · {item.status}</strong>
          <small>{item.account_id} · {item.entity_name || "Unknown entity"}</small>
        </button>
      ))}
    </div>
  );
}

function TmAlertDetail({ alert, onDisposition }) {
  return (
    <div className="report-grid">
      <section className="summary-band">
        <div>
          <h3>{alert.scenario_id}</h3>
          <p>{alert.reason}</p>
        </div>
        <div className="saved-pill">Alert #{alert.alert_id}</div>
      </section>

      <section className="panel profile-panel">
        <h3>Alert Summary</h3>
        <InfoRows rows={[
          ["Account", alert.account_id],
          ["Entity", alert.entity_name],
          ["Bank", alert.bank_name],
          ["Priority", alert.priority],
          ["Status", alert.status],
          ["Risk Score", `${alert.risk_score}/100`],
          ["Created", alert.created_at],
        ]} />
      </section>

      <section className="panel recommendation-panel">
        <h3>Recommended Action</h3>
        <p>{alert.recommended_action}</p>
        <div className="disposition-actions">
          <button onClick={() => onDisposition("true_positive")}>True Positive</button>
          <button onClick={() => onDisposition("false_positive")}>False Positive</button>
          <button onClick={() => onDisposition("escalate_edd")}>Escalate EDD</button>
        </div>
      </section>

      <section className="panel findings-panel">
        <h3>Evidence</h3>
        {(alert.evidence || []).map((item) => (
          <article className="evidence-card" key={item.evidence_id}>
            <strong>{item.evidence_type}</strong>
            <pre>{JSON.stringify(item.evidence_json, null, 2)}</pre>
          </article>
        ))}
      </section>

      <section className="panel timeline-panel">
        <h3>Disposition History</h3>
        {(alert.dispositions || []).length === 0 && <p className="muted">No disposition recorded yet.</p>}
        {(alert.dispositions || []).map((item) => (
          <article className="log-event" key={item.disposition_id}>
            <strong>{item.disposition}</strong>
            <p>{item.notes || "No notes"} · {item.analyst || "unknown"} · {item.created_at}</p>
          </article>
        ))}
      </section>
    </div>
  );
}

function EmptyState({ loading, title, text }) {
  return (
    <div className="empty-state">
      <h3>{loading ? "Loading..." : title || "Ready for investigation"}</h3>
      <p>{text || "Enter an account ID or choose a sample account, then generate an EDD report."}</p>
    </div>
  );
}

function ReportView({ report, findings }) {
  const account = report.customer_profile;
  const metrics = report.transaction_metrics;

  return (
    <div className="report-grid">
      <section className="summary-band">
        <div>
          <h3>{account.entity_name}</h3>
          <p>{report.edd_summary}</p>
        </div>
        {report.report_id && <div className="saved-pill">Saved #{report.report_id}</div>}
      </section>

      <section className="panel narrative-panel">
        <div className="panel-heading">
          <h3>AI Investigation Narrative</h3>
          {report.llm && (
            <span className={`llm-pill ${report.llm.status}`}>
              Groq: {report.llm.status}
            </span>
          )}
        </div>
        {report.llm?.error && <p className="llm-note">{report.llm.error}</p>}
        <NarrativeBlock title="Executive Summary" text={report.ai_narrative?.executive_summary} />
        <NarrativeBlock title="Risk Rationale" text={report.ai_narrative?.risk_rationale} />
        <NarrativeBlock title="Confidence Note" text={report.ai_narrative?.confidence_note} />
      </section>

      <section className="panel confidence-panel">
        <h3>Confidence & Review</h3>
        <div className={`confidence-score ${riskClass(report.confidence?.level)}`}>
          <span>{report.confidence?.level || "medium"}</span>
          <strong>{report.confidence?.score || 0}/100</strong>
        </div>
        <ul className="compact-list">
          {(report.confidence?.basis || []).map((item) => <li key={item}>{item}</li>)}
        </ul>
      </section>

      <section className="panel profile-panel">
        <h3>Customer Profile</h3>
        <InfoRows rows={[
          ["Account", report.account_id],
          ["Bank", account.bank_name],
          ["Type", account.customer_type],
          ["Country", account.country],
          ["Industry", account.industry],
          ["KYC Risk", account.kyc_risk_rating],
          ["KYC Status", account.kyc_status],
          ["Expected Monthly Volume", formatMoney(account.expected_monthly_volume)],
        ]} />
      </section>

      <section className="panel metrics-panel">
        <h3>Transaction Metrics</h3>
        <div className="metric-grid">
          <Metric label="Transactions" value={Number(metrics.total_transactions || 0).toLocaleString()} />
          <Metric label="Incoming" value={formatMoney(metrics.total_incoming_amount)} />
          <Metric label="Outgoing" value={formatMoney(metrics.total_outgoing_amount)} />
          <Metric label="Max Amount" value={formatMoney(metrics.max_transaction_amount)} />
          <Metric label="Fan-In" value={Number(metrics.unique_incoming_counterparties || 0).toLocaleString()} />
          <Metric label="Fan-Out" value={Number(metrics.unique_outgoing_counterparties || 0).toLocaleString()} />
        </div>
      </section>

      <section className="panel findings-panel">
        <h3>Risk Findings</h3>
        {findings.length === 0 ? (
          <p className="muted">No material risk findings.</p>
        ) : findings.map((finding, index) => (
          <article className="finding" key={`${finding.rule_id}-${index}`}>
            <div className={`severity ${riskClass(finding.severity)}`}>{finding.severity}</div>
            <div>
              <strong>{finding.rule_id}</strong>
              <p>{finding.reason}</p>
              <small>Score +{finding.score} · Evidence {finding.evidence_count}</small>
            </div>
          </article>
        ))}
      </section>

      <section className="panel timeline-panel">
        <h3>Investigation Log</h3>
        {(report.investigation_events || []).map((event) => (
          <article className="log-event" key={event.stage}>
            <strong>{event.stage}</strong>
            <p>{event.message}</p>
          </article>
        ))}
      </section>

      <section className="panel">
        <h3>Screening & Media</h3>
        <InfoRows rows={[
          ["Screening Matches", report.screening_matches.length],
          ["Adverse Media", report.adverse_media.length],
          ["Existing Cases", report.existing_cases.length],
          ["Beneficial Owners", report.beneficial_owners.length],
        ]} />
        <div className="mini-list">
          {report.screening_matches.slice(0, 3).map((match) => (
            <p key={match.match_id}>{match.source} · {match.list_type} · confidence {match.confidence}</p>
          ))}
          {report.adverse_media.slice(0, 3).map((media) => (
            <p key={media.media_id}>{media.risk_topic}: {media.headline}</p>
          ))}
        </div>
      </section>

      <section className="panel recommendation-panel">
        <h3>Final Recommendation</h3>
        <p>{report.final_recommendation}</p>
      </section>

      <section className="panel questions-panel">
        <h3>Analyst Questions</h3>
        <ol className="question-list">
          {(report.analyst_questions || []).map((question) => (
            <li key={question}>{question}</li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function NarrativeBlock({ title, text }) {
  if (!text) return null;
  return (
    <div className="narrative-block">
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

function InfoRows({ rows }) {
  return (
    <dl className="info-rows">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value ?? "-"}</dd>
        </div>
      ))}
    </dl>
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
