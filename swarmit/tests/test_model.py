import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from swarmit.testbed.model import (
    AwareDateTime,
    Base,
    JWTRecord,
    create_prevent_overlap_trigger,
)


@pytest.fixture(scope="function")
def db_session():
    """Creates an isolated in-memory SQLite DB with triggers installed."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(bind=engine)

    # Recreate schema
    Base.metadata.create_all(bind=engine)

    # Recreate triggers
    with engine.connect() as conn:
        create_prevent_overlap_trigger(conn)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_aware_datetime_assigns_utc_on_bind():
    """Ensure AwareDateTime coerces naive datetimes to UTC."""
    naive = datetime.datetime(2024, 1, 1, 12, 0, 0)
    aware = AwareDateTime().process_bind_param(naive, None)
    assert aware.tzinfo == datetime.timezone.utc


def test_aware_datetime_process_result_value(db_session):
    """Ensure process_result_value adds UTC tzinfo when DB returns naive datetime."""
    start = datetime.datetime(
        2024, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc
    )
    end = datetime.datetime(2024, 1, 1, 13, 0, 0, tzinfo=datetime.timezone.utc)

    rec = JWTRecord(jwt="abc123", date_start=start, date_end=end)
    db_session.add(rec)
    db_session.commit()

    fetched = db_session.query(JWTRecord).filter_by(jwt="abc123").first()

    # SQLite returns naive datetime → process_result_value should add UTC
    assert fetched.date_start.tzinfo == datetime.timezone.utc
    assert fetched.date_end.tzinfo == datetime.timezone.utc


def test_insert_non_overlapping_ranges(db_session):
    start1 = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    end1 = datetime.datetime(2024, 1, 2, tzinfo=datetime.timezone.utc)

    start2 = datetime.datetime(2024, 1, 3, tzinfo=datetime.timezone.utc)
    end2 = datetime.datetime(2024, 1, 4, tzinfo=datetime.timezone.utc)

    rec1 = JWTRecord(jwt="token1", date_start=start1, date_end=end1)
    rec2 = JWTRecord(jwt="token2", date_start=start2, date_end=end2)

    db_session.add(rec1)
    db_session.add(rec2)
    db_session.commit()

    assert db_session.query(JWTRecord).count() == 2


def test_insert_overlapping_fails(db_session):
    start1 = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    end1 = datetime.datetime(2024, 1, 5, tzinfo=datetime.timezone.utc)

    start2 = datetime.datetime(2024, 1, 4, tzinfo=datetime.timezone.utc)
    end2 = datetime.datetime(2024, 1, 10, tzinfo=datetime.timezone.utc)

    rec1 = JWTRecord(jwt="token1", date_start=start1, date_end=end1)
    db_session.add(rec1)
    db_session.commit()

    rec2 = JWTRecord(jwt="token2", date_start=start2, date_end=end2)
    db_session.add(rec2)

    with pytest.raises(Exception) as excinfo:
        db_session.commit()

    assert "Overlapping date range detected" in str(excinfo.value)


def test_update_to_overlapping_fails(db_session):
    # First record
    rec1 = JWTRecord(
        jwt="token1",
        date_start=datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
        date_end=datetime.datetime(2024, 1, 3, tzinfo=datetime.timezone.utc),
    )
    # Second record
    rec2 = JWTRecord(
        jwt="token2",
        date_start=datetime.datetime(2024, 1, 5, tzinfo=datetime.timezone.utc),
        date_end=datetime.datetime(2024, 1, 7, tzinfo=datetime.timezone.utc),
    )

    db_session.add(rec1)
    db_session.add(rec2)
    db_session.commit()

    # Attempt to update rec2 to overlap rec1
    rec2.date_start = datetime.datetime(
        2024, 1, 2, tzinfo=datetime.timezone.utc
    )
    rec2.date_end = datetime.datetime(2024, 1, 6, tzinfo=datetime.timezone.utc)

    with pytest.raises(Exception) as excinfo:
        db_session.commit()

    assert "Overlapping date range detected" in str(excinfo.value)


def test_update_non_overlapping_succeeds(db_session):
    # Initial records
    rec1 = JWTRecord(
        jwt="token1",
        date_start=datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
        date_end=datetime.datetime(2024, 1, 3, tzinfo=datetime.timezone.utc),
    )
    rec2 = JWTRecord(
        jwt="token2",
        date_start=datetime.datetime(2024, 1, 4, tzinfo=datetime.timezone.utc),
        date_end=datetime.datetime(2024, 1, 6, tzinfo=datetime.timezone.utc),
    )

    db_session.add(rec1)
    db_session.add(rec2)
    db_session.commit()

    # Adjust rec2 but still non-overlapping
    rec2.date_start = datetime.datetime(
        2024, 1, 7, tzinfo=datetime.timezone.utc
    )
    rec2.date_end = datetime.datetime(2024, 1, 8, tzinfo=datetime.timezone.utc)

    db_session.commit()  # Should not raise

    assert db_session.query(JWTRecord).count() == 2
