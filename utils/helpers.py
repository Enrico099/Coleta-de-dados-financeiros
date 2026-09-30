"""
Funções utilitárias do Bot de Inteligência Econômica.
"""
import os
import re
import sys
import yaml
import logging
import unicodedata
from dotenv import load_dotenv
from datetime import datetime, timezone


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def project_path(path: str) -> str:
    """Resolve caminhos relativos a partir da raiz do projeto (independe do cwd)."""
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)


def load_config(config_path: str = None) -> dict:
    """Carrega o arquivo de configuração YAML."""
    if config_path is None:
        config_path = os.path.join(PROJECT_ROOT, 'config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_env(key: str, default: str = None) -> str:
    """Obtém variável de ambiente, carregando .env se necessário."""
    load_dotenv(os.path.join(PROJECT_ROOT, '.env'))
    value = os.getenv(key, default)
    if value is None:
        raise ValueError(f"Variável de ambiente '{key}' não configurada. Verifique o arquivo .env")
    return value


def setup_logging(config: dict = None) -> logging.Logger:
    """Configura o sistema de logging."""
    if config is None:
        config = load_config()

    log_config = config.get('logging', {})
    log_level = getattr(logging, log_config.get('level', 'INFO'))
    log_file = project_path(log_config.get('file', 'data/bot.log'))

    # Console do Windows (cp1252) não suporta emojis — força UTF-8
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass

    # Garante que o diretório do log existe
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # Configura logging
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

    # Bibliotecas barulhentas — e o httpx loga URLs do Telegram com o token do bot
    for lib in ('httpx', 'httpcore', 'telegram', 'apscheduler', 'yfinance', 'instaloader', 'urllib3'):
        logging.getLogger(lib).setLevel(logging.WARNING)

    logger = logging.getLogger('bot_economia')
    logger.info("=" * 60)
    logger.info("Bot de Inteligência Econômica iniciado")
    logger.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 60)
    return logger


def format_currency(value: float, currency: str = "R$") -> str:
    """Formata valor como moeda."""
    if value is None:
        return "N/A"
    # Formato brasileiro: 1.234,56
    return f"{currency} {value:,.2f}".replace(',', '_').replace('.', ',').replace('_', '.')


def format_number(value: float, decimals: int = 2) -> str:
    """Número no formato brasileiro (1.234,56)."""
    if value is None:
        return "N/A"
    return f"{value:,.{decimals}f}".replace(',', '_').replace('.', ',').replace('_', '.')


def format_variation(variation: float) -> str:
    """Formata variação percentual com seta."""
    if variation is None:
        return "N/A"
    seta = "🟢 ↑" if variation >= 0 else "🔴 ↓"
    return f"{seta} {abs(variation):.2f}%".replace('.', ',')


def truncate_text(text: str, max_length: int = 200) -> str:
    """Trunca texto com reticências."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def safe_get(data: dict, *keys, default=None):
    """Acessa chaves aninhadas de forma segura."""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key, default)
        else:
            return default
    return data


# Apelidos amigáveis para os ativos (usados no Telegram: /grafico IBOV, /alerta_criar DOLAR ...)
SYMBOL_ALIASES = {
    'IBOV': '^BVSP', 'IBOVESPA': '^BVSP',
    'DOLAR': 'BRL=X', 'DÓLAR': 'BRL=X', 'USD': 'BRL=X', 'USDBRL': 'BRL=X',
    'EURO': 'EURBRL=X', 'EUR': 'EURBRL=X',
    'BTC': 'BTC-USD', 'BITCOIN': 'BTC-USD',
    'ETH': 'ETH-USD', 'ETHEREUM': 'ETH-USD',
    'OURO': 'GC=F', 'GOLD': 'GC=F',
    'SP500': '^GSPC', 'S&P500': '^GSPC', 'SPX': '^GSPC',
    'NASDAQ': '^IXIC',
}


def resolve_symbol(config: dict, text: str) -> tuple[str, str]:
    """
    Converte o que o usuário digitou (IBOV, dolar, PETR4, ^BVSP...) no símbolo do Yahoo.
    Retorna (symbol, name). Se não reconhecer, devolve o texto em maiúsculas.
    """
    ativos = safe_get(config, 'finance', 'ativos', default=[]) or []
    key = (text or '').strip().upper()

    for ativo in ativos:
        symbol = ativo.get('symbol', '')
        name = ativo.get('name', symbol)
        if key in (symbol.upper(), name.upper(), symbol.upper().removesuffix('.SA')):
            return symbol, name

    alias = SYMBOL_ALIASES.get(key)
    if alias:
        for ativo in ativos:
            if ativo.get('symbol') == alias:
                return alias, ativo.get('name', alias)
        return alias, key

    return key, key


def strip_accents(text: str) -> str:
    """Minúsculas e sem acentos ('Eleições' -> 'eleicoes')."""
    text = unicodedata.normalize('NFKD', (text or '').lower())
    return ''.join(c for c in text if not unicodedata.combining(c))


def keyword_pattern(keywords: list[str]) -> re.Pattern | None:
    """Regex que casa qualquer uma das palavras/expressões inteiras, sem acento e sem caixa."""
    termos = [re.escape(strip_accents(k)) for k in keywords or [] if k]
    if not termos:
        return None
    return re.compile(r'(?<!\w)(' + '|'.join(sorted(termos, key=len, reverse=True)) + r')(?!\w)')


def is_election_news(text: str, config: dict) -> bool:
    """True se o texto fala de eleições (palavras em config.yaml -> news.eleicoes_palavras)."""
    pattern = keyword_pattern(safe_get(config, 'news', 'eleicoes_palavras', default=[]))
    return bool(pattern and pattern.search(strip_accents(text)))


_MARKET_PATTERN = keyword_pattern([
    'mercado', 'mercados', 'fiscal', 'economia', 'economica', 'economico', 'dolar', 'bolsa', 'ibovespa',
    'juros', 'selic', 'inflacao', 'investidor', 'investidores', 'investimento', 'investimentos',
    'acoes', 'risco', 'arcabouco', 'divida', 'gastos', 'reforma', 'agenda economica', 'banco central',
])


def mentions_market(text: str) -> bool:
    """True se o texto cita economia/mercado — usado para priorizar notícias de eleição."""
    return bool(_MARKET_PATTERN.search(strip_accents(text)))
