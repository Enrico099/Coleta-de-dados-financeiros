"""
Módulo para análise de sentimento de textos.

O TextBlob só entende inglês, então combinamos:
  1. Um léxico financeiro em português (alta, queda, lucro, prejuízo, crise...)
  2. O TextBlob, para textos em inglês (Bloomberg, Investing, posts do LinkedIn)
"""
import re
import logging
import unicodedata
from datetime import date
from textblob import TextBlob
from database.db import Database
from database.models import Noticia, PostSocial
from utils.helpers import load_config

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    """Minúsculas e sem acentos, para casar 'inflação' com 'inflacao'."""
    text = unicodedata.normalize('NFKD', text.lower())
    return ''.join(c for c in text if not unicodedata.combining(c))


# Peso de cada termo (sem acento). Palavra inteira, exceto radicais com '*' (casam por prefixo).
LEXICO_POSITIVO = {
    'alta': 1.0, 'sobe': 1.0, 'subiu': 1.0, 'subir': 0.8, 'sobem': 1.0, 'subindo': 0.8, 'avanca': 1.0, 'avancou': 1.0, 'avanco': 1.0,
    'dispara': 1.2, 'disparou': 1.2, 'valoriza*': 1.0, 'ganho': 1.0, 'ganha*': 0.8, 'lucro': 1.2,
    'lucrativ*': 1.0, 'recorde': 1.0, 'crescimento': 1.0, 'cresce*': 1.0, 'cresceu': 1.0,
    'recupera*': 1.0, 'otimis*': 1.2, 'positiv*': 0.8, 'melhora*': 1.0, 'melhor': 0.6, 'supera*': 0.8,
    'superavit': 1.0, 'aprovad*': 0.6, 'expansao': 0.8, 'forte': 0.5, 'robust*': 0.8,
    'dividendo': 0.6, 'corte de juros': 1.0, 'corta juros': 1.0, 'reduz juros': 1.0,
    'desacelera a inflacao': 1.0, 'inflacao desacelera': 1.0, 'rali': 1.0, 'renova maxima': 1.2,
    'bull': 1.0, 'upgrade': 1.0, 'oportunidade': 0.6, 'estabilidade': 0.5, 'emprego': 0.5,
}
LEXICO_NEGATIVO = {
    'queda': 1.0, 'cai': 1.0, 'caiu': 1.0, 'cair': 0.8, 'caem': 1.0, 'caindo': 0.8, 'recua': 1.0, 'recuou': 1.0, 'recuo': 1.0,
    'despenca': 1.3, 'despencou': 1.3, 'desaba': 1.3, 'tomba': 1.2, 'desvaloriza*': 1.0,
    'perda': 1.0, 'perde*': 0.8, 'prejuizo': 1.2, 'crise': 1.3, 'recessao': 1.3, 'risco': 0.6,
    'incerteza': 0.8, 'pessimis*': 1.2, 'negativ*': 0.8, 'piora*': 1.0, 'pior': 0.6, 'deficit': 0.8,
    'calote': 1.3, 'falencia': 1.3, 'recuperacao judicial': 1.2, 'fraude': 1.2, 'rombo': 1.2,
    'inflacao sobe': 1.0, 'inflacao acelera': 1.0, 'alta de juros': 0.8, 'eleva juros': 0.8,
    'aumenta juros': 0.8, 'tensao*': 0.8, 'guerra': 1.0, 'tarifa': 0.5, 'volatil*': 0.5,
    'desemprego': 1.0, 'rebaixa*': 1.0, 'downgrade': 1.0, 'bear': 1.0, 'sell-off': 1.2,
    'panico': 1.3, 'temor': 1.0, 'medo': 0.8, 'alerta': 0.5, 'minima': 0.6,
}

# Palavras comuns em PT — usadas para decidir se o texto está em português
_PT_HINTS = {'de', 'da', 'do', 'que', 'em', 'para', 'com', 'nao', 'uma', 'os', 'as', 'no', 'na', 'ao', 'mais'}


# Termos financeiros em inglês que o TextBlob não conhece
LEXICO_POSITIVO.update({
    'rally*': 1.0, 'surge*': 1.0, 'soar*': 1.0, 'gain*': 0.8, 'jump*': 0.8, 'rebound*': 1.0,
    'record high': 1.2, 'beat*': 0.6, 'optimis*': 1.2, 'cools': 0.6, 'eases': 0.6, 'rate cut*': 1.0,
})
LEXICO_NEGATIVO.update({
    'plunge*': 1.3, 'slump*': 1.2, 'tumble*': 1.2, 'fall*': 0.8, 'drop*': 0.8, 'loss*': 1.0,
    'fear*': 1.0, 'recession': 1.3, 'crash*': 1.3, 'default*': 1.0, 'rate hike*': 0.8, 'selloff': 1.2,
})


def _compile(lexico: dict) -> list[tuple[re.Pattern, float]]:
    compiled = []
    for termo, peso in lexico.items():
        if termo.endswith('*'):
            pattern = r'\b' + re.escape(termo[:-1])
        else:
            pattern = r'\b' + re.escape(termo) + r'\b'
        compiled.append((re.compile(pattern), peso))
    return compiled


_POS = _compile(LEXICO_POSITIVO)
_NEG = _compile(LEXICO_NEGATIVO)


class SentimentAnalyzer:
    """Analisador de sentimento para notícias e posts (léxico PT + TextBlob)."""

    def __init__(self, config: dict | None = None):
        """Inicializa o analisador de sentimento carregando as configurações."""
        self.config = config or load_config()
        analysis_config = self.config.get('analysis', {})
        self.pos_threshold = analysis_config.get('sentiment_threshold_positive', 0.05)
        self.neg_threshold = analysis_config.get('sentiment_threshold_negative', -0.05)

    def classify_sentiment(self, score: float) -> str:
        """Classifica o score em 'positivo', 'negativo' ou 'neutro'."""
        if score >= self.pos_threshold:
            return 'positivo'
        elif score <= self.neg_threshold:
            return 'negativo'
        return 'neutro'

    @staticmethod
    def _lexicon_score(text_norm: str) -> float | None:
        pos = sum(peso * len(p.findall(text_norm)) for p, peso in _POS)
        neg = sum(peso * len(p.findall(text_norm)) for p, peso in _NEG)
        if pos == 0 and neg == 0:
            return None
        # Normaliza em [-1, 1]; o +1 no denominador suaviza textos com 1 termo só
        return (pos - neg) / (pos + neg + 1)

    def analyze(self, text: str) -> tuple[float, str]:
        """
        Analisa o sentimento de um texto.

        Returns:
            Uma tupla contendo o score (-1.0 a 1.0) e a classificação.
        """
        try:
            if not text:
                return 0.0, 'neutro'

            text_norm = _normalize(text)
            palavras = set(re.findall(r'\w+', text_norm))
            is_pt = len(palavras & _PT_HINTS) >= 2

            lex = self._lexicon_score(text_norm)
            if is_pt:
                score = lex if lex is not None else 0.0
            else:
                blob = TextBlob(text).sentiment.polarity
                score = blob if lex is None else (blob + lex) / 2

            score = round(max(-1.0, min(1.0, score)), 3)
            return score, self.classify_sentiment(score)
        except Exception as e:
            logger.error(f"Erro ao analisar sentimento: {e}")
            return 0.0, 'neutro'

    def analyze_batch(self, texts: list[str]) -> list[tuple[float, str]]:
        """Analisa o sentimento de uma lista de textos."""
        return [self.analyze(text) for text in texts]

    def score_pending(self, db: Database) -> int:
        """Calcula o sentimento de notícias e posts que ainda não foram analisados."""
        total = 0
        with db.session_scope() as session:
            for n in session.query(Noticia).filter(Noticia.sentiment_score.is_(None)).all():
                n.sentiment_score, n.sentiment_label = self.analyze(f"{n.title}. {n.summary or ''}")
                total += 1
            for p in session.query(PostSocial).filter(PostSocial.sentiment_score.is_(None)).all():
                p.sentiment_score, p.sentiment_label = self.analyze(p.content or '')
                total += 1
        return total

    def get_market_sentiment(self, db: Database) -> dict:
        """
        Consulta notícias e posts de hoje, calcula o sentimento geral do mercado.

        Returns:
            Dicionário com o score geral, label e detalhamento por fonte.
        """
        try:
            today = date.today()
            noticias_scores = []
            posts_scores = []
            por_fonte: dict[str, list[float]] = {}

            with db.session_scope() as session:
                noticias = session.query(Noticia).filter(Noticia.collected_at >= today).all()
                for notic in noticias:
                    if notic.sentiment_score is not None:
                        noticias_scores.append(notic.sentiment_score)
                        por_fonte.setdefault(notic.source or 'Outros', []).append(notic.sentiment_score)

                posts = session.query(PostSocial).filter(PostSocial.collected_at >= today).all()
                for post in posts:
                    if post.sentiment_score is not None:
                        posts_scores.append(post.sentiment_score)

            todos = noticias_scores + posts_scores
            avg_score = sum(todos) / len(todos) if todos else 0.0
            avg_news = sum(noticias_scores) / len(noticias_scores) if noticias_scores else 0.0
            avg_posts = sum(posts_scores) / len(posts_scores) if posts_scores else 0.0

            return {
                'score': round(avg_score, 3),
                'label': self.classify_sentiment(avg_score),
                'positivos': sum(1 for s in todos if self.classify_sentiment(s) == 'positivo'),
                'negativos': sum(1 for s in todos if self.classify_sentiment(s) == 'negativo'),
                'neutros': sum(1 for s in todos if self.classify_sentiment(s) == 'neutro'),
                'sources': {
                    'news': {
                        'score': round(avg_news, 3),
                        'label': self.classify_sentiment(avg_news),
                        'count': len(noticias_scores)
                    },
                    'social': {
                        'score': round(avg_posts, 3),
                        'label': self.classify_sentiment(avg_posts),
                        'count': len(posts_scores)
                    }
                },
                # fonte -> (score médio, quantidade de notícias)
                'por_fonte': {
                    fonte: (round(sum(v) / len(v), 3), len(v)) for fonte, v in por_fonte.items()
                },
            }
        except Exception as e:
            logger.error(f"Erro ao obter sentimento de mercado: {e}")
            return {
                'score': 0.0,
                'label': 'neutro',
                'sources': {}
            }
