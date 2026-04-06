"""
Monitor Agent
Monitora menzioni, tag e nuovi commenti su tutte le piattaforme.
"""
from __future__ import annotations

import httpx
from datetime import datetime, timedelta
from config.settings import settings
from models.post import Platform, Comment


class MonitorAgent:
    def __init__(self, db_session):
        self.db = db_session

    def run_full_check(self) -> dict:
        """Esegue un controllo completo su tutte le piattaforme."""
        results = {
            "linkedin": self._check_linkedin(),
            "facebook": self._check_facebook(),
            "instagram": self._check_instagram(),
            "checked_at": datetime.utcnow().isoformat(),
        }
        return results

    def _check_linkedin(self) -> list[dict]:
        """Recupera commenti e menzioni da LinkedIn."""
        if not settings.linkedin_access_token:
            return []

        headers = {"Authorization": f"Bearer {settings.linkedin_access_token}"}
        new_interactions = []

        try:
            # Recupera commenti sui post dell'organizzazione
            url = (
                "https://api.linkedin.com/v2/socialActions/"
                f"urn:li:organization:{settings.linkedin_organization_id}/comments"
            )
            response = httpx.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                for item in data.get("elements", []):
                    comment = self._save_comment(
                        platform=Platform.LINKEDIN,
                        platform_comment_id=item.get("$URN", ""),
                        platform_post_id=str(item.get("object", "")),
                        author_name=item.get("actor", {}).get("localizedName", ""),
                        content=item.get("message", {}).get("text", ""),
                    )
                    if comment:
                        new_interactions.append(comment)
        except httpx.RequestError:
            pass

        return new_interactions

    def _check_facebook(self) -> list[dict]:
        """Recupera commenti e menzioni da Facebook."""
        if not settings.facebook_access_token:
            return []

        new_interactions = []
        token = settings.facebook_access_token
        page_id = settings.facebook_page_id

        try:
            since = int((datetime.utcnow() - timedelta(minutes=settings.monitor_interval_minutes)).timestamp())
            url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
            params = {"access_token": token, "fields": "id,comments{id,from,message}", "since": since}
            response = httpx.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                for post in data.get("data", []):
                    for comment in post.get("comments", {}).get("data", []):
                        saved = self._save_comment(
                            platform=Platform.FACEBOOK,
                            platform_comment_id=comment["id"],
                            platform_post_id=post["id"],
                            author_name=comment.get("from", {}).get("name", ""),
                            content=comment.get("message", ""),
                        )
                        if saved:
                            new_interactions.append(saved)
        except httpx.RequestError:
            pass

        return new_interactions

    def _check_instagram(self) -> list[dict]:
        """Recupera commenti da Instagram Business."""
        if not settings.instagram_business_account_id or not settings.facebook_access_token:
            return []

        new_interactions = []
        token = settings.facebook_access_token
        account_id = settings.instagram_business_account_id

        try:
            url = f"https://graph.facebook.com/v19.0/{account_id}/media"
            params = {"access_token": token, "fields": "id,comments{id,username,text}"}
            response = httpx.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                for media in data.get("data", []):
                    for comment in media.get("comments", {}).get("data", []):
                        saved = self._save_comment(
                            platform=Platform.INSTAGRAM,
                            platform_comment_id=comment["id"],
                            platform_post_id=media["id"],
                            author_name=comment.get("username", ""),
                            content=comment.get("text", ""),
                        )
                        if saved:
                            new_interactions.append(saved)
        except httpx.RequestError:
            pass

        return new_interactions

    def _save_comment(
        self,
        platform: Platform,
        platform_comment_id: str,
        platform_post_id: str,
        author_name: str,
        content: str,
    ) -> dict | None:
        """Salva un commento se non esiste già. Restituisce None se duplicato."""
        existing = (
            self.db.query(Comment)
            .filter(Comment.platform_comment_id == platform_comment_id)
            .first()
        )
        if existing:
            return None

        is_mention = any(kw.lower() in content.lower() for kw in settings.brand_keywords_list)
        comment = Comment(
            platform=platform,
            platform_comment_id=platform_comment_id,
            platform_post_id=platform_post_id,
            author_name=author_name,
            content=content,
            is_mention=is_mention,
        )
        self.db.add(comment)
        self.db.commit()
        return {
            "id": comment.id,
            "platform": platform.value,
            "author": author_name,
            "content": content,
            "is_mention": is_mention,
        }
