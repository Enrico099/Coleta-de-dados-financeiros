"""
Scraper para o LinkedIn usando as páginas públicas de empresas.

O LinkedIn exige login para ver o feed e perfis pessoais, e os buscadores
(Google/Bing/DuckDuckGo) bloqueiam scraping ou ignoram o operador site:.
Mas a página pública de uma empresa (linkedin.com/company/<slug>/) mostra,
para visitantes sem login, os ~10 posts mais recentes — é isso que coletamos.

Configure os slugs em config.yaml -> linkedin.empresas
(o slug é o trecho da URL: linkedin.com/company/<slug>/).
"""
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from .base import BaseScraper
from database.db import Database
from database.models import PostSocial
from utils.helpers import safe_get

COMPANY_URL = "https://www.linkedin.com/company/{slug}/"
POST_URL = "https://www.linkedin.com/feed/update/{urn}/"


class LinkedInScraper(BaseScraper):
    """Scraper para posts públicos de páginas de empresas no LinkedIn."""

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }

    @staticmethod
    def _date_from_urn(urn: str) -> datetime | None:
        """Os IDs de atividade do LinkedIn carregam o timestamp (ms) nos 41 bits mais altos."""
        try:
            activity_id = int(urn.rsplit(":", 1)[1])
            return datetime.fromtimestamp((activity_id >> 22) / 1000, timezone.utc)
        except (ValueError, IndexError, OSError):
            return None

    @staticmethod
    def _to_int(text: str) -> int:
        digits = re.sub(r"\D", "", text or "")
        return int(digits) if digits else 0

    def _fetch_company_posts(self, slug: str) -> list[dict]:
        response = requests.get(COMPANY_URL.format(slug=slug), headers=self.headers, timeout=15)
        if response.status_code == 999:
            raise RuntimeError("LinkedIn limitou o acesso (HTTP 999) — tente mais tarde")
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        company_name = soup.select_one("h1")
        company_name = company_name.get_text(" ", strip=True) if company_name else slug

        posts = []
        for card in soup.select("article[data-activity-urn]"):
            urn = card["data-activity-urn"]
            text_tag = card.select_one('[data-test-id="main-feed-activity-card__commentary"]')
            content = text_tag.get_text("\n", strip=True) if text_tag else ""
            if not content:
                continue
            reactions = card.select_one('[data-test-id="social-actions__reaction-count"]')
            comments = card.select_one('[data-test-id="social-actions__comments"]')
            hashtags = re.findall(r"#(\w+)", content)
            posts.append({
                "urn": urn,
                "author": company_name,
                "content": content,
                "hashtags": ",".join(hashtags),
                "likes": self._to_int(reactions.get_text() if reactions else ""),
                "comments": self._to_int(comments.get_text() if comments else ""),
                "date": self._date_from_urn(urn),
            })
        return posts

    def collect(self, db: Database) -> dict:
        """Coleta os posts recentes das empresas configuradas e salva no banco de dados."""
        empresas = safe_get(self.config, 'linkedin', 'empresas', default=[]) or []
        max_posts = safe_get(self.config, 'linkedin', 'max_posts', default=10)
        total = 0

        with db.session_scope() as session:
            for i, slug in enumerate(empresas):
                self.log_info(f"Coletando posts do LinkedIn: {slug}")
                try:
                    novos = 0
                    for post in self._fetch_company_posts(slug)[:max_posts]:
                        post_url = POST_URL.format(urn=post["urn"])
                        if session.query(PostSocial.id).filter(PostSocial.post_url == post_url).first():
                            continue
                        session.add(PostSocial(
                            platform='linkedin',
                            author=post["author"][:100],
                            content=post["content"],
                            hashtags=post["hashtags"],
                            likes=post["likes"],
                            comments_count=post["comments"],
                            post_url=post_url,
                            post_date=post["date"],
                            collected_at=datetime.now(timezone.utc),
                        ))
                        novos += 1
                    session.flush()
                    total += novos
                except Exception as e:
                    self.log_error(f"Erro ao coletar LinkedIn de '{slug}': {e}")

                if i < len(empresas) - 1:
                    self._wait(3)  # Rate limiting — o LinkedIn devolve HTTP 999 se for rápido demais

        self.log_info(f"Coleta do LinkedIn finalizada. Total de novas publicações: {total}")
        return {'posts': total}
