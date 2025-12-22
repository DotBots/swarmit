import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    TypeDecorator,
    create_engine,
    text,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class AwareDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return value


class JWTRecord(Base):
    __tablename__ = "jwt_records"

    id_ = Column(Integer, primary_key=True, index=True)
    jwt = Column(String, unique=True, nullable=False)
    date_start = Column(AwareDateTime, nullable=False)
    date_end = Column(AwareDateTime, nullable=False)


def create_db_engine(url: str) -> Engine:
    return create_engine(url, connect_args={"check_same_thread": False})


def create_session_factory(engine: Engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_prevent_overlap_trigger(conn: Connection):
    conn.execute(
        text(
            """
        CREATE TRIGGER IF NOT EXISTS prevent_overlap
        BEFORE INSERT ON jwt_records
        FOR EACH ROW
        BEGIN
            SELECT CASE
                WHEN EXISTS (
                    SELECT 1 FROM jwt_records
                    WHERE NEW.date_start < date_end
                    AND NEW.date_end > date_start
                )
                THEN RAISE (ABORT, 'Overlapping date range detected')
            END;
        END;
    """
        )
    )
    conn.execute(
        text(
            """
        CREATE TRIGGER IF NOT EXISTS prevent_overlap_update
        BEFORE UPDATE ON jwt_records
        FOR EACH ROW
        BEGIN
            SELECT CASE
                WHEN EXISTS (
                    SELECT 1 FROM jwt_records
                    WHERE id_ != OLD.id_
                    AND NEW.date_start < date_end
                    AND NEW.date_end > date_start
                )
                THEN RAISE (ABORT, 'Overlapping date range detected')
            END;
        END;
    """
        )
    )
