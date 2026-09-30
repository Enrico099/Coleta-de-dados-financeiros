import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import datetime
import os
import sys

# Adicionar o diretório raiz ao PYTHONPATH para poder importar os módulos locais
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import Database
from database.models import Cotacao, Noticia, PostSocial, IndicadorEconomico, ResumoDiario
from utils.helpers import load_config
from analysis.summarizer import format_price
from analysis.trend_detector import TrendDetector

# Configuração da página
st.set_page_config(
    page_title="📊 Painel de Inteligência Econômica",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilo customizado
st.markdown("""
    <style>
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 15px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
    }
    .sentiment-positive { color: green; }
    .sentiment-neutral { color: gray; }
    .sentiment-negative { color: red; }
    </style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_db():
    config = load_config()
    return Database(), config

@st.cache_data(ttl=300)
def load_data(start_date, end_date):
    db, config = get_db()
    with db.session_scope() as session:
        # Load Cotacoes
        cotacoes_query = session.query(Cotacao).filter(Cotacao.collected_at >= start_date, Cotacao.collected_at <= end_date).all()
        df_cotacoes = pd.DataFrame([{
            'id': c.id, 'symbol': c.symbol, 'name': c.name, 'tipo': c.tipo,
            'price': c.price, 'previous_close': c.previous_close, 'variation_percent': c.variation_percent,
            'high': c.high, 'low': c.low, 'volume': c.volume, 'collected_at': c.collected_at
        } for c in cotacoes_query])

        # Load Noticias
        noticias_query = session.query(Noticia).filter(Noticia.collected_at >= start_date, Noticia.collected_at <= end_date).all()
        df_noticias = pd.DataFrame([{
            'id': n.id, 'title': n.title, 'source': n.source, 'url': n.url,
            'published_at': n.published_at, 'sentiment_score': n.sentiment_score,
            'sentiment_label': n.sentiment_label, 'collected_at': n.collected_at
        } for n in noticias_query])

        # Load Posts Sociais
        posts_query = session.query(PostSocial).filter(PostSocial.collected_at >= start_date, PostSocial.collected_at <= end_date).all()
        df_posts = pd.DataFrame([{
            'id': p.id, 'platform': p.platform, 'author': p.author, 'content': p.content,
            'likes': p.likes, 'sentiment_score': p.sentiment_score,
            'sentiment_label': p.sentiment_label, 'collected_at': p.collected_at,
            'post_url': p.post_url
        } for p in posts_query])

        # Load Indicadores
        indicadores_query = session.query(IndicadorEconomico).all()
        df_indicadores = pd.DataFrame([{
            'id': i.id, 'name': i.name, 'code': i.code, 'value': i.value,
            'reference_date': i.reference_date, 'collected_at': i.collected_at
        } for i in indicadores_query])

    return df_cotacoes, df_noticias, df_posts, df_indicadores, config

def get_sentiment_emoji(label):
    if label == 'positivo': return '🟢'
    if label == 'negativo': return '🔴'
    return '🟡'

def main():
    # Sidebar
    st.sidebar.title("📊 Inteligência Econômica")

    today = datetime.datetime.now()
    default_start = today - datetime.timedelta(days=30)

    start_date = st.sidebar.date_input("Data Inicial", default_start)
    end_date = st.sidebar.date_input("Data Final", today)

    # Adicionando a hora para o final do dia
    end_date_full = datetime.datetime.combine(end_date, datetime.time(23, 59, 59))
    start_date_full = datetime.datetime.combine(start_date, datetime.time(0, 0, 0))

    if st.sidebar.button("Atualizar Dados"):
        st.cache_data.clear()

    st.sidebar.markdown(f"*Última atualização: {today.strftime('%d/%m/%Y %H:%M')}*")

    # Load data
    df_cotacoes, df_noticias, df_posts, df_indicadores, config = load_data(start_date_full, end_date_full)
    pos_thr = config.get('analysis', {}).get('sentiment_threshold_positive', 0.05)
    neg_thr = config.get('analysis', {}).get('sentiment_threshold_negative', -0.05)
    for df in (df_noticias, df_posts):
        if not df.empty:
            df['sentiment_score'] = df['sentiment_score'].fillna(0.0)

    # 1. KPI Cards Row
    st.header("Resumo de Mercado")
    col1, col2, col3, col4, col5 = st.columns(5)

    def get_latest_quote(symbol):
        if not df_cotacoes.empty:
            df_sym = df_cotacoes[df_cotacoes['symbol'] == symbol]
            if not df_sym.empty:
                return df_sym.sort_values('collected_at', ascending=False).iloc[0]
        return None

    def fmt_delta(v):
        return f"{v:+.2f}%" if v is not None and pd.notna(v) else None

    ibov = get_latest_quote('^BVSP')
    usd = get_latest_quote('BRL=X')
    btc = get_latest_quote('BTC-USD')

    selic_val = "N/A"
    if not df_indicadores.empty:
        selic_df = df_indicadores[df_indicadores['name'].str.contains('Selic', case=False, na=False)]
        if not selic_df.empty:
            selic_val = f"{selic_df.sort_values('collected_at', ascending=False).iloc[0]['value']:.2f}% a.a."

    with col1:
        if ibov is not None:
            st.metric("IBOVESPA", format_price(ibov['symbol'], ibov['tipo'], ibov['price']), fmt_delta(ibov['variation_percent']))
        else:
            st.metric("IBOVESPA", "Sem dados", "0%")

    with col2:
        if usd is not None:
            st.metric("Dólar", format_price(usd['symbol'], usd['tipo'], usd['price']), fmt_delta(usd['variation_percent']))
        else:
            st.metric("Dólar", "Sem dados", "0%")

    with col3:
        if btc is not None:
            st.metric("Bitcoin", format_price(btc['symbol'], btc['tipo'], btc['price']), fmt_delta(btc['variation_percent']))
        else:
            st.metric("Bitcoin", "Sem dados", "0%")

    with col4:
        st.metric("Taxa Selic", selic_val)

    with col5:
        # Calcular sentimento geral
        overall_sentiment = "Neutro"
        emoji = "🟡"
        if not df_noticias.empty:
            mean_score = df_noticias['sentiment_score'].mean()
            if mean_score >= pos_thr:
                overall_sentiment = "Otimista"
                emoji = "🟢"
            elif mean_score <= neg_thr:
                overall_sentiment = "Pessimista"
                emoji = "🔴"
        st.metric("Sentimento de Mercado", f"{emoji} {overall_sentiment}")

    st.divider()

    # Filtros para gráficos
    if not df_cotacoes.empty:
        ativos_disponiveis = df_cotacoes['symbol'].unique().tolist()
        nomes = df_cotacoes.drop_duplicates('symbol').set_index('symbol')['name'].to_dict()
        ativos_selecionados = st.sidebar.multiselect(
            "Ativos", ativos_disponiveis, default=ativos_disponiveis[:3],
            format_func=lambda s: f"{nomes.get(s, s)} ({s})")
        modo_grafico = st.sidebar.radio("Gráfico de preços", ["Variação % (base 100)", "Preço absoluto"])
    else:
        ativos_selecionados = []

    # 2. Price Charts
    st.header("Análise de Preços")
    if not df_cotacoes.empty and ativos_selecionados:
        fig = go.Figure()

        normalizar = modo_grafico.startswith("Variação")
        for ativo in ativos_selecionados:
            df_ativo = df_cotacoes[df_cotacoes['symbol'] == ativo].sort_values('collected_at').copy()
            # Uma cotação por dia (a última coletada)
            df_ativo['dia'] = pd.to_datetime(df_ativo['collected_at']).dt.normalize()
            df_ativo = df_ativo.groupby('dia', as_index=False).last()
            df_ativo['collected_at'] = df_ativo['dia']
            if normalizar and not df_ativo.empty:
                df_ativo['price'] = df_ativo['price'] / df_ativo['price'].iloc[0] * 100

            fig.add_trace(go.Scatter(
                x=df_ativo['collected_at'],
                y=df_ativo['price'],
                mode='lines',
                name=nomes.get(ativo, ativo)
            ))

            # Médias móveis
            if len(df_ativo) >= 7:
                df_ativo['MA7'] = df_ativo['price'].rolling(window=7).mean()
                fig.add_trace(go.Scatter(
                    x=df_ativo['collected_at'],
                    y=df_ativo['MA7'],
                    line=dict(dash='dash'),
                    name=f'{nomes.get(ativo, ativo)} MM7'
                ))
            if len(df_ativo) >= 30:
                df_ativo['MA30'] = df_ativo['price'].rolling(window=30).mean()
                fig.add_trace(go.Scatter(
                    x=df_ativo['collected_at'],
                    y=df_ativo['MA30'],
                    line=dict(dash='dot'),
                    name=f'{nomes.get(ativo, ativo)} MM30'
                ))

        fig.update_layout(title="Evolução de Preços" + (" (base 100)" if normalizar else ""), height=500)
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("Nenhum dado de cotação disponível para o período selecionado.")

    st.divider()

    # 3. Sentiment Analysis
    st.header("Análise de Sentimento")
    col_sent1, col_sent2 = st.columns(2)

    with col_sent1:
        if not df_noticias.empty:
            mean_score = df_noticias['sentiment_score'].mean()
            fig_gauge = go.Figure(go.Indicator(
                mode = "gauge+number",
                value = mean_score,
                domain = {'x': [0, 1], 'y': [0, 1]},
                title = {'text': "Sentimento Geral (Notícias)"},
                gauge = {
                    'axis': {'range': [-1, 1]},
                    'bar': {'color': "darkblue"},
                    'steps': [
                        {'range': [-1, neg_thr], 'color': "lightcoral"},
                        {'range': [neg_thr, pos_thr], 'color': "lightgray"},
                        {'range': [pos_thr, 1], 'color': "lightgreen"}
                    ]
                }
            ))
            st.plotly_chart(fig_gauge, width='stretch')
        else:
            st.info("Sem dados de notícias para sentimento.")

    with col_sent2:
        if not df_noticias.empty:
            sent_by_source = df_noticias.groupby('source')['sentiment_score'].mean().reset_index()
            sent_by_source = sent_by_source.sort_values('sentiment_score')
            fig_bar = px.bar(sent_by_source, x='sentiment_score', y='source', orientation='h',
                             title='Sentimento Médio por Fonte', labels={'sentiment_score': 'Score', 'source': ''},
                             color='sentiment_score', color_continuous_scale='RdYlGn', range_color=[-0.5, 0.5])
            st.plotly_chart(fig_bar, width='stretch')

    st.divider()

    # 4. News Feed & 5. Social Media Posts
    col_feed1, col_feed2 = st.columns(2)

    with col_feed1:
        st.subheader("Notícias Recentes")
        if not df_noticias.empty:
            noticias_recentes = df_noticias.sort_values('published_at', ascending=False).head(10)
            for _, row in noticias_recentes.iterrows():
                with st.expander(f"{get_sentiment_emoji(row['sentiment_label'])} {row['title']} ({row['source']})"):
                    st.markdown(f"**Data:** {row['published_at']}")
                    st.markdown(f"**Sentimento Score:** {row['sentiment_score']:.2f}")
                    if pd.notna(row['url']):
                        st.markdown(f"[Ler notícia completa]({row['url']})")
        else:
            st.info("Nenhuma notícia recente encontrada.")

    with col_feed2:
        st.subheader("Redes Sociais")
        if not df_posts.empty:
            tab1, tab2 = st.tabs(["LinkedIn", "Instagram"])
            with tab1:
                df_linkedin = df_posts[df_posts['platform'].str.lower() == 'linkedin']
                if not df_linkedin.empty:
                    for _, row in df_linkedin.sort_values('collected_at', ascending=False).head(5).iterrows():
                        st.markdown(f"**{row['author']}** {get_sentiment_emoji(row['sentiment_label'])}")
                        st.write(f"{str(row['content'])[:150]}...")
                        st.caption(f"[ver post]({row['post_url']}) | Coletado: {row['collected_at']:%d/%m %H:%M}")
                        st.divider()
                else:
                    st.write("Sem posts no LinkedIn")

            with tab2:
                df_insta = df_posts[df_posts['platform'].str.lower() == 'instagram']
                if not df_insta.empty:
                    for _, row in df_insta.sort_values('collected_at', ascending=False).head(5).iterrows():
                        st.markdown(f"**{row['author']}** {get_sentiment_emoji(row['sentiment_label'])}")
                        st.write(f"{str(row['content'])[:150]}...")
                        st.caption(f"❤️ {row['likes']} | Data: {row['collected_at']}")
                        st.divider()
                else:
                    st.write("Sem posts no Instagram")
        else:
            st.info("Nenhum post social encontrado.")

    st.divider()

    # 6. Word Cloud
    st.header("Nuvem de Palavras")
    text = ""
    if not df_noticias.empty:
        text += " ".join(df_noticias['title'].dropna().tolist())
    if not df_posts.empty:
        text += " ".join(df_posts['content'].dropna().tolist())

    if text:
        stopwords_pt = ['de', 'a', 'o', 'que', 'e', 'do', 'da', 'em', 'um', 'para', 'é', 'com', 'não', 'uma', 'os', 'no', 'se', 'na', 'por', 'mais', 'as', 'dos', 'como', 'mas', 'foi', 'ao', 'ele', 'das', 'tem', 'à', 'seu', 'sua', 'ou', 'ser', 'quando', 'muito', 'há', 'nos', 'já', 'está', 'eu', 'também', 'só', 'pelo', 'pela', 'até', 'isso', 'ela', 'entre', 'era', 'depois', 'sem', 'mesmo', 'aos', 'ter', 'seus', 'quem', 'nas', 'me', 'esse', 'eles', 'estão', 'você', 'tinha', 'foram', 'essa', 'num', 'nem', 'suas', 'meu', 'às', 'minha', 'têm', 'numa', 'pelos', 'elas', 'havia', 'seja', 'qual', 'será', 'nós', 'tenho', 'lhe', 'deles', 'essas', 'esses', 'pelas', 'este', 'fosse', 'dele', 'tu', 'te', 'vocês', 'vos', 'lhes', 'meus', 'minhas', 'teu', 'tua', 'teus', 'tuas', 'nosso', 'nossa', 'nossos', 'nossas', 'dela', 'delas', 'esta', 'estes', 'estas', 'aquele', 'aquela', 'aqueles', 'aquelas', 'isto', 'aquilo', 'estou', 'está', 'estamos', 'estão', 'estive', 'esteve', 'estivemos', 'estiveram', 'estava', 'estávamos', 'estavam', 'estivera', 'estivéramos', 'esteja', 'estejamos', 'estejam', 'estivesse', 'estivéssemos', 'estivessem', 'estiver', 'estivermos', 'estiverem', 'hei', 'há', 'havemos', 'hão', 'houve', 'houvemos', 'houveram', 'houvera', 'houvéramos', 'haja', 'hajamos', 'hajam', 'houvesse', 'houvéssemos', 'houvessem', 'houver', 'houvermos', 'houverem', 'houverei', 'houverá', 'houveremos', 'houverão', 'houveria', 'houveríamos', 'houveriam', 'sou', 'somos', 'são', 'era', 'éramos', 'eram', 'fui', 'foi', 'fomos', 'foram', 'fora', 'fôramos', 'seja', 'sejamos', 'sejam', 'fosse', 'fôssemos', 'fossem', 'for', 'formos', 'forem', 'serei', 'será', 'seremos', 'serão', 'seria', 'seríamos', 'seriam', 'tenho', 'tem', 'temos', 'tém', 'tinha', 'tínhamos', 'tinham', 'tive', 'teve', 'tivemos', 'tiveram', 'tivera', 'tivéramos', 'tenha', 'tenhamos', 'tenham', 'tivesse', 'tivéssemos', 'tivessem', 'tiver', 'tivermos', 'tiverem', 'terei', 'terá', 'teremos', 'terão', 'teria', 'teríamos', 'teriam']

        stopwords_pt = set(stopwords_pt) | {'sobre', 'após', 'diz', 'ano', 'anos', 'hoje', 'the', 'and', 'of', 'to', 'in', 'for', 'on', 'is', 'linkedin', 'r'}
        wordcloud = WordCloud(width=800, height=400, background_color='white', stopwords=stopwords_pt,
                              collocations=False, colormap='viridis').generate(text)

        fig_wc, ax_wc = plt.subplots(figsize=(10, 5))
        ax_wc.imshow(wordcloud, interpolation='bilinear')
        ax_wc.axis('off')
        st.pyplot(fig_wc)
    else:
        st.info("Texto insuficiente para gerar a nuvem de palavras.")

    st.divider()

    # 7. Economic Indicators
    st.header("Indicadores Econômicos")
    if not df_indicadores.empty:
        # Group by name and get the latest
        latest_indicadores = df_indicadores.sort_values('collected_at', ascending=False).drop_duplicates(subset=['code'])
        st.dataframe(
            latest_indicadores[['name', 'value', 'reference_date']].rename(
                columns={'name': 'Indicador', 'value': 'Valor', 'reference_date': 'Data de referência'}),
            hide_index=True, width='stretch')
    else:
        st.info("Sem dados de indicadores econômicos.")

    st.divider()

    # 8. Tendências
    st.header("Tendências (7 dias)")
    db, _ = get_db()
    tendencias = TrendDetector(config).detect_all_trends(db)
    if tendencias:
        df_t = pd.DataFrame(tendencias)
        seta = {'alta': '📈 alta', 'baixa': '📉 baixa', 'lateral': '➡️ lateral'}
        df_t['trend'] = df_t['trend'].map(seta)
        st.dataframe(
            df_t[['name', 'trend', 'change_percent', 'volatility_percent', 'min_price', 'max_price', 'current_price']]
            .rename(columns={'name': 'Ativo', 'trend': 'Tendência', 'change_percent': 'Var. 7d (%)',
                             'volatility_percent': 'Volatilidade (%)', 'min_price': 'Mínimo',
                             'max_price': 'Máximo', 'current_price': 'Atual'}),
            hide_index=True, width='stretch')
    else:
        st.info("Sem dados suficientes para tendências.")

if __name__ == "__main__":
    main()
