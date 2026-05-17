import streamlit as st
import database
import urllib.parse

# Set page configuration to wide mode for a better Kanban view
st.set_page_config(page_title="The Job Finder Dashboard", layout="wide")

# Custom CSS for modern styling
st.markdown("""
<style>
    .job-card {
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 15px;
        background-color: #f9f9f9;
        color: #333;
    }
    .job-title {
        font-size: 18px;
        font-weight: bold;
        margin-bottom: 5px;
        color: #1f77b4;
    }
    .company-name {
        font-size: 16px;
        font-weight: 600;
        margin-bottom: 10px;
    }
    .ai-summary {
        font-size: 14px;
        color: #555;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

st.title("🎯 Job Finder Kanban Dashboard")

# Initialize DB on load to ensure migrations are run
database.init_db()

# --- Callback for updating state ---
def update_stage(job_id, stage_key, sub_stage_key=None):
    new_stage = st.session_session_state[stage_key] if hasattr(st, 'session_session_state') else st.session_state[stage_key]
    new_sub = None
    if sub_stage_key and sub_stage_key in st.session_state:
        new_sub = st.session_state[sub_stage_key]
        
    database.update_job_stage(job_id, new_stage, new_sub)

# --- Define the Kanban Columns ---
col1, col2, col3 = st.columns(3)

STAGES = ["To Apply", "In Process", "Declined", "Irrelevant"]
SUB_STAGES = ["HR Screen", "Home Assignment", "Tech Interview", "Manager Interview", "Offer"]

def render_job_card(job, column_obj):
    with column_obj:
        with st.container():
            import json
            try:
                eval_data = json.loads(job['ai_summary'])
                summary = eval_data.get('summary', job['ai_summary'])
                location = eval_data.get('location', 'Not specified')
                key_features = eval_data.get('key_features', '')
                important_qualifications = eval_data.get('important_qualifications', '')
            except (json.JSONDecodeError, TypeError):
                summary = job['ai_summary']
                location = 'Not specified'
                key_features = ''
                important_qualifications = ''
                
            st.markdown(f"""
            <div class="job-card">
                <div class="job-title">{job['title']}</div>
                <div class="company-name">🏢 {job['company']}</div>
            </div>
            """, unsafe_allow_html=True)
            
            if important_qualifications:
                 st.markdown("**🎓 Important Qualifications:**")
                 st.markdown(important_qualifications)
            
            if key_features:
                 st.markdown(f"**✨ Key Features:** {key_features}")
                 
            with st.expander("Show more"):
                if location != 'Not specified' and location:
                     st.markdown(f"**📍 Location:** {location}")
                st.write("**Summary:**")
                st.write(summary)
                st.markdown(f"[🔗 View on LinkedIn]({job['url']})")
            
            # State Management Dropdowns
            stage_key = f"stage_{job['id']}"
            current_stage_idx = STAGES.index(job['stage']) if job['stage'] in STAGES else 0
            
            # Selectbox for Stage
            selected_stage = st.selectbox(
                "Stage", 
                STAGES, 
                index=current_stage_idx, 
                key=stage_key
            )
            
            selected_sub = None
            if selected_stage == "In Process":
                sub_key = f"sub_{job['id']}"
                current_sub_idx = SUB_STAGES.index(job['sub_stage']) if job['sub_stage'] in SUB_STAGES else 0
                selected_sub = st.selectbox(
                    "Sub-Stage", 
                    SUB_STAGES, 
                    index=current_sub_idx, 
                    key=sub_key
                )
            
            # If the user changed something, update DB and rerun
            if selected_stage != job['stage'] or (selected_stage == "In Process" and selected_sub != job['sub_stage']):
                database.update_job_stage(job['id'], selected_stage, selected_sub)
                st.rerun()
            
            st.write("---")

# Fetch Jobs
to_apply_jobs = database.get_jobs_by_stage("To Apply")
in_process_jobs = database.get_jobs_by_stage("In Process")
declined_jobs = database.get_jobs_by_stage("Declined")

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

