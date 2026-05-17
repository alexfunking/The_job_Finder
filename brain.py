"""
Phase 3: The Brain Module (Groq Edition)
Evaluates job descriptions using Groq's high-speed API to determine relevance.
"""
import os
import json
import re
import time
import PyPDF2
from groq import Groq

def extract_text_from_pdf(pdf_path):
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            return text
    except Exception as e:
        print(f"Error reading CV PDF: {e}")
        return "Student looking for Junior/Student roles."

CV_TEXT = extract_text_from_pdf(os.path.join(os.path.dirname(__file__), "AlexanderKozakevichCV.pdf"))

def get_user_priorities():
    priorities_path = os.path.join(os.path.dirname(__file__), "priorities.txt")
    try:
        if os.path.exists(priorities_path):
            with open(priorities_path, 'r', encoding='utf-8') as file:
                return file.read()
    except Exception as e:
        print(f"Error reading priorities file: {e}")
    return "No specific priorities set."

PRIORITIES_TEXT = get_user_priorities()

def evaluate_job(job_details: dict) -> dict:
    """
    Uses Groq (Llama 3.3 70B) to evaluate a job description based on Alex's profile.
    Returns a dictionary with match_score, is_relevant, and summary.
    
    Retries indefinitely on rate limit / 429 limits using a smart wait.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set.")
    
    client = Groq(api_key=api_key)

    system_prompt = f"""
    You are an AI assistant helping Alex find a job. 
    Here is Alex's CV:
    {CV_TEXT}
    
    Here are Alex's specific job search priorities:
    {PRIORITIES_TEXT}
    
    Evaluate the following job description for relevance. Focus on matching the job requirements to the skills and experience present in the CV, but heavily weigh Alex's explicitly stated priorities when calculating the match_score and determining relevance.
    """

    user_prompt = f"""
    Job Title: {job_details.get('title')}
    Company: {job_details.get('company')}
    Description: {job_details.get('description')}
    
    Return your response strictly as a JSON object with the following schema:
    {{
        "is_relevant": true/false, // Set to true ONLY if match_score is 70 or higher
        "match_score": integer (0-100), // Assign high scores (80-100) to Student or Part-time roles matching skills, and lower scores to full-time junior positions.
        "summary": "Short 1-2 sentence objective description of the job and what the role entails. DO NOT explain why it is a good fit for Alex, do not mention Alex, and do not mention his CV.",
        "location": "string (extract location if mentioned, e.g. 'Tel Aviv', 'Hybrid', 'Remote', else 'Not specified')",
        "key_features": "string (1 short sentence highlighting the most important requirements or perks)",
        "important_qualifications": "string (2-3 short bullet points of the most critical qualifications required)"
    }}
    """

    attempt = 0
    while True:
        attempt += 1
        try:
            # We use Llama 3.1 8B Instant, which is super fast and has incredibly generous rate limits.
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"}
            )
            
            clean_text = chat_completion.choices[0].message.content.strip()
            evaluation = json.loads(clean_text)
            return evaluation

        except Exception as e:
            error_msg = str(e)
            # Standard HTTP 429 or Groq specific rate limit exception checking
            is_rate_limit = (
                "429" in error_msg 
                or "rate limit" in error_msg.lower() 
                or "RateLimitError" in type(e).__name__
            )
            
            if is_rate_limit:
                # Groq rate limit reset times are super fast (usually a few seconds)
                # We'll parse the headers if possible, or wait a safe 10 seconds.
                wait_seconds = 10
                
                # Check for Groq retry header info in error message
                match = re.search(r'try again in (\d+\.?\d*)s', error_msg)
                if match:
                    wait_seconds = float(match.group(1)) + 1.0  # add 1s buffer
                else:
                    match_min = re.search(r'try again in (\d+)m(\d+\.?\d*)s', error_msg)
                    if match_min:
                        wait_seconds = int(match_min.group(1)) * 60 + float(match_min.group(2)) + 2.0
                
                wait_seconds = max(1.0, wait_seconds) # prevent 0 or negative wait times
                print(f"  [Groq Brain] Rate limit hit. Waiting {wait_seconds:.1f}s to retry... (attempt {attempt})")
                time.sleep(wait_seconds)
            else:
                print(f"  [Groq Brain] Unrecoverable error evaluating job: {e}")
                return {"is_relevant": False, "match_score": 0, "summary": "Error evaluating job."}
