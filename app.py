import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, auth, firestore, exceptions
from datetime import datetime, date
import requests

# ----------------------
# Firebase Initialization
# ----------------------
if not firebase_admin._apps:
    try:
        firebase_config = dict(st.secrets["firebase"])
        cred = credentials.Certificate(firebase_config)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase initialization failed: {str(e)}")
        st.stop()

db = firestore.client()

# ----------------------
# Authentication Functions
# ----------------------
def is_iba_user(email):
    allowed_domains = ("@iba.edu.pk", "@khi.iba.edu.pk")
    return any(email.endswith(domain) for domain in allowed_domains)

def handle_auth_error(e):
    error_messages = {
        "EMAIL_NOT_FOUND": "Account not found",
        "INVALID_PASSWORD": "Invalid password",
        "USER_DISABLED": "Account disabled",
        "EMAIL_EXISTS": "Email already registered"
    }
    return error_messages.get(str(e), f"Authentication error: {str(e)}")

def sign_in_with_email_and_password(email, password):
    api_key = st.secrets["firebase"]["apiKey"]
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        return response.json()
    else:
        error = response.json().get("error", {}).get("message", "Unknown error")
        raise Exception(error)

def send_password_reset_email(email):
    api_key = st.secrets["firebase"]["apiKey"]
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={api_key}"
    payload = {"requestType": "PASSWORD_RESET", "email": email}
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        return True
    else:
        error = response.json().get("error", {}).get("message", "Unknown error")
        raise Exception(error)

# ----------------------
# Session State Management
# ----------------------
if 'firebase_user' not in st.session_state:
    st.session_state.update({
        'firebase_user': None,
        'applications': pd.DataFrame(),
        'bookmarks': [],
        'reviews': [],
        'show_form': False,
        'edit_review_index': None,
        'data_loaded': False,
        'page': "👤 User Profile",
        'show_forgot': False,
        'reviews_submitted': 0,
        'current_review_step': 0,
        'review_data': [{} for _ in range(2)],
        'user_profile': {}
    })

# ----------------------
# Authentication Interface
# ----------------------
if not st.session_state.firebase_user:
    st.title("IBA Internship Portal")
    login_tab, register_tab = st.tabs(["Login", "Register"])
    
    with login_tab:
        with st.form("login_form"):
            email = st.text_input("IBA Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In")
            if submitted:
                try:
                    if not is_iba_user(email):
                        st.error("Only IBA email addresses allowed")
                    else:
                        user_info = sign_in_with_email_and_password(email, password)
                        st.session_state.firebase_user = user_info
                        st.rerun()
                except Exception as e:
                    st.error(f"Authentication failed: {str(e)}")
        
        if st.button("Forgot Password?"):
            st.session_state.show_forgot = True
        
        if st.session_state.show_forgot:
            with st.form("forgot_form"):
                forgot_email = st.text_input("Enter your IBA Email for password reset")
                if st.form_submit_button("Send Reset Email"):
                    try:
                        if not is_iba_user(forgot_email):
                            st.error("Only IBA email addresses allowed")
                        else:
                            send_password_reset_email(forgot_email)
                            st.success("Password reset email sent!")
                            st.session_state.show_forgot = False
                    except Exception as e:
                        st.error(f"Failed to send reset email: {str(e)}")
    
    with register_tab:
        with st.form("register_form"):
            new_email = st.text_input("New IBA Email")
            new_password = st.text_input("New Password", type="password")
            if st.form_submit_button("Create Account"):
                if is_iba_user(new_email):
                    try:
                        user = auth.create_user(
                            email=new_email,
                            password=new_password,
                            email_verified=False
                        )
                        auth.generate_email_verification_link(new_email)
                        st.success("Account created! Check your email for verification")
                    except Exception as e:
                        st.error(handle_auth_error(e))
                else:
                    st.error("Only IBA email addresses allowed")
    st.stop()

# ----------------------
# Profile Management
# ----------------------
def complete_profile():
    st.header("Complete Your Profile")
    with st.form("profile_form"):
        full_name = st.text_input("Full Name")
        age = st.number_input("Age", min_value=16, max_value=100)
        semester = st.number_input("Current Semester", min_value=1, max_value=12)
        program = st.text_input("Program")
        grad_year = st.number_input("Expected Graduation Year", min_value=2023)
        
        if st.form_submit_button("Save Profile"):
            profile_data = {
                "full_name": full_name,
                "age": age,
                "semester": semester,
                "program": program,
                "expected_grad_year": grad_year,
                "profile_completed": True
            }
            try:
                db.collection("users").document(st.session_state.firebase_user["localId"]).set(profile_data, merge=True)
                st.session_state.user_profile = profile_data
                st.session_state.reviews_submitted = 0
                st.rerun()
            except Exception as e:
                st.error(f"Profile save failed: {str(e)}")

# ----------------------
# Review Components
# ----------------------
def validate_stipend(stipend):
    if not stipend:
        return True
    try:
        parts = stipend.split('-')
        return len(parts) == 2 and all(part.strip().isdigit() for part in parts)
    except:
        return False

def get_review_form(step):
    with st.form(key=f"review_form_{step}"):
        col1, col2 = st.columns(2)
        
        with col1:
            company = st.selectbox("Company", [
                'Unilever Pakistan', 'Reckitt Benckiser', 'Procter & Gamble',
                'Nestlé Pakistan', 'L’Oréal Pakistan', 'Coca-Cola Pakistan',
                'PepsiCo Pakistan', 'Other'
            ], key=f"company_{step}")
            
            custom_company = ""
            if company == 'Other':
                custom_company = st.text_input("Custom Company", key=f"custom_company_{step}")
            
            industry = st.selectbox("Industry", ["Tech", "Finance", "Marketing", "HR", "Other"], key=f"industry_{step}")
            ease_process = st.selectbox("Ease of Process", ["Easy", "Moderate", "Hard"], key=f"ease_{step}")
            assessments = st.text_area("Gamified Assessments", key=f"assessments_{step}")
            interview_questions = st.text_area("Interview Questions", key=f"questions_{step}")
            stipend = st.text_input("Stipend Range (Rs) (Optional)", key=f"stipend_{step}")

        with col2:
            hiring_rating = st.slider("Hiring Ease (1-5)", 1, 5, 3, key=f"hiring_{step}")
            referral = st.radio("Referral Used?", ["Yes", "No"], key=f"referral_{step}")
            red_flags = st.slider("Red Flags (1-5)", 1, 5, 3, key=f"redflags_{step}")
            department = st.selectbox("Department", ["Tech", "Finance", "HR", "Marketing", "Operations"], key=f"dept_{step}")
            semester = st.slider("Semester", 1, 8, 5, key=f"sem_{step}")
            outcome = st.selectbox("Outcome", ["Accepted", "Rejected", "In Process"], key=f"outcome_{step}")
            post_option = st.radio("Post As", ["Use my full name", "Anonymous"], key=f"post_{step}")

        errors = []
        if company == 'Other' and not custom_company:
            errors.append("Company name required")
        if stipend and not validate_stipend(stipend):
            errors.append("Invalid stipend format (use 'min-max')")
        
        submitted = st.form_submit_button("Submit Review ➡️")
        
        if submitted:
            if not errors:
                return {
                    'company': custom_company if company == 'Other' else company,
                    'industry': industry,
                    'ease_process': ease_process,
                    'assessments': assessments,
                    'interview_questions': interview_questions,
                    'stipend': stipend,
                    'hiring_rating': hiring_rating,
                    'referral': referral,
                    'red_flags': red_flags,
                    'department': department,
                    'semester': semester,
                    'outcome': outcome,
                    'post_option': post_option
                }
            else:
                for error in errors:
                    st.error(error)
                return None

# ----------------------
# Onboarding Process
# ----------------------
def onboarding_process():
    st.header("Complete Onboarding (2 Reviews Required)")
    current_step = st.session_state.current_review_step
    progress = (current_step + 1) / 2
    st.progress(progress)
    
    review_data = get_review_form(current_step)
    
    if review_data:
        st.session_state.review_data[current_step] = review_data
        
        if current_step == 1:
            try:
                for i in range(2):
                    data = st.session_state.review_data[i]
                    review = {
                        'user_id': st.session_state.firebase_user["localId"],
                        'reviewer_name': st.session_state.user_profile.get('full_name', 'Anonymous') 
                            if data['post_option'] == "Use my full name" else "Anonymous",
                        'timestamp': firestore.SERVER_TIMESTAMP,
                        **data
                    }
                    db.collection("reviews").add(review)
                
                st.balloons()
                st.session_state.reviews_submitted = 2
                st.session_state.page = "👤 User Profile"
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save reviews: {str(e)}")
        else:
            st.session_state.current_review_step += 1
            st.rerun()
    
    col1, col2 = st.columns(2)
    with col1:
        if current_step > 0:
            if st.button("← Previous"):
                st.session_state.current_review_step -= 1
                st.rerun()

# ----------------------
# Main Application Pages
# ----------------------
def user_profile_page():
    st.header("👤 User Profile")
    user_ref = db.collection("users").document(st.session_state.firebase_user["localId"])
    user_profile = user_ref.get().to_dict() or {}
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Personal Info")
        st.write(f"**Name:** {user_profile.get('full_name', 'N/A')}")
        st.write(f"**Age:** {user_profile.get('age', 'N/A')}")
        st.write(f"**Program:** {user_profile.get('program', 'N/A')}")
    
    with col2:
        st.subheader("Academic Info")
        st.write(f"**Semester:** {user_profile.get('semester', 'N/A')}")
        st.write(f"**Graduation Year:** {user_profile.get('expected_grad_year', 'N/A')}")
    
    st.subheader("Applications Tracker")
    with st.expander("➕ Add New Application"):
        with st.form("new_application"):
            name = st.text_input("Company Name")
            status = st.selectbox("Status", [
                'Applied', 'Assessment Given', 'Interview R1 given',
                'Interview R2 given', 'Interview R3 given', 
                'Accepted', 'Offer Received', 'Rejected'
            ])
            deadline = st.date_input("Deadline")
            referral = st.text_input("Referral Details")
            link = st.text_input("Application Link")
            notes = st.text_area("Notes")
            
            if st.form_submit_button("Add"):
                new_app = {
                    'Company Name': name,
                    'Status': status,
                    'Deadline': datetime.combine(deadline, datetime.min.time()),
                    'Referral Details': referral,
                    'Link': link,
                    'Notes': notes
                }
                db.collection("users").document(st.session_state.firebase_user["localId"]) \
                  .collection("applications").add(new_app)
                st.rerun()
    
    apps = db.collection("users").document(st.session_state.firebase_user["localId"]) \
           .collection("applications").stream()
    app_data = [app.to_dict() for app in apps]
    
    if app_data:
        st.dataframe(pd.DataFrame(app_data))
    else:
        st.info("No applications submitted yet")

def internship_feed_page():
    st.header("📰 Internship Feed")
    
    col1, col2, col3 = st.columns(3)
    company_filter = col1.text_input("Search Company")
    industry_filter = col2.selectbox("Industry", ["All", "Tech", "Finance", "Marketing", "HR"])
    stipend_filter = col3.slider("Stipend Range (Rs)", 0, 150000, (30000, 100000))
    
    reviews = db.collection("reviews").stream()
    for review in reviews:
        rdata = review.to_dict()
        if (company_filter.lower() in rdata.get('company', '').lower() and
            (industry_filter == "All" or rdata.get('industry') == industry_filter)):
            
            with st.expander(f"{rdata.get('company', 'Unknown')} Review"):
                col1, col2 = st.columns([3,1])
                with col1:
                    st.markdown(f"**Industry:** {rdata.get('industry')}")
                    st.markdown(f"**Process:** {rdata.get('ease_process')}")
                    st.markdown(f"**Stipend:** {rdata.get('stipend', 'Not specified')}")
                    st.markdown(f"**Outcome:** {rdata.get('outcome')}")
                with col2:
                    st.markdown(f"**Rating:** {'⭐' * rdata.get('hiring_rating', 3)}")
                    st.markdown(f"**Red Flags:** {'🚩' * rdata.get('red_flags', 3)}")
                
                if st.button("Bookmark", key=f"bm_{review.id}"):
                    db.collection("users").document(st.session_state.firebase_user["localId"]) \
                      .update({"bookmarks": firestore.ArrayUnion([review.id])})
                
                if st.button("Upvote", key=f"uv_{review.id}"):
                    db.collection("reviews").document(review.id) \
                      .update({"upvotes": firestore.Increment(1)})

# ----------------------
# Main App Flow
# ----------------------
# Check profile completion
user_ref = db.collection("users").document(st.session_state.firebase_user["localId"])
user_profile = user_ref.get().to_dict()

if not user_profile or not user_profile.get("profile_completed"):
    complete_profile()
    st.stop()

# Check onboarding status
if st.session_state.reviews_submitted < 2:
    onboarding_process()
    st.stop()

# Main page routing
if st.session_state.page == "👤 User Profile":
    user_profile_page()
else:
    internship_feed_page()

# Sidebar controls
st.sidebar.radio("Navigation", ["👤 User Profile", "📰 Internship Feed"], key="page")
if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()

# Style injections
st.markdown("""
<style>
    .stButton>button {
        transition: transform 0.2s, box-shadow 0.2s;
        border-radius: 8px;
    }
    .stButton>button:hover {
        transform: scale(1.05);
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    .stProgress > div > div {
        background: #4CAF50 !important;
        height: 12px;
        border-radius: 6px;
    }
    .stMarkdown h1 {
        color: #2c3e50;
        border-bottom: 2px solid #4CAF50;
        padding-bottom: 0.3em;
    }
    .stDataFrame {
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)
