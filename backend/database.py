from decouple import config
from sqlmodel import create_engine, Session

DATABASE_URL = config("DATABASE_URL")
engine = create_engine(DATABASE_URL)

def get_db():
    with Session(engine) as session:
        yield session
