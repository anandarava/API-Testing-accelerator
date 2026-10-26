from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


def _make_engine(url):
    if not url.startswith('sqlite'):
        return create_engine(url, pool_pre_ping=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30})

    @event.listens_for(engine, 'connect')
    def _sqlite_pragmas(connection, _):
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.close()

    return engine


engine = _make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db():
    from . import models  # noqa: F401  (register tables)
    Base.metadata.create_all(engine)
    add_missing_columns()


def add_missing_columns():
    """Add columns that newer versions define to tables an older version created (create_all only adds tables)."""
    existing = inspect(engine)
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if not existing.has_table(table.name):
                continue
            present = {column['name'] for column in existing.get_columns(table.name)}
            for column in table.columns:
                if column.name in present or column.primary_key:
                    continue
                default = column.default.arg if column.default is not None and not callable(column.default.arg) else None
                sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(engine.dialect)}'
                if isinstance(default, (str, int, float, bool)):
                    sql += ' DEFAULT ' + (repr(default) if isinstance(default, str) else str(int(default) if isinstance(default, bool) else default))
                connection.execute(text(sql))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
