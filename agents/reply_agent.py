"""
ReplyAgent
Genera bozze di risposta ai commenti (richiede approvazione umana prima della pubblicazione).
"""
import anthropic
from openai import OpenAI
from config.settings import settings
from models.post import Platform, Comment, PostStatus


REPLY_SYSTEM_PROMPT = """Sei il social media manager di {company}.
Genera risposte brevi, educate e professionali ai commenti sui social.
- Rispondi sempre in modo positivo e costruttivo
- Sii conciso (max 2-3 frasi)
- Personalizza in base al contesto del commento
- Non usare risposte generiche come "Grazie per il commento!"
- Rispondi in italiano salvo diversa indicazione"""


class ReplyAgent:
    def __init__(self, db_session):
        self.db = db_session
        self._anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._openai = OpenAI(
            base_url=settings.openai_compatible_base_url,
            api_key=settings.openai_compatible_api_key,
        )

    def generate_reply_drafts(self) -> list[dict]:
        """Genera bozze per tutti i commenti senza risposta. Richiede approvazione umana."""
        pending_comments = (
            self.db.query(Comment)
            .filter(Comment.reply_draft.is_(None))
            .all()
        )
        drafts = []
        for comment in pending_comments:
            draft = self._generate_draft(comment)
            comment.reply_draft = draft
            comment.reply_status = PostStatus.PENDING
            self.db.commit()
            drafts.append({"comment_id": comment.id, "draft": draft})
        return drafts

    def _generate_draft(self, comment: Comment) -> str:
        prompt = (
            f"Commento ricevuto su {comment.platform.value.upper()} da {comment.author_name}:\n"
            f'"{comment.content}"\n\n'
            "Genera una risposta appropriata."
        )
        system = REPLY_SYSTEM_PROMPT.format(company=settings.company_name)

        if settings.ai_primary_provider == "anthropic":
            msg = self._anthropic.messages.create(
                model=settings.anthropic_model,
                max_tokens=256,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text.strip()

        response = self._openai.chat.completions.create(
            model=settings.openai_compatible_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=256,
        )
        return (response.choices[0].message.content or "").strip()
