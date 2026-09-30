"""
Scraper de dados financeiros e econômicos usando yfinance e python-bcb.
"""
import logging
from datetime import datetime, timedelta, timezone
from .base import BaseScraper
from database.db import Database
from database.models import Cotacao, IndicadorEconomico

logger = logging.getLogger(__name__)


class FinanceAPIScraper(BaseScraper):
    """Scraper para dados de mercado (yfinance) e indicadores econômicos (BCB)."""

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)

    @staticmethod
    def _historico(hist, symbol: str, name: str, tipo: str) -> list[Cotacao]:
        """Converte o DataFrame do yfinance em cotações diárias (uma por pregão)."""
        registros = []
        closes = hist['Close'].tolist()
        for i, (ts, row) in enumerate(hist.iterrows()):
            prev = closes[i - 1] if i > 0 else None
            price = float(row['Close'])
            registros.append(Cotacao(
                symbol=symbol,
                name=name,
                tipo=tipo,
                price=price,
                previous_close=float(prev) if prev else None,
                variation_percent=round((price - prev) / prev * 100, 2) if prev else None,
                high=float(row['High']),
                low=float(row['Low']),
                volume=float(row['Volume'] or 0),
                collected_at=ts.to_pydatetime().astimezone(timezone.utc).replace(hour=21, minute=0, second=0, microsecond=0),
            ))
        return registros

    def collect(self, db: Database) -> dict:
        """
        Coleta cotações de ativos e indicadores econômicos do BCB.

        Returns:
            dict com contadores: {'cotacoes': int, 'indicadores': int}
        """
        ativos = self.config.get('finance', {}).get('ativos', [])
        indicadores_bcb = self.config.get('finance', {}).get('indicadores_bcb', [])

        count_cotacoes = 0
        count_indicadores = 0

        # === Yahoo Finance (Cotações) ===
        try:
            import yfinance as yf

            for ativo in ativos:
                symbol = ativo.get('symbol', '')
                name = ativo.get('name', symbol)
                tipo = ativo.get('tipo', 'outro')

                self.log_info(f"Coletando cotação de {name} ({symbol})")
                try:
                    ticker = yf.Ticker(symbol)
                    hist = ticker.history(period="3mo")

                    if hist.empty:
                        self.log_error(f"Sem dados para {symbol}")
                        continue

                    current_price = float(hist['Close'].iloc[-1])
                    previous_close = float(hist['Close'].iloc[-2]) if len(hist) > 1 else current_price
                    variation = ((current_price - previous_close) / previous_close) * 100 if previous_close else 0.0

                    cotacao = Cotacao(
                        symbol=symbol,
                        name=name,
                        tipo=tipo,
                        price=current_price,
                        previous_close=previous_close,
                        variation_percent=round(variation, 2),
                        high=float(hist['High'].iloc[-1]),
                        low=float(hist['Low'].iloc[-1]),
                        volume=float(hist['Volume'].iloc[-1]) if hist['Volume'].iloc[-1] else 0,
                    )

                    with db.session_scope() as session:
                        # Primeira coleta do ativo: grava o histórico diário para que
                        # tendências, médias móveis e gráficos funcionem desde o dia 1.
                        ja_existe = session.query(Cotacao.id).filter(Cotacao.symbol == symbol).first()
                        if not ja_existe:
                            session.add_all(self._historico(hist.iloc[:-1], symbol, name, tipo))
                        session.add(cotacao)
                    count_cotacoes += 1

                except Exception as e:
                    self.log_error(f"Erro ao coletar cotação de {symbol}: {e}")

        except ImportError:
            self.log_error("yfinance não instalado. Instale com: pip install yfinance")

        # === Banco Central do Brasil (Indicadores) ===
        try:
            from bcb import sgs

            for indicador in indicadores_bcb:
                code = indicador.get('code')
                name = indicador.get('name', f'Indicador {code}')

                self.log_info(f"Coletando indicador BCB: {name} (código: {code})")
                try:
                    data_inicio = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
                    dados = sgs.get({name: code}, start=data_inicio)

                    if dados is not None and not dados.empty:
                        valor_recente = float(dados[name].dropna().iloc[-1])
                        data_referencia = dados.index[-1].to_pydatetime()

                        indicador_obj = IndicadorEconomico(
                            name=name,
                            code=code,
                            value=valor_recente,
                            reference_date=data_referencia,
                        )

                        with db.session_scope() as session:
                            session.add(indicador_obj)
                        count_indicadores += 1
                    else:
                        self.log_error(f"Sem dados retornados pelo BCB para {name}")

                except Exception as e:
                    self.log_error(f"Erro ao coletar indicador {name} do BCB: {e}")

        except ImportError:
            self.log_error("python-bcb não instalado. Instale com: pip install python-bcb")

        self.log_info(f"Coleta financeira finalizada: {count_cotacoes} cotações, {count_indicadores} indicadores")
        return {'cotacoes': count_cotacoes, 'indicadores': count_indicadores}

