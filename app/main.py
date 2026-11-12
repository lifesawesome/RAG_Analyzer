from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
import io
from pathlib import Path
import threading
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import ROOT, Settings
from app.contracts import AccessContext, Evidence, permitted, search_filters
from app.local_search import LocalSearch, build_chunks, document_path, load_manifest


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=3, max_length=2000)
    as_of: date = Field(default_factory=date.today)
    top_k: int = Field(default=6, ge=1, le=8)


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    search_lock = threading.Lock()
    render_lock = threading.Lock()
    state = {"index": None, "last_live_success": None, "verified_services": set()}
    context = AccessContext(settings.tenant_id, settings.acl_groups)

    @asynccontextmanager
    async def lifespan(application):
        if settings.mode == "offline":
            state["index"] = LocalSearch(build_chunks(settings.data_dir))
        yield
        if state["index"]:
            state["index"].connection.close()

    application = FastAPI(title="Regulatory Research Workbench", lifespan=lifespan)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @application.middleware("http")
    async def local_only(request: Request, call_next):
        if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "This presenter-only demo accepts loopback clients only."}, status_code=403)
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Cross-origin requests are not allowed."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/api/status")
    def status():
        manifest = load_manifest(settings.data_dir)
        chunks = len(state["index"].chunks) if state["index"] else None
        try:
            settings.validate_live()
            configuration_error = None
        except ValueError as error:
            configuration_error = str(error)
        return {
            "mode": settings.mode, "documents": len(manifest),
            "public_documents": sum(bool(entry.get("source_url")) for entry in manifest),
            "chunks": chunks, "tenant": context.tenant_id, "groups": context.acl_groups,
            "last_live_success": state["last_live_success"], "configuration_error": configuration_error,
            "pipeline": [
                {"name": "PDF corpus", "state": "ready" if manifest else "missing"},
                {"name": "Local rehearsal index", "state": "ready" if chunks else "not active"},
                {"name": "Databricks AI Search", "state": "verified" if "Databricks hybrid search" in state["verified_services"] else "not called"},
                {"name": "Foundry Agent Service", "state": "verified" if "Foundry Agent Service" in state["verified_services"] else "not called"},
            ],
        }

    @application.get("/api/documents")
    def documents():
        result = []
        for entry in load_manifest(settings.data_dir):
            guard = Evidence("", entry["doc_id"], entry["title"], "", 1, entry["document_version"], entry["effective_date"], entry["tenant_id"], entry["acl_group"], entry["classification"])
            if permitted(guard, context, date.today()):
                result.append({key: value for key, value in entry.items() if key not in {"path", "sha256"}})
        return result

    def authorized_document(doc_id: str):
        entry = next((item for item in load_manifest(settings.data_dir) if item["doc_id"] == doc_id), None)
        if not entry:
            raise HTTPException(404, "Document not found in the local corpus.")
        guard = Evidence("", entry["doc_id"], entry["title"], "", 1, entry["document_version"], entry["effective_date"], entry["tenant_id"], entry["acl_group"], entry["classification"])
        if not permitted(guard, context, date.today()):
            raise HTTPException(404, "Document not found in the authorized corpus.")
        return entry

    @application.get("/api/documents/{doc_id}")
    def document(doc_id: str):
        entry = authorized_document(doc_id)
        return FileResponse(document_path(settings.data_dir, entry), media_type="application/pdf", filename=f"{doc_id}.pdf", content_disposition_type="inline")

    @application.get("/api/documents/{doc_id}/preview/{page_number}")
    def preview(doc_id: str, page_number: int):
        import pypdfium2 as pdfium
        entry = authorized_document(doc_id)
        with render_lock:
            pdf = pdfium.PdfDocument(str(document_path(settings.data_dir, entry)))
            try:
                page_count = len(pdf)
                if not 1 <= page_number <= page_count:
                    raise HTTPException(404, "Page not found.")
                page = pdf[page_number - 1]
                try:
                    bitmap = page.render(scale=1.5)
                    try:
                        image = bitmap.to_pil()
                        buffer = io.BytesIO()
                        image.save(buffer, format="PNG")
                        image.close()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            finally:
                pdf.close()
        return Response(buffer.getvalue(), media_type="image/png", headers={"X-Page-Count": str(page_count)})

    @application.post("/api/ask")
    def ask(question: Question):
        started = perf_counter()
        trace = []
        request_id = str(uuid4())
        filters = search_filters(context, question.as_of)

        def retrieve(query):
            search_started = perf_counter()
            if settings.mode == "offline":
                with search_lock:
                    evidence = state["index"].search(query, context, question.as_of, question.top_k)
            else:
                from app.cloud import databricks_search
                evidence = databricks_search(settings, query, context, question.as_of, question.top_k)
            trace.append({"stage": "Local BM25 search" if settings.mode == "offline" else "Databricks hybrid search", "detail": f"{len(evidence)} authorized passages", "milliseconds": round((perf_counter() - search_started) * 1000), "status": "ok", "filters": filters})
            return evidence

        try:
            settings.validate_live()
            if settings.mode == "foundry":
                from app.cloud import foundry_answer
                answer, evidence = foundry_answer(settings, question.query, retrieve, trace)
            else:
                evidence = retrieve(question.query)
                answer = {
                    "answer": "Authorized passages are shown below. This is extractive retrieval, not a model-generated answer." if evidence else "No authorized evidence matched the question and as-of date.",
                    "citations": [f"E{position}" for position in range(1, len(evidence) + 1)],
                }
            if settings.mode != "offline":
                state["verified_services"].update(item["stage"] for item in trace if item["status"] == "ok")
                required = {"Databricks hybrid search"}
                if settings.mode == "foundry":
                    required.add("Foundry Agent Service")
                if required.issubset(state["verified_services"]):
                    state["last_live_success"] = date.today().isoformat()
        except Exception as error:
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else f"{type(error).__name__}: live operation failed. Check sign-in, project/index configuration and service permissions."
            raise HTTPException(503, message) from error
        return {
            **answer, "request_id": request_id, "mode": settings.mode,
            "query": question.query, "as_of": question.as_of.isoformat(),
            "corpus_documents": len(load_manifest(settings.data_dir)),
            "elapsed_ms": round((perf_counter() - started) * 1000), "filters": filters,
            "evidence": [{**asdict(item), "evidence_id": f"E{position}"} for position, item in enumerate(evidence, start=1)],
            "trace": trace,
        }

    application.mount("/", StaticFiles(directory=ROOT / "app" / "static", html=True), name="web")
    return application


app = create_app()
