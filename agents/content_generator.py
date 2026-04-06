"""
ContentGenerator Agent
Genera contenuti per i social usando Claude (primario) o OpenAI-compatible (fallback).
"""
from __future__ import annotations

import anthropic
from openai import OpenAI
from config.settings import settings
from models.post import Platform


def _load_company_context() -> str:
    """Carica il contesto aziendale dal DB se disponibile."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from models.context import CompanyContext
        engine = create_engine(settings.database_url)
        Session = sessionmaker(bind=engine)
        db = Session()
        ctx = db.query(CompanyContext).first()
        db.close()
        return ctx.to_prompt_block() if ctx else ""
    except Exception:
        return ""


SYSTEM_PROMPT = """Sei un esperto social media manager aziendale.
Generi contenuti professionali, coinvolgenti e ottimizzati per ogni piattaforma.
Rispondi SEMPRE in italiano salvo diversa indicazione.
Non includere mai commenti meta o spiegazioni — restituisci solo il contenuto del post."""

PLATFORM_GUIDELINES = {
    Platform.LINKEDIN: """
- Tono: professionale ma accessibile
- Lunghezza: 150-300 parole
- Struttura: hook forte → valore → call to action
- Usa paragrafi brevi e spazi bianchi
- Max 5 hashtag rilevanti alla fine
""",
    Platform.FACEBOOK: """
- Tono: amichevole e diretto
- Lunghezza: 50-150 parole
- Struttura: domanda/affermazione → contenuto → invito all'azione
- Max 3 hashtag
""",
    Platform.INSTAGRAM: """
- Tono: ispirazionale e visivo
- Lunghezza: 100-150 parole + emoji moderate
- Struttura: frase d'impatto → storytelling breve → CTA
- 10-20 hashtag misti (popolari + di nicchia) su riga separata
""",
}


class ContentGeneratorAgent:
    def __init__(self):
        self._anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._openai = OpenAI(
            base_url=settings.openai_compatible_base_url,
            api_key=settings.openai_compatible_api_key,
        )

    def generate(
        self,
        topic: str,
        platform: Platform,
        tone: str = "professionale",
        additional_context: str = "",
        provider: str | None = None,
    ) -> dict:
        """
        Genera un post per la piattaforma specificata.
        Restituisce: {"content": str, "hashtags": str, "generated_by": str}
        """
        provider = provider or settings.ai_primary_provider
        prompt = self._build_prompt(topic, platform, tone, additional_context)

        if provider == "anthropic":
            return self._generate_with_anthropic(prompt, platform)
        return self._generate_with_openai(prompt, platform)

    def _build_prompt(self, topic: str, platform: Platform, tone: str, context: str) -> str:
        guidelines = PLATFORM_GUIDELINES.get(platform, "")
        company_context = _load_company_context()
        parts = [
            f"Crea un post per {platform.value.upper()} sul seguente argomento:",
            f"ARGOMENTO: {topic}",
            f"TONE: {tone}",
        ]
        if company_context:
            parts.append(f"\n--- CONTESTO AZIENDALE ---\n{company_context}\n---")
        if context:
            parts.append(f"CONTESTO AGGIUNTIVO: {context}")
        parts.append(f"\nLINEE GUIDA PIATTAFORMA:{guidelines}")
        parts.append("Restituisci PRIMA il testo del post, poi su una riga separata gli hashtag.")
        return "\n".join(parts)

    def _parse_response(self, raw: str) -> dict:
        lines = raw.strip().split("\n")
        hashtag_lines = [l for l in lines if l.strip().startswith("#")]
        content_lines = [l for l in lines if not l.strip().startswith("#")]
        return {
            "content": "\n".join(content_lines).strip(),
            "hashtags": " ".join(hashtag_lines).strip(),
        }

    def _generate_with_anthropic(self, prompt: str, platform: Platform) -> dict:
        message = self._anthropic.messages.create(
            model=settings.anthropic_model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text
        result = self._parse_response(raw)
        result["generated_by"] = "anthropic"
        return result

    def _generate_with_openai(self, prompt: str, platform: Platform) -> dict:
        response = self._openai.chat.completions.create(
            model=settings.openai_compatible_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
        )
        raw = response.choices[0].message.content or ""
        result = self._parse_response(raw)
        result["generated_by"] = "openai"
        return result
