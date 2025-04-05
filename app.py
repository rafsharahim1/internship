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
    if hasattr(e, "code"):
        return error_messages.get(e.code, f"Authentication error: {str(e)}")
    else:
        return f"Authentication error: {str(e)}"

def sign_in_with_email_and_password(email, password):
    api_key = st.secrets["firebase"]["apiKey"]
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        return response.json()  # Contains "localId", "idToken", etc.
    else:
        error = response.json().get("error", {}).get("message", "Unknown error")
        raise Exception(error)

def send_password_reset_email(email):
    """Sends a password reset email via Firebase."""
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
        'contributions': pd.DataFrame(),
        'bookmarks': [],
        'reviews': [],
        'show_form': False,           # Ensure this exists
        'review_to_edit': None,       # Ensure this exists
        'data_loaded': False,
        'page': "👤 User Profile",    # Default page
        'dummy': False,
        'show_forgot': False,
        # New state for onboarding reviews
        'reviews_submitted': 0,
        'current_review_step': 0,
        'review_data': [{} for _ in range(2)],
        'user_profile': {},
        'profile_saved': False  # Flag for profile saved
    })

query_params = st.query_params
if "page" in query_params:
    st.session_state.page = query_params["page"][0]

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
                        st.session_state.firebase_user = user_info  # localId acts as UID
                        st.query_params = {"page": st.session_state.page}
                        st.stop()
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
                        link = auth.generate_email_verification_link(new_email)
                        st.success("Account created! Kindly Proceed to Login")
                    except Exception as e:
                        st.error(handle_auth_error(e))
                else:
                    st.error("Only IBA email addresses allowed")
    st.stop()

# ----------------------
# Profile Completion Functions
# ----------------------
def complete_profile():
    st.header("Complete Your Profile")
    with st.form("profile_form"):
        full_name = st.text_input("Full Name")
        age = st.number_input("Age", min_value=16, max_value=100, step=1)
        semester = st.number_input("Current Semester", min_value=1, max_value=12, step=1)
        program = st.text_input("Program (required)")
        grad_year = st.number_input("Expected Graduation Year", min_value=2023, max_value=2100, step=1)
        submitted = st.form_submit_button("Save Profile")
        if submitted:
            if not program.strip():
                st.error("Program is required.")
                st.stop()
            profile_data = {
                "full_name": full_name,
                "age": age,
                "semester": semester,
                "program": program,
                "expected_grad_year": grad_year,
                "profile_completed": True,
                "onboarding_complete": False  # Initially false
            }
            try:
                user_ref = db.collection("users").document(st.session_state.firebase_user["localId"])
                user_ref.set(profile_data, merge=True)
                st.session_state.user_profile = profile_data
                st.success("Profile saved!")
                st.session_state.profile_saved = True
            except Exception as e:
                st.error(f"Failed to save profile: {str(e)}")
    if st.session_state.get("profile_saved", False):
        if st.button("Next"):
            st.session_state.page = "Onboarding"
            st.stop()

user_ref = db.collection("users").document(st.session_state.firebase_user["localId"])
user_doc = user_ref.get()
if user_doc.exists:
    user_profile_data = user_doc.to_dict()
    profile_completed = user_profile_data.get("profile_completed", False)
    onboarding_complete = user_profile_data.get("onboarding_complete", False)
else:
    user_profile_data = {}
    profile_completed = False
    onboarding_complete = False

# ----------------------
# Data Management Functions
# ----------------------
def load_data():
    try:
        user_ref = db.collection("users").document(st.session_state.firebase_user["localId"])
        apps_ref = user_ref.collection("applications")
        apps = [doc.to_dict() for doc in apps_ref.stream()]
        st.session_state.applications = pd.DataFrame(apps) if apps else pd.DataFrame()
        user_data = user_ref.get().to_dict() or {}
        st.session_state.contributions = pd.DataFrame(user_data.get("contributions", []))
        st.session_state.bookmarks = user_data.get("bookmarks", [])
        reviews_ref = db.collection("reviews")
        st.session_state.reviews = [{**doc.to_dict(), "id": doc.id} for doc in reviews_ref.stream()]
    except Exception as e:
        st.error(f"Data load failed: {str(e)}")

if not st.session_state.data_loaded:
    load_data()
    st.session_state.data_loaded = True

def save_applications():
    try:
        apps_ref = db.collection("users").document(st.session_state.firebase_user["localId"]).collection("applications")
        for doc in apps_ref.stream():
            doc.reference.delete()
        for _, row in st.session_state.applications.iterrows():
            row_dict = row.to_dict()
            if "Deadline" in row_dict:
                if isinstance(row_dict["Deadline"], date) and not isinstance(row_dict["Deadline"], datetime):
                    row_dict["Deadline"] = datetime.combine(row_dict["Deadline"], datetime.min.time())
            apps_ref.add(row_dict)
    except Exception as e:
        st.error(f"Failed to save applications: {str(e)}")

def save_contributions():
    try:
        user_ref = db.collection("users").document(st.session_state.firebase_user["localId"])
        user_ref.update({"contributions": st.session_state.contributions.to_dict("records")})
    except Exception as e:
        st.error(f"Failed to save contributions: {str(e)}")

def save_bookmarks():
    try:
        user_ref = db.collection("users").document(st.session_state.firebase_user["localId"])
        user_ref.update({"bookmarks": list(set(st.session_state.bookmarks))})
    except Exception as e:
        st.error(f"Failed to save bookmarks: {str(e)}")

def save_review(review_data, edit=False, review_doc_id=None):
    try:
        reviews_ref = db.collection("reviews")
        if edit and review_doc_id:
            reviews_ref.document(review_doc_id).update(review_data)
        else:
            # Add additional fields for new reviews so they appear in the user's profile
            review_data['upvoters'] = review_data.get('upvoters', [])
            review_data['bookmarkers'] = review_data.get('bookmarkers', [])
            review_data['user_id'] = st.session_state.firebase_user["localId"]
            review_data['reviewer_name'] = st.session_state.user_profile.get('full_name', 'Anonymous') if review_data.get("Post As") == "Use my full name" else "Anonymous"
            review_data['timestamp'] = firestore.SERVER_TIMESTAMP
            new_doc = reviews_ref.add(review_data)
            review_data['id'] = new_doc[1].id
        load_data()
    except Exception as e:
        st.error(f"Failed to save review: {str(e)}")

# ----------------------
# Helper Functions
# ----------------------
def calculate_kpis():
    if st.session_state.applications.empty:
        return {'Total Applications': 0, 'Rejected': 0, 'In Progress': 0}
    if 'Status' not in st.session_state.applications.columns:
        total = len(st.session_state.applications)
        return {'Total Applications': total, 'Rejected': 0, 'In Progress': total}
    total = len(st.session_state.applications)
    rejected = len(st.session_state.applications[st.session_state.applications['Status'] == 'Rejected'])
    in_progress = len(st.session_state.applications[~st.session_state.applications['Status'].isin(['Offer Received', 'Rejected'])])
    return {'Total Applications': total, 'Rejected': rejected, 'In Progress': in_progress}

def validate_stipend(stipend):
    if not stipend:
        return True
    try:
        parts = stipend.split('-')
        return len(parts) == 2 and all(part.strip().isdigit() for part in parts)
    except:
        return False

# ----------------------
# New Editable Review Form Function with Pre-Populated Fields
# ----------------------
def review_form(review_to_edit=None):
    # Use a unique form key based on whether editing or adding a new review.
    form_key = "edit_review_form" if review_to_edit else "new_review_form"

    companies = [
        'Unilever Pakistan', 'Reckitt Benckiser', 'Procter & Gamble',
        'Nestlé Pakistan', 'L’Oréal Pakistan', 'Coca-Cola Pakistan',
        'PepsiCo Pakistan', 'Engro Corporation', 'Packages Limited',
        'Fauji Fertilizer Company', 'Hub Power Company', 'Lucky Cement',
        'National Bank of Pakistan', 'Habib Bank Limited', 'MCB Bank',
        'United Bank Limited', 'Meezan Bank', 'SNGPL', 'Systems Limited', "Bazaar Tech", 
        'Pakistan State Oil', 'K-Electric', 'Bank Alfalah', 'Gul Ahmed',
        'Interloop Limited', 'Nishat Group', 'Faysal Bank', 'Askari Bank',
        'Soneri Bank', 'Summit Bank', 'Other'
    ]
    gaming_options_list = [
        "Pymetrics", "Factor Talent Game", "HireVue Game-Based Assessments",
        "Mettl Situational Judgment Tests (SJTs)", "Codility Code Challenges",
        "HackerRank Coding Assessments",  "Behavioral", "Technical", "Other"
    ]
    interview_modes = ["Virtual (Zoom/Teams)", "In-Person", "Digital", "No Interview"]

    # Prepare default values if editing an existing review.
    default_program_type = review_to_edit.get("program_type") if review_to_edit else "MT Program"
    default_company = review_to_edit.get("Company") if review_to_edit else companies[0]
    default_industry = review_to_edit.get("Industry") if review_to_edit else "Tech"
    default_ease = review_to_edit.get("Ease of Process") if review_to_edit else "Easy"
    default_assessments = review_to_edit.get("Gamified Assessments", "") if review_to_edit else ""
    default_gaming = review_to_edit.get("Gaming Options", []) if review_to_edit else []
    default_mode_interview = review_to_edit.get("Mode of Interview", []) if review_to_edit else []
    default_interview_questions = review_to_edit.get("Interview Questions", "") if review_to_edit else ""
    default_stipend = review_to_edit.get("Stipend Range", "") if review_to_edit else ""
    default_rating = review_to_edit.get("Rating", 3) if review_to_edit else 3
    default_referral = review_to_edit.get("Referral Used", "No") if review_to_edit else "No"
    default_red_flags = review_to_edit.get("Red Flags", 3) if review_to_edit else 3
    default_semester = review_to_edit.get("Semester", 5) if review_to_edit else 5
    default_interview_round = review_to_edit.get("Interview Round", "Waiting") if review_to_edit else "Waiting"
    default_outcome = review_to_edit.get("Offer Outcome", "In Process") if review_to_edit else "In Process"
    default_post_option = review_to_edit.get("Post As", "Use my full name") if review_to_edit else "Use my full name"

    with st.form(form_key, clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            program_type = st.radio(
                "Program Type", 
                ["MT Program", "Internship"],
                index=0 if default_program_type == "MT Program" else 1
            )
            try:
                company_index = companies.index(default_company)
            except ValueError:
                company_index = 0
            company = st.selectbox("Company", companies, index=company_index)
            custom_company = ""
            if company == "Other":
                custom_company = st.text_input(
                    "Custom Company", 
                    value=review_to_edit.get("Company") if review_to_edit else ""
                )
            industry_options = ["Tech", "Finance", "Marketing", "HR", "Data/AI", "Engineering",
                                "Retail", "Manufacturing", "Consulting",
                                "Education", "Logistics", "Telecommunications", "Supply Chain", "Other"]
            try:
                industry_index = industry_options.index(default_industry)
            except ValueError:
                industry_index = 0
            industry = st.selectbox("Industry", industry_options, index=industry_index)
            ease_options = ["Easy", "Moderate", "Hard"]
            try:
                ease_index = ease_options.index(default_ease)
            except ValueError:
                ease_index = 0
            ease_process = st.selectbox("Ease of Process", ease_options, index=ease_index)
            assessments = st.text_area(
                "How was your experience with the gamified assessment? Kindly provide details about the tasks, challenges, and how you felt during the process.",
                value=default_assessments
            )
            selected_gaming = st.multiselect(
                "Select Gaming Assessment Options (You can select multiple)", 
                options=gaming_options_list, 
                default=default_gaming
            )
            custom_gaming = ""
            if "Other" in selected_gaming:
                custom_gaming = st.text_input("Custom Gaming Option", value="")
            gaming_options = selected_gaming.copy()
            if "Other" in gaming_options and custom_gaming:
                gaming_options[gaming_options.index("Other")] = custom_gaming

            default_mode_interview = default_mode_interview if isinstance(default_mode_interview, list) else []
            mode_interview = st.multiselect(
                "Mode of Interview (Select one or more)", 
                options=interview_modes, 
                default=default_mode_interview
            )
            interview_questions = st.text_area(
                "Interview Questions Asked * ",
                value=default_interview_questions
            )
            stipend = st.text_input(
                "Stipend Range (Rs) [e.g 25000-30000] (Optional)",
                value=default_stipend
            )
        with col2:
            hiring_rating = st.slider(
                "Rating (1-5) [5 being the highest]", 1, 5, default_rating
            )
            referral = st.radio(
                "Referral Used?", ["Yes", "No"],
                index=0 if default_referral=="Yes" else 1
            )
            red_flags = st.slider(
                "Red Flags (1-5) [5 being the biggest Red Flag]", 1, 5, default_red_flags
            )
            semester = st.slider(
                "Semester", 1, 8, default_semester
            )
            interview_round_options = ["Yes. made it to interview", "No, did not make it to interview", "Waiting"]
            try:
                interview_round_index = interview_round_options.index(default_interview_round)
            except ValueError:
                interview_round_index = 2
            interview_round = st.selectbox(
                "Interview Round: Select your interview outcome (if any)", 
                interview_round_options,
                index=interview_round_index
            )
            outcome_options = ["Accepted", "Rejected", "In Process"]
            try:
                outcome_index = outcome_options.index(default_outcome)
            except ValueError:
                outcome_index = 2
            outcome = st.selectbox(
                "Outcome", outcome_options,
                index=outcome_index
            )
            post_option = st.radio(
                "Post As", ["Use my full name", "Anonymous"],
                index=0 if default_post_option=="Use my full name" else 1
            )
        
        submitted = st.form_submit_button("Submit Review")
        if submitted:
            errors = []
            if company == "Other" and not custom_company:
                errors.append("Company name required")
            if not interview_questions.strip():
                errors.append("Interview Questions field is required")
            if not mode_interview:
                errors.append("At least one Mode of Interview must be selected")
            if assessments.strip() == "":
                errors.append("Gamified Assessment feedback is required")
            if stipend and not validate_stipend(stipend):
                errors.append("Invalid stipend format (use 'min-max')")
            if errors:
                for error in errors:
                    st.error(error)
                return None
            return {
                "program_type": program_type,
                "Company": custom_company if company == "Other" else company,
                "Industry": industry,
                "Ease of Process": ease_process,
                "Gamified Assessments": assessments,
                "Gaming Options": gaming_options,
                "Mode of Interview": mode_interview,
                "Interview Questions": interview_questions,
                "Stipend Range": stipend,
                "Rating": hiring_rating,
                "Referral Used": referral,
                "Red Flags": red_flags,
                "Semester": semester,
                "Interview Round": interview_round,
                "Offer Outcome": outcome,
                "Post As": post_option
            }
    return None

def get_review_form(step):
    gaming_options_list = ["Pymetrics", "Factor Talent Game", "HireVue Game-Based Assessments",
                           "Mettl Situational Judgment Tests (SJTs)", "Codility Code Challenges",
                           "HackerRank Coding Assessments", "Behavioral", "Technical", "Other"]
    interview_modes = ["Virtual (Zoom)", "Virtual (Teams)", "In-Person", "Digital", "No Interview"]
    with st.form(key=f"onboarding_review_form_{step}"):
        program_type = st.radio("Program Type", ["MT Program", "Internship"], key=f"program_type_{step}")
        col1, col2 = st.columns(2)
        with col1:
            company = st.selectbox("Company", [
                'Unilever Pakistan', 'Reckitt Benckiser', 'Procter & Gamble',
                'Nestlé Pakistan', 'L’Oréal Pakistan', 'Coca-Cola Pakistan',
                'PepsiCo Pakistan', 'Other'
            ], key=f"company_{step}")
            custom_company = ""
            if company == "Other":
                custom_company = st.text_input("Custom Company", key=f"custom_company_{step}")
            industry = st.selectbox("Industry", ["Tech", "Finance", "Marketing", "HR", "Other"], key=f"industry_{step}")
            ease_process = st.selectbox("Ease of Process", ["Easy", "Moderate", "Hard"], key=f"ease_{step}")
            assessments = st.text_area(
                "How was your experience with the gamified assessment? Kindly provide details about the tasks, challenges, and how you felt during the process. * ",
                key=f"assessments_{step}"
            )
            selected_gaming = st.multiselect("Select Gaming Assessment Options * ", options=gaming_options_list, key=f"gaming_{step}")
            custom_gaming = ""
            if "Other" in selected_gaming:
                custom_gaming = st.text_input("Custom Gaming Option", key=f"custom_gaming_{step}")
            gaming_options = selected_gaming.copy()
            if "Other" in gaming_options and custom_gaming:
                gaming_options[gaming_options.index("Other")] = custom_gaming

            mode_interview = st.multiselect("Mode of Interview (Select one or more) * ", options=interview_modes, key=f"mode_interview_{step}")
            
            interview_questions = st.text_area("Interview Questions", key=f"questions_{step}")
            stipend = st.text_input("Stipend Range (Rs) (Optional)", key=f"stipend_{step}")
        with col2:
            hiring_rating = st.slider("Rating (1-5) [5 being the highest]", 1, 5, 3, key=f"hiring_{step}")
            referral = st.radio("Referral Used?", ["Yes", "No"], key=f"referral_{step}")
            red_flags = st.slider("Red Flags (1-5)[5 being the Biggest Red Flag]", 1, 5, 3, key=f"redflags_{step}")
            semester = st.slider("Semester", 1, 8, 5, key=f"sem_{step}")
            interview_round = st.selectbox("Interview Round: Select your interview outcome (if any) * ", ["Yes. made it to interview", "No, did not make it to interview", "Waiting"], key=f"interview_round_{step}")
            outcome = st.selectbox("Outcome", ["Accepted", "Rejected", "In Process"], key=f"outcome_{step}")
            post_option = st.radio("Post As", ["Use my full name", "Anonymous"], key=f"post_{step}")
        errors = []
        if company == "Other" and not custom_company:
            errors.append("Company name required")
        if not interview_questions.strip():
            errors.append("Interview Questions field is required")
        if not mode_interview:
            errors.append("At least one Mode of Interview must be selected")
        if assessments.strip() == "":
            errors.append("Gamified Assessment feedback is required")
        if stipend and not validate_stipend(stipend):
            errors.append("Invalid stipend format (use 'min-max')")
        submitted = st.form_submit_button("Submit Review ➡️")
        if submitted:
            if not errors:
                return {
                    "program_type": program_type,
                    "Company": custom_company if company == "Other" else company,
                    "Industry": industry,
                    "Ease of Process": ease_process,
                    "Gamified Assessments": assessments,
                    "Gaming Options": gaming_options,
                    "Mode of Interview": mode_interview,
                    "Interview Questions": interview_questions,
                    "Stipend Range": stipend,
                    "Rating": hiring_rating,
                    "Referral Used": referral,
                    "Red Flags": red_flags,
                    "Semester": semester,
                    "Interview Round": interview_round,
                    "Offer Outcome": outcome,
                    "Post As": post_option
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
                                         if data['Post As'] == "Use my full name" else "Anonymous",
                        'timestamp': firestore.SERVER_TIMESTAMP,
                        **data
                    }
                    db.collection("reviews").add(review)

                load_data()
                # Update the onboarding complete flag in Firestore and local session
                db.collection("users").document(st.session_state.firebase_user["localId"]).update({"onboarding_complete": True})
                st.session_state.reviews_submitted = 2
                st.session_state.page = "👤 User Profile"  # Set new page for redirection

                st.balloons()
                st.write("Your reviews have been submitted successfully!")
                if st.button("Continue to Profile"):
                    st.stop()  # Force a rerun so that the main flow loads the profile page
            except Exception as e:
                st.error(f"Failed to save reviews: {str(e)}")
        else:
            st.session_state.current_review_step += 1
            st.stop()
    
    col1, col2 = st.columns(2)
    with col1:
        if current_step > 0:
            if st.button("← Previous"):
                st.session_state.current_review_step -= 1
                st.stop()

# ----------------------
# Sidebar Navigation and Page Storage
# ----------------------
if "page" not in st.session_state:
    st.session_state.page = "👤 User Profile"

page = st.sidebar.radio("Go to", ("👤 User Profile", "📰 Internship Feed"),
                          index=0 if st.session_state.get("page", "👤 User Profile") == "👤 User Profile" else 1)
# Force Internship Feed if the edit form is active
if st.session_state.get("show_form", False):
    st.session_state.page = "📰 Internship Feed"
elif profile_completed and not onboarding_complete:
    st.session_state.page = "Onboarding"
else:
    st.session_state.page = page

# ----------------------
# User Profile Page
# ----------------------
def user_profile():
    st.subheader("Your Profile Information")
    st.write(f"**Name:** {user_profile_data.get('full_name', 'N/A')}")
    st.write(f"**Age:** {user_profile_data.get('age', 'N/A')}")
    st.write(f"**Semester:** {user_profile_data.get('semester', 'N/A')}")
    st.write(f"**Program:** {user_profile_data.get('program', 'N/A')}")
    st.write(f"**Expected Graduation:** {user_profile_data.get('expected_grad_year', 'N/A')}")
    
    st.title('User Dashboard')
    kpis = calculate_kpis()
    cols = st.columns(3)
    cols[0].metric("Applications", kpis['Total Applications'])
    cols[1].metric("Rejected", kpis['Rejected'])
    cols[2].metric("In Progress", kpis['In Progress'])
    
    st.header("Applications Tracker")
    with st.expander("➕ Add New Application"):
        with st.form("new_application"):
            name = st.text_input("Company Name")
            status = st.selectbox("Status", ['Need to Apply','Applied', 'Assessment Given', 'Interview R1 given',
                                               'Interview R2 given', 'Interview R3 given', 
                                               'Accepted', 'Offer Received', 'Rejected'])
            deadline = st.date_input("Deadline")
            referral = st.text_input("Referral Details")
            link = st.text_input("Application Link")
            notes = st.text_area("Notes")
            if st.form_submit_button("Add Application"):
                deadline_dt = datetime.combine(deadline, datetime.min.time())
                new_app = pd.DataFrame([{'Company Name': name,
                                          'Status': status,
                                          'Deadline': deadline_dt,
                                          'Referral Details': referral,
                                          'Link': link,
                                          'Notes': notes}])
                st.session_state.applications = pd.concat([st.session_state.applications, new_app], ignore_index=True)
                save_applications()
                st.rerun()
    
    edited_df = st.data_editor(st.session_state.applications,
                               column_config={"Deadline": st.column_config.DateColumn(),
                                              "Link": st.column_config.LinkColumn()},
                               num_rows="dynamic")
    if not edited_df.equals(st.session_state.applications):
        st.session_state.applications = edited_df
        save_applications()
    
    # Display Bookmarked Reviews
    current_user = st.session_state.firebase_user["localId"]
    bookmarked_reviews = [review for review in st.session_state.reviews if current_user in review.get("bookmarkers", [])]
    st.header("Bookmarked Reviews")
    if bookmarked_reviews:
        for review in bookmarked_reviews:
            st.markdown(f"### {review.get('Company', 'Unknown')} ({review.get('Industry', 'Unknown')}) - {review.get('program_type', 'Unknown')}")
            st.caption(f"🎓 Semester {review.get('Semester', 'Unknown')}")
            st.write(f"**Process:** {review.get('Ease of Process', 'Unknown')}")
            st.write(f"**Outcome:** {review.get('Offer Outcome', 'Unknown')}")
            st.write(f"**Gamified Assessments:** {review.get('Gamified Assessments', 'N/A')}")
            st.write(f"**Gaming Options:** {', '.join(review.get('Gaming Options', []))}")
            st.write(f"**Interview Round:** {review.get('Interview Round', 'Unknown')}")
            st.write(f"**Upvotes:** {len(review.get('upvoters', []))}  |  **Bookmarks:** {len(review.get('bookmarkers', []))}")
    else:
        st.write("No bookmarked reviews.")
    
    # Display Your Reviews with Edit Option
    st.header("Your Reviews")
    user_reviews = [review for review in st.session_state.reviews
                    if review.get("user_id") == st.session_state.firebase_user["localId"]]
    if user_reviews:
        for review in user_reviews:
            col1, col2 = st.columns([8,2])
            reviewer_display = review.get("reviewer_name", "Anonymous")
            col1.markdown(f"**{review.get('Company', 'Unknown')} ({review.get('Industry', 'Unknown')}) - {review.get('program_type', 'Unknown')}** - {review.get('Offer Outcome', 'Unknown')}")
            col1.caption(f"Reviewed by: {reviewer_display}")
            if col2.button("Edit", key=f"edit_{review.get('id')}"):
                st.session_state.review_to_edit = review
                st.session_state.show_form = True  
                st.session_state.page = "📰 Internship Feed"
                st.rerun()
    else:
        st.write("You have not submitted any reviews yet.")

# ----------------------
# Internship Feed Page
# ----------------------
def internship_feed():
    # If a review is being edited or added, display the form at the top.
    if st.session_state.get("show_form", False):
        form_container = st.empty()
        with form_container.container():
            review_to_edit = st.session_state.get("review_to_edit")
            review_data = review_form(review_to_edit)
            if review_data:
                if review_to_edit:  # Editing an existing review.
                    doc_id = review_to_edit["id"]
                    save_review(review_data, edit=True, review_doc_id=doc_id)
                else:
                    save_review(review_data)
                st.success("Review Submitted!")
                st.session_state.show_form = False
                st.session_state.review_to_edit = None
                st.rerun()

    st.header("🎯 Internship Feed")
    
    # Filtering Section
    all_companies = sorted({review.get("Company", "") for review in st.session_state.reviews if review.get("Company", "")})
    company_options = ["All"] + all_companies

    with st.form("filter_form"):
        company_search = st.selectbox("Company", options=company_options, help="Type to search among companies")
        industry_filter = st.selectbox("Industry", ["All", "Tech", "Finance", "Marketing", "HR"])
        stipend_range = st.slider("Stipend Range (Rs)", 0, 250000, (0, 100000))
        program_filter = st.selectbox("Program Type", ["All", "MT Program", "Internship"])
        search_clicked = st.form_submit_button("Search")
    
    if not search_clicked:
        company_search = "All"
        industry_filter = "All"
        stipend_range = (0, 150000)
        program_filter = "All"
    
    if st.button("➕ Add Review"):
        st.session_state.show_form = True
        st.session_state.review_to_edit = None
        st.rerun()
    
    filtered_reviews = []
    for review in st.session_state.reviews:
        try:
            stipend_val = review.get('Stipend Range', '0-0')
            min_stipend = max_stipend = 0
            if stipend_val != "Not Specified" and '-' in stipend_val:
                parts = stipend_val.split('-')
                min_stipend, max_stipend = int(parts[0].strip()), int(parts[1].strip())
            matches = (
                (company_search == "All" or company_search.lower() == review.get('Company', '').lower()) and
                (industry_filter == "All" or review.get('Industry') == industry_filter) and
                (program_filter == "All" or review.get('program_type') == program_filter) and
                (min_stipend >= stipend_range[0]) and 
                (max_stipend <= stipend_range[1])
            )
            if matches:
                filtered_reviews.append(review)
        except Exception:
            continue
    
    st.subheader("Top Reviews")
    for idx, review in enumerate(sorted(filtered_reviews, key=lambda x: len(x.get("upvoters", [])), reverse=True)[:5]):
        with st.container():
            col1, col2 = st.columns([4,1])
            with col1:
                st.markdown(f"### {review.get('Company', 'Unknown')} ({review.get('Industry', 'Unknown')}) - {review.get('program_type', 'Unknown')}")
                st.caption(f"🎓 Semester {review.get('Semester', 'Unknown')}")
                st.write(f"**Process:** {review.get('Ease of Process', 'Unknown')}")
                st.write(f"**Stipend:** {review.get('Stipend Range', 'Unknown')}")
                rating = int(review.get('Rating', 0))
                st.write(f"**Rating:** {'⭐' * rating if rating > 0 else 'N/A'}")
                st.write(f"**Red Flags:** {'🚩' * int(review.get('Red Flags', 0))}")
                with st.expander("Details"):
                    st.write(f"**Gamified Assessments:** {review.get('Gamified Assessments', 'N/A')}")
                    st.write(f"**Gaming Options:** {', '.join(review.get('Gaming Options', []))}")
                    st.write(f"**Interview Round:** {review.get('Interview Round', 'Unknown')}")
                    st.write(f"**Interview Questions:** {review.get('Interview Questions', 'Unknown')}")
                st.write(f"**Reviewed by:** {review.get('reviewer_name', 'Anonymous')}")
            with col2:
                st.write(f"**Outcome:** {review.get('Offer Outcome', 'Unknown')}")
                user_id = st.session_state.firebase_user["localId"]
                upvoters = review.get("upvoters", [])
                bookmarkers = review.get("bookmarkers", [])
                if user_id in upvoters:
                    if st.button(f"Remove Upvote (👍 {len(upvoters)})", key=f"upvote_{idx}"):
                        review_ref = db.collection("reviews").document(review['id'])
                        review_ref.update({"upvoters": firestore.ArrayRemove([user_id])})
                        load_data()
                        st.rerun()
                else:
                    if st.button(f"Upvote (👍 {len(upvoters)})", key=f"upvote_{idx}"):
                        review_ref = db.collection("reviews").document(review['id'])
                        review_ref.update({"upvoters": firestore.ArrayUnion([user_id])})
                        load_data()
                        st.rerun()
                if user_id in bookmarkers:
                    if st.button(f"Remove Bookmark (🔖 {len(bookmarkers)})", key=f"bookmark_{idx}"):
                        review_ref = db.collection("reviews").document(review['id'])
                        review_ref.update({"bookmarkers": firestore.ArrayRemove([user_id])})
                        load_data()
                        st.rerun()
                else:
                    if st.button(f"Bookmark (🔖 {len(bookmarkers)})", key=f"bookmark_{idx}"):
                        review_ref = db.collection("reviews").document(review['id'])
                        review_ref.update({"bookmarkers": firestore.ArrayUnion([user_id])})
                        load_data()
                        st.rerun()

# ----------------------
# Main Flow Control
# ----------------------
if not profile_completed:
    complete_profile()
    st.stop()
elif not onboarding_complete or st.session_state.page == "Onboarding":
    onboarding_process()
    st.stop()

if st.session_state.page == "👤 User Profile":
    user_profile()
else:
    internship_feed()

if st.session_state.firebase_user:
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.query_params = {}
        st.stop()

# ----------------------
# Custom CSS Styling
# ----------------------
st.markdown("""
    <style>
        /* Overall Background & Font */
        body {
            background-color: #f0f2f6;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        /* Header Styling */
        .css-18e3th9 {
            font-size: 2.5rem;
            color: #333333;
            font-weight: 600;
        }
        /* Metric Cards */
        [data-testid="stMetricValue"] {
            font-size: 1.8rem;
            color: #0a3d62;
        }
        [data-testid="stMetricLabel"] {
            font-size: 1rem;
            color: #57606f;
        }
        /* Data Editor and Expander Styling */
        .stDataFrame, .st-expanderHeader, .css-1d391kg {
            background: #ffffff;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.05);
            padding: 16px;
        }
        /* Button Styling */
        .stButton>button {
            background-color: #0a3d62;
            color: #ffffff;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            font-size: 1rem;
            transition: background-color 0.3s ease, transform 0.3s ease;
        }
        .stButton>button:hover {
            background-color: #084c8d;
            transform: scale(1.03);
        }
        /* Container Cards */
        .stContainer {
            background-color: #ffffff;
            border-radius: 12px;
            padding: 20px;
            margin: 10px 0;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }
        /* Sidebar */
        .css-1lcbmhc {
            background-color: #ffffff;
            border-right: 1px solid #e2e2e2;
        }
    </style>
""", unsafe_allow_html=True)
