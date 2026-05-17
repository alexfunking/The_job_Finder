import streamlit as st
import database
import json
import ast

# Set page configuration to wide mode for a premium Kanban view
st.set_page_config(page_title="The Job Finder Dashboard", layout="wide")

# Custom HSL-based Dark Mode & Modern Theme CSS
st.markdown("""
<style>
    /* Premium card containers */
    .job-card {
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 12px;
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.04) 0%, rgba(255, 255, 255, 0.01) 100%);
        backdrop-filter: blur(10px);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
        transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
    }
    .job-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 30px rgba(0, 0, 0, 0.3);
        border-color: rgba(255, 255, 255, 0.18);
    }
    
    /* Header layout */
    .card-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 12px;
    }
    
    /* Job Title & Company */
    .job-title {
        font-size: 16px;
        font-weight: 700;
        color: #f8fafc;
        line-height: 1.35;
        margin: 0;
    }
    .company-name {
        font-size: 13px;
        font-weight: 500;
        color: #94a3b8;
        margin-top: 4px;
    }
    
    /* Premium Score Badge */
    .score-badge {
        background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
        color: white;
        font-size: 12px;
        font-weight: 700;
        padding: 4px 10px;
        border-radius: 20px;
        white-space: nowrap;
        box-shadow: 0 2px 8px rgba(59, 130, 246, 0.35);
    }
    .score-badge-high {
        background: linear-gradient(135deg, #10b981 0%, #047857 100%);
        box-shadow: 0 2px 8px rgba(16, 185, 129, 0.35);
    }
    
    /* Divider */
    .card-divider {
        height: 1px;
        background: rgba(255, 255, 255, 0.06);
        margin: 12px 0;
    }
</style>
""", unsafe_allow_html=True)

st.title("🎯 Job Finder Kanban Dashboard")

try:
    with open("last_update.txt", "r") as f:
        last_update = f.read().strip()
    st.info(f"🕒 Last updated: {last_update} (Updates automatically every 1 hour)")
except FileNotFoundError:
    st.info("🕒 Last updated: Not updated yet (Updates automatically every 1 hour)")

# Initialize DB on load to ensure migrations are run
database.init_db()

# --- Robust helper to format lists, dicts, and messy fields cleanly ---
def format_field(value):
    """
    Cleans up nested lists, dictionaries, or raw strings containing python
    literal representations, rendering them as beautifully formatted markdown bullet points.
    """
    if not value:
        return ""
    
    # If it's already structured as a list
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value if item)
        
    # If it's structured as a dictionary
    if isinstance(value, dict):
        for key in ['bullet_points', 'qualifications', 'items', 'list']:
            if key in value and isinstance(value[key], list):
                return "\n".join(f"- {item}" for item in value[key] if item)
        return "\n".join(f"- **{k.replace('_', ' ').title()}:** {v}" for k, v in value.items() if v)
    
    # If it's a string, attempt parsing in case of python-literal dictionary/lists
    if isinstance(value, str):
        val_strip = value.strip()
        if not val_strip:
            return ""
            
        # Try JSON parsing
        try:
            parsed = json.loads(val_strip)
            return format_field(parsed)
        except Exception:
            pass
            
        # Try Python Literal Evaluation (e.g. literal strings of dicts/lists)
        try:
            parsed = ast.literal_eval(val_strip)
            return format_field(parsed)
        except Exception:
            pass
            
        # Fallback split check for manually formatted list-like strings "[a, b, c]"
        if val_strip.startswith('[') and val_strip.endswith(']'):
            try:
                items = [item.strip("'\" ") for item in val_strip[1:-1].split(',')]
                return "\n".join(f"- {item}" for item in items if item)
            except Exception:
                pass
                
        return value

def get_match_score(job):
    """Parses match score from job AI summary for sorting."""
    try:
        eval_data = json.loads(job['ai_summary'])
        return int(eval_data.get('match_score', 0))
    except Exception:
        return 0

# --- Define the Kanban Columns ---
col1, col2, col3 = st.columns(3)

STAGES = ["To Apply", "In Process", "Declined", "Irrelevant"]
SUB_STAGES = ["HR Screen", "Home Assignment", "Tech Interview", "Manager Interview", "Offer"]

def render_job_card(job, column_obj):
    with column_obj:
        with st.container():
            try:
                eval_data = json.loads(job['ai_summary'])
                summary = eval_data.get('summary', job['ai_summary'])
                location = eval_data.get('location', 'Not specified')
                key_features = eval_data.get('key_features', '')
                important_qualifications = eval_data.get('important_qualifications', '')
                match_score = int(eval_data.get('match_score', 0))
            except (json.JSONDecodeError, TypeError):
                summary = job['ai_summary']
                location = 'Not specified'
                key_features = ''
                important_qualifications = ''
                match_score = 0
                
            # Clean up fields
            clean_qualifications = format_field(important_qualifications)
            clean_key_features = format_field(key_features)
            
            # Select badge color
            badge_class = "score-badge-high" if match_score >= 80 else ""
            
            # Render compact Card HTML (Only Job Name, Company, Match Score)
            st.markdown(f"""
            <div class="job-card">
                <div class="card-header">
                    <div>
                        <div class="job-title">{job['title']}</div>
                        <div class="company-name">🏢 {job['company']}</div>
                    </div>
                    <span class="score-badge {badge_class}">🔥 {match_score}% Match</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Expander for showing ALL specific job details
            with st.expander("👉 Show more details"):
                if location and location != 'Not specified':
                     st.markdown(f"**📍 Location:** {location}")
                
                if clean_qualifications:
                     st.markdown("**🎓 Key Qualifications:**")
                     st.markdown(clean_qualifications)
                
                if clean_key_features:
                     display_features = clean_key_features.lstrip('- ')
                     st.markdown(f"**✨ Highlights:** {display_features}")
                
                st.markdown("**📝 AI Summary:**")
                st.write(summary)
                
                st.markdown(f"[🔗 Apply / View Original Job Listing]({job['url']})")
            
            # State Management Dropdowns directly below the expander
            stage_key = f"stage_{job['id']}"
            current_stage_idx = STAGES.index(job['stage']) if job['stage'] in STAGES else 0
            
            selected_stage = st.selectbox(
                "Change Stage", 
                STAGES, 
                index=current_stage_idx, 
                key=stage_key
            )
            
            selected_sub = None
            if selected_stage == "In Process":
                sub_key = f"sub_{job['id']}"
                current_sub_idx = SUB_STAGES.index(job['sub_stage']) if job['sub_stage'] in SUB_STAGES else 0
                selected_sub = st.selectbox(
                    "Select Sub-Stage", 
                    SUB_STAGES, 
                    index=current_sub_idx, 
                    key=sub_key
                )
            
            # State update triggers database update & app refresh
            if selected_stage != job['stage'] or (selected_stage == "In Process" and selected_sub != job['sub_stage']):
                database.update_job_stage(job['id'], selected_stage, selected_sub)
                st.rerun()
            
            st.markdown('<div class="card-divider"></div>', unsafe_allow_html=True)

# Fetch and sort jobs in Descending Order of match score
to_apply_jobs = sorted(database.get_jobs_by_stage("To Apply"), key=get_match_score, reverse=True)
in_process_jobs = sorted(database.get_jobs_by_stage("In Process"), key=get_match_score, reverse=True)
declined_jobs = sorted(database.get_jobs_by_stage("Declined"), key=get_match_score, reverse=True)

# Render Columns
with col1:
    st.header(f"📥 To Apply ({len(to_apply_jobs)})")
    for job in to_apply_jobs:
        render_job_card(job, col1)

with col2:
    st.header(f"⏳ In Process ({len(in_process_jobs)})")
    for job in in_process_jobs:
        render_job_card(job, col2)

with col3:
    st.header(f"❌ Declined ({len(declined_jobs)})")
    for job in declined_jobs:
        render_job_card(job, col3)
