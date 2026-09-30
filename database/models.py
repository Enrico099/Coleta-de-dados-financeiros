"""
Modelos do banco de dados SQLAlchemy para o Bot de Inteligência Econômica.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


class Cotacao(Base):
    """Cotações de ativos financeiros (ações, moedas, cripto, commodities)."""
    __tablename__ = 'cotacoes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String(100))
    tipo = Column(String(20))  # indice, moeda, cripto, commodity, acao
    price = Column(Float)
    previous_close = Column(Float)
    variation_percent = Column(Float)
    high = Column(Float)
    low = Column(Float)
    volume = Column(Float)
    collected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def __repr__(self):
        seta = "↑" if (self.variation_percent or 0) >= 0 else "↓"
        return f"<Cotacao({self.name}: R${self.price:.2f} {seta}{abs(self.variation_percent or 0):.2f}%)>"


class Noticia(Base):
    """Notícias coletadas de RSS feeds e Google News."""
    __tablename__ = 'noticias'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text)
    source = Column(String(100), index=True)
    url = Column(String(500), unique=True)
    published_at = Column(DateTime)
    sentiment_score = Column(Float)  # -1.0 a 1.0
    sentiment_label = Column(String(20))  # positivo, negativo, neutro
    collected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def __repr__(self):
        return f"<Noticia({self.source}: {self.title[:50]}... [{self.sentiment_label}])>"


class PostSocial(Base):
    """Posts coletados de redes sociais (Instagram, LinkedIn)."""
    __tablename__ = 'posts_social'

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(20), nullable=False, index=True)  # instagram, linkedin
    author = Column(String(100), index=True)
    content = Column(Text)
    hashtags = Column(Text)  # JSON list
    likes = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    post_url = Column(String(500), unique=True)
    post_date = Column(DateTime)
    sentiment_score = Column(Float)
    sentiment_label = Column(String(20))
    collected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def __repr__(self):
        return f"<PostSocial({self.platform}/{self.author}: {(self.content or '')[:50]}...)>"


class IndicadorEconomico(Base):
    """Indicadores econômicos do Banco Central (Selic, IPCA, etc)."""
    __tablename__ = 'indicadores'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, index=True)
    code = Column(Integer)  # Código BCB
    value = Column(Float)
    reference_date = Column(DateTime)
    collected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def __repr__(self):
        return f"<Indicador({self.name}: {self.value})>"


class Alerta(Base):
    """Alertas configurados pelos usuários via Telegram."""
    __tablename__ = 'alertas'

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String(50), nullable=False, index=True)
    asset_symbol = Column(String(50), nullable=False)
    asset_name = Column(String(100))
    condition = Column(String(20), nullable=False)  # acima, abaixo
    threshold = Column(Float, nullable=False)
    active = Column(Boolean, default=True)
    triggered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    triggered_at = Column(DateTime, nullable=True)

    def __repr__(self):
        status = "✅ ativo" if self.active else "❌ inativo"
        return f"<Alerta({self.asset_name} {self.condition} {self.threshold} - {status})>"


class ResumoDiario(Base):
    """Resumos diários gerados pelo bot."""
    __tablename__ = 'resumos_diarios'

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False, unique=True, index=True)
    total_noticias = Column(Integer, default=0)
    total_posts = Column(Integer, default=0)
    sentimento_geral = Column(String(20))  # positivo, negativo, neutro
    sentimento_score = Column(Float)
    resumo_texto = Column(Text)
    destaques = Column(Text)  # JSON
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Resumo({self.date}: {self.sentimento_geral})>"
