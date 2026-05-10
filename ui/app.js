const { useEffect, useMemo, useState } = React;

const severityOrder = { critical: 4, high: 3, medium: 2, low: 1 };

function formatMoney(value) {
  return Number(value || 0).toLocaleString(undefined, {
    maximumFractionDigits: 2,
  });
}

function riskClass(level) {
  return `risk-${String(level || "low").toLowerCase()}`;
}

function App() {
  const [accountId, setAccountId] = useState("100428660");
  const [saveReport, setSaveReport] = useState(false);
  const [samples, setSamples] = useState([]);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch("/api/sample-accounts")
      .then((res) => res.json())
      .then(setSamples)
      .catch(() => setSamples([]));
  }, []);

  async function generateReport(event) {
    event?.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: accountId, save: saveReport }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not generate report");
      setReport(data);
    } catch (err) {
      setReport(null);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const findings = useMemo(() => {
    return [...(report?.risk_findings || [])].sort((a, b) => {
      return (severityOrder[b.severity] || 0) - (severityOrder[a.severity] || 0);
    });
  }, [report]);

  return (
    React.createElement("main", { className: "app-shell" },
      React.createElement("section", { className: "workspace" },
        React.createElement("aside", { className: "sidebar" },
          React.createElement("div", { className: "brand" },
            React.createElement("div", { className: "brand-mark" }, "F"),
            React.createElement("div", null,
              React.createElement("h1", null, "FinAgent EDD"),
              React.createElement("p", null, "Analyst investigation console")
            )
          ),
          React.createElement("form", { className: "search-panel", onSubmit: generateReport },
            React.createElement("label", { htmlFor: "account-id" }, "Account ID"),
            React.createElement("input", {
              id: "account-id",
              value: accountId,
              onChange: (event) => setAccountId(event.target.value),
              placeholder: "Enter account ID",
            }),
            React.createElement("label", { className: "toggle" },
              React.createElement("input", {
                type: "checkbox",
                checked: saveReport,
                onChange: (event) => setSaveReport(event.target.checked),
              }),
              React.createElement("span", null, "Save report to database")
            ),
            React.createElement("button", { type: "submit", disabled: loading },
              loading ? "Generating..." : "Generate EDD Report"
            )
          ),
          React.createElement("div", { className: "sample-list" },
            React.createElement("h2", null, "Sample Accounts"),
            samples.map((item) =>
              React.createElement("button", {
                key: item.account_id,
                className: "sample-item",
                onClick: () => setAccountId(item.account_id),
              },
                React.createElement("span", null, item.account_id),
                React.createElement("small", null, `${item.entity_name} · ${item.risk_rating}`)
              )
            )
          )
        ),
        React.createElement("section", { className: "content" },
          React.createElement("header", { className: "topbar" },
            React.createElement("div", null,
              React.createElement("h2", null, "EDD Investigation"),
              React.createElement("p", null, "Profile, transaction behavior, screening, media, evidence, and recommendation.")
            ),
            report && React.createElement("div", { className: `risk-badge ${riskClass(report.risk_level)}` },
              React.createElement("span", null, report.risk_level),
              React.createElement("strong", null, `${report.risk_score}/100`)
            )
          ),
          error && React.createElement("div", { className: "error" }, error),
          !report && !error && React.createElement(EmptyState, { loading }),
          report && React.createElement(ReportView, { report, findings })
        )
      )
    )
  );
}

function EmptyState({ loading }) {
  return React.createElement("div", { className: "empty-state" },
    React.createElement("h3", null, loading ? "Investigation running..." : "Ready for investigation"),
    React.createElement("p", null, "Enter an account ID or choose a sample account, then generate an EDD report.")
  );
}

function ReportView({ report, findings }) {
  const account = report.customer_profile;
  const metrics = report.transaction_metrics;
  return React.createElement("div", { className: "report-grid" },
    React.createElement("section", { className: "summary-band" },
      React.createElement("div", null,
        React.createElement("h3", null, account.entity_name),
        React.createElement("p", null, report.edd_summary)
      ),
      report.report_id && React.createElement("div", { className: "saved-pill" }, `Saved #${report.report_id}`)
    ),
    React.createElement("section", { className: "panel profile-panel" },
      React.createElement("h3", null, "Customer Profile"),
      React.createElement(InfoRows, { rows: [
        ["Account", report.account_id],
        ["Bank", account.bank_name],
        ["Type", account.customer_type],
        ["Country", account.country],
        ["Industry", account.industry],
        ["KYC Risk", account.kyc_risk_rating],
        ["KYC Status", account.kyc_status],
        ["Expected Monthly Volume", formatMoney(account.expected_monthly_volume)],
      ]})
    ),
    React.createElement("section", { className: "panel metrics-panel" },
      React.createElement("h3", null, "Transaction Metrics"),
      React.createElement("div", { className: "metric-grid" },
        React.createElement(Metric, { label: "Transactions", value: Number(metrics.total_transactions || 0).toLocaleString() }),
        React.createElement(Metric, { label: "Incoming", value: formatMoney(metrics.total_incoming_amount) }),
        React.createElement(Metric, { label: "Outgoing", value: formatMoney(metrics.total_outgoing_amount) }),
        React.createElement(Metric, { label: "Max Amount", value: formatMoney(metrics.max_transaction_amount) }),
        React.createElement(Metric, { label: "Fan-In", value: Number(metrics.unique_incoming_counterparties || 0).toLocaleString() }),
        React.createElement(Metric, { label: "Fan-Out", value: Number(metrics.unique_outgoing_counterparties || 0).toLocaleString() })
      )
    ),
    React.createElement("section", { className: "panel findings-panel" },
      React.createElement("h3", null, "Risk Findings"),
      findings.length === 0
        ? React.createElement("p", { className: "muted" }, "No material risk findings.")
        : findings.map((finding, index) => React.createElement("article", { className: "finding", key: `${finding.rule_id}-${index}` },
            React.createElement("div", { className: `severity ${riskClass(finding.severity)}` }, finding.severity),
            React.createElement("div", null,
              React.createElement("strong", null, finding.rule_id),
              React.createElement("p", null, finding.reason),
              React.createElement("small", null, `Score +${finding.score} · Evidence ${finding.evidence_count}`)
            )
          ))
    ),
    React.createElement("section", { className: "panel" },
      React.createElement("h3", null, "Screening & Media"),
      React.createElement(InfoRows, { rows: [
        ["Screening Matches", report.screening_matches.length],
        ["Adverse Media", report.adverse_media.length],
        ["Existing Cases", report.existing_cases.length],
        ["Beneficial Owners", report.beneficial_owners.length],
      ]}),
      React.createElement("div", { className: "mini-list" },
        report.screening_matches.slice(0, 3).map((match) =>
          React.createElement("p", { key: match.match_id }, `${match.source} · ${match.list_type} · confidence ${match.confidence}`)
        ),
        report.adverse_media.slice(0, 3).map((media) =>
          React.createElement("p", { key: media.media_id }, `${media.risk_topic}: ${media.headline}`)
        )
      )
    ),
    React.createElement("section", { className: "panel recommendation-panel" },
      React.createElement("h3", null, "Final Recommendation"),
      React.createElement("p", null, report.final_recommendation)
    )
  );
}

function InfoRows({ rows }) {
  return React.createElement("dl", { className: "info-rows" },
    rows.map(([label, value]) => React.createElement("div", { key: label },
      React.createElement("dt", null, label),
      React.createElement("dd", null, value ?? "-")
    ))
  );
}

function Metric({ label, value }) {
  return React.createElement("div", { className: "metric" },
    React.createElement("span", null, label),
    React.createElement("strong", null, value)
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(App));
