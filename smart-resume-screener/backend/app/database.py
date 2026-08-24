"""
database.py
------------
SQLite database setup using SQLAlchemy ORM.

Tables:
  - candidates : one row per uploaded resume, holds extracted structured data
  - job_descriptions : one row per JD the recruiter pastes/uploads
  - matches : one row per (candidate, job_description) pair with score + justification
"""

from sqlalchemy import create_engine, Column, Integer, String, Text, Float, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

DATABASE_URL = "sqlite:///./resume_screener.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    raw_text = Column(Text, nullable=False)

    # Structured fields extracted by the LLM
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    skills = Column(Text, nullable=True)          # stored as comma-separated string
    experience_years = Column(Float, nullable=True)
    education = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    matches = relationship("Match", back_populates="candidate")


class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    raw_text = Column(Text, nullable=False)
    required_skills = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    matches = relationship("Match", back_populates="job")


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"))
    job_id = Column(Integer, ForeignKey("job_descriptions.id"))

    score = Column(Float, nullable=False)          # 1-10 fit score from LLM
    justification = Column(Text, nullable=False)   # LLM's reasoning
    created_at = Column(DateTime, default=datetime.utcnow)

    candidate = relationship("Candidate", back_populates="matches")
    job = relationship("JobDescription", back_populates="matches")


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
