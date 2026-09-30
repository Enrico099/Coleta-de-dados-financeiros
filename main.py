"""
🤖 Bot de Inteligência Econômica
=================================
Ponto de entrada principal do sistema.

Uso:
    python main.py              # Inicia o bot completo (coleta + Telegram + agendamento)
    python main.py --coletar    # Executa uma coleta imediata
    python main.py --resumo     # Gera e envia resumo imediato
    python main.py --dashboard  # Inicia apenas o dashboard Streamlit
    python main.py --telegram   # Inicia apenas o bot Telegram
    python main.py --teste      # Testa todas as conexões
"""
import argparse
import sys
import os
import time
import asyncio
import logging
import subprocess

from utils.helpers import load_config, setup_logging, get_env
from database.db import Database


def executar_coleta(config: dict, db: Database, logger: logging.Logger):
    """Executa a coleta de todas as fontes configuradas."""
    logger.info("=" * 50)
    logger.info("🕷️  INICIANDO COLETA DE DADOS")
    logger.info("=" * 50)

    resultados = {
        'cotacoes': 0,
        'noticias': 0,
        'posts': 0,
        'indicadores': 0,
        'erros': []
    }

    # 1. APIs Financeiras (mais rápido e confiável)
    try:
        from scrapers.finance_api import FinanceAPIScraper
        logger.info("📈 Coletando dados financeiros...")
        scraper = FinanceAPIScraper("finance_api", config)
        dados = scraper.collect(db)
        resultados['cotacoes'] = dados.get('cotacoes', 0)
        resultados['indicadores'] = dados.get('indicadores', 0)
        logger.info(f"   ✅ {resultados['cotacoes']} cotações, {resultados['indicadores']} indicadores")
    except Exception as e:
        logger.error(f"   ❌ Erro na coleta financeira: {e}")
        resultados['erros'].append(f"Finance API: {e}")

    # 2. Notícias (RSS + Google News)
    try:
        from scrapers.news_scraper import NewsScraper
        logger.info("📰 Coletando notícias...")
        scraper = NewsScraper("news", config)
        dados = scraper.collect(db)
        resultados['noticias'] = dados.get('noticias', 0)
        logger.info(f"   ✅ {resultados['noticias']} notícias coletadas")
    except Exception as e:
        logger.error(f"   ❌ Erro na coleta de notícias: {e}")
        resultados['erros'].append(f"News: {e}")

    # 3. Instagram
    try:
        from scrapers.instagram_scraper import InstagramScraper
        logger.info("📸 Coletando posts do Instagram...")
        scraper = InstagramScraper("instagram", config)
        dados = scraper.collect(db)
        resultados['posts'] += dados.get('posts', 0)
        logger.info(f"   ✅ {dados.get('posts', 0)} posts do Instagram")
    except Exception as e:
        logger.error(f"   ❌ Erro na coleta do Instagram: {e}")
        resultados['erros'].append(f"Instagram: {e}")

    # 4. LinkedIn
    try:
        from scrapers.linkedin_scraper import LinkedInScraper
        logger.info("💼 Coletando posts do LinkedIn...")
        scraper = LinkedInScraper("linkedin", config)
        dados = scraper.collect(db)
        resultados['posts'] += dados.get('posts', 0)
        logger.info(f"   ✅ {dados.get('posts', 0)} posts do LinkedIn")
    except Exception as e:
        logger.error(f"   ❌ Erro na coleta do LinkedIn: {e}")
        resultados['erros'].append(f"LinkedIn: {e}")

    # 5. Sentimento de tudo que chegou
    try:
        from analysis.sentiment import SentimentAnalyzer
        analisados = SentimentAnalyzer(config).score_pending(db)
        logger.info(f"🧠 Sentimento calculado para {analisados} itens novos")
    except Exception as e:
        logger.error(f"   ❌ Erro na análise de sentimento: {e}")
        resultados['erros'].append(f"Sentimento: {e}")

    # Resumo da coleta
    logger.info("-" * 50)
    logger.info("📊 RESUMO DA COLETA:")
    logger.info(f"   Cotações:    {resultados['cotacoes']}")
    logger.info(f"   Indicadores: {resultados['indicadores']}")
    logger.info(f"   Notícias:    {resultados['noticias']}")
    logger.info(f"   Posts:       {resultados['posts']}")
    if resultados['erros']:
        logger.warning(f"   Erros:       {len(resultados['erros'])}")
        for erro in resultados['erros']:
            logger.warning(f"      - {erro}")
    logger.info("=" * 50)

    return resultados


def executar_analise_e_envio(config: dict, db: Database, logger: logging.Logger):
    """Executa análise dos dados e envia resumo."""
    logger.info("🧠 Gerando análise e resumo diário...")

    from analysis.summarizer import DailySummarizer
    summarizer = DailySummarizer(config, db)
    summary = summarizer.generate_summary(db)
    if not summary:
        logger.error("   ❌ Erro ao gerar resumo (veja o log acima)")
        return None
    logger.info("   ✅ Resumo gerado com sucesso")
    logger.info(f"   📝 {summary['resumo_texto']}")

    # Enviar via Telegram (resumo + alertas disparados)
    try:
        from notifications.telegram_bot import TelegramBot
        bot = TelegramBot(config, db)
        if bot.is_configured():
            asyncio.run(bot.send_daily_summary(summary))
            logger.info("   ✅ Resumo enviado via Telegram")
            if summary.get('alertas_disparados'):
                asyncio.run(bot.send_alert_notifications(summary['alertas_disparados']))
                logger.info(f"   🚨 {len(summary['alertas_disparados'])} alerta(s) notificado(s)")
        else:
            logger.warning("   ⚠️ Telegram não configurado no .env — envio ignorado")
    except Exception as e:
        logger.error(f"   ❌ Erro ao enviar via Telegram: {e}")

    # Enviar via E-mail
    try:
        from notifications.email_sender import EmailSender
        email = EmailSender(config)
        if email.is_configured():
            if email.send_daily_report(summary):
                logger.info("   ✅ Resumo enviado via E-mail")
        else:
            logger.warning("   ⚠️ E-mail não configurado no .env — envio ignorado")
    except Exception as e:
        logger.error(f"   ❌ Erro ao enviar via E-mail: {e}")

    return summary


def atualizar_cotacoes_e_alertas(config: dict, db: Database, logger: logging.Logger):
    """Atualiza só as cotações (rápido) e notifica alertas de preço disparados."""
    try:
        from scrapers.finance_api import FinanceAPIScraper
        FinanceAPIScraper("finance_api", config).collect(db)

        from notifications.telegram_bot import TelegramBot
        bot = TelegramBot(config, db)
        if bot.is_configured():
            asyncio.run(bot.notify_alerts())
    except Exception as e:
        logger.error(f"Erro na atualização de cotações/alertas: {e}")


def ciclo_completo(config: dict, db: Database, logger: logging.Logger):
    """Executa coleta + análise + envio."""
    executar_coleta(config, db, logger)
    executar_analise_e_envio(config, db, logger)


def iniciar_agendamento(config: dict, db: Database, logger: logging.Logger):
    """Configura e inicia o agendador APScheduler."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler(timezone=config['schedule']['timezone'])

    # Coleta diária
    hora_coleta, min_coleta = config['schedule']['coleta_hora'].split(':')
    scheduler.add_job(
        executar_coleta,
        CronTrigger(hour=int(hora_coleta), minute=int(min_coleta)),
        args=[config, db, logger],
        id='coleta_diaria',
        name='Coleta Diária de Dados',
        replace_existing=True
    )

    # Envio do resumo
    hora_envio, min_envio = config['schedule']['envio_hora'].split(':')
    scheduler.add_job(
        executar_analise_e_envio,
        CronTrigger(hour=int(hora_envio), minute=int(min_envio)),
        args=[config, db, logger],
        id='resumo_diario',
        name='Resumo Diário',
        replace_existing=True
    )

    # Atualização de cotações + verificação de alertas ao longo do dia
    intervalo = config['schedule'].get('alertas_intervalo_min', 60)
    if intervalo:
        from apscheduler.triggers.interval import IntervalTrigger
        scheduler.add_job(
            atualizar_cotacoes_e_alertas,
            IntervalTrigger(minutes=int(intervalo)),
            args=[config, db, logger],
            id='cotacoes_alertas',
            name='Cotações e Alertas',
            replace_existing=True
        )

    scheduler.start()
    logger.info(f"⏰ Agendador iniciado:")
    logger.info(f"   Coleta: todos os dias às {config['schedule']['coleta_hora']}")
    logger.info(f"   Resumo: todos os dias às {config['schedule']['envio_hora']}")
    if intervalo:
        logger.info(f"   Cotações/alertas: a cada {intervalo} min")
    logger.info(f"   Timezone: {config['schedule']['timezone']}")

    return scheduler


def iniciar_telegram(config: dict, db: Database, logger: logging.Logger):
    """Inicia o bot do Telegram em modo polling."""
    from notifications.telegram_bot import TelegramBot

    logger.info("📱 Iniciando bot do Telegram...")
    bot = TelegramBot(config, db)
    bot.run()


def iniciar_dashboard(config: dict, logger: logging.Logger):
    """Inicia o dashboard Streamlit em um subprocesso."""
    port = config['dashboard']['port']
    logger.info(f"📊 Iniciando dashboard na porta {port}...")
    dashboard_path = os.path.join(os.path.dirname(__file__), 'dashboard', 'app.py')
    subprocess.Popen([
        sys.executable, '-m', 'streamlit', 'run', dashboard_path,
        '--server.port', str(port),
        '--server.headless', 'true',
        '--browser.gatherUsageStats', 'false'
    ])
    logger.info(f"   ✅ Dashboard disponível em http://localhost:{port}")


def testar_conexoes(config: dict, logger: logging.Logger):
    """Testa todas as conexões e dependências."""
    logger.info("🔍 Testando conexões...")
    erros = []

    # Teste: Database
    try:
        db = Database()
        logger.info("   ✅ Banco de dados OK")
    except Exception as e:
        logger.error(f"   ❌ Banco de dados: {e}")
        erros.append(str(e))

    # Teste: yfinance
    try:
        import yfinance as yf
        ticker = yf.Ticker("^BVSP")
        info = ticker.fast_info
        logger.info(f"   ✅ Yahoo Finance OK (IBOV: {info.get('lastPrice', 'N/A')})")
    except Exception as e:
        logger.error(f"   ❌ Yahoo Finance: {e}")
        erros.append(str(e))

    # Teste: Banco Central
    try:
        from bcb import sgs
        from datetime import date, timedelta
        selic = sgs.get({'selic': 432}, start=(date.today() - timedelta(days=10)).isoformat())
        logger.info(f"   ✅ Banco Central OK (Selic: {selic['selic'].iloc[-1]}%)")
    except Exception as e:
        logger.error(f"   ❌ Banco Central: {e}")
        erros.append(str(e))

    # Teste: Telegram
    try:
        token = get_env('TELEGRAM_BOT_TOKEN', '')
        if token and token != 'seu_token_aqui':
            import requests
            resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
            if resp.status_code == 200:
                bot_name = resp.json()['result']['username']
                logger.info(f"   ✅ Telegram OK (@{bot_name})")
            else:
                logger.error(f"   ❌ Telegram: Token inválido")
                erros.append("Telegram token inválido")
        else:
            logger.warning("   ⚠️ Telegram: Token não configurado")
    except ValueError:
        logger.warning("   ⚠️ Telegram: Token não configurado")
    except Exception as e:
        logger.error(f"   ❌ Telegram: {e}")
        erros.append(str(e))

    # Teste: Email
    try:
        from notifications.email_sender import EmailSender
        sender = EmailSender(config)
        if sender.is_configured():
            if sender.test_connection():
                logger.info("   ✅ E-mail SMTP OK")
            else:
                logger.error("   ❌ E-mail: Falha na conexão")
                erros.append("Email SMTP connection failed")
        else:
            logger.warning("   ⚠️ E-mail: Não configurado no .env")
    except ValueError:
        logger.warning("   ⚠️ E-mail: Não configurado")
    except Exception as e:
        logger.error(f"   ❌ E-mail: {e}")
        erros.append(str(e))

    # Teste: RSS Feeds (todos)
    try:
        import feedparser
        for feed_info in config['news']['feeds']:
            feed = feedparser.parse(feed_info['url'])
            if feed.entries:
                logger.info(f"   ✅ RSS {feed_info['name']} OK ({len(feed.entries)} entradas)")
            else:
                logger.warning(f"   ⚠️ RSS {feed_info['name']}: feed vazio ou inacessível")
    except Exception as e:
        logger.error(f"   ❌ RSS: {e}")
        erros.append(str(e))

    if erros:
        logger.warning(f"\n⚠️ {len(erros)} erro(s) encontrado(s). Verifique o .env e as dependências.")
    else:
        logger.info("\n🎉 Todos os testes passaram!")

    return len(erros) == 0


def main():
    """Função principal — ponto de entrada do bot."""
    parser = argparse.ArgumentParser(
        description='🤖 Bot de Inteligência Econômica',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python main.py               Inicia o bot completo
  python main.py --coletar     Coleta dados agora
  python main.py --resumo      Gera e envia resumo agora
  python main.py --dashboard   Inicia o dashboard web
  python main.py --telegram    Inicia apenas o bot Telegram
  python main.py --teste       Testa conexões
        """
    )
    parser.add_argument('--coletar', action='store_true', help='Executa coleta imediata')
    parser.add_argument('--resumo', action='store_true', help='Gera e envia resumo imediato')
    parser.add_argument('--dashboard', action='store_true', help='Inicia o dashboard Streamlit')
    parser.add_argument('--telegram', action='store_true', help='Inicia apenas o bot Telegram')
    parser.add_argument('--teste', action='store_true', help='Testa conexões e dependências')
    parser.add_argument('--config', type=str, default=None, help='Caminho para config.yaml alternativo')

    args = parser.parse_args()

    # Carrega configuração e inicia logging
    config = load_config(args.config)
    logger = setup_logging(config)

    # Inicializa banco de dados
    db = Database()

    # === Modo: Teste ===
    if args.teste:
        success = testar_conexoes(config, logger)
        sys.exit(0 if success else 1)

    # === Modo: Coleta imediata ===
    if args.coletar:
        executar_coleta(config, db, logger)
        sys.exit(0)

    # === Modo: Resumo imediato ===
    if args.resumo:
        executar_coleta(config, db, logger)
        executar_analise_e_envio(config, db, logger)
        sys.exit(0)

    # === Modo: Dashboard ===
    if args.dashboard:
        iniciar_dashboard(config, logger)
        input("Pressione Enter para encerrar o dashboard...\n")
        sys.exit(0)

    # === Modo: Apenas Telegram ===
    if args.telegram:
        iniciar_telegram(config, db, logger)
        sys.exit(0)

    # === Modo: Completo (padrão) ===
    logger.info("🚀 Iniciando bot em modo completo...")

    # 1. Inicia agendamento
    scheduler = iniciar_agendamento(config, db, logger)

    # 2. Inicia dashboard em background
    try:
        iniciar_dashboard(config, logger)
    except Exception as e:
        logger.warning(f"Dashboard não pôde ser iniciado: {e}")

    # 3. Executa primeira coleta
    logger.info("📥 Executando coleta inicial...")
    executar_coleta(config, db, logger)

    # 4. Inicia bot Telegram (bloqueante — mantém o programa rodando)
    from notifications.telegram_bot import TelegramBot
    try:
        if TelegramBot(config, db).is_configured():
            logger.info("📱 Iniciando bot Telegram (modo polling)...")
            iniciar_telegram(config, db, logger)
        else:
            logger.warning("⚠️ Telegram não configurado — rodando só agendador + dashboard. Ctrl+C para sair.")
            while True:
                time.sleep(60)
    except KeyboardInterrupt:
        logger.info("⏹️ Bot encerrado pelo usuário.")
    finally:
        scheduler.shutdown()
        logger.info("👋 Bot de Inteligência Econômica encerrado. Até amanhã!")


if __name__ == '__main__':
    main()
