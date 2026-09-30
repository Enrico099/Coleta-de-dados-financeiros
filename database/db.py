"""
Gerenciador de conexão com o banco de dados SQLite.
"""
import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from .models import Base
from utils.helpers import load_config, project_path

logger = logging.getLogger(__name__)


class Database:
    """Gerencia a conexão e sessões do banco de dados SQLite."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = load_config()['database']['path']
        db_path = project_path(db_path)

        # Garante que o diretório existe
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self.db_path = db_path
        self.engine = create_engine(
            f'sqlite:///{db_path}',
            echo=False,
            connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(self.engine)
        self._SessionFactory = sessionmaker(bind=self.engine, expire_on_commit=False)
        logger.info(f"Banco de dados inicializado em: {db_path}")

    def get_session(self):
        """Retorna uma nova sessão do banco."""
        return self._SessionFactory()

    @contextmanager
    def session_scope(self):
        """Context manager para sessões com commit/rollback automático."""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def add_record(self, record):
        """Adiciona um registro ao banco."""
        with self.session_scope() as session:
            session.add(record)
            return record

    def add_records(self, records: list):
        """Adiciona múltiplos registros ao banco."""
        with self.session_scope() as session:
            session.add_all(records)
            return records

    def query(self, model, **filters):
        """Query simples com filtros."""
        with self.session_scope() as session:
            q = session.query(model)
            for key, value in filters.items():
                q = q.filter(getattr(model, key) == value)
            return q.all()
