import io
import html
import asyncio
import logging
from datetime import datetime, timedelta

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from telegram import Bot, Update, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from utils.helpers import get_env, format_variation, format_number, resolve_symbol, is_election_news, mentions_market
from database.models import Cotacao, Noticia, PostSocial, IndicadorEconomico, Alerta, ResumoDiario

logger = logging.getLogger(__name__)

MAX_MSG = 4096
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def split_message(text: str, limit: int = MAX_MSG) -> list[str]:
    """Quebra mensagens longas em blocos, respeitando quebras de linha."""
    chunks, atual = [], ""
    for linha in text.split("\n"):
        if len(atual) + len(linha) + 1 > limit:
            chunks.append(atual)
            atual = ""
        atual += linha + "\n"
    if atual.strip():
        chunks.append(atual)
    return chunks


class TelegramBot:
    def __init__(self, config: dict, db):
        """
        Inicializa o bot do Telegram.
        """
        self.config = config
        self.db = db
        self.token = get_env('TELEGRAM_BOT_TOKEN', '')
        self.default_chat_id = get_env('TELEGRAM_CHAT_ID', '')
        if self.default_chat_id in ('', 'seu_chat_id_aqui'):
            self.default_chat_id = None
        self.app = None

    def is_configured(self) -> bool:
        return bool(self.token) and self.token != 'seu_token_aqui'

    def setup_handlers(self):
        """
        Configura os handlers de comando do bot.
        """
        if not self.is_configured():
            raise ValueError("TELEGRAM_BOT_TOKEN não configurado no .env")

        self.app = Application.builder().token(self.token).build()

        comandos = {
            "start": self.cmd_start,
            "ajuda": self.cmd_ajuda,
            "help": self.cmd_ajuda,
            "resumo": self.cmd_resumo,
            "cotacoes": self.cmd_cotacoes,
            "noticias": self.cmd_noticias,
            "eleicoes": self.cmd_eleicoes,
            "sentimento": self.cmd_sentimento,
            "grafico": self.cmd_grafico,
            "tendencia": self.cmd_tendencia,
            "alertas": self.cmd_alertas,
            "alerta_criar": self.cmd_alerta_criar,
            "alerta_remover": self.cmd_alerta_remover,
            "coletar": self.cmd_coletar,
            "fontes": self.cmd_fontes,
            "status": self.cmd_status,
        }
        for nome, handler in comandos.items():
            self.app.add_handler(CommandHandler(nome, handler))

    def run(self):
        """
        Inicia o bot em modo polling (bloqueante até Ctrl+C).
        """
        if not self.app:
            self.setup_handlers()
        logger.info("Bot do Telegram em modo polling — envie /start para o bot.")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

    # ------------------------------------------------------------------ helpers

    async def _reply(self, update: Update, text: str):
        for chunk in split_message(text):
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)

    # ----------------------------------------------------------------- comandos

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /start."""
        chat_id = update.effective_chat.id
        msg = (
            "Olá! Eu sou o <b>Bot de Inteligência Econômica</b> 📊\n\n"
            "Acompanho cotações, indicadores do Banco Central, notícias e redes sociais "
            "sobre economia e investimentos, e mando um resumo todo dia.\n\n"
            f"Seu chat ID é <code>{chat_id}</code> — coloque em <code>TELEGRAM_CHAT_ID</code> "
            "no arquivo .env para receber o resumo diário.\n\n"
            "Digite /ajuda para ver os comandos."
        )
        await self._reply(update, msg)

    async def cmd_ajuda(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /ajuda."""
        msg = (
            "🤖 <b>Comandos Disponíveis</b>\n\n"
            "/resumo — Resumo do mercado hoje\n"
            "/cotacoes — Cotações (bolsa, moedas, cripto, commodities)\n"
            "/noticias — Últimas 10 notícias\n"
            "/eleicoes — Notícias das eleições (últimas 48h)\n"
            "/sentimento — Humor do mercado nas notícias/redes\n"
            "/grafico [ativo] — Gráfico de 30 dias (ex: /grafico IBOV)\n"
            "/tendencia [ativo] — Médias móveis e leitura técnica simples\n"
            "/alertas — Seus alertas ativos\n"
            "/alerta_criar [ativo] [acima|abaixo] [valor]\n"
            "   ex: /alerta_criar DOLAR acima 5.80\n"
            "/alerta_remover [id]\n"
            "/coletar — Força uma coleta agora\n"
            "/fontes — Fontes monitoradas\n"
            "/status — Status do sistema\n\n"
            "Ativos: IBOV, DOLAR, EURO, BTC, ETH, OURO, SP500, NASDAQ, PETR4, VALE3"
        )
        await self._reply(update, msg)

    async def cmd_resumo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /resumo."""
        from analysis.summarizer import DailySummarizer

        await update.message.reply_text("⏳ Gerando resumo...")
        summarizer = DailySummarizer(self.config, self.db)
        summary = await asyncio.to_thread(summarizer.generate_summary, self.db)
        await self._reply(update, summarizer.format_telegram_message(summary))

    async def cmd_cotacoes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /cotacoes."""
        from analysis.summarizer import format_price

        titulos = {'indice': '📊 Índices', 'moeda': '💱 Moedas', 'cripto': '🪙 Cripto',
                   'commodity': '🥇 Commodities', 'acao': '🏢 Ações'}
        try:
            grupos: dict[str, list[str]] = {}
            ultima = None
            with self.db.session_scope() as session:
                for ativo in self.config.get('finance', {}).get('ativos', []):
                    c = session.query(Cotacao).filter(Cotacao.symbol == ativo['symbol']) \
                        .order_by(Cotacao.collected_at.desc()).first()
                    if not c:
                        continue
                    ultima = max(ultima, c.collected_at) if ultima else c.collected_at
                    grupos.setdefault(c.tipo or 'outro', []).append(
                        f"• {html.escape(c.name)}: <b>{format_price(c.symbol, c.tipo, c.price)}</b> "
                        f"({format_variation(c.variation_percent)})"
                    )

            if not grupos:
                await update.message.reply_text("Nenhuma cotação ainda. Use /coletar para buscar agora.")
                return

            msg = "📈 <b>Cotações</b>\n\n"
            for tipo, linhas in grupos.items():
                msg += f"<b>{titulos.get(tipo, tipo.title())}</b>\n" + "\n".join(linhas) + "\n\n"
            msg += f"<i>Atualizado em {ultima:%d/%m %H:%M} (UTC)</i>"
            await self._reply(update, msg)
        except Exception as e:
            logger.error(f"Erro em cmd_cotacoes: {e}")
            await update.message.reply_text("Ocorreu um erro ao buscar as cotações.")

    async def cmd_noticias(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /noticias."""
        emoji = {'positivo': '🟢', 'negativo': '🔴'}
        try:
            with self.db.session_scope() as session:
                noticias = session.query(Noticia).order_by(Noticia.published_at.desc()).limit(10).all()

            if not noticias:
                await update.message.reply_text("Nenhuma notícia ainda. Use /coletar para buscar agora.")
                return

            msg = "📰 <b>Últimas Notícias</b>\n\n"
            for i, n in enumerate(noticias, 1):
                msg += (f"{i}. {emoji.get(n.sentiment_label, '🟡')} "
                        f"<a href=\"{html.escape(n.url or '')}\">{html.escape(n.title)}</a>"
                        f" — <i>{html.escape(n.source or '')}</i>\n\n")
            await self._reply(update, msg)
        except Exception as e:
            logger.error(f"Erro em cmd_noticias: {e}")
            await update.message.reply_text("Ocorreu um erro ao buscar as notícias.")

    async def cmd_eleicoes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /eleicoes — notícias eleitorais das últimas 48h."""
        emoji = {'positivo': '🟢', 'negativo': '🔴'}
        try:
            desde = datetime.now() - timedelta(hours=48)
            with self.db.session_scope() as session:
                recentes = session.query(Noticia).filter(Noticia.collected_at >= desde) \
                    .order_by(Noticia.published_at.desc()).all()
            eleicoes = [n for n in recentes if is_election_news(f"{n.title} {n.summary or ''}", self.config)]
            # Economia/mercado primeiro (a ordenação é estável, então mantém a mais recente na frente)
            eleicoes.sort(key=lambda n: not mentions_market(f"{n.title} {n.summary or ''}"))

            if not eleicoes:
                await update.message.reply_text("Nenhuma notícia sobre eleições nas últimas 48h. Use /coletar para buscar agora.")
                return

            msg = f"🗳️ <b>Eleições</b> — {len(eleicoes)} notícias nas últimas 48h\n\n"
            for i, n in enumerate(eleicoes[:10], 1):
                msg += (f"{i}. {emoji.get(n.sentiment_label, '🟡')} "
                        f"<a href=\"{html.escape(n.url or '')}\">{html.escape(n.title)}</a>"
                        f" — <i>{html.escape(n.source or '')}</i>\n\n")
            await self._reply(update, msg)
        except Exception as e:
            logger.error(f"Erro em cmd_eleicoes: {e}")
            await update.message.reply_text("Ocorreu um erro ao buscar as notícias das eleições.")

    async def cmd_sentimento(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /sentimento."""
        from analysis.sentiment import SentimentAnalyzer

        analyzer = SentimentAnalyzer(self.config)
        await asyncio.to_thread(analyzer.score_pending, self.db)
        s = await asyncio.to_thread(analyzer.get_market_sentiment, self.db)
        emoji = {'positivo': '🟢', 'negativo': '🔴'}.get(s['label'], '🟡')

        total = s.get('positivos', 0) + s.get('negativos', 0) + s.get('neutros', 0)
        if total == 0:
            await update.message.reply_text("Ainda não há notícias/posts de hoje. Use /coletar.")
            return

        msg = (f"🧠 <b>Sentimento do Mercado (hoje)</b>\n\n"
               f"{emoji} <b>{s['label'].title()}</b> — score {s['score']:+.2f}\n\n"
               f"🟢 Positivos: {s.get('positivos', 0)}\n"
               f"🔴 Negativos: {s.get('negativos', 0)}\n"
               f"🟡 Neutros: {s.get('neutros', 0)}\n\n")
        src = s.get('sources', {})
        if src:
            msg += (f"📰 Notícias: {src['news']['score']:+.2f} ({src['news']['count']})\n"
                    f"💬 Redes sociais: {src['social']['score']:+.2f} ({src['social']['count']})\n\n")
        if s.get('por_fonte'):
            msg += "<b>Por fonte</b>\n"
            # As fontes com mais notícias hoje
            for fonte, (score, n) in sorted(s['por_fonte'].items(), key=lambda kv: kv[1][1], reverse=True)[:8]:
                msg += f"• {html.escape(fonte)}: {score:+.2f} ({n})\n"
        await self._reply(update, msg)

    async def cmd_grafico(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /grafico."""
        texto = context.args[0] if context.args else "IBOV"
        symbol, name = resolve_symbol(self.config, texto)
        await self.send_chart(update.effective_chat.id, symbol, name, days=30)

    async def cmd_tendencia(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /tendencia — médias móveis e sugestão."""
        from analysis.trend_detector import TrendDetector

        texto = context.args[0] if context.args else "IBOV"
        symbol, name = resolve_symbol(self.config, texto)
        detector = TrendDetector(self.config)
        t = await asyncio.to_thread(detector.detect_price_trends, self.db, symbol)
        s = await asyncio.to_thread(detector.suggest_best_time, self.db, symbol)
        if not t:
            await update.message.reply_text(f"Sem dados para {texto}. Use /coletar primeiro.")
            return

        seta = {'alta': '📈', 'baixa': '📉'}.get(t['trend'], '➡️')
        msg = (f"{seta} <b>{html.escape(name)}</b> ({html.escape(symbol)})\n\n"
               f"Tendência 7d: <b>{t['trend']}</b> ({format_variation(t['change_percent'])})\n"
               f"Atual: <b>{format_number(t['current_price'])}</b>\n"
               f"Mín/Máx 7d: {format_number(t['min_price'])} / {format_number(t['max_price'])}\n"
               f"Volatilidade diária: {format_number(t['volatility_percent'])}%\n")
        if 'sma_7' in s:
            msg += f"MM7: {format_number(s['sma_7'])} | MM14: {format_number(s['sma_14'])}\n"
        msg += f"\n💡 {html.escape(s['suggestion'])}\n\n<i>Não é recomendação de investimento.</i>"
        await self._reply(update, msg)

    async def cmd_alertas(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /alertas."""
        chat_id = str(update.effective_chat.id)
        try:
            with self.db.session_scope() as session:
                alertas = session.query(Alerta).filter(
                    Alerta.chat_id == chat_id, Alerta.active == True, Alerta.triggered == False  # noqa: E712
                ).all()

            if not alertas:
                await update.message.reply_text(
                    "Você não tem alertas ativos.\nCrie um: /alerta_criar DOLAR acima 5.80")
                return

            msg = "🔔 <b>Seus Alertas Ativos</b>\n\n"
            for a in alertas:
                msg += f"ID <code>{a.id}</code> — {html.escape(a.asset_name or a.asset_symbol)} {a.condition} {format_number(a.threshold)}\n"
            await self._reply(update, msg)
        except Exception as e:
            logger.error(f"Erro em cmd_alertas: {e}")
            await update.message.reply_text("Erro ao buscar alertas.")

    async def cmd_alerta_criar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /alerta_criar."""
        chat_id = str(update.effective_chat.id)
        args = context.args
        if len(args) < 3:
            await update.message.reply_text("Uso: /alerta_criar [ativo] [acima|abaixo] [valor]\nex: /alerta_criar BTC abaixo 60000")
            return

        symbol, name = resolve_symbol(self.config, args[0])
        condicao = args[1].lower()
        try:
            valor = float(args[2].replace(',', '.'))
        except ValueError:
            await update.message.reply_text("Valor numérico inválido.")
            return

        if condicao not in ['acima', 'abaixo']:
            await update.message.reply_text("A condição deve ser 'acima' ou 'abaixo'.")
            return

        try:
            with self.db.session_scope() as session:
                alerta = Alerta(
                    chat_id=chat_id,
                    asset_symbol=symbol,
                    asset_name=name,
                    condition=condicao,
                    threshold=valor,
                    active=True
                )
                session.add(alerta)
            await update.message.reply_text(f"✅ Alerta criado: {name} {condicao} {format_number(valor)}")
        except Exception as e:
            logger.error(f"Erro ao criar alerta: {e}")
            await update.message.reply_text("Erro ao criar o alerta.")

    async def cmd_alerta_remover(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /alerta_remover."""
        chat_id = str(update.effective_chat.id)
        args = context.args
        if not args:
            await update.message.reply_text("Uso: /alerta_remover [id]")
            return

        try:
            alerta_id = int(args[0])
            with self.db.session_scope() as session:
                alerta = session.query(Alerta).filter(Alerta.id == alerta_id, Alerta.chat_id == chat_id).first()
                if alerta:
                    session.delete(alerta)
            if alerta:
                await update.message.reply_text(f"✅ Alerta {alerta_id} removido.")
            else:
                await update.message.reply_text("Alerta não encontrado.")
        except ValueError:
            await update.message.reply_text("ID inválido.")
        except Exception as e:
            logger.error(f"Erro ao remover alerta: {e}")
            await update.message.reply_text("Erro ao remover alerta.")

    async def cmd_coletar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /coletar — dispara uma coleta completa."""
        from main import executar_coleta

        await update.message.reply_text("🕷️ Coletando dados... isso leva de 1 a 3 minutos.")
        res = await asyncio.to_thread(executar_coleta, self.config, self.db, logging.getLogger('bot_economia'))
        msg = (f"✅ <b>Coleta concluída</b>\n\n"
               f"Cotações: {res['cotacoes']}\nIndicadores: {res['indicadores']}\n"
               f"Notícias novas: {res['noticias']}\nPosts novos: {res['posts']}")
        if res['erros']:
            msg += "\n\n⚠️ " + html.escape("; ".join(res['erros']))[:500]
        await self._reply(update, msg)
        await self.notify_alerts()

    async def cmd_fontes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /fontes."""
        cfg = self.config
        e = html.escape
        feeds = ", ".join(e(f['name']) for f in cfg.get('news', {}).get('feeds', []))
        termos = ", ".join(e(t) for t in cfg.get('news', {}).get('google_news_termos', []))
        insta = ", ".join("@" + e(p) for p in cfg.get('instagram', {}).get('perfis', []))
        linkedin = ", ".join(e(t) for t in cfg.get('linkedin', {}).get('empresas', []))
        ativos = ", ".join(e(a['name']) for a in cfg.get('finance', {}).get('ativos', []))
        bcb = ", ".join(e(i['name']) for i in cfg.get('finance', {}).get('indicadores_bcb', []))
        msg = (f"📚 <b>Fontes Monitoradas</b>\n\n"
               f"📰 <b>RSS:</b> {feeds}\n\n"
               f"🔎 <b>Google News:</b> {termos}\n\n"
               f"📸 <b>Instagram:</b> {insta}\n\n"
               f"💼 <b>LinkedIn (empresas):</b> {linkedin}\n\n"
               f"💰 <b>Ativos (Yahoo Finance):</b> {ativos}\n\n"
               f"🏦 <b>Banco Central:</b> {bcb}\n\n"
               f"<i>Para alterar, edite o config.yaml.</i>")
        await self._reply(update, msg)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /status."""
        try:
            with self.db.session_scope() as session:
                ultima_cot = session.query(Cotacao.collected_at).order_by(Cotacao.collected_at.desc()).first()
                ultima_not = session.query(Noticia.collected_at).order_by(Noticia.collected_at.desc()).first()
                n_cot = session.query(Cotacao).count()
                n_not = session.query(Noticia).count()
                n_posts = session.query(PostSocial).count()
                n_ind = session.query(IndicadorEconomico).count()
                n_alertas = session.query(Alerta).filter(Alerta.active == True, Alerta.triggered == False).count()  # noqa: E712
                n_resumos = session.query(ResumoDiario).count()

            fmt = lambda r: f"{r[0]:%d/%m/%Y %H:%M} UTC" if r else "nunca"  # noqa: E731
            sched = self.config.get('schedule', {})
            msg = (f"⚙️ <b>Status do Sistema</b> — operacional ✅\n\n"
                   f"Última coleta de cotações: {fmt(ultima_cot)}\n"
                   f"Última coleta de notícias: {fmt(ultima_not)}\n\n"
                   f"<b>Banco de dados</b>\n"
                   f"• Cotações: {n_cot}\n• Indicadores: {n_ind}\n• Notícias: {n_not}\n"
                   f"• Posts sociais: {n_posts}\n• Alertas ativos: {n_alertas}\n• Resumos: {n_resumos}\n\n"
                   f"⏰ Coleta diária às {sched.get('coleta_hora')} e resumo às {sched.get('envio_hora')} "
                   f"({sched.get('timezone')})")
            await self._reply(update, msg)
        except Exception as e:
            logger.error(f"Erro em cmd_status: {e}")
            await update.message.reply_text("Erro ao consultar o status.")

    # ------------------------------------------------------ envios automáticos

    async def _send(self, chat_id, text: str):
        """Envia uma mensagem HTML usando a Application ativa ou um Bot avulso (jobs agendados)."""
        if self.app is not None and self.app.running:
            bot = self.app.bot
            for chunk in split_message(text):
                await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.HTML,
                                       link_preview_options=NO_PREVIEW)
        else:
            async with Bot(self.token) as bot:
                for chunk in split_message(text):
                    await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.HTML,
                                           link_preview_options=NO_PREVIEW)

    async def send_daily_summary(self, summary: dict) -> bool:
        """Envia o resumo diário para TELEGRAM_CHAT_ID."""
        from analysis.summarizer import DailySummarizer

        if not self.is_configured():
            raise ValueError("TELEGRAM_BOT_TOKEN não configurado no .env")
        if not self.default_chat_id:
            raise ValueError("TELEGRAM_CHAT_ID não configurado no .env (envie /start ao bot para descobrir)")

        text = DailySummarizer(self.config).format_telegram_message(summary)
        await self._send(self.default_chat_id, text)
        return True

    async def send_alert_notifications(self, alertas: list[dict]):
        """Notifica cada usuário sobre seus alertas disparados."""
        for a in alertas:
            preco = format_number(a.get('price'))
            msg = (f"🚨 <b>ALERTA DISPARADO</b>\n\n"
                   f"Ativo: <b>{html.escape(a['symbol'])}</b>\n"
                   f"Condição: {a['condition']} {format_number(a['threshold'])}\n"
                   f"Preço atual: <b>{preco}</b>")
            try:
                await self._send(a['chat_id'], msg)
            except Exception as e:
                logger.error(f"Erro ao enviar alerta para {a['chat_id']}: {e}")

    async def notify_alerts(self):
        """Verifica alertas com as cotações atuais e notifica os disparados."""
        from analysis.trend_detector import TrendDetector

        disparados = await asyncio.to_thread(TrendDetector(self.config).check_alerts, self.db)
        await self.send_alert_notifications([
            {'chat_id': a.chat_id, 'symbol': a.asset_name or a.asset_symbol, 'condition': a.condition,
             'threshold': a.threshold, 'price': getattr(a, 'current_price', None)}
            for a in disparados
        ])

    async def send_chart(self, chat_id, symbol: str, name: str | None = None, days: int = 30):
        """Gera e envia o gráfico de preço."""
        bot = self.app.bot
        try:
            cutoff = datetime.now() - timedelta(days=days)
            with self.db.session_scope() as session:
                data = session.query(Cotacao).filter(
                    Cotacao.symbol == symbol,
                    Cotacao.collected_at >= cutoff
                ).order_by(Cotacao.collected_at.asc()).all()

            if len(data) < 2:
                await bot.send_message(chat_id=chat_id, text=f"Sem dados suficientes para gerar gráfico de {name or symbol}.")
                return

            import pandas as pd
            # Uma cotação por dia (a última coletada)
            serie = pd.Series([d.price for d in data], index=pd.to_datetime([d.collected_at for d in data]))
            serie = serie.groupby(serie.index.date).last()
            serie.index = pd.to_datetime(serie.index)
            ma7 = serie.rolling(window=min(7, len(serie))).mean()

            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(serie.index, serie.values, label='Preço', color='#1a237e', linewidth=2)
            ax.plot(ma7.index, ma7.values, label='Média Móvel 7d', color='#ff9800', linestyle='--')
            var = (serie.iloc[-1] / serie.iloc[0] - 1) * 100
            ax.set_title(f'{name or symbol} — {days} dias ({var:+.2f}%)')
            ax.grid(True, alpha=0.3)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
            fig.autofmt_xdate()
            ax.legend()

            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
            buf.seek(0)
            plt.close(fig)

            await bot.send_photo(chat_id=chat_id, photo=buf,
                                 caption=f"{name or symbol}: último {format_number(serie.iloc[-1])}")
        except Exception as e:
            logger.error(f"Erro ao enviar gráfico de {symbol}: {e}")
            await bot.send_message(chat_id=chat_id, text="Erro ao gerar o gráfico.")
