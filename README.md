# FinAgent EDD Agent

SQLite-backed Enhanced Due Diligence agent for the local AML dataset.

## Generate an EDD report

```bash
python3 -m edd_agent.cli report --account-id 100428660
```

Save the generated report and an audit-log entry:

```bash
python3 -m edd_agent.cli report --account-id 100428660 --save
```

Print the full report payload as JSON:

```bash
python3 -m edd_agent.cli report --account-id 100428660 --json
```

## What the Agent Checks

- Account and KYC profile from `accounts` and `customer_kyc`
- Beneficial ownership and PEP indicators from `beneficial_owners`
- Transaction behavior from `transactions`
- Watchlist and PEP hits from `screening_matches` and `watchlists`
- Negative-news style indicators from `adverse_media`
- Existing EDD cases from `edd_cases`

The first implementation keeps scoring deterministic and explainable. The report narrative is generated from the collected context and fired risk rules, then persisted to `edd_reports` when `--save` is used.

## Run the React UI

Configure Groq LLM:

```bash
cp .env.example .env
```

Then edit `.env` and set:

```text
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
```

Build the React app:

```bash
cd frontend
npm install
npm run build
cd ..
```

Start the FastAPI API/static server:

```bash
python3 -m edd_agent.web
```

Then open:

```text
http://127.0.0.1:5050
```

If port `5050` is already busy:

```bash
PORT=5052 python3 -m edd_agent.web
```

The UI lets an analyst choose or enter an account ID, generate an EDD report, inspect findings and transaction metrics, and optionally save the report to the SQLite database.
It also includes a Transaction Monitoring alert queue where analysts can run scenario scans, inspect alert evidence, and disposition alerts.

For frontend-only development with hot reload:

```bash
cd frontend
npm run dev
```

Keep `python3 -m edd_agent.web` running in another terminal so Vite can proxy `/api` requests.

The backend uses FastAPI and SQLAlchemy ORM for database access.
Groq is used for the AI narrative when `GROQ_API_KEY` is configured. If the key is missing or the Groq request fails, the app keeps the structured fallback narrative and shows the LLM status in the UI.

## Transaction Monitoring Agent

The TM agent creates alerts from transaction patterns and stores evidence.

Available API endpoints:

```text
POST /api/tm/run
GET  /api/tm/alerts
GET  /api/tm/alerts/{alert_id}
POST /api/tm/alerts/{alert_id}/disposition
```

Scenarios currently included:

- Known laundering label
- High value activity
- Structuring below threshold
- Fan-out distribution
- Fan-in aggregation
- Rapid in-out movement
- Cash or crypto exposure

## Project Structure

```text
edd_agent/
  api/          FastAPI app factory and request schemas
  core/         shared integrations such as Groq LLM
  database/     SQLite connection helpers and SQLAlchemy ORM models
  edd/          EDD investigation, rules, and report generation
  tm/           Transaction Monitoring scanner, alerts, evidence, dispositions
  cli.py        CLI entrypoint
  web.py        compatibility server entrypoint

frontend/src/
  pages/        React page-level views
  components/   reserved for shared UI components
  utils/        reserved for shared frontend helpers
```
