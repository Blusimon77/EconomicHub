"""
Analytics Agent
Raccoglie e analizza le metriche di performance dai social.
"""
from __future__ import annotations

import httpx
from datetime import datetime, timezone
from config.settings import settings
from config.logging import get_logger
from models.post import Platform

logger = get_logger("agents.analytics")


class AnalyticsAgent:
    def collect_all(self) -> dict:
        """Raccoglie metriche da tutte le piattaforme configurate."""
        return {
            "linkedin": self._collect_linkedin(),
            "facebook": self._collect_facebook(),
            "instagram": self._collect_instagram(),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

    def _collect_linkedin(self) -> dict:
        if not settings.linkedin_access_token:
            return {"error": "Token non configurato"}

        headers = {"Authorization": f"Bearer {settings.linkedin_access_token}"}
        org_id = settings.linkedin_organization_id

        try:
            url = f"https://api.linkedin.com/v2/organizationalEntityShareStatistics?q=organizationalEntity&organizationalEntity=urn:li:organization:{org_id}"
            response = httpx.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                elements = data.get("elements", [])
                if elements:
                    stats = elements[0].get("totalShareStatistics", {})
                    return {
                        "impressions": stats.get("impressionCount", 0),
                        "clicks": stats.get("clickCount", 0),
                        "reactions": stats.get("likeCount", 0),
                        "comments": stats.get("commentCount", 0),
                        "shares": stats.get("shareCount", 0),
                        "engagement_rate": stats.get("engagement", 0),
                    }
        except httpx.RequestError:
            logger.warning("Errore connessione LinkedIn Analytics API")
            return {"error": "Connessione fallita"}
        return {}

    def _collect_facebook(self) -> dict:
        if not settings.facebook_access_token:
            return {"error": "Token non configurato"}

        token = settings.facebook_access_token
        page_id = settings.facebook_page_id

        try:
            url = f"https://graph.facebook.com/{settings.facebook_api_version}/{page_id}/insights"
            params = {
                "access_token": token,
                "metric": "page_impressions,page_engaged_users,page_fans,page_reactions_total",
                "period": "week",
            }
            response = httpx.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                metrics = {}
                for item in data.get("data", []):
                    name = item.get("name", "")
                    values = item.get("values", [])
                    if values:
                        metrics[name] = values[-1].get("value", 0)
                return metrics
        except httpx.RequestError:
            logger.warning("Errore connessione Facebook Analytics API")
            return {"error": "Connessione fallita"}
        return {}

    def _collect_instagram(self) -> dict:
        if not settings.instagram_business_account_id or not settings.facebook_access_token:
            return {"error": "Token/Account ID non configurato"}

        token = settings.facebook_access_token
        account_id = settings.instagram_business_account_id

        try:
            url = f"https://graph.facebook.com/{settings.facebook_api_version}/{account_id}/insights"
            params = {
                "access_token": token,
                "metric": "impressions,reach,profile_views,follower_count",
                "period": "week",
            }
            response = httpx.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                metrics = {}
                for item in data.get("data", []):
                    name = item.get("name", "")
                    values = item.get("values", [])
                    if values:
                        metrics[name] = values[-1].get("value", 0)
                return metrics
        except httpx.RequestError:
            logger.warning("Errore connessione Instagram Analytics API")
            return {"error": "Connessione fallita"}
        return {}
