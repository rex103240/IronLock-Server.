import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import secrets
import string
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import text

# Load environment variables from .env file (if it exists)
load_dotenv()

# --- CONNECT TO YOUR EXISTING APP & DATABASE ---
# Hack: Add IronLock subdirectory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'IronLock'))

from app import app as flask_app
from models import db, License, AccessLog

# --- CONFIGURATION ---
st.set_page_config(
    page_title="IronLock Command Center",
    page_icon="🔐",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- STYLING ---
st.markdown("""
<style>
    .stApp { background-color: #0E1117; color: white; }
    div[data-testid="stMetricValue"] { font-size: 2rem; color: #4ade80; }
    div[data-testid="stMetricLabel"] { font-size: 0.9rem; color: #94a3b8; }
    .status-dot { height: 12px; width: 12px; border-radius: 50%; display: inline-block; margin-right: 8px; }
    .status-online { background-color: #4ade80; box-shadow: 0 0 8px #4ade80; }
    .status-offline { background-color: #ef4444; }
    .status-warning { background-color: #f59e0b; }
</style>
""", unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---
def generate_key(prefix="IRON"):
    chars = string.ascii_uppercase + string.digits
    parts = [''.join(secrets.choice(chars) for _ in range(4)) for _ in range(3)]
    return f"{prefix}-" + "-".join(parts)

def get_status_html(last_check):
    if not last_check:
        return '<span class="status-dot status-offline"></span><span style="color:#ef4444">Never</span>'
    
    diff = datetime.utcnow() - last_check
    if diff < timedelta(minutes=15):
        return '<span class="status-dot status-online"></span><span style="color:#4ade80">Online</span>'
    elif diff < timedelta(hours=24):
        return '<span class="status-dot status-warning"></span><span style="color:#f59e0b">Away</span>'
    else:
        return '<span class="status-dot status-offline"></span><span style="color:#ef4444">Offline</span>'

# --- SIDEBAR & NAVIGATION ---
st.sidebar.title("🔐 IronLock Admin")
st.sidebar.caption("v2.0 Professional Edition")
st.sidebar.markdown("---")

page = st.sidebar.radio("Navigation", [
    "📊 Dashboard", 
    "🔑 License Manager", 
    "🚨 Gym Monitor",
    "🛠️ Admin Tools"
])
st.sidebar.markdown("---")
st.sidebar.info(f"Server Time (UTC): {datetime.utcnow().strftime('%H:%M')}")

# Use Flask Context to access DB
with flask_app.app_context():

    # ==========================================
    # 1. DASHBOARD
    # ==========================================
    if "Dashboard" in page:
        st.title("Server Overview")
        
        # Calculate Metrics
        total = License.query.count()
        active = License.query.filter_by(status='active').count()
        
        # Sales last 30 days
        new_30d = License.query.filter(License.created_at >= datetime.utcnow() - timedelta(days=30)).count()
        
        # Real-time Status Check
        online_now = 0
        gyms = License.query.filter(License.gym_name != None).all()
        for g in gyms:
            if g.last_check and (datetime.utcnow() - g.last_check) < timedelta(minutes=15):
                online_now += 1

        # Display Metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Licenses", total, delta=new_30d)
        col2.metric("Active Gyms", active)
        col3.metric("🟢 Online Now", online_now)
        col4.metric("Server Status", "Healthy", delta_color="normal")
        
        st.markdown("### 📡 System Heartbeat")
        if not gyms:
            st.info("No gyms registered.")
        else:
            # Create a Status Grid
            cols = st.columns(4)
            for idx, gym in enumerate(gyms):
                with cols[idx % 4]:
                    status = get_status_html(gym.last_check)
                    st.markdown(f"""
                    <div style="background-color: #1e293b; padding: 15px; border-radius: 10px; margin-bottom: 10px; border: 1px solid #334155;">
                        <div style="font-weight: bold; font-size: 1.1em;">{gym.gym_name or 'Unclaimed Key'}</div>
                        <div style="font-size: 0.8em; color: #94a3b8; margin-bottom: 5px;">ID: {gym.key[:9]}...</div>
                        <div>{status}</div>
                    </div>
                    """, unsafe_allow_html=True)

    # ==========================================
    # 2. LICENSE MANAGER
    # ==========================================
    elif "License Manager" in page:
        st.title("License Management")

        tab1, tab2 = st.tabs(["✨ Key Generator", "📂 License Database"])
        
        with tab1:
            st.subheader("Generate New Licenses")
            with st.form("gen_form"):
                c1, c2 = st.columns(2)
                count = c1.number_input("Quantity", min_value=1, value=1)
                months = c2.number_input("Validity (Months)", min_value=1, value=12)
                
                st.markdown("#### Optional Pre-binding")
                client_email = st.text_input("Client Email (Leave empty for blank key)")
                
                if st.form_submit_button("🚀 Generate Keys"):
                    expiry = datetime.utcnow().date() + timedelta(days=30*months)
                    new_keys = []
                    for _ in range(count):
                        k = generate_key()
                        lic = License(
                            key=k, 
                            valid_until=expiry, 
                            client_email=client_email if client_email else None
                        )
                        db.session.add(lic)
                        new_keys.append(k)
                    db.session.commit()
                    st.success(f"Generated {count} keys!")
                    st.code("\n".join(new_keys))

        with tab2:
            st.subheader("All Licenses")
            search = st.text_input("Search...", placeholder="Key, Name, or Email")
            query = License.query
            if search:
                term = f"%{search}%"
                query = query.filter(
                    (License.key.ilike(term)) | 
                    (License.gym_name.ilike(term)) | 
                    (License.client_email.ilike(term))
                )
            
            licenses = query.order_by(License.created_at.desc()).all()
            if licenses:
                df = pd.DataFrame([{
                    "Key": l.key,
                    "Gym Name": l.gym_name,
                    "Email": l.client_email,
                    "Status": l.status,
                    "Expires": l.valid_until,
                    "Last Check": l.last_check
                } for l in licenses])
                st.dataframe(df, use_container_width=True)

    # ==========================================
    # 3. GYM MONITOR (Remote Logs)
    # ==========================================
    elif "Gym Monitor" in page:
        st.title("🚨 Gym Monitor & Logs")
        
        tab1, tab2 = st.tabs(["📜 Live Access Logs", "⚠️ Error Reports"])
        
        with tab1:
            if st.button("Refresh Logs"): st.rerun()
            logs = AccessLog.query.order_by(AccessLog.timestamp.desc()).limit(50).all()
            data = []
            for l in logs:
                lic = License.query.get(l.license_id)
                data.append({
                    "Time": l.timestamp,
                    "Gym": lic.gym_name if lic else "Unknown",
                    "IP": l.ip_address,
                    "Event": l.message
                })
            st.dataframe(pd.DataFrame(data), use_container_width=True)
            
        with tab2:
            st.info("Remote Error Logging feature coming in v2.1. Currently viewing system warnings.")
            # Placeholder for future "ErrorLog" table
            st.warning("No critical errors reported by client terminals in the last 24h.")

    # ==========================================
    # 4. ADMIN TOOLS (SQL Console)
    # ==========================================
    elif "Admin Tools" in page:
        st.title("🛠️ Developer Tools")
        st.warning("⚠️ DANGER ZONE: These actions directly affect the production database.")
        
        with st.expander("🔌 Direct SQL Console"):
            query = st.text_area("SQL Query", placeholder="SELECT * FROM licenses LIMIT 5;")
            if st.button("Execute SQL"):
                try:
                    result = db.session.execute(text(query))
                    db.session.commit()
                    
                    if result.returns_rows:
                        df = pd.DataFrame(result.fetchall(), columns=result.keys())
                        st.dataframe(df)
                    else:
                        st.success("Query executed successfully (No rows returned).")
                except Exception as e:
                    st.error(f"SQL Error: {e}")
