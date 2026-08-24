import os
import json
import re
import logging
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

logger = logging.getLogger("llm_matcher")
logging.basicConfig(level=logging.INFO)

_API_KEY = os.environ.get("GEMINI_API_KEY")
if not _API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not set. Create a .env file next to this module "
        "(or export the env var) with:\n\n"
        "    GEMINI_API_KEY=your_key_here\n\n"
        "Get a key from https://aistudio.google.com/apikey"
    )

client = genai.Client(api_key=_API_KEY)

# Use the required model version
MODEL = "gemini-3.6-flash"


def _clean_json_response(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate_json = cleaned[start:end + 1]
        try:
            return json.loads(candidate_json)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Could not parse JSON from LLM response after fallback extraction: {e}\n"
                f"Raw response was:\n{raw[:1000]}"
            ) from e

    raise ValueError(f"No JSON object found in LLM response. Raw response was:\n{raw[:1000]}")


def _extract_text(response) -> str:
    if not response.candidates:
        feedback = getattr(response, "prompt_feedback", None)
        raise RuntimeError(f"Gemini returned no candidates at all. prompt_feedback={feedback}")

    candidate = response.candidates[0]
    if candidate.finish_reason == "MAX_TOKENS":
        raise RuntimeError(
            "Gemini response was cut off before finishing (hit max_output_tokens)."
        )
    if candidate.finish_reason not in ("STOP", None) and not response.text:
        raise RuntimeError(
            f"Gemini did not return usable text. finish_reason={candidate.finish_reason}"
        )
    if not response.text:
        raise RuntimeError(f"Gemini returned no text. finish_reason={candidate.finish_reason}")
    return response.text


def extract_structured_data(resume_text: str) -> dict:
    system_prompt = (
        "You are a resume-parsing engine. You will be given raw resume text. "
        "Extract structured information and respond with ONLY valid JSON, "
        "no preamble, no markdown fences, no commentary. "
        "JSON schema:\n"
        "{\n"
        '  "name": string,\n'
        '  "email": string or null,\n'
        '  "phone": string or null,\n'
        '  "skills": [string, ...],\n'
        '  "experience_years": number (total professional experience, estimate if needed),\n'
        '  "education": string (highest degree + institution, one line)\n'
        "}\n"
        "If a field cannot be found, use null (or an empty list for skills)."
    )

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=f"Resume text:\n\n{resume_text}",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=2048,
                response_mime_type="application/json",
            ),
        )
    except Exception as e:
        logger.exception("Gemini call failed in extract_structured_data")
        raise RuntimeError(f"Gemini API call failed during extraction: {e}") from e

    raw_text = _extract_text(response)
    try:
        return _clean_json_response(raw_text)
    except ValueError:
        logger.error("Failed to parse extraction JSON. Raw text was: %s", raw_text[:1000])
        raise


def score_resume_against_jd(resume_text: str, jd_text: str) -> dict:
    system_prompt = (
        "You are an expert technical recruiter. Compare a candidate's resume "
        "against a job description and rate the fit on a scale of 1-10 "
        "(10 = excellent fit). Consider skills overlap, years of relevant "
        "experience, and education/domain relevance. Be honest and specific — "
        "do not inflate scores. Respond with ONLY valid JSON, no markdown fences:\n"
        "{\n"
        '  "score": number (1-10, can be decimal e.g. 7.5),\n'
        '  "justification": string (2-4 sentences explaining the score),\n'
        '  "matched_skills": [string, ...],\n'
        '  "missing_skills": [string, ...]\n'
        "}"
    )

    user_prompt = (
        f"Job Description:\n{jd_text}\n\n"
        f"---\n\n"
        f"Candidate Resume:\n{resume_text}\n\n"
        "Compare the resume with this job description and rate fit on 1-10 "
        "with justification."
    )

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=2048,
                response_mime_type="application/json",
            ),
        )
    except Exception as e:
        logger.exception("Gemini call failed in score_resume_against_jd")
        raise RuntimeError(f"Gemini API call failed during scoring: {e}") from e

    raw_text = _extract_text(response)
    try:
        return _clean_json_response(raw_text)
    except ValueError:
        logger.error("Failed to parse scoring JSON. Raw text was: %s", raw_text[:1000])
        raise