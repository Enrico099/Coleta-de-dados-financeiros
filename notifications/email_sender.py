import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import logging
from datetime import datetime
from jinja2 import Template

from utils.helpers import get_env

logger = logging.getLogger(__name__)

EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; padding: 20px; color: #222;">
<div style="max-width: 720px; margin: auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 0 10px rgba(0,0,0,0.1);">
  <div style="background-color: #1a237e; color: white; padding: 20px; text-align: center;">
    <h2 style="margin: 0;">📊 Resumo Econômico</h2>
    <p style="margin: 6px 0 0;">{{ date }}</p>
  </div>

  <div style="padding: 20px;">
    <h3 style="color: #1a237e; border-bottom: 2px solid #1a237e; padding-bottom: 5px;">Resumo do Dia</h3>
    <p><strong>Sentimento geral:</strong> {{ sentiment_emoji }} {{ sentiment_label|capitalize }} ({{ "%+.2f"|format(sentiment_score) }})</p>
    <p>{{ summary_text }}</p>

    {% if indicators %}
    <h3 style="color: #1a237e; border-bottom: 2px solid #1a237e; padding-bottom: 5px;">🏦 Indicadores (BCB)</h3>
    <table style="width: 100%; border-collapse: collapse;">
      {% for ind in indicators %}
      <tr style="border-bottom: 1px solid #eee;">
        <td style="padding: 6px;">{{ ind.name }}</td>
        <td style="padding: 6px; text-align: right;"><strong>{{ ind.value_fmt }}</strong></td>
        <td style="padding: 6px; text-align: right; color: #777; font-size: 12px;">{{ ind.reference_date }}</td>
      </tr>
      {% endfor %}
    </table>
    {% endif %}

    {% if assets %}
    <h3 style="color: #1a237e; border-bottom: 2px solid #1a237e; padding-bottom: 5px;">💰 Cotações</h3>
    <table style="width: 100%; border-collapse: collapse;">
      {% for a in assets %}
      <tr style="border-bottom: 1px solid #eee;">
        <td style="padding: 6px;">{{ a.name }}</td>
        <td style="padding: 6px; text-align: right;">{{ a.price_fmt }}</td>
        <td style="padding: 6px; text-align: right; font-weight: bold; color: {{ '#2e7d32' if (a.variation or 0) >= 0 else '#c62828' }};">
          {{ '▲' if (a.variation or 0) >= 0 else '▼' }} {{ "%.2f"|format((a.variation or 0)|abs) }}%
        </td>
      </tr>
      {% endfor %}
    </table>
    {% endif %}

    {% if trends %}
    <h3 style="color: #1a237e; border-bottom: 2px solid #1a237e; padding-bottom: 5px;">📐 Tendências (7 dias)</h3>
    <ul>
      {% for t in trends %}
      <li>{{ t.emoji }} <strong>{{ t.name }}</strong>: {{ t.trend }} ({{ "%+.2f"|format(t.change_percent) }}%), volatilidade {{ "%.2f"|format(t.volatility_percent) }}%</li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if news %}
    <h3 style="color: #1a237e; border-bottom: 2px solid #1a237e; padding-bottom: 5px;">📰 Destaques</h3>
    <ul>
      {% for n in news %}
      <li style="margin-bottom: 6px;">{{ n.emoji }} <a href="{{ n.url }}" style="color: #1a237e;">{{ n.title }}</a> <span style="color: #777;">— {{ n.source }}</span></li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if elections %}
    <h3 style="color: #1a237e; border-bottom: 2px solid #1a237e; padding-bottom: 5px;">🗳️ Eleições <span style="font-size: 13px; color: #777; font-weight: normal;">({{ elections_total }} notícias nas últimas 24h)</span></h3>
    <ul>
      {% for n in elections %}
      <li style="margin-bottom: 6px;"><a href="{{ n.url }}" style="color: #1a237e;">{{ n.title }}</a> <span style="color: #777;">— {{ n.source }}</span></li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if posts %}
    <h3 style="color: #1a237e; border-bottom: 2px solid #1a237e; padding-bottom: 5px;">💬 Redes Sociais</h3>
    {% for p in posts %}
    <p style="margin: 8px 0;"><strong>{{ p.author }}</strong> <span style="color: #777;">({{ p.platform }})</span><br>{{ p.content }}
      {% if p.url %}<br><a href="{{ p.url }}" style="color: #1a237e; font-size: 12px;">ver post</a>{% endif %}</p>
    {% endfor %}
    {% endif %}
  </div>

  <div style="text-align: center; font-size: 12px; color: #777; padding: 15px; border-top: 1px solid #ddd;">
    <p>E-mail gerado automaticamente pelo Bot de Inteligência Econômica.</p>
    <p>As informações contidas aqui não são recomendações de investimento.</p>
  </div>
</div>
</body>
</html>
"""


class EmailSender:
    def __init__(self, config: dict):
        """Inicializa o disparador de e-mails."""
        self.config = config
        self.server = get_env('EMAIL_SMTP_SERVER', '')
        self.port = get_env('EMAIL_SMTP_PORT', '587')
        self.sender = get_env('EMAIL_SENDER', '')
        self.password = get_env('EMAIL_PASSWORD', '')
        self.recipients = get_env('EMAIL_RECIPIENTS', '')

    def is_configured(self) -> bool:
        """True se as credenciais foram preenchidas (e não são os placeholders do .env.example)."""
        placeholders = ('seu_email', 'sua_senha', 'destinatario1')
        valores = [self.server, self.sender, self.password, self.recipients]
        return all(valores) and not any(p in v for v in valores for p in placeholders)

    def _connect(self) -> smtplib.SMTP:
        port = int(self.port)
        if port == 465:
            server = smtplib.SMTP_SSL(self.server, port, timeout=20)
        else:
            server = smtplib.SMTP(self.server, port, timeout=20)
            server.starttls()
        server.login(self.sender, self.password)
        return server

    def test_connection(self) -> bool:
        """Testa a conexão SMTP."""
        if not self.is_configured():
            logger.error("Credenciais de email incompletas no .env.")
            return False
        try:
            with self._connect():
                pass
            return True
        except Exception as e:
            logger.error(f"Erro ao testar conexão SMTP: {e}")
            return False

    def _send_email(self, subject: str, html_body: str, attachments: list = None) -> bool:
        """Função de baixo nível para envio de e-mail."""
        if not self.is_configured():
            logger.error("E-mail não configurado no .env — envio ignorado.")
            return False

        msg = MIMEMultipart('related')
        msg['Subject'] = subject
        msg['From'] = self.sender
        msg['To'] = self.recipients

        msg_alternative = MIMEMultipart('alternative')
        msg.attach(msg_alternative)
        msg_alternative.attach(MIMEText(html_body, 'html', 'utf-8'))

        for att in attachments or []:
            image = MIMEImage(att['data'])
            image.add_header('Content-ID', f"<{att['cid']}>")
            msg.attach(image)

        try:
            with self._connect() as server:
                server.send_message(msg)
            logger.info("Email enviado com sucesso.")
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar email: {e}")
            return False

    def build_html(self, email_data: dict) -> str:
        """Constrói o HTML do email a partir de DailySummarizer.format_email_data()."""
        return Template(EMAIL_TEMPLATE).render(**email_data)

    def send_daily_report(self, summary: dict) -> bool:
        """Envia o relatório diário por email."""
        from analysis.summarizer import DailySummarizer

        email_data = DailySummarizer(self.config).format_email_data(summary)
        if not email_data:
            logger.error("Resumo vazio — e-mail não enviado.")
            return False

        sent = summary.get('sentimento', {})
        subject = (f"📊 Resumo Econômico {summary.get('data', datetime.now().strftime('%d/%m/%Y'))} — "
                   f"mercado {sent.get('label', 'neutro')}")
        return self._send_email(subject, self.build_html(email_data))
