"""
Test degli agenti AI con mock delle API esterne.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest

from models.post import Platform, Comment, PostStatus, Post


class TestContentGenerator:
    """Test ContentGeneratorAgent."""

    def test_parse_response_extracts_hashtags(self):
        from agents.content_generator import ContentGeneratorAgent
        agent = ContentGeneratorAgent()
        result = agent._parse_response(
            "Ecco il contenuto del post.\n\n#social #marketing #test"
        )
        assert "contenuto del post" in result["content"]
        assert "#social" in result["hashtags"]
        assert "#marketing" in result["hashtags"]

    def test_parse_response_no_hashtags(self):
        from agents.content_generator import ContentGeneratorAgent
        agent = ContentGeneratorAgent()
        result = agent._parse_response("Un post senza hashtag.")
        assert result["content"] == "Un post senza hashtag."
        assert result["hashtags"] == ""

    @patch("agents.content_generator.ContentGeneratorAgent._generate_with_anthropic")
    def test_generate_calls_anthropic_by_default(self, mock_anthropic):
        from agents.content_generator import ContentGeneratorAgent
        mock_anthropic.return_value = {
            "content": "Test", "hashtags": "#test", "generated_by": "anthropic"
        }
        agent = ContentGeneratorAgent()
        result = agent.generate(topic="test", platform=Platform.LINKEDIN, provider="anthropic")
        mock_anthropic.assert_called_once()
        assert result["generated_by"] == "anthropic"


class TestMonitorAgent:
    """Test MonitorAgent."""

    def test_save_new_comment(self, db_session):
        from agents.monitor import MonitorAgent
        agent = MonitorAgent(db_session=db_session)
        result = agent._save_comment(
            platform=Platform.LINKEDIN,
            platform_comment_id="test-123",
            platform_post_id="post-456",
            author_name="Test User",
            content="Ottimo post!",
        )
        assert result is not None
        assert result["author"] == "Test User"
        assert result["platform"] == "linkedin"

    def test_save_duplicate_comment_returns_none(self, db_session):
        from agents.monitor import MonitorAgent
        agent = MonitorAgent(db_session=db_session)
        # Prima volta: salva
        agent._save_comment(
            platform=Platform.LINKEDIN,
            platform_comment_id="dup-123",
            platform_post_id="post-456",
            author_name="User",
            content="Commento",
        )
        # Seconda volta: duplicato
        result = agent._save_comment(
            platform=Platform.LINKEDIN,
            platform_comment_id="dup-123",
            platform_post_id="post-456",
            author_name="User",
            content="Commento",
        )
        assert result is None

    def test_skip_platforms_without_token(self, db_session):
        from agents.monitor import MonitorAgent
        agent = MonitorAgent(db_session=db_session)
        # Con token vuoti, deve ritornare liste vuote senza errori
        results = agent.run_full_check()
        assert results["linkedin"] == []
        assert results["facebook"] == []
        assert results["instagram"] == []


class TestReplyAgent:
    """Test ReplyAgent."""

    @patch("agents.reply_agent.ReplyAgent._generate_draft")
    def test_generate_drafts_for_pending(self, mock_draft, db_session):
        from agents.reply_agent import ReplyAgent

        # Crea un commento senza bozza
        comment = Comment(
            platform=Platform.FACEBOOK,
            platform_comment_id="c-1",
            platform_post_id="p-1",
            author_name="User",
            content="Bel post!",
            reply_draft=None,
        )
        db_session.add(comment)
        db_session.commit()

        mock_draft.return_value = "Grazie per il feedback!"
        agent = ReplyAgent(db_session=db_session)
        drafts = agent.generate_reply_drafts()
        assert len(drafts) == 1
        assert drafts[0]["draft"] == "Grazie per il feedback!"

    @patch("agents.reply_agent.ReplyAgent._generate_draft")
    def test_skip_comments_with_existing_draft(self, mock_draft, db_session):
        from agents.reply_agent import ReplyAgent

        comment = Comment(
            platform=Platform.FACEBOOK,
            platform_comment_id="c-2",
            platform_post_id="p-1",
            author_name="User",
            content="Bel post!",
            reply_draft="Già risposto",
        )
        db_session.add(comment)
        db_session.commit()

        agent = ReplyAgent(db_session=db_session)
        drafts = agent.generate_reply_drafts()
        assert len(drafts) == 0
        mock_draft.assert_not_called()


class TestCompetitorAnalyst:
    """Test CompetitorAnalystAgent."""

    def test_parse_json_valid(self):
        from agents.competitor_analyst import _parse_json
        result = _parse_json('```json\n{"summary": "test"}\n```')
        assert result == {"summary": "test"}

    def test_parse_json_invalid(self):
        from agents.competitor_analyst import _parse_json
        result = _parse_json("non è json")
        assert result is None

    def test_parse_json_with_extra_text(self):
        from agents.competitor_analyst import _parse_json
        result = _parse_json('Ecco la risposta:\n{"key": "value"}\nFine.')
        assert result == {"key": "value"}

    def test_fallback_result(self):
        from agents.competitor_analyst import _fallback_result
        competitors = [MagicMock(name="Test Corp")]
        result = _fallback_result(competitors)
        assert "summary" in result
        assert len(result["per_competitor"]) == 1
