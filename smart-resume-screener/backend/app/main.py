"""
main.py
--------
FastAPI application exposing the Smart Resume Screener API.

Endpoints:
  POST /resumes/upload        -> upload one resume (PDF/txt), parses + extracts structured data
  GET  /resumes                -> list all parsed candidates
  POST /jobs                   -> create a job description
  GET  /jobs                   -> list job descriptions
  POST /match                  -> run LLM matching for a JD against candidates
  GET  /jobs/{job_id}/matches  -> get ranked, shortlisted candidates for a job

Run with:  uvicorn app.main:app --reload

--------------------------------------------------------------------------
FIXED (this pass):
--------------------------------------------------------------------------
- /match no longer aborts the ENTIRE batch when a single candidate's LLM
  call fails. Previously, one bad response (malformed JSON, a transient
  Gemini error, a safety-filtered empty response, etc.) raised an
  HTTPException mid-loop, which killed the whole request -- even though
  matches for candidates processed *before* the failure had already been
  committed to the DB. The frontend only renders that one response, so a
  single failure looked like "matching ran but showed zero results,"
  even when most candidates actually scored successfully.
  Now each candidate is scored in its own try/except: failures are logged
  and skipped, successes are still returned, and the response includes
  which candidates (if any) failed so you can see it in the UI/console.
- /match now deletes any previous Match rows for this job before inserting
  new ones, so re-running "Match All Candidates" doesn't pile up duplicate
  rows for the same candidate/job pair.
- Added logging so failures are visible in the uvicorn terminal, not just
  swallowed into an HTTP error string.
"""

import logging
import time
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List

from . import database, schemas
from .resume_parser import extract_text_from_upload
from .llm_matcher import extract_structured_data, score_resume_against_jd

logger = logging.getLogger("main")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Smart Resume Screener")

# Allow the frontend (served separately) to call this API during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

database.init_db()


@app.post("/resumes/upload", response_model=schemas.CandidateOut)
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    file_bytes = await file.read()

    try:
        raw_text = extract_text_from_upload(file.filename, file_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        structured = extract_structured_data(raw_text)
    except Exception as e:
        logger.exception("LLM extraction failed for %s", file.filename)
        raise HTTPException(status_code=502, detail=f"LLM extraction failed: {e}")

    candidate = database.Candidate(
        filename=file.filename,
        raw_text=raw_text,
        name=structured.get("name"),
        email=structured.get("email"),
        phone=structured.get("phone"),
        skills=", ".join(structured.get("skills") or []),
        experience_years=structured.get("experience_years"),
        education=structured.get("education"),
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


@app.get("/resumes", response_model=List[schemas.CandidateOut])
def list_resumes(db: Session = Depends(database.get_db)):
    return db.query(database.Candidate).all()


@app.post("/jobs", response_model=schemas.JobDescriptionOut)
def create_job(job: schemas.JobDescriptionIn, db: Session = Depends(database.get_db)):
    jd = database.JobDescription(title=job.title, raw_text=job.raw_text)
    db.add(jd)
    db.commit()
    db.refresh(jd)
    return jd


@app.post("/jobs/upload", response_model=schemas.JobDescriptionOut)
async def upload_job(
    title: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
):
    """
    Alternative to POST /jobs: lets the recruiter attach a JD as a
    PDF/txt file instead of pasting text. Reuses the same text-extraction
    logic as resume uploads.
    """
    file_bytes = await file.read()
    try:
        raw_text = extract_text_from_upload(file.filename, file_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    jd = database.JobDescription(title=title, raw_text=raw_text)
    db.add(jd)
    db.commit()
    db.refresh(jd)
    return jd


@app.get("/jobs", response_model=List[schemas.JobDescriptionOut])
def list_jobs(db: Session = Depends(database.get_db)):
    return db.query(database.JobDescription).all()


@app.post("/match", response_model=List[schemas.MatchOut])
def run_matching(req: schemas.MatchRequest, db: Session = Depends(database.get_db)):
    job = db.query(database.JobDescription).filter(database.JobDescription.id == req.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job description not found")

    query = db.query(database.Candidate)
    if req.candidate_ids:
        query = query.filter(database.Candidate.id.in_(req.candidate_ids))
    candidates = query.all()

    if not candidates:
        raise HTTPException(status_code=404, detail="No candidates found to match")

    db.query(database.Match).filter(database.Match.job_id == job.id).delete()
    db.commit()

    results = []
    failures = []

    for candidate in candidates:
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                result = score_resume_against_jd(candidate.raw_text, job.raw_text)
                
                match = database.Match(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    score=result.get("score", 0),
                    justification=result.get("justification", ""),
                )
                db.add(match)
                db.commit()
                db.refresh(match)

                results.append(schemas.MatchOut(
                    id=match.id,
                    candidate_id=candidate.id,
                    job_id=job.id,
                    score=match.score,
                    justification=match.justification,
                    candidate_name=candidate.name,
                    candidate_filename=candidate.filename,
                ))
                
                time.sleep(2) 
                break

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    if attempt < max_retries - 1:
                        # Increased to 60 seconds to safely clear the API's minute-based quota
                        logger.warning(f"Rate limited on {candidate.filename}. Waiting 60s before retry {attempt + 1}...")
                        time.sleep(60)
                        continue
                
                logger.exception("LLM scoring failed for %s", candidate.filename)
                failures.append({"candidate": candidate.filename, "error": error_str})
                break

    if failures:
        logger.warning("%d/%d candidates failed scoring for job %s: %s",
                        len(failures), len(candidates), job.id, failures)

    if not results and failures:
        raise HTTPException(
            status_code=502,
            detail=f"LLM scoring failed for all {len(failures)} candidate(s). "
                   f"First error: {failures[0]['error']}",
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return results


@app.get("/jobs/{job_id}/matches", response_model=List[schemas.MatchOut])
def get_matches_for_job(job_id: int, db: Session = Depends(database.get_db)):
    matches = (
        db.query(database.Match)
        .filter(database.Match.job_id == job_id)
        .order_by(desc(database.Match.score))
        .all()
    )
    out = []
    for m in matches:
        out.append(schemas.MatchOut(
            id=m.id,
            candidate_id=m.candidate_id,
            job_id=m.job_id,
            score=m.score,
            justification=m.justification,
            candidate_name=m.candidate.name,
            candidate_filename=m.candidate.filename,
        ))
    return out

@app.delete("/resumes/{candidate_id}")
def delete_resume(candidate_id: int, db: Session = Depends(database.get_db)):
    # 1. First, delete any AI matches tied to this resume to prevent database errors
    db.query(database.Match).filter(database.Match.candidate_id == candidate_id).delete()
    
    # 2. Find the candidate
    candidate = db.query(database.Candidate).filter(database.Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    
    # 3. Delete the resume
    db.delete(candidate)
    db.commit()
    
    return {"status": "success", "detail": f"Deleted resume for {candidate.name or candidate.filename}"}


@app.get("/")
def root():
    return {"status": "ok", "service": "Smart Resume Screener API"}