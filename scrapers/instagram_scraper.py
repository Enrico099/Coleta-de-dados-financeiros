"""
Scraper para o Instagram usando a biblioteca instaloader.
"""
import instaloader
from datetime import datetime, timezone
from .base import BaseScraper
from database.db import Database
from database.models import PostSocial
from utils.helpers import safe_get, get_env

class InstagramScraper(BaseScraper):
    """Scraper para coletar posts públicos do Instagram."""
    
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.L = instaloader.Instaloader(
            quiet=True,
            max_connection_attempts=1,
            download_pictures=False,
            download_video_thumbnails=False,
            download_videos=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False
        )
        self._load_session()

    def _load_session(self):
        """
        O Instagram bloqueia quase todo acesso anônimo (HTTP 401/429).
        Para coletar de verdade, faça login UMA vez pelo terminal:
            .venv\\Scripts\\instaloader --login SEU_USUARIO
        e coloque INSTAGRAM_USERNAME=SEU_USUARIO no .env.
        A sessão fica salva pelo instaloader — a senha não é guardada no projeto.
        """
        username = get_env('INSTAGRAM_USERNAME', '')
        if not username:
            self.log_info("Instagram sem login (INSTAGRAM_USERNAME vazio) — acesso anônimo costuma ser bloqueado.")
            return
        try:
            self.L.load_session_from_file(username)
            self.log_info(f"Sessão do Instagram carregada para @{username}")
        except FileNotFoundError:
            self.log_error(f"Sessão de @{username} não encontrada. Rode: instaloader --login {username}")
        except Exception as e:
            self.log_error(f"Erro ao carregar sessão do Instagram: {e}")
        
    def collect(self, db: Database) -> dict:
        """Coleta os posts dos perfis configurados e salva no banco de dados."""
        perfis = safe_get(self.config, 'instagram', 'perfis', default=[])
        max_posts = safe_get(self.config, 'instagram', 'max_posts_por_perfil', default=5)
        delay = safe_get(self.config, 'instagram', 'delay_entre_perfis', default=10)
        
        collected_posts = []
        falhas = 0

        with db.session_scope() as session:
            for i, perfil in enumerate(perfis):
                self.log_info(f"Iniciando coleta do perfil: {perfil}")
                try:
                    profile = instaloader.Profile.from_username(self.L.context, perfil)
                    posts = profile.get_posts()
                    
                    count = 0
                    for post in posts:
                        if count >= max_posts:
                            break
                            
                        post_url = f"https://www.instagram.com/p/{post.shortcode}/"
                        
                        # Verifica duplicidade
                        if session.query(PostSocial).filter(PostSocial.post_url == post_url).first():
                            self.log_info(f"Post {post_url} já existe no banco de dados. Ignorando.")
                            count += 1
                            continue
                            
                        # Extrai hashtags do texto (aproximação simples)
                        hashtags = ",".join([word.strip("#") for word in (post.caption or "").split() if word.startswith("#")])
                        
                        novo_post = PostSocial(
                            platform='instagram',
                            author=perfil,
                            content=post.caption or "",
                            hashtags=hashtags,
                            likes=post.likes,
                            comments_count=post.comments,
                            post_url=post_url,
                            post_date=post.date_utc,
                            collected_at=datetime.now(timezone.utc)
                        )
                        session.add(novo_post)
                        collected_posts.append(novo_post)
                        count += 1
                        
                except Exception as e:
                    falhas += 1
                    self.log_error(f"Erro ao coletar posts do perfil {perfil}: {e}")
                    # Instagram bloqueia acesso anônimo com frequência (401/429).
                    # Após 2 falhas sem nenhum sucesso, não insiste nos demais perfis.
                    if falhas >= 2 and not collected_posts:
                        self.log_error("Instagram está bloqueando o acesso anônimo — pulando os perfis restantes.")
                        break
                
                # Rate limit entre perfis, mas não depois do último
                if i < len(perfis) - 1:
                    self._wait(delay)
                    
        self.log_info(f"Coleta do Instagram finalizada. Total de novos posts: {len(collected_posts)}")
        return {'posts': len(collected_posts)}
