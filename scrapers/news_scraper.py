"""
Scraper de notícias usando feedparser (RSS dos portais + busca do Google News).
"""
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from .base import BaseScraper
from database.db import Database
from database.models import Noticia
from sqlalchemy import or_
import urllib.parse

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"

logger = logging.getLogger(__name__)


class NewsScraper(BaseScraper):
    """Scraper para coletar notícias de RSS Feeds e Google News."""

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)

    @staticmethod
    def _exists(db: Database, url: str, title: str) -> bool:
        """Duplicata por URL ou pelo mesmo título (a mesma matéria chega por RSS e Google News)."""
        with db.session_scope() as session:
            return session.query(Noticia.id).filter(
                or_(Noticia.url == url, Noticia.title == title)
            ).first() is not None

    def _parse_date(self, date_str: str) -> datetime:
        """Tenta fazer o parse de várias strings de data do RSS."""
        if not date_str:
            return datetime.now(timezone.utc)
        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            pass
        # Tenta outros formatos comuns
        for fmt in ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M'):
            try:
                return datetime.strptime(date_str, fmt)
            except (ValueError, TypeError):
                continue
        return datetime.now(timezone.utc)

    def collect(self, db: Database) -> dict:
        """
        Coleta notícias de RSS feeds e Google News.

        Returns:
            dict com contador: {'noticias': int}
        """
        feeds = self.config.get('news', {}).get('feeds', [])
        gnews_termos = self.config.get('news', {}).get('google_news_termos', [])
        max_noticias = self.config.get('news', {}).get('max_noticias', 20)

        count = 0

        # === RSS Feeds ===
        try:
            import feedparser

            for feed_info in feeds:
                feed_name = feed_info.get('name', 'RSS Feed') if isinstance(feed_info, dict) else 'RSS Feed'
                feed_url = feed_info.get('url', feed_info) if isinstance(feed_info, dict) else feed_info

                self.log_info(f"Coletando feed RSS: {feed_name} ({feed_url})")
                try:
                    parsed_feed = feedparser.parse(feed_url)

                    for entry in parsed_feed.entries[:max_noticias]:
                        url = getattr(entry, 'link', '')
                        if not url:
                            continue

                        title = getattr(entry, 'title', '')
                        if self._exists(db, url, title):
                            continue

                        summary = getattr(entry, 'summary', getattr(entry, 'description', ''))
                        # Remove tags HTML do summary
                        if summary:
                            from bs4 import BeautifulSoup
                            summary = BeautifulSoup(summary, 'html.parser').get_text(strip=True)

                        source = feed_name
                        pub_date = self._parse_date(getattr(entry, 'published', ''))

                        noticia = Noticia(
                            title=title,
                            summary=summary[:500] if summary else '',
                            source=source,
                            url=url,
                            published_at=pub_date,
                        )

                        try:
                            with db.session_scope() as session:
                                session.add(noticia)
                            count += 1
                        except Exception:
                            pass  # Duplicata ou erro de constraint

                except Exception as e:
                    self.log_error(f"Erro ao coletar feed {feed_name}: {e}")

        except ImportError:
            self.log_error("feedparser não instalado. Instale com: pip install feedparser")

        # === Google News (RSS de busca — bem mais rápido que a lib gnews) ===
        try:
            import feedparser

            for i, termo in enumerate(gnews_termos):
                self.log_info(f"Buscando no Google News: '{termo}'")
                try:
                    # when:2d = só notícias das últimas 48h
                    feed_url = GOOGLE_NEWS_RSS.format(q=urllib.parse.quote(f"{termo} when:2d"))
                    parsed_feed = feedparser.parse(feed_url)

                    for entry in parsed_feed.entries[:max_noticias]:
                        url = getattr(entry, 'link', '')
                        if not url:
                            continue

                        source = entry.get('source', {}).get('title', 'Google News')
                        title = getattr(entry, 'title', '')
                        # Google News anexa " - Veículo" ao título
                        if source and title.endswith(f" - {source}"):
                            title = title[: -len(f" - {source}")]

                        if self._exists(db, url, title):
                            continue

                        noticia = Noticia(
                            title=title,
                            summary='',  # o resumo do Google News é só o título repetido
                            source=source,
                            url=url,
                            published_at=self._parse_date(getattr(entry, 'published', '')),
                        )
                        try:
                            with db.session_scope() as session:
                                session.add(noticia)
                            count += 1
                        except Exception:
                            pass

                except Exception as e:
                    self.log_error(f"Erro ao buscar Google News para '{termo}': {e}")

                if i < len(gnews_termos) - 1:
                    self._wait(1)  # Rate limiting entre buscas

        except ImportError:
            self.log_error("feedparser não instalado. Instale com: pip install feedparser")

        self.log_info(f"Coleta de notícias finalizada. Total: {count}")
        return {'noticias': count}

