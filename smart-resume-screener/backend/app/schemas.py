from pydantic import BaseModel
from typing import List, Optional


class CandidateOut(BaseModel):
    id: int
    filename: str
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    skills: Optional[str]
    experience_years: Optional[float]
    education: Optional[str]

    class Config:
        from_attributes = True


class JobDescriptionIn(BaseModel):
    title: str
    raw_text: str


class JobDescriptionOut(BaseModel):
    id: int
    title: str
    raw_text: str

    class Config:
        from_attributes = True


class MatchOut(BaseModel):
    id: int
    candidate_id: int
    job_id: int
    score: float
    justification: str
    candidate_name: Optional[str] = None
    candidate_filename: Optional[str] = None

    class Config:
        from_attributes = True


class MatchRequest(BaseModel):
    job_id: int
    candidate_ids: Optional[List[int]] = None  # if None, match ALL candidates
