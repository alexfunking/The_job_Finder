"""
Phase 3: The Brain Module
Evaluates job descriptions using Google Gemini API to determine relevance.
"""
import os
import json
import PyPDF2
import google.generativeai as genai

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

def setup_gemini():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")
    genai.configure(api_key=api_key)

def evaluate_job(job_details: dict) -> dict:
    """
    Uses Gemini to evaluate a job description based on Alex's profile.
    Returns a dictionary with match_score, is_relevant, and summary.
    """
    setup_gemini()
    
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    You are an AI assistant helping Alex. 
    Here is Alex's CV:
    {CV_TEXT}
    
    Here are Alex's specific job search priorities:
    {PRIORITIES_TEXT}
    
    Evaluate the following job description for relevance. Focus on matching the job requirements to the skills and experience present in the CV, but heavily weigh Alex's explicitly stated priorities when calculating the match_score and determining relevance.
    
    Job Title: {job_details.get('title')}
    Company: {job_details.get('company')}
    Description: {job_details.get('description')}
    
    Return your response strictly as a JSON object with the following schema:
    {
        "is_relevant": true/false,
        "match_score": integer (0-100),
        "summary": "Short 1-2 sentence objective description of the job and what the role entails. DO NOT explain why it is a good fit for Alex, do not mention Alex, and do not mention his CV.",
        "location": "string (extract location if mentioned, e.g. 'Tel Aviv', 'Hybrid', 'Remote', else 'Not specified')",
        "key_features": "string (1 short sentence highlighting the most important requirements or perks)",
        "important_qualifications": "string (2-3 short bullet points of the most critical qualifications required)"
    }
    """
    
    try:
        response = model.generate_content(prompt)
        # Assuming the response is clean JSON. In production, might need to strip markdown JSON blocks.
        clean_text = response.text.strip('`').removeprefix('json\n')
        evaluation = json.loads(clean_text)
        return evaluation
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return {"is_relevant": False, "match_score": 0, "summary": "Error evaluating job."}
