from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    mode: str = "offline"
    data_dir: Path = ROOT / "data"
    tenant_id: str = "us-commercial"
    acl_groups: tuple[str, ...] = ("compliance-analysts",)
    azure_tenant_id: str = ""
    databricks_host: str = ""
    databricks_index: str = "rag_demo.rag.policy_chunks_index"
    foundry_endpoint: str = ""
    foundry_agent: str = "regulatory-research-demo"
    foundry_model: str = "gpt-4.1"

    @classmethod
    def from_env(cls):
        return cls(
            mode=os.getenv("RAG_MODE", "offline"),
            tenant_id=os.getenv("DEMO_TENANT_ID", "us-commercial"),
            acl_groups=tuple(group.strip() for group in os.getenv(
                "DEMO_ACL_GROUPS", "compliance-analysts"
            ).split(",") if group.strip()),
            azure_tenant_id=os.getenv("AZURE_TENANT_ID", cls.azure_tenant_id),
            databricks_host=os.getenv("DATABRICKS_HOST", "").rstrip("/"),
            databricks_index=os.getenv("DATABRICKS_INDEX", cls.databricks_index),
            foundry_endpoint=os.getenv("FOUNDRY_PROJECT_ENDPOINT", ""),
            foundry_agent=os.getenv("FOUNDRY_AGENT_NAME", cls.foundry_agent),
            foundry_model=os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", cls.foundry_model),
        )

    def validate_live(self):
        if self.mode not in {"offline", "databricks", "foundry"}:
            raise ValueError("RAG_MODE must be offline, databricks, or foundry.")
        if self.mode == "offline":
            return
        host = urlparse(self.databricks_host)
        if host.scheme != "https" or not host.hostname or not host.hostname.endswith(".azuredatabricks.net"):
            raise ValueError("Set DATABRICKS_HOST to the new Azure Databricks workspace HTTPS URL.")
        if not self.azure_tenant_id:
            raise ValueError("Set AZURE_TENANT_ID to the approved Microsoft Entra tenant.")
        if self.mode == "foundry":
            endpoint = urlparse(self.foundry_endpoint)
            if endpoint.scheme != "https" or not endpoint.hostname or not endpoint.hostname.endswith(".services.ai.azure.com"):
                raise ValueError("Set FOUNDRY_PROJECT_ENDPOINT to the new Foundry project HTTPS endpoint.")
