import os, uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, Boolean, DateTime, ForeignKey, Float, Uuid
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

# Monta a URL por partes (aceita caracteres especiais na senha, ex: !#@)
DATABASE_URL = os.getenv("DATABASE_URL") or URL.create(
    "postgresql+psycopg2",
    username=os.getenv("POSTGRES_USER", "sistema"),
    password=os.getenv("POSTGRES_PASSWORD", "sistema"),
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=5432,
    database=os.getenv("POSTGRES_DB", "sistema"),
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

def now(): return datetime.now(timezone.utc)

class Base(DeclarativeBase): pass

class Usuario(Base):
    __tablename__ = "usuarios"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(Text)
    cidade: Mapped[str] = mapped_column(String(80))
    uf: Mapped[str] = mapped_column(String(2))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    rua: Mapped[str | None] = mapped_column(String(160), nullable=True)
    numero: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bairro: Mapped[str | None] = mapped_column(String(100), nullable=True)
    perfil: Mapped[str] = mapped_column(String(12), default="aluno")  # aluno | professor | admin

class Curso(Base):
    __tablename__ = "cursos"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    titulo: Mapped[str] = mapped_column(String(160))
    descricao: Mapped[str] = mapped_column(Text, default="")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    aulas: Mapped[list["Aula"]] = relationship(back_populates="curso")

class Aula(Base):
    __tablename__ = "aulas"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    curso_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cursos.id"))
    titulo: Mapped[str] = mapped_column(String(160))
    descricao: Mapped[str] = mapped_column(Text, default="")
    conteudo: Mapped[str] = mapped_column(Text, default="")  # HTML sanitizado
    tipo: Mapped[str] = mapped_column(String(10), default="aula")  # aula | culto
    video_url: Mapped[str] = mapped_column(Text)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)
    curso: Mapped[Curso] = relationship(back_populates="aulas")

class LogVisualizacao(Base):
    __tablename__ = "logs_visualizacao"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"))
    aula_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("aulas.id"))
    assistiu: Mapped[bool] = mapped_column(Boolean, default=True)
    acessado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    usuario: Mapped[Usuario] = relationship()
    aula: Mapped[Aula] = relationship()

class Pergunta(Base):
    """Pergunta de um aluno ao pastor sobre uma aula/culto (assincrona: o pastor responde depois)."""
    __tablename__ = "perguntas"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), index=True)
    aula_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("aulas.id"), index=True)
    texto: Mapped[str] = mapped_column(Text)
    resposta: Mapped[str | None] = mapped_column(Text, nullable=True)
    respondida_por_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    respondida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visto: Mapped[bool] = mapped_column(Boolean, default=False)  # aluno ja viu a resposta?
    usuario: Mapped[Usuario] = relationship(foreign_keys=[usuario_id])
    respondida_por: Mapped[Usuario | None] = relationship(foreign_keys=[respondida_por_id])
    aula: Mapped[Aula] = relationship()
