"""
Módulo base para todos os scrapers.
Define a classe abstrata BaseScraper.
"""
import time
import logging
from abc import ABC, abstractmethod
from typing import List, Any
from database.db import Database

class BaseScraper(ABC):
    """Classe base abstrata para scrapers."""

    def __init__(self, name: str, config: dict):
        """
        Inicializa o scraper.
        
        Args:
            name (str): Nome do scraper.
            config (dict): Configurações carregadas do config.yaml.
        """
        self.name = name
        self.config = config
        self.logger = logging.getLogger(f"scraper.{name}")

    @abstractmethod
    def collect(self, db: Database) -> List[Any]:
        """
        Método abstrato para coletar dados.
        
        Args:
            db (Database): Instância do banco de dados para salvar ou consultar registros.
            
        Returns:
            List[Any]: Lista de itens coletados.
        """
        pass

    def log_info(self, msg: str):
        """Registra uma mensagem de informação."""
        self.logger.info(msg)

    def log_error(self, msg: str):
        """Registra uma mensagem de erro."""
        self.logger.error(msg)

    def _wait(self, seconds: float):
        """
        Espera um determinado número de segundos para rate limiting.
        
        Args:
            seconds (float): Tempo em segundos para esperar.
        """
        self.log_info(f"Aguardando {seconds} segundos...")
        time.sleep(seconds)
