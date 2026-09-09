"""
Centralized N8N webhook notifications.
Set N8N_WEBHOOK_URL and optional N8N_WEBHOOK_TOKEN in .env
"""
from __future__ import annotations
import json
import time
from datetime import datetime
from typing import Any, Dict, Optional
from urllib import request as _req
from urllib.error import URLError, HTTPError
from django.conf import settings


def _post_json(url: str, payload: Dict[str, Any], token: str = "", timeout: int = 6) -> bool:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = _req.Request(url, data=data, headers=headers, method="POST")
    try:
        with _req.urlopen(req, timeout=timeout) as resp:
            # 2xx accepted
            return 200 <= resp.status < 300
    except (URLError, HTTPError):
        return False


def send_to_n8n(event_type: str, payload: Dict[str, Any], user: Optional[Any] = None, meta: Optional[Dict[str, Any]] = None) -> bool:
    """
    Send a structured event to N8N webhook.
    - event_type: e.g. 'prediction', 'alert', 'alert_action', 'drift_snapshot', 'drift_alert', 'batch_summary', 'profile_updated'
    - payload: domain-specific data
    - user: optional Django user to enrich metadata
    - meta: additional metadata
    Returns True if delivered, False otherwise.
    """
    url = getattr(settings, "N8N_WEBHOOK_URL", "") or ""
    if not url:
        return False
    token = getattr(settings, "N8N_WEBHOOK_TOKEN", "") or ""
    envelope = {
        "event": event_type,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "payload": payload or {},
        "meta": meta or {},
    }
    if user is not None:
        try:
            envelope["user"] = {
                "id": str(getattr(user, "id", "")),
                "email": getattr(user, "email", ""),
                "username": getattr(user, "username", ""),
                "role": getattr(user, "role", ""),
            }
        except Exception:
            pass
    return _post_json(url, envelope, token)
