# Regulatory Research Workbench

## Architecture and Walkthrough

Read the [detailed solution architecture and execution walkthrough](docs/architecture.md) for the deployed resource layout, data objects, every ingestion/request step, user actions, identity boundaries, source viewing, update behavior and production gaps. The [two-layer architecture diagrams](.github/modernize/assessment/engines/facts/architecture-diagram.md) show deployment boundaries and code-component relationships.

The implemented live path is: **browser -> local FastAPI -> Foundry prompt agent -> function-call request -> backend-enforced Databricks hybrid search -> authorized evidence -> Foundry answer -> citation-ID validation -> browser**. Foundry does not directly invoke a deployed Databricks MCP server; the application executes its retrieval function. The source viewer separately renders local PDF copies.

| Stage | What happens | Detailed explanation |
| --- | --- | --- |
| Prepare knowledge | Download/generate PDFs, verify manifest, upload to a managed Volume, parse pages, split 600/80 characters, write Delta tables | [Knowledge preparation](docs/architecture.md#4-knowledge-preparation-every-step) |
| Finalize retrieval | Cast the effective date to `DATE`, create a versioned triggered index and let Databricks compute embeddings | [Data objects](docs/architecture.md#3-data-objects-and-where-they-live) |
| Research a question | Validate input, create a fresh Foundry conversation, execute the requested search with server-owned filters, generate and validate a cited response | [Online research](docs/architecture.md#6-online-research-every-request-step) |
| Inspect sources | Recheck demo permissions, render a local PDF page and navigate its pages | [Source viewing](docs/architecture.md#7-source-pdf-viewing-every-step) |
| Inspect execution | View service stages/response IDs and download an actual request receipt | [Traces and evidence](docs/architecture.md#12-traces-evidence-and-verification) |
| Operate or extend | Restart the presenter app, verify live mode, plan explicit refreshes and understand unimplemented production controls | [Operator runbook](docs/architecture.md#13-operator-runbook) and [production gaps](docs/architecture.md#14-production-work-not-implemented) |

The live demo uses a **fixed presenter access context**, not browser-user delegation. Its date filter does not automatically select the latest policy version, and its citation validator checks IDs rather than claim entailment. The active DATE-typed Gold table is a snapshot: future source changes require an explicit projection refresh and active-index sync. These limits are detailed in the guide so the implemented demo is not confused with the full original plan.

## Public Repository and Configuration

This repository contains the application, infrastructure templates, notebook, scripts, tests and architecture documentation. Live Azure IDs and service URLs are intentionally not published. Local credentials/configuration, deployment notes, generated PDFs, caches and execution receipts are excluded from Git.

For a new checkout, copy the example without overwriting an existing local configuration:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Offline mode does not require Azure configuration. For live mode, set `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `DATABRICKS_HOST`, `DATABRICKS_INDEX` and `FOUNDRY_PROJECT_ENDPOINT` in the ignored local `.env`, using your own approved environment. Set the agent/model names if they differ from the examples. Authenticate with Azure CLI separately; never put access tokens, passwords or API keys in committed files.

The original live demonstration verified a 40-PDF corpus and 6,560 indexed chunks, a Foundry-to-Databricks function call, access-denial cases and desktop/mobile workflows. The notebook run itself timed out; independent index/query checks established the completed data path, not a successful notebook return. These are historical local results, not a deployment supplied by cloning this repository.

This is a presenter-only, runnable PDF research demo. The browser clearly distinguishes local rehearsal, Databricks retrieval and Foundry-backed answers. It never silently substitutes local results for a failed cloud operation.

## What Is Ready

- 20 downloaded public BIS/Basel Committee PDFs plus 20 explicitly synthetic bank-policy PDFs in `data/pdfs`, with provenance and hashes in `data/manifest.json`.
- Responsive research screen, source PDF viewer, authorized corpus browser, date filtering and inspectable application execution receipts.
- Server-owned tenant/group/classification filters; browser identity headers cannot change them.
- Databricks notebook: managed Volume, Bronze/Silver/Gold Delta tables, deterministic character-based 600/80 chunks, CDF, triggered managed-embedding index and a real hybrid-query/denied-cohort check.
- Foundry saved prompt agent and bounded function-call loop, using Azure CLI credentials rather than keys.
- Backend tests and a desktop/mobile browser smoke test.

## Start the Local Rehearsal

Windows / Python 3.13:

```powershell
.\scripts\Start-Demo.ps1
```

The script prints the selected URL, normally http://127.0.0.1:8765, and chooses another port if needed. Keep the terminal running. The first corpus parse can take a few minutes; subsequent starts reuse a document-hash-keyed cache (approximately 1.1 seconds for 6,560 chunks on the build machine). The existing corpus is retained; `-DownloadPublic` explicitly regenerates the fixtures and refreshes the public corpus. VS Code also has offline/live debug configurations on port 8766.

Offline mode uses SQLite FTS5 BM25 over real local PDF text. **It does not call Databricks, compute embeddings, or generate a Foundry answer.** Its output is evidence retrieval for rehearsal, not proof of the cloud architecture. The interface and receipts say so.

## Prepare Your Own Live Environment

1. Review [infra/main.bicep](infra/main.bicep) and its parameters before provisioning a dedicated demo workspace and Foundry resource/project/model. Resource names in the templates are sample defaults, not references to an available shared deployment. Cloud provisioning and model/search usage incur charges.
2. Have a Databricks account administrator assign a metastore and approve a dedicated demo catalog with managed storage, schema/table/Volume privileges and embedding access. Azure subscription Owner is not Databricks account admin.
3. Generate the local corpus with the launcher, then use [the notebook](notebooks/01_databricks_rag.ipynb) to upload/process the manifest and PDFs. The notebook's paid-search widget remains confirmation-gated. The optional live runner below requires its explicit host/tenant to match your local configuration, and checks subscription-derived schema/Volume ownership markers before overwriting demo contents.
4. Finalize the DATE-typed projection/index if needed, set `DATABRICKS_INDEX` to that index, and verify real retrieval using `.\scripts\Start-Demo.ps1 -Mode databricks`. The finalizer retains existing data and requires explicit subscription and warehouse IDs for execution.
5. Configure `FOUNDRY_PROJECT_ENDPOINT` and the model deployment. The signed-in Azure CLI principal needs Foundry project agent-management/invocation permissions, Databricks workspace access, Unity Catalog `USE CATALOG`, `USE SCHEMA`, `SELECT` on the index and embedding endpoint query permissions. Azure subscription Contributor alone does not establish those data-plane permissions.
6. Create the saved prompt agent in your own project, or intentionally create a new version of an existing definition:

```powershell
$env:RAG_MODE = 'foundry'
.\.venv\Scripts\python.exe -m app.cloud
```

7. Restart with `.\scripts\Start-Demo.ps1 -Mode foundry`. A successful request should show an actual Foundry response ID, Databricks hybrid retrieval, the exact application-enforced predicates, evidence and validated citation IDs. The app creates and deletes a fresh conversation per question; persistent multi-turn history is deliberately out of scope.

The following are command templates, not automatic deployment steps. Replace every placeholder with an explicitly approved value; do not run the paid steps without reviewing their targets:

```powershell
.\.venv\Scripts\python.exe scripts\live_preflight.py --subscription "<your-subscription-id>" --tenant "<your-tenant-id>"
.\.venv\Scripts\python.exe scripts\live_databricks.py --host "<configured-workspace-url>" --tenant "<configured-tenant-id>" --subscription "<your-subscription-id>" --catalog "<approved-demo-catalog>"
.\.venv\Scripts\python.exe scripts\finalize_live_index.py --catalog "<approved-demo-catalog>"
```

The ingestion runner uploads the corpus even without `--execute`; adding that flag starts paid serverless processing and index creation. The finalizer only prints SQL without `--execute`; execution additionally requires `--subscription "<your-subscription-id>" --warehouse "<approved-warehouse-id>"`. Keep your own environment values in local configuration or command arguments rather than source code.

The quickest reliable bridge is an **application-executed Foundry function tool**: the managed agent requests retrieval; this application executes the Databricks call under its server-owned demo policy and returns the evidence. It does not require exposing a local HTTP server to Foundry. **No remote MCP/OpenAPI tool is deployed.** A public bridge would require authenticated HTTPS hosting and verified identity/delegation, not an unverified caller header.

## Five-Minute Customer Walkthrough

1. Show mode and corpus counts. Open a public Basel PDF to establish real provenance. Explain that bank-policy fixtures are fictional and governance dates/classifications are demo labels, not original publication metadata.
2. Ask: "How do liquidity coverage and stable funding requirements differ?" In Foundry mode, inspect the grounded answer; in offline mode, show the retrieved passages and explicitly call it a rehearsal.
3. Ask: "What approvals apply to elevated-risk commercial lending?" Show synthetic policy evidence and page/version citations. Do not present synthetic bank rules as actual Basel obligations.
4. Open **Execution trace**. In live mode capture the Foundry response ID, Databricks operation and exact predicates. This is the application's trace; internal Databricks predicates are not assumed to be visible inside Foundry's own trace UI.
5. Set the as-of date to 2024-01-01. The fixture corpus has no eligible documents, so retrieval should abstain. Explain that this proves the demo's effective-date predicate, not a complete historical policy/versioning system.

## Test and Capture Screenshots

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip install playwright==1.64.1
.\.venv\Scripts\python.exe scripts/browser_smoke.py
```

By default, the browser script requires offline mode and writes honestly labeled rehearsal evidence. With explicit `--allow-live`, it exercises real Foundry/Databricks requests and writes separate live screenshots/receipts under `artifacts`. It uses installed Microsoft Edge; PDFium renders source pages rather than depending on a browser PDF plugin. In the UI, use **Execution trace -> Download receipt** to export the actual request, filters, evidence and trace. The independently verified live RAG receipt is the authoritative end-to-end evidence; the timed-out notebook run remains recorded as timed out.

Current verification includes the backend/runner suite, an actual Foundry-to-Databricks tool call and live desktop/mobile browser flows with receipt download. The six-cell source notebook remains unchanged; its prepared remote copy handles runtime compatibility. The original text-typed date column was migrated through a versioned DATE-typed Gold projection/index rather than weakening the server-side date filter.

For explicitly authorized cloud-backed browser tests, use `./.venv/Scripts/python.exe scripts/browser_smoke.py --url http://127.0.0.1:8766 --allow-live`. Without `--allow-live`, the browser checker refuses cloud mode. Live screenshots are under `artifacts/live-*.png`; these checks incur real model/retrieval usage.

## Scope and Costs

This is a **loopback-only presenter application**, not a signed-in multi-user or production bank system. Do not change the bind address or expose it through a tunnel. Source permissions, revocation reconciliation, safe conversation retention, production classification policy, parser quality evaluation, Entra sign-in, remote MCP delegation, private networking and enterprise connectors remain follow-on work. Current policy metadata is fixture configuration, not SharePoint ACL inheritance.

The recorded West Europe estimate was USD 0.336/hour for one standard search unit (4 DBU/hour at USD 0.084 per DBU-hour), approximately USD 24.19 for 48 active hours plus a documented 24-hour post-deletion tail. This is a historical planning assumption, not a current quote. Actual compute, indexing, embeddings, model tokens, managed networking and storage are additional, and capacity depends on the combined index size. USD 300/month was a target, not a hard cap. No automatic cleanup or hard cap is configured. Review your own active resources and verify subscription, ownership and managed-resource lifecycle before any cleanup; never delete unrelated/shared resources.