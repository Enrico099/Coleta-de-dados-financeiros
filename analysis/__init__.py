"""
Módulo de análise e processamento de dados do bot de inteligência econômica.
"""
from .sentiment import SentimentAnalyzer
from .trend_detector import TrendDetector
from .summarizer import DailySummarizer

__all__ = ['SentimentAnalyzer', 'TrendDetector', 'DailySummarizer']
