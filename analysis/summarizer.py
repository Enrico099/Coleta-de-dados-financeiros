"""
Módulo para sumarização diária de dados.
"""
import json
import html
import logging
from datetime import date, datetime, timedelta
from database.db import Database
from database.models import Cotacao, Noticia, PostSocial, IndicadorEconomico, ResumoDiario
from analysis.sentiment import SentimentAnalyzer
from analysis.trend_detector import TrendDetector
from utils.helpers import format_currency, format_variation, load_config, truncate_text, is_election_news, mentions_market

logger = logging.getLogger(__name__)

SENTIMENTO_EMOJI = {'positivo': '🟢', 'negativo': '🔴', 'neutro': '🟡'}
TENDENCIA_EMOJI = {'alta': '📈', 'baixa': '📉', 'lateral': '➡️'}

# Unidade de exibição por tipo de ativo
MOEDA_POR_TIPO = {'cripto': 'US$', 'commodity': 'US$', 'indice': 'pts'}
MOEDA_POR_SIMBOLO = {'^GSPC': 'pts', '^IXIC': 'pts', '^BVSP': 'pts'}


def format_price(symbol: str, tipo: str | None, price: float | None) -> str:
    """Formata o preço com a unidade certa (R$, US$ ou pontos)."""
    if price is None:
        return "N/A"
    unidade = MOEDA_POR_SIMBOLO.get(symbol) or MOEDA_POR_TIPO.get(tipo or '', 'R$')
    if unidade == 'pts':
        return f"{price:,.0f} pts".replace(',', '.')
    return format_currency(price, unidade)


class DailySummarizer:
    """Gera resumos diários dos dados coletados e formata mensagens."""

    def __init__(self, config: dict | None = None, db: Database | None = None):
        """Inicializa o sumarizador e as dependências."""
        self.config = config or load_config()
        self.db = db
        self.sentiment_analyzer = SentimentAnalyzer(self.config)
        self.trend_detector = TrendDetector(self.config)

    def generate_summary(self, db: Database | None = None) -> dict:
        """
        Gera um resumo diário abrangente e salva no banco.
        """
        db = db or self.db
        try:
            today = date.today()
            # Considera as últimas 24h para não perder a coleta da madrugada
            desde = datetime.now() - timedelta(hours=24)
            summary_dict = {
                'data': today.strftime('%d/%m/%Y'),
                'cotacoes': [],
                'indicadores': [],
                'top_noticias': [],
                'posts_destaque': [],
                'eleicoes': [],
                'total_eleicoes': 0,
                'sentimento': {},
                'tendencias': [],
                'alertas_disparados': [],
                'total_noticias': 0,
                'total_posts': 0,
                'resumo_texto': ""
            }

            # Garante que tudo tem sentimento calculado antes de resumir
            self.sentiment_analyzer.score_pending(db)

            with db.session_scope() as session:
                # Última cotação de cada ativo (na ordem do config.yaml)
                ordem = [a['symbol'] for a in self.config.get('finance', {}).get('ativos', [])]
                for symbol in ordem:
                    c = session.query(Cotacao).filter(Cotacao.symbol == symbol) \
                        .order_by(Cotacao.collected_at.desc()).first()
                    if c:
                        summary_dict['cotacoes'].append({
                            'symbol': c.symbol,
                            'name': c.name,
                            'tipo': c.tipo,
                            'price': c.price,
                            'variation': c.variation_percent,
                            'price_fmt': format_price(c.symbol, c.tipo, c.price),
                        })

                # Último valor de cada indicador
                unidades = {i['name']: i.get('unidade', '')
                            for i in self.config.get('finance', {}).get('indicadores_bcb', [])}
                vistos = set()
                for ind in session.query(IndicadorEconomico).order_by(IndicadorEconomico.collected_at.desc()).all():
                    if ind.name in vistos:
                        continue
                    vistos.add(ind.name)
                    summary_dict['indicadores'].append({
                        'name': ind.name,
                        'value': ind.value,
                        'value_fmt': self._fmt_indicador(ind.value, unidades.get(ind.name, '')),
                        'reference_date': ind.reference_date.strftime('%d/%m/%Y') if ind.reference_date else '',
                    })

                noticias_q = session.query(Noticia).filter(Noticia.collected_at >= desde)
                summary_dict['total_noticias'] = noticias_q.count()
                # Destaques: notícias com sentimento mais forte (positivo ou negativo) primeiro
                noticias = noticias_q.order_by(Noticia.published_at.desc()).limit(60).all()
                noticias.sort(key=lambda n: abs(n.sentiment_score or 0), reverse=True)
                for n in noticias[:5]:
                    summary_dict['top_noticias'].append({
                        'title': n.title,
                        'source': n.source,
                        'url': n.url,
                        'sentiment': n.sentiment_label or 'neutro',
                    })

                # Eleições: as que falam de economia/mercado primeiro, depois as mais recentes
                ja_listadas = {n['url'] for n in summary_dict['top_noticias']}
                eleicoes = [n for n in noticias_q.order_by(Noticia.published_at.desc()).all()
                            if n.url not in ja_listadas
                            and is_election_news(f"{n.title} {n.summary or ''}", self.config)]
                eleicoes.sort(key=lambda n: not mentions_market(f"{n.title} {n.summary or ''}"))
                summary_dict['total_eleicoes'] = len(eleicoes)
                for n in eleicoes[:5]:
                    summary_dict['eleicoes'].append({
                        'title': n.title,
                        'source': n.source,
                        'url': n.url,
                        'sentiment': n.sentiment_label or 'neutro',
                    })

                posts_q = session.query(PostSocial).filter(PostSocial.collected_at >= desde)
                summary_dict['total_posts'] = posts_q.count()
                for p in posts_q.order_by(PostSocial.likes.desc()).limit(3).all():
                    summary_dict['posts_destaque'].append({
                        'platform': p.platform,
                        'author': p.author,
                        'content': truncate_text(p.content, 200),
                        'likes': p.likes,
                        'url': p.post_url,
                    })

            sentimento_data = self.sentiment_analyzer.get_market_sentiment(db)
            summary_dict['sentimento'] = sentimento_data

            summary_dict['tendencias'] = self.trend_detector.detect_all_trends(db)
            triggered_alerts = self.trend_detector.check_alerts(db)
            summary_dict['alertas_disparados'] = [
                {'chat_id': a.chat_id, 'symbol': a.asset_symbol, 'condition': a.condition,
                 'threshold': a.threshold, 'price': getattr(a, 'current_price', None)}
                for a in triggered_alerts
            ]

            summary_dict['resumo_texto'] = self._build_text(summary_dict)

            # Upsert: rodar o resumo mais de uma vez no mesmo dia atualiza o registro
            with db.session_scope() as session:
                dia = datetime.combine(today, datetime.min.time())
                resumo_db = session.query(ResumoDiario).filter(ResumoDiario.date == dia).first()
                if resumo_db is None:
                    resumo_db = ResumoDiario(date=dia)
                    session.add(resumo_db)
                resumo_db.total_noticias = summary_dict['total_noticias']
                resumo_db.total_posts = summary_dict['total_posts']
                resumo_db.sentimento_geral = sentimento_data.get('label', 'neutro')
                resumo_db.sentimento_score = sentimento_data.get('score', 0.0)
                resumo_db.resumo_texto = summary_dict['resumo_texto']
                resumo_db.destaques = json.dumps({
                    'noticias': summary_dict['top_noticias'],
                    'alertas': len(triggered_alerts),
                }, ensure_ascii=False)

            return summary_dict
        except Exception as e:
            logger.exception(f"Erro ao gerar resumo diário: {e}")
            return {}

    @staticmethod
    def _fmt_indicador(value: float | None, unidade: str) -> str:
        if value is None:
            return "N/A"
        numero = f"{value:.2f}".replace('.', ',')
        if unidade == 'R$':
            return f"R$ {numero}"
        return f"{numero}{unidade}" if unidade.startswith('%') else f"{numero} {unidade}".strip()

    @staticmethod
    def _build_text(summary: dict) -> str:
        """Síntese em linguagem natural do dia."""
        sent = summary.get('sentimento', {})
        partes = [
            f"O sentimento geral do mercado hoje está {sent.get('label', 'neutro')} "
            f"(score {sent.get('score', 0):+.2f}, com {sent.get('positivos', 0)} sinais positivos "
            f"e {sent.get('negativos', 0)} negativos em {summary['total_noticias']} notícias e "
            f"{summary['total_posts']} posts)."
        ]

        cot = [c for c in summary.get('cotacoes', []) if c.get('variation') is not None]
        if cot:
            maior = max(cot, key=lambda c: c['variation'])
            menor = min(cot, key=lambda c: c['variation'])
            partes.append(f"Maior alta: {maior['name']} ({maior['variation']:+.2f}%). "
                          f"Maior queda: {menor['name']} ({menor['variation']:+.2f}%).")

        tend = summary.get('tendencias', [])
        altas = [t['name'] for t in tend if t.get('trend') == 'alta']
        baixas = [t['name'] for t in tend if t.get('trend') == 'baixa']
        if altas:
            partes.append(f"Tendência de alta na semana: {', '.join(altas)}.")
        if baixas:
            partes.append(f"Tendência de baixa na semana: {', '.join(baixas)}.")

        if summary.get('total_eleicoes'):
            partes.append(f"{summary['total_eleicoes']} notícia(s) sobre as eleições nas últimas 24h.")

        if summary.get('alertas_disparados'):
            partes.append(f"Atenção: {len(summary['alertas_disparados'])} alerta(s) de preço disparado(s).")
        return " ".join(partes)

    def format_telegram_message(self, summary: dict) -> str:
        """Formata o resumo como mensagem do Telegram (parse_mode=HTML)."""
        if not summary:
            return "❌ Erro ao gerar resumo diário."
        e = html.escape

        sent = summary.get('sentimento', {})
        label = sent.get('label', 'neutro')
        msg = f"📊 <b>Resumo Econômico — {e(summary.get('data', ''))}</b>\n\n"
        msg += f"🧠 <b>Sentimento:</b> {SENTIMENTO_EMOJI.get(label, '🟡')} {label.title()} ({sent.get('score', 0):+.2f})\n\n"

        if summary.get('cotacoes'):
            msg += "💰 <b>Cotações</b>\n"
            for c in summary['cotacoes']:
                msg += f"• {e(c['name'])}: {e(c['price_fmt'])} ({format_variation(c.get('variation'))})\n"
            msg += "\n"

        if summary.get('indicadores'):
            msg += "🏦 <b>Indicadores (BCB)</b>\n"
            for ind in summary['indicadores']:
                msg += f"• {e(ind['name'])}: <b>{e(ind['value_fmt'])}</b> <i>({ind['reference_date']})</i>\n"
            msg += "\n"

        if summary.get('tendencias'):
            msg += "📐 <b>Tendências (7 dias)</b>\n"
            for t in summary['tendencias']:
                msg += f"• {e(t['name'])}: {TENDENCIA_EMOJI.get(t['trend'], '')} {t['trend']} ({t['change_percent']:+.2f}%)\n"
            msg += "\n"

        if summary.get('top_noticias'):
            msg += "📰 <b>Destaques</b>\n"
            for n in summary['top_noticias']:
                msg += (f"{SENTIMENTO_EMOJI.get(n['sentiment'], '🟡')} "
                        f"<a href=\"{e(n['url'] or '')}\">{e(n['title'])}</a> — <i>{e(n['source'] or '')}</i>\n")
            msg += "\n"

        if summary.get('eleicoes'):
            msg += f"🗳️ <b>Eleições</b> <i>({summary.get('total_eleicoes', 0)} notícias nas últimas 24h)</i>\n"
            for n in summary['eleicoes']:
                msg += (f"• <a href=\"{e(n['url'] or '')}\">{e(n['title'])}</a> — <i>{e(n['source'] or '')}</i>\n")
            msg += "\n"

        msg += f"📝 <b>Síntese:</b>\n{e(summary.get('resumo_texto', ''))}\n\n"
        msg += "<i>⚠️ Informativo automático — não é recomendação de investimento.</i>"
        return msg

    def format_email_data(self, summary: dict) -> dict:
        """Prepara dados do resumo para um template de email."""
        if not summary:
            return {}
        sent = summary.get('sentimento', {})
        return {
            'date': summary.get('data'),
            'sentiment_label': sent.get('label', 'neutro'),
            'sentiment_score': sent.get('score', 0.0),
            'sentiment_emoji': SENTIMENTO_EMOJI.get(sent.get('label', 'neutro'), '🟡'),
            'summary_text': summary.get('resumo_texto', ''),
            'assets': summary.get('cotacoes', []),
            'indicators': summary.get('indicadores', []),
            'trends': [dict(t, emoji=TENDENCIA_EMOJI.get(t.get('trend'), '')) for t in summary.get('tendencias', [])],
            'news': [dict(n, emoji=SENTIMENTO_EMOJI.get(n.get('sentiment'), '🟡')) for n in summary.get('top_noticias', [])],
            'posts': summary.get('posts_destaque', []),
            'elections': summary.get('eleicoes', []),
            'elections_total': summary.get('total_eleicoes', 0),
        }
