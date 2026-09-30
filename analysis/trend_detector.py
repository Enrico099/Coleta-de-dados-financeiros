"""
Módulo para detecção de tendências financeiras.
"""
import logging
from datetime import datetime, timedelta, date
import pandas as pd
import numpy as np
from database.db import Database
from database.models import Cotacao, Alerta

logger = logging.getLogger(__name__)

class TrendDetector:
    """Detector de tendências de preços usando pandas e numpy."""

    def __init__(self, config: dict | None = None):
        """Inicializa o detector de tendências."""
        self.config = config or {}
        self.window_days = self.config.get('analysis', {}).get('trend_window_days', 7)

    @staticmethod
    def _daily_prices(cotacoes) -> pd.Series:
        """Uma cotação por dia (a última), para várias coletas no mesmo dia não distorcerem as médias."""
        df = pd.DataFrame(
            {'price': [c.price for c in cotacoes]},
            index=pd.to_datetime([c.collected_at for c in cotacoes]),
        ).dropna()
        if df.empty:
            return df['price']
        return df['price'].groupby(df.index.date).last()

    def detect_price_trends(self, db: Database, symbol: str, days: int | None = None) -> dict:
        """
        Analisa dados históricos de um ativo para detectar tendências.
        """
        days = days or self.window_days
        try:
            start_date = date.today() - timedelta(days=days)

            with db.session_scope() as session:
                cotacoes = session.query(Cotacao).filter(
                    Cotacao.symbol == symbol,
                    Cotacao.collected_at >= start_date
                ).order_by(Cotacao.collected_at).all()
                name = cotacoes[-1].name if cotacoes else symbol

            prices = self._daily_prices(cotacoes)
            if prices.empty:
                return {}

            first_price = float(prices.iloc[0])
            last_price = float(prices.iloc[-1])
            change = (last_price - first_price) / first_price * 100 if first_price else 0.0
            if change > 1:
                trend = 'alta'
            elif change < -1:
                trend = 'baixa'
            else:
                trend = 'lateral'

            volatility = float(prices.pct_change().std() * 100) if len(prices) > 2 else 0.0

            return {
                'symbol': symbol,
                'name': name,
                'days': days,
                'sma': float(prices.mean()),
                'trend': trend,
                'change_percent': round(change, 2),
                'volatility_percent': round(volatility, 2) if not np.isnan(volatility) else 0.0,
                'min_price': float(prices.min()),
                'max_price': float(prices.max()),
                'current_price': last_price
            }
        except Exception as e:
            logger.error(f"Erro ao detectar tendências para {symbol}: {e}")
            return {}

    def detect_all_trends(self, db: Database) -> list[dict]:
        """Detecta tendências para todos os ativos monitorados recentemente."""
        trends = []
        try:
            with db.session_scope() as session:
                start_date = date.today() - timedelta(days=7)
                recent_quotes = session.query(Cotacao.symbol).filter(
                    Cotacao.collected_at >= start_date
                ).distinct().all()
                symbols = [r[0] for r in recent_quotes]
                
            for symbol in symbols:
                trend_data = self.detect_price_trends(db, symbol)
                if trend_data:
                    trends.append(trend_data)
                    
            return trends
        except Exception as e:
            logger.error(f"Erro ao detectar todas as tendências: {e}")
            return []

    def check_alerts(self, db: Database) -> list[Alerta]:
        """
        Verifica alertas ativos e marca os disparados.
        """
        triggered_alerts = []
        try:
            with db.session_scope() as session:
                alerts = session.query(Alerta).filter(Alerta.active == True, Alerta.triggered == False).all()
                
                symbols = set(a.asset_symbol for a in alerts)
                latest_prices = {}
                for symbol in symbols:
                    latest = session.query(Cotacao).filter(Cotacao.symbol == symbol).order_by(Cotacao.collected_at.desc()).first()
                    if latest and latest.price is not None:
                        latest_prices[symbol] = latest.price
                
                for alert in alerts:
                    price = latest_prices.get(alert.asset_symbol)
                    if price is None:
                        continue
                        
                    if alert.condition in ('acima', '>', '>='):
                        is_triggered = price >= alert.threshold
                    elif alert.condition in ('abaixo', '<', '<='):
                        is_triggered = price <= alert.threshold
                    else:
                        is_triggered = False

                    if is_triggered:
                        alert.current_price = price  # usado na notificação (não persiste)
                        alert.triggered = True
                        alert.triggered_at = datetime.now()
                        triggered_alerts.append(alert)
                        logger.info(f"Alerta disparado: {alert.asset_symbol} {alert.condition} {alert.threshold} (Preço atual: {price})")
            
            return triggered_alerts
        except Exception as e:
            logger.error(f"Erro ao verificar alertas: {e}")
            return []

    def suggest_best_time(self, db: Database, symbol: str) -> dict:
        """
        Analisa dados históricos para sugerir se é um bom momento de compra/venda.
        """
        try:
            with db.session_scope() as session:
                cotacoes = session.query(Cotacao).filter(
                    Cotacao.symbol == symbol
                ).order_by(Cotacao.collected_at).all()
                
            prices = self._daily_prices(cotacoes)
            if len(prices) < 14:
                return {'symbol': symbol, 'suggestion': 'Dados insuficientes para análise.'}

            df = pd.DataFrame({'price': prices.values})
            
            sma_short = df['price'].rolling(window=7).mean().iloc[-1]
            sma_long = df['price'].rolling(window=14).mean().iloc[-1]
            current_price = df['price'].iloc[-1]
            
            if pd.isna(sma_short) or pd.isna(sma_long):
                return {'symbol': symbol, 'suggestion': 'Dados insuficientes para análise de médias móveis.'}
            
            suggestion_text = "Mantenha a posição."
            # Médias muito próximas (< 0,5%) = sem tendência clara
            if abs(sma_short - sma_long) / sma_long < 0.005:
                suggestion_text = "Médias móveis praticamente iguais — mercado sem tendência clara. Mantenha a posição."
            elif sma_short > sma_long and current_price > sma_short:
                suggestion_text = "Tendência de alta forte. Possível oportunidade de venda para realizar lucros, ou manter se acreditar na continuação."
            elif sma_short < sma_long and current_price < sma_short:
                suggestion_text = "Tendência de baixa forte. Possível oportunidade de compra perto de suportes históricos, mas cuidado com quedas maiores."
                
            return {
                'symbol': symbol,
                'current_price': float(current_price),
                'sma_7': float(sma_short),
                'sma_14': float(sma_long),
                'suggestion': suggestion_text
            }
        except Exception as e:
            logger.error(f"Erro ao sugerir melhor momento para {symbol}: {e}")
            return {'symbol': symbol, 'suggestion': 'Erro na análise.'}
