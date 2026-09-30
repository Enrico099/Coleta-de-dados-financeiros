# 🤖 Bot de Inteligência Econômica

Bot automatizado que coleta diariamente informações sobre economia mundial e investimentos de múltiplas fontes, analisa tendências e sentimento do mercado, e entrega resumos inteligentes via **Telegram** e **E-mail**, com um **dashboard visual** interativo.

## 📦 Instalação

```bash
# 1. Acesse o diretório do projeto
cd Coleta

# 2. Crie o ambiente virtual (o projeto usa .venv)
python -m venv .venv
.venv\Scripts\activate   # Windows

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Configure as credenciais
copy .env.example .env
# Edite o .env com seus tokens e senhas
```

> Sem ativar o venv, use `.venv\Scripts\python main.py ...` no lugar de `python main.py ...`.

## ⚙️ Configuração

### Telegram Bot
1. Fale com o [@BotFather](https://t.me/BotFather) no Telegram
2. Crie um novo bot com `/newbot`
3. Copie o token e cole no `.env` em `TELEGRAM_BOT_TOKEN`
4. Rode `python main.py --telegram` e mande `/start` para o bot — ele responde com o seu **chat ID**
5. Coloque esse número em `TELEGRAM_CHAT_ID` no `.env` (é para onde vai o resumo diário)

### E-mail (Gmail)
1. Ative a verificação em duas etapas na sua conta Google
2. Gere uma "Senha de App" em https://myaccount.google.com/apppasswords
3. Use essa senha no `.env` em `EMAIL_PASSWORD`

### Instagram (opcional)
O Instagram bloqueia acesso anônimo (erro 429). Para coletar os perfis:
1. Rode uma vez: `.venv\Scripts\instaloader --login SEU_USUARIO` (pede a senha e salva a sessão)
2. Coloque `INSTAGRAM_USERNAME=SEU_USUARIO` no `.env`

A senha não fica salva no projeto. De preferência, use uma conta secundária.

### Fontes de Dados
Edite o `config.yaml` para personalizar:
- Perfis do Instagram a monitorar
- Empresas do LinkedIn (slug de `linkedin.com/company/<slug>/` — posts públicos, sem login)
- Feeds RSS de notícias e termos de busca do Google News
- Ativos financeiros a rastrear (Yahoo Finance)
- Indicadores do Banco Central (códigos SGS)
- Horários do agendamento e intervalo de checagem dos alertas

### Como funciona
- **06:00** — coleta completa (cotações, BCB, notícias, LinkedIn, Instagram) + análise de sentimento
- **08:00** — gera o resumo e envia por Telegram e e-mail
- **A cada 60 min** — atualiza as cotações e dispara os alertas de preço
- Na primeira coleta de cada ativo o bot grava ~3 meses de histórico, então gráficos e tendências já funcionam no dia 1
- Sentimento: léxico financeiro em português + TextBlob para textos em inglês

## 🚀 Uso

```bash
# Modo completo (agendamento + Telegram + dashboard)
python main.py

# Executar apenas uma coleta
python main.py --coletar

# Coletar + gerar e enviar resumo
python main.py --resumo

# Iniciar apenas o dashboard web
python main.py --dashboard

# Iniciar apenas o bot Telegram
python main.py --telegram

# Testar conexões e dependências
python main.py --teste
```

## 📱 Comandos do Telegram

| Comando | Descrição |
|---------|-----------|
| `/start` | Boas-vindas + seu chat ID |
| `/resumo` | Resumo econômico do dia |
| `/cotacoes` | Cotações atualizadas |
| `/noticias` | Últimas notícias com sentimento |
| `/sentimento` | Sentimento do mercado (geral, por canal e por fonte) |
| `/grafico [ativo]` | Gráfico de 30 dias com média móvel (ex: `/grafico IBOV`) |
| `/tendencia [ativo]` | Tendência 7d, MM7/MM14 e leitura técnica simples |
| `/alertas` | Listar alertas ativos |
| `/alerta_criar [ativo] [acima/abaixo] [valor]` | Criar alerta (ex: `/alerta_criar DOLAR acima 5.80`) |
| `/alerta_remover [id]` | Remover um alerta |
| `/coletar` | Forçar uma coleta agora |
| `/fontes` | Fontes monitoradas |
| `/status` | Status do bot e do banco |
| `/ajuda` | Lista de comandos |

Ativos aceitos pelo nome curto: `IBOV`, `DOLAR`, `EURO`, `BTC`, `ETH`, `OURO`, `SP500`, `NASDAQ`, `PETR4`, `VALE3` (ou o símbolo do Yahoo, ex: `^BVSP`).

## 📊 Dashboard

Acesse `http://localhost:8501` após iniciar o dashboard.

Funcionalidades:
- KPIs (IBOV, Dólar, Bitcoin, Selic, sentimento)
- Gráficos interativos de cotações (preço absoluto ou variação base 100)
- Análise de sentimento com gauge e ranking por fonte
- Feed de notícias com sentimento
- Posts do LinkedIn e Instagram
- Nuvem de palavras
- Indicadores econômicos
- Tabela de tendências (7 dias)

## 🏗️ Estrutura

```
Coleta/
├── main.py                  # Ponto de entrada
├── config.yaml              # Configurações
├── .env                     # Credenciais (não versionar!)
├── requirements.txt         # Dependências
├── scrapers/                # Módulos de coleta
│   ├── base.py              # Classe base
│   ├── instagram_scraper.py # Instagram (instaloader)
│   ├── linkedin_scraper.py  # LinkedIn (páginas públicas de empresas)
│   ├── news_scraper.py      # Notícias (RSS + Google News)
│   └── finance_api.py       # Yahoo Finance + Banco Central
├── analysis/                # Análise inteligente
│   ├── sentiment.py         # Análise de sentimento
│   ├── trend_detector.py    # Tendências e alertas
│   └── summarizer.py        # Gerador de resumos
├── notifications/           # Canais de notificação
│   ├── telegram_bot.py      # Bot Telegram interativo
│   └── email_sender.py      # E-mail HTML
├── dashboard/               # Visualização
│   └── app.py               # Dashboard Streamlit
├── database/                # Persistência (SQLite em data/)
│   ├── models.py            # Modelos SQLAlchemy
│   └── db.py                # Conexão
└── utils/                   # Utilitários
    └── helpers.py
```

## 📄 Licença

Uso pessoal / educacional. As informações geradas não são recomendação de investimento.
