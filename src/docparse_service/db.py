from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class ParseTask(Base):
    __tablename__ = "parse_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(64), nullable=False)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    engine: Mapped[str] = mapped_column(String(32), nullable=False, default="mineru")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    result_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    markdown_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_list_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    middle_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    images_prefix: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    if database_url.startswith("sqlite:///"):
        db_path = database_url.removeprefix("sqlite:///")
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
