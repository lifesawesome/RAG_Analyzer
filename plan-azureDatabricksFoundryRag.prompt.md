## Plan: Azure Databricks + Foundry RAG

Build a working compliance-research pilot first, then harden it for production. **Azure Databricks owns document processing, embeddings and retrieval; Foundry Agent Service owns reasoning and tool orchestration.**

**Confirmed Setup**
- **Region:** West Europe.
- **Subscription:** your approved `AZURE_SUBSCRIPTION_ID`, using the locally configured tenant.
- **Budget:** USD 300/month target, with time-boxed build/demo windows.
- **Pilot:** synthetic DOCX/PDF documents, authenticated public endpoints, signed-in chat, citations and ingestion status.
- Existing Foundry and Azure AI Search resources remain untouched. No standalone VM, AKS or APIM.

**Resource Layout**
| New Resource Group | Contents |
|---|---|
| `rg-rag-dbx-dev-weu` | Azure Databricks, ADLS Gen2, Access Connector and data-platform identities |
| `rg-rag-foundry-dev-weu` | New Foundry resource and child project, model deployment, Container Apps application, application state and monitoring |

Databricks also creates its platform-managed resource group, as you approved. Production configuration will be separate, but production resources will not initially be deployed.

**Architecture**
**Ingestion:** Blob/ADLS documents → Databricks Auto Loader → Bronze → document parsing → Silver → structured chunks → Gold Delta table → Databricks-managed embeddings → Databricks AI Search.

**Chat:** signed-in user → application backend → Foundry agent → authorized Databricks retrieval → evidence-grounded answer with verified citations.

**Implementation Phases**
1. **Validate Readiness and Cost.** Check West Europe availability, subscription quota, Databricks account/Unity Catalog permissions, app-registration permissions and supported secretless authentication. Produce a complete cost estimate and operating schedule. **Your approval gates all paid deployment.**

2. **Create the Application and Sample Corpus.** Scaffold a Python/FastAPI backend and React/TypeScript frontend. Generate approximately 20 fictional DOCX/PDF documents covering lending, risk, compliance, agreements and audit findings, including historical versions, restricted documents and negative-test fixtures. This can proceed alongside infrastructure preparation.

3. **Provision the Foundations.** Deploy the two resource groups using Bicep. Configure private Blob containers, Unity Catalog storage access, Entra sign-in and scoped identities. Create a new Foundry project and a new `gpt-4.1` deployment, subject to availability and approved cost. Prove runtime authentication before building further.

4. **Build Databricks Document Processing.** Implement rerunnable Bronze/Silver/Gold jobs, structured PDF/DOCX parsing, section-aware chunking, table preservation, quarantine handling and ingestion status. Preserve source, page/section, document version, effective dates, classification and authorization metadata.

5. **Build Secure Hybrid Retrieval.** Create one standard Databricks AI Search endpoint with triggered Delta synchronization. Apply server-controlled tenant, entitlement and effective-date filters. Recheck current permissions before returning evidence to the model. Handle updates, deletions and revocations explicitly; index synchronization alone is insufficient.

6. **Connect Foundry and Complete the UI.** Start with a saved Foundry prompt agent using application-executed function calling, which keeps verified user identity outside model-controlled arguments. Add chat, citations, authenticated source viewing, historical-date queries and ingestion status. Enforce conversation ownership and invalidate stale context after permission changes.

7. **Add MCP Using the Same Retriever.** Expose the retrieval logic through authenticated MCP. Enable Foundry’s remote MCP path only after delegated-user authentication and two-user isolation tests pass. Current custom-MCP delegation has preview requirements; retain the working function-tool path if those requirements cannot be satisfied securely.

8. **Evaluate and Deliver the Pilot.** Add correlated tracing, billing visibility, security tests and a 50-question evaluation set. Deliver deployment, shutdown, rebuild and troubleshooting runbooks.

9. **Progress to Production Separately.** Add SharePoint/SQL ingestion with source-permission reconciliation, private networking, CI/CD, recovery procedures and staged load testing. Size the five-million-page deployment from measured document/chunk statistics, not assumptions.

**Acceptance Checks**
- Correct answers and citations for current and historical policies; abstention when evidence is missing.
- Zero unauthorized evidence in tool outputs, model inputs, citations or conversation history.
- Repeatable ingestion, update/delete propagation, revocation handling and recovery from failed jobs.
- Proposed retrieval target: `Recall@8 ≥ 0.85`; all displayed citations must resolve to authorized evidence.
- Successful desktop/mobile workflows and measured latency, token usage and operating cost.

**Cost Constraint**
USD 300 is **not yet a verified estimate**. Idle Databricks search indexes incur charges, and documented endpoint billing can continue for 24 hours after the last index is deleted. The plan therefore includes approved demo windows, billing-tail allowance and cleanup/rebuild procedures. Budget alerts are not hard spending caps.

**Planned Artifacts**
Under the repository root: Azure infrastructure, Databricks jobs, sample-document generator, backend/MCP adapter, frontend, evaluation suite and operational documentation.

The detailed execution plan is saved for handoff. **Nothing has been deployed or changed in your workspace, and no credentials are needed to review this plan.**