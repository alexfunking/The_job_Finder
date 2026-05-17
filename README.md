# The Job Finder: AI-Powered Job Hunter

An automated, intelligent system that acts as your personal job-hunting assistant. It scrapes job boards, evaluates roles based on your specific CV and priorities using Google Gemini AI, manages your applications in a Kanban board, tracks your progress via email, and sends daily summaries directly to your WhatsApp.

## 🌟 Comprehensive Feature List

### 1. Automated Job Scraping (`scraper.py`)
- **Daily Scans:** Automatically searches specific job platforms (like LinkedIn or Glassdoor) for relevant roles.
- **De-duplication:** Ensures you never see the same job twice by tracking processed URLs.

### 2. AI-Powered Evaluation "The Brain" (`brain.py`)
- **CV Matching:** Reads your personal CV (PDF format) and evaluates how well your skills match a job description.
- **Priority Consideration:** Reads a custom `priorities.txt` file to heavily weigh your personal preferences (e.g., location, tech stack, salary).
- **Intelligent Summarization:** Uses Gemini 2.5 Flash to generate a match score (0-100), extract key features, highlight important qualifications, and provide a 1-2 sentence summary of *why* the job is a good fit.

### 3. Interactive Kanban Dashboard (`dashboard.py`)
- **Visual Pipeline:** A Streamlit-based Kanban board to visualize your application pipeline.
- **Minimalistic UI:** Clean cards displaying the Job Title, Company, Important Qualifications, and Key Features. Less critical details are tucked behind a "Show more" expander.
- **Drag-and-Drop State:** Easily move jobs between stages: "To Apply", "In Process", "Declined", and "Irrelevant".
- **Sub-stages:** Track granular progress for jobs "In Process" (e.g., HR Screen, Tech Interview, Home Assignment, Offer).

### 4. Automated AI Email Tracking (`email_tracker.py`)
- **Inbox Integration:** Securely connects to your Gmail via IMAP to monitor incoming emails.
- **Smart Matching:** Automatically identifies emails from companies you are actively tracking in your dashboard.
- **AI Classification:** Uses Gemini to read the email and determine its intent (e.g., is this a rejection, a tech interview invite, or just an automated receipt?).
- **Auto-updating Kanban:** Automatically moves the job to the correct stage on your dashboard based on the email's content, completely hands-free.

### 5. WhatsApp Notifications (`notifier.py`)
- **Daily Digests:** Sends a daily batch summary of all high-scoring job matches directly to your WhatsApp using Twilio.
- **Actionable Links:** Includes direct links to the job postings so you can apply immediately from your phone.

### 6. Orchestrator & Database (`main.py` & `database.py`)
- **SQLite Persistence:** Uses a lightweight local database to store all job data, evaluations, and current stages.
- **Automated Scheduler:** The `main.py` script orchestrates the entire flow: checking emails for updates, scraping new jobs, evaluating them, and sending notifications. Runs on a daily schedule.

---

## 🛠️ Setup Instructions

### Prerequisites
- Python 3.10+
- Playwright browsers installed
- Google Gemini API key
- Twilio account (for WhatsApp API)
- Gmail account with 2-Step Verification and an App Password

### 1. Install Dependencies
```bash
pip install -r requirements.txt
playwright install
```

### 2. Configure Environment Variables
Create a `.env` file in the root directory and add the following keys:

```env
# AI
GEMINI_API_KEY=your_gemini_api_key

# WhatsApp Notifications (Twilio)
TWILIO_SID=your_twilio_account_sid
TWILIO_TOKEN=your_twilio_auth_token
TWILIO_FROM_PHONE=whatsapp:+14155238886 # Example twilio number
TARGET_PHONE_NUMBER=whatsapp:+1234567890 # Your number

# AI Email Tracking (Gmail)
EMAIL_ACCOUNT=your_email@gmail.com
EMAIL_PASSWORD=your_16_letter_app_password
```

### 3. Personalize the AI
- Replace `AlexanderKozakevichCV.pdf` with your own CV PDF.
- Edit `priorities.txt` to state exactly what you are looking for in your next role.

### 4. Run the Application

**To view the Dashboard:**
```bash
streamlit run dashboard.py
```

**To start the automated background worker (Scraping + Email Tracking + Notifications):**
```bash
python main.py
```

## Hardware & Automation Setup
- You can set up a Windows Task Scheduler task to run `main.py` daily in the background.
- Alternatively, you can use the provided `JobFinder_Background.vbs` script to run the orchestrator silently.
