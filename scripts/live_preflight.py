import argparse
import json
from pathlib import Path
import shutil
import subprocess

import httpx


def az_json(*arguments):
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is required.")
    result = subprocess.run([executable, *arguments, "--output", "json"], capture_output=True, text=True, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError(f"Azure CLI read failed for {arguments[:3]}: {result.stderr[:1000]}")
    return json.loads(result.stdout)


def prices(client, service, region="westeurope"):
    url = "https://prices.azure.com/api/retail/prices"
    params = {"$filter": f"serviceName eq '{service}' and armRegionName eq '{region}' and priceType eq 'Consumption'", "currencyCode": "USD"}
    items = []
    while url:
        response = client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        items.extend(payload["Items"])
        url = payload.get("NextPageLink")
        params = None
    return items


def main():
    parser = argparse.ArgumentParser(description="Read-only Azure RAG quota and pricing preflight.")
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    context = az_json("account", "show", "--subscription", args.subscription)
    if context["id"] != args.subscription or context["tenantId"] != args.tenant:
        raise RuntimeError("The signed-in Azure subscription or tenant differs from the approved environment.")
    quotas = az_json("cognitiveservices", "usage", "list", "--location", "westeurope", "--subscription", args.subscription)
    relevant = [item for item in quotas if item["name"]["value"] in {"OpenAI.DataZoneStandard.gpt4.1", "OpenAI.GlobalStandard.gpt4.1"}]
    role = az_json("role", "definition", "list", "--name", "Foundry User", "--subscription", args.subscription)
    if len(role) != 1:
        raise RuntimeError("Could not uniquely resolve the Foundry User role definition.")
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        databricks = prices(client, "Azure Databricks")
        databricks.extend(prices(client, "Azure Databricks", "global"))
        databricks.extend(prices(client, "Azure Databricks", ""))
    selected = [item for item in databricks if any(term in " ".join(str(item.get(key, "")) for key in ["meterName", "skuName", "productName"]).lower() for term in ["vector", "search", "serverless", "inference", "jobs", "model serving"])]
    report = {
        "subscription": args.subscription, "tenant": args.tenant, "region": "westeurope",
        "foundry_user_role_id": role[0]["name"],
        "model_quota": [{"name": item["name"]["value"], "limit": item["limit"], "used": item["currentValue"]} for item in relevant],
        "databricks_consumption_prices": [{key: item.get(key) for key in ["meterName", "skuName", "productName", "armRegionName", "retailPrice", "unitOfMeasure", "currencyCode", "effectiveStartDate"]} for item in selected],
        "pricing_source": "https://prices.azure.com/api/retail/prices",
        "search_billing_tail_hours": 24,
        "mutations_performed": False,
    }
    output = args.output or Path(__file__).resolve().parents[1] / "artifacts" / f"live-preflight-{args.subscription[:8]}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()