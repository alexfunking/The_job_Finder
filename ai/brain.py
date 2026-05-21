"""
Phase 3: The Brain Module (Groq Edition)
Evaluates job descriptions using Groq's high-speed API to determine relevance.
"""
import os
import json
import re
import time
import logging
from pathlib import Path
import PyPDF2
from groq import Groq

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CV extraction
# ---------------------------------------------------------------------------
_CACHED_CV_TEXT = None

def extract_text_from_pdf(pdf_path: str) -> str:
    global _CACHED_CV_TEXT
    if _CACHED_CV_TEXT is not None:
        return _CACHED_CV_TEXT

    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            parts = []
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    parts.append(extracted)
            _CACHED_CV_TEXT = "\n".join(parts)
            return _CACHED_CV_TEXT
    except Exception as e:
        logger.error("Error reading CV PDF: %s", e)
        # fallback
        return (
            "Alexander Kozakevich - Data Engineering Student at Bar-Ilan University. "
            "Looking for Student, Internship, Junior, or Entry-Level roles in Data Engineering, "
            "Data Analysis, Python Development, Software Engineering, or similar tech fields."
        )


def _get_cv_text() -> str:
    return extract_text_from_pdf(os.path.join(os.path.dirname(__file__), "..", "AlexanderKozakevichCV.pdf"))


def _get_priorities_text() -> str:
    priorities_path = os.path.join(os.path.dirname(__file__), "..", "priorities.txt")
    try:
        if os.path.exists(priorities_path):
            with open(priorities_path, 'r', encoding='utf-8') as f:
                return f.read()
    except Exception as e:
        logger.error("Error reading priorities file: %s", e)
    return ""


def _build_system_prompt(cv_text: str, priorities_text: str) -> str:
    """Construct the AI system prompt tailored to Alex's profile."""
    return f"""
You are an AI job evaluator helping Alex find his first tech job.

--- ALEX'S PROFILE ---
{cv_text}

--- PRIORITIES ---
{priorities_text}

You MUST evaluate each job against the STRICT criteria provided in the PRIORITIES section above.
The PRIORITIES are the absolute source of truth.

When assigning a `match_score`, you MUST follow the priority tiers explicitly defined in the PRIORITIES text.
For example, if it's a student position, it MUST receive a score in the 95-100 range.
If a job violates ANY "REJECT" rule (e.g. 4+ days on-site, requires 3+ years experience, wrong location), you MUST set `is_relevant` to false and `match_score` to 0.

Be exceptionally strict with "REJECT" rules. If you are unsure about experience requirements but it feels senior, reject it.
"""


# Cache expensive prompt building
_CACHED_SYSTEM_PROMPT = None


def _get_system_prompt() -> str:
    global _CACHED_SYSTEM_PROMPT
    if _CACHED_SYSTEM_PROMPT is not None:
        return _CACHED_SYSTEM_PROMPT

    cv_text = _get_cv_text()
    priorities_text = _get_priorities_text()
    _CACHED_SYSTEM_PROMPT = _build_system_prompt(cv_text, priorities_text)
    return _CACHED_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Groq client singleton
# ---------------------------------------------------------------------------
_GROQ_CLIENT = None


def _get_groq_client() -> Groq:
    global _GROQ_CLIENT
    if _GROQ_CLIENT is not None:
        return _GROQ_CLIENT

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set.")
    _GROQ_CLIENT = Groq(api_key=api_key)
    return _GROQ_CLIENT


def _build_user_prompt(job_details: dict) -> str:
    return f"""Evaluate this job posting:

Job Title: {job_details.get('title', 'N/A')}
Company: {job_details.get('company', 'N/A')}
Location: {job_details.get('location', 'Not specified')}
Description: {job_details.get('description', '')}

Respond ONLY with a valid JSON object exactly following this schema (no markdown, no code blocks, no extra text):
{{"is_relevant": true/false, "match_score": integer(0-100), "summary": "string", "location": "string", "key_features": "string", "important_qualifications": "string"}}
"""


def evaluate_job(job_details: dict) -> dict:
    """
    Uses Groq (Llama 3.1 8B) to evaluate a job description based on Alex's profile.
    Retries indefinitely on rate limit (429).
    """
    client = _get_groq_client()
    system_prompt = _get_system_prompt()

    attempt = 0
    max_wait_seconds = 180  # cap backoff to avoid hanging forever

    while True:
        attempt += 1
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": _build_user_prompt(job_details)}
                ],
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"}
            )

            raw = chat_completion.choices[0].message.content or ""
            evaluation = json.loads(raw)

            # Defensive: enforce numeric types
            evaluation["match_score"] = int(evaluation.get("match_score", 0))
            evaluation["is_relevant"] = bool(evaluation.get("is_relevant", False))
            return evaluation

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("[Groq Brain] Malformed JSON response (attempt %d): %s", attempt, e)
            if attempt >= 2:
                # Give up after a few malformed responses
                logger.error("[Groq Brain] JSON decode failed repeatedly. Returning safe default.")
                return {"is_relevant": False, "match_score": 0, "summary": "Error: invalid JSON from AI."}
            time.sleep(1)

        except Exception as e:
            error_msg = str(e)
            is_rate_limit = (
                "429" in error_msg
                or "rate limit" in error_msg.lower()
                or "RateLimitError" in type(e).__name__
            )

            if is_rate_limit:
                # Parse wait hint from error message
                wait = 10
                m = re.search(r'try again in (\d+\.?\d*)s', error_msg)
                if m:
                    wait = float(m.group(1)) + 1.0
                else:
                    m = re.search(r'try again in (\d+)m(\d+\.?\d*)s', error_msg)
                    if m:
                        wait = int(m.group(1)) * 60 + float(m.group(2)) + 2.0
                wait = max(1.0, min(wait, max_wait_seconds))
                logger.info(
                    "[Groq Brain] Rate limit hit. Waiting %.1fs to retry... (attempt %d)",
                    wait, attempt
                )
                time.sleep(wait)
            else:
                logger.error("[Groq Brain] Unrecoverable error evaluating job: %s", e)
                return {
                    "is_relevant": False,
                    "match_score": 0,
                    "summary": f"Error evaluating job: {e}"
                }

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    
    # quick sanity test
    result = evaluate_job({
        "title": "Junior Python Developer (Student)",
        "company": "TechCorp",
        "location": "Tel Aviv, Israel",
        "description": "Looking for a student Python developer with SQL skills. 0-1 years experience. Hybrid (2 days/week in office)."
    })
    print(json.dumps(result, indent=2))
