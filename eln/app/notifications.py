"""Optional outbound notifications.  Empty configuration is always a no-op."""
import requests


def teams(storage, title, text):
    url = (storage.get_settings().get("teams_webhook_url") or "").strip()
    if not url:
        return False
    try:
        response = requests.post(url, json={"text": "**%s**\n\n%s" % (title, text)}, timeout=8)
        return response.ok
    except requests.RequestException:
        return False
