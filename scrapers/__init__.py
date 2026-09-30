"""
Módulo de scrapers para o bot de inteligência econômica.
Exporta todas as classes de scraper.
"""
from .base import BaseScraper
from .instagram_scraper import InstagramScraper
from .linkedin_scraper import LinkedInScraper
from .news_scraper import NewsScraper
from .finance_api import FinanceAPIScraper

__all__ = [
    'BaseScraper',
    'InstagramScraper',
    'LinkedInScraper',
    'NewsScraper',
    'FinanceAPIScraper'
]
