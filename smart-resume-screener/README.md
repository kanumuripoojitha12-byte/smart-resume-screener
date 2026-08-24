# Smart Resume Screener

Parses resumes (PDF/Text), extracts structured candidate data using an LLM,
and semantically matches candidates against a job description with a 1-10
fit score and justification.

## Architecture

```
                    ┌─────────────────────┐
                    │   Frontend (HTML)    │
                    │  index.html + JS     │
                    └──────────┬───────────┘
                               │ REST (fetch)
                               ▼
                    ┌─────────────────────┐
                    │   FastAPI Backend    │
                    │      (main.py)       │
                    ├─────────────────────┤
   PDF/txt file --> │ resume_parser.py     │ --> raw text
                    │ llm_matcher.py        │ --> LLM calls (extraction + scoring)
                    │ database.py           │ --> SQLite (SQLAlchemy ORM)
                    └──────────┬───────────┘
                               ▼
                    ┌─────────────────────┐
                    │  Anthropic Claude API │
                    └─────────────────────┘
```

**Flow:**
1. Recruiter uploads a resume (PDF/txt) → `resume_parser.py` extracts raw text.
2. Raw text is sent to Claude with a structured-extraction prompt → returns
   JSON (name, skills, experience, education) → stored in `candidates` table.
3. Recruiter either pastes JD text (`POST /jobs`) or attaches a JD file —
   PDF/txt (`POST /jobs/upload`, reuses the same parser as resumes) → stored
   in `job_descriptions` table.
4. Recruiter clicks "Match" → for every candidate, resume text + JD text are
   sent to Claude with a scoring prompt → returns `{score, justification}` →
   stored in `matches` table.
5. Frontend fetches matches, sorted by score descending → this ranked list
   **is** the shortlist.

## Technologies Used

| Layer | Technology | Why |
|---|---|---|
| Backend API | FastAPI (Python) | Async, auto-generates OpenAPI docs at `/docs`, minimal boilerplate |
| PDF parsing | pdfplumber | Reliable text extraction from PDF resumes |
| LLM | Anthropic Claude (`claude-sonnet-4-6`) | Structured extraction + semantic scoring |
| Database | SQLite + SQLAlchemy ORM | Zero-config, swappable for Postgres later |
| Frontend | Vanilla HTML/CSS/JS | No build step, easy to demo; swap for React if desired |

## LLM Prompts Used

### 1. Structured Extraction Prompt (`llm_matcher.extract_structured_data`)
System prompt instructs Claude to act as a resume-parsing engine and return
**only JSON** matching a fixed schema (name, email, phone, skills,
experience_years, education). This replaces brittle regex-based parsing —
resumes come in wildly inconsistent formats, and an LLM reading raw text
generalizes far better.

### 2. Match Scoring Prompt (`llm_matcher.score_resume_against_jd`)
Directly implements the assignment's example prompt: *"Compare the following
resume with this job description and rate fit on 1-10 with justification."*
Extended to also return `matched_skills` and `missing_skills` arrays so the
dashboard can show *why* a candidate scored the way they did — this is what
the assignment calls "output clarity."

Both prompts force strict JSON output so the API layer never has to guess
at parsing free-form text.

## Setup & Run

```bash
# 1. Backend
cd backend
python -m venv venv && source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env        # then add your ANTHROPIC_API_KEY inside .env
uvicorn app.main:app --reload --port 8000

# 2. Frontend
# just open frontend/index.html in a browser (double-click it),
# or serve it: python -m http.server 5500 -d frontend
```

Test with the sample files in `sample_data/`:
- Upload `sample_data/sample_resume.txt` via the dashboard.
- Paste the contents of `sample_data/sample_jd.txt` as a job description.
- Click "Match All Candidates" and see the ranked shortlist appear.

API docs (auto-generated): `http://localhost:8000/docs`

## Suggested Enhancements (stretch goals)
- OCR fallback (`pytesseract`) for scanned/image-based PDF resumes.
- Bulk resume upload (zip file → loop through).
- Auth so multiple recruiters have separate candidate pools.
- Deploy backend on Render/Railway, frontend on Vercel/Netlify, for the demo video.
- Add a `/resumes/{id}` detail view showing the full extracted profile.

## Deliverables Checklist (per assignment)
- [x] GitHub repo with commits — push this folder, commit incrementally (init → parser → LLM → API → frontend)
- [x] README with architecture & LLM prompts — this file
- [ ] 2-3 min demo video — record after running the flow above end-to-end
