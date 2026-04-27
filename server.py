#!/usr/bin/env python3
"""TourScale Listmonk MCP — read + write access to lists, subscribers, campaigns,
templates, and transactional sends.

Talks to the running Listmonk instance (listmonk.tourscale.com) via the REST API
as a dedicated `claude-api` user (type=api, token stored as plaintext in
users.password — Listmonk v6 quirk). Auth header: `Authorization: token user:token`.

Tools cover the surface agents need:
- Read: who's on which list, what templates exist, what campaigns ran
- Write: add/update subscribers, create + start campaigns, transactional sends
"""
import json
import os
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("listmonk")

API_URL = os.environ.get("LISTMONK_URL", "https://listmonk.tourscale.com").rstrip("/")
API_USER = os.environ["LISTMONK_API_USER"]
API_TOKEN = os.environ["LISTMONK_API_TOKEN"]


def _headers(json_body: bool = False) -> dict:
    h = {
        "Authorization": f"token {API_USER}:{API_TOKEN}",
        "Accept": "application/json",
    }
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _call(method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any:
    url = f"{API_URL}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url = f"{url}?{urlencode(clean)}"
    data = json.dumps(body).encode() if body is not None else None
    try:
        req = Request(url, data=data, headers=_headers(json_body=data is not None), method=method)
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")
        return {"_error": e.code, "_body": body_txt[:500]}
    except URLError as e:
        return {"_error": "URLError", "_body": str(e)}


def _fmt(resp: Any) -> str:
    if isinstance(resp, dict) and "_error" in resp:
        return f"ERROR {resp['_error']}: {resp.get('_body', '')}"
    return json.dumps(resp.get("data", resp) if isinstance(resp, dict) else resp, indent=2, default=str)


# ─── Health / probe ──────────────────────────────────────────────────────────

@mcp.tool()
def health() -> str:
    """Probe Listmonk connectivity and authentication."""
    res = _call("GET", "/api/lists", params={"per_page": 1})
    if isinstance(res, dict) and "_error" in res:
        return f"DOWN — {res['_error']}: {res.get('_body', '')}"
    total = res.get("data", {}).get("total", "?")
    return f"OK — listmonk {API_URL} reachable, lists.total={total}"


# ─── Lists ───────────────────────────────────────────────────────────────────

@mcp.tool()
def list_lists(per_page: int = 50, query: str | None = None) -> str:
    """List all subscriber lists. Optional query for name search."""
    return _fmt(_call("GET", "/api/lists", params={"per_page": per_page, "query": query}))


@mcp.tool()
def get_list(list_id: int) -> str:
    """Get one list by numeric ID."""
    return _fmt(_call("GET", f"/api/lists/{list_id}"))


# ─── Subscribers ─────────────────────────────────────────────────────────────

@mcp.tool()
def list_subscribers(
    list_id: int | None = None,
    query: str | None = None,
    per_page: int = 50,
    page: int = 1,
) -> str:
    """List subscribers. Filter by list_id or by query (Listmonk's SQL-like subscriber query syntax, e.g. `subscribers.email='kai@tourscale.com'`)."""
    params = {"per_page": per_page, "page": page}
    if list_id is not None:
        params["list_id"] = list_id
    if query:
        params["query"] = query
    return _fmt(_call("GET", "/api/subscribers", params=params))


@mcp.tool()
def get_subscriber(subscriber_id: int) -> str:
    """Get a subscriber by numeric ID. Use list_subscribers with a query first if you only have an email."""
    return _fmt(_call("GET", f"/api/subscribers/{subscriber_id}"))


@mcp.tool()
def find_subscriber_by_email(email: str) -> str:
    """Look up a subscriber by email address. Returns 0 or 1 results."""
    q = f"subscribers.email='{email.replace(chr(39), chr(39)*2)}'"
    return _fmt(_call("GET", "/api/subscribers", params={"query": q, "per_page": 5}))


@mcp.tool()
def add_subscriber(
    email: str,
    name: str,
    list_ids: str,
    status: str = "enabled",
    attribs_json: str | None = None,
) -> str:
    """Create a subscriber and attach to one or more lists. list_ids is a comma-separated string of list IDs (e.g. '3,5'). attribs_json is an optional JSON object of custom attributes."""
    body = {
        "email": email,
        "name": name,
        "status": status,
        "lists": [int(x) for x in list_ids.split(",") if x.strip()],
    }
    if attribs_json:
        body["attribs"] = json.loads(attribs_json)
    return _fmt(_call("POST", "/api/subscribers", body=body))


@mcp.tool()
def update_subscriber(subscriber_id: int, payload_json: str) -> str:
    """Update a subscriber. payload_json is the partial JSON body (e.g. {\"name\":\"New Name\",\"status\":\"blocklisted\"})."""
    return _fmt(_call("PUT", f"/api/subscribers/{subscriber_id}", body=json.loads(payload_json)))


@mcp.tool()
def add_subscribers_to_lists(subscriber_ids: str, list_ids: str, action: str = "add") -> str:
    """Bulk-attach existing subscribers to lists. subscriber_ids and list_ids are comma-separated. action: add | remove | unsubscribe."""
    body = {
        "ids": [int(x) for x in subscriber_ids.split(",") if x.strip()],
        "lists": [int(x) for x in list_ids.split(",") if x.strip()],
        "action": action,
    }
    return _fmt(_call("PUT", "/api/subscribers/lists", body=body))


# ─── Templates ───────────────────────────────────────────────────────────────

@mcp.tool()
def list_templates() -> str:
    """List all email templates (campaign and transactional)."""
    return _fmt(_call("GET", "/api/templates"))


@mcp.tool()
def get_template(template_id: int) -> str:
    """Get one template by ID — includes the full HTML body."""
    return _fmt(_call("GET", f"/api/templates/{template_id}"))


# ─── Campaigns ───────────────────────────────────────────────────────────────

@mcp.tool()
def list_campaigns(per_page: int = 30, status: str | None = None) -> str:
    """List campaigns. Status: draft | scheduled | running | paused | finished | cancelled."""
    params = {"per_page": per_page}
    if status:
        params["status"] = status
    return _fmt(_call("GET", "/api/campaigns", params=params))


@mcp.tool()
def get_campaign(campaign_id: int) -> str:
    """Get one campaign by ID, including its body and stats."""
    return _fmt(_call("GET", f"/api/campaigns/{campaign_id}"))


@mcp.tool()
def create_campaign(
    name: str,
    subject: str,
    list_ids: str,
    body: str,
    template_id: int | None = None,
    content_type: str = "html",
    from_email: str | None = None,
) -> str:
    """Create a draft campaign. list_ids is a comma-separated string. content_type: html | richtext | plain | markdown. If template_id is omitted, the default template is used."""
    payload = {
        "name": name,
        "subject": subject,
        "lists": [int(x) for x in list_ids.split(",") if x.strip()],
        "body": body,
        "content_type": content_type,
        "type": "regular",
        "messenger": "email",
    }
    if template_id is not None:
        payload["template_id"] = template_id
    if from_email:
        payload["from_email"] = from_email
    return _fmt(_call("POST", "/api/campaigns", body=payload))


@mcp.tool()
def start_campaign(campaign_id: int) -> str:
    """Move a draft campaign to 'running' status — Listmonk's send worker picks it up immediately."""
    return _fmt(_call("PUT", f"/api/campaigns/{campaign_id}/status", body={"status": "running"}))


@mcp.tool()
def cancel_campaign(campaign_id: int) -> str:
    """Cancel a running or scheduled campaign."""
    return _fmt(_call("PUT", f"/api/campaigns/{campaign_id}/status", body={"status": "cancelled"}))


# ─── Transactional sends (one-off, no campaign) ──────────────────────────────

@mcp.tool()
def tx_send(
    subscriber_email: str,
    template_id: int,
    data_json: str | None = None,
    headers_json: str | None = None,
    from_email: str | None = None,
    content_type: str = "html",
) -> str:
    """Send a transactional (one-off) email to a single subscriber using a tx-type template. data_json is a JSON object of template variables. The subscriber must already exist in Listmonk; templates can reference {{ .Subscriber.Email }} / {{ .Tx.Data.* }}."""
    payload = {
        "subscriber_email": subscriber_email,
        "template_id": template_id,
        "content_type": content_type,
    }
    if data_json:
        payload["data"] = json.loads(data_json)
    if headers_json:
        payload["headers"] = json.loads(headers_json)
    if from_email:
        payload["from_email"] = from_email
    return _fmt(_call("POST", "/api/tx", body=payload))


# ─── Stats ───────────────────────────────────────────────────────────────────

@mcp.tool()
def dashboard_stats() -> str:
    """Aggregate Listmonk stats: list/subscriber/campaign counts, recent activity."""
    return _fmt(_call("GET", "/api/dashboard/counts"))


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        port = int(os.environ.get("MCP_PORT", "8000"))
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        mcp.settings.transport_security.enable_dns_rebinding_protection = False
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
