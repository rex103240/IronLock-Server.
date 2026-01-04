import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import secrets
import string
import os
import sys

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
</style>
""", unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---
def generate_key(prefix="IRON"):
    chars = string.ascii_uppercase + string.digits
    parts = [''.join(secrets.choice(chars) for _ in range(4)) for _ in range(3)]
    return f"{prefix}-" + "-".join(parts)

# --- SIDEBAR & NAVIGATION ---
st.sidebar.title("🔐 IronLock Admin")
st.sidebar.markdown("---")
page = st.sidebar.radio("Navigation", [
    "📊 Dashboard", 
    "🔑 License Manager", 
    "🏢 Gym Inspector", 
    "📜 Live Logs"
])
st.sidebar.markdown("---")
st.sidebar.info(f"Server Time: {datetime.utcnow().strftime('%H:%M')}")

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
        
        # Sales last 30 days (New licenses created)
        new_30d = License.query.filter(License.created_at >= datetime.utcnow() - timedelta(days=30)).count()
        
        # Activity last 24h
        pings_24h = AccessLog.query.filter(AccessLog.timestamp >= datetime.utcnow() - timedelta(hours=24)).count()

        # Display Metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Licenses", total, delta=new_30d)
        col2.metric("Active Gyms", active)
        col3.metric("24h Activity", pings_24h)
        col4.metric("Server Status", "Online", delta_color="normal")

        st.markdown("### 📈 Recent Validations")
        logs = AccessLog.query.order_by(AccessLog.timestamp.desc()).limit(10).all()
        
        if logs:
            log_data = []
            for l in logs:
                # Find gym name for this log
                lic = License.query.get(l.license_id)
                gym_name = lic.gym_name if lic else "Unknown"
                log_data.append({
                    "Time": l.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    "Gym": gym_name,
                    "IP Address": l.ip_address,
                    "Result": l.message
                })
            st.dataframe(pd.DataFrame(log_data), use_container_width=True, hide_index=True)
        else:
            st.info("No activity logs found.")

    # ==========================================
    # 2. LICENSE MANAGER
    # ==========================================
    elif "License Manager" in page:
        st.title("License Management")

        # --- GENERATOR TAB ---
        tab1, tab2 = st.tabs(["✨ Create Keys", "🛠️ Manage Existing"])
        
        with tab1:
            st.markdown("### Generate New Licenses")
            with st.form("gen_form"):
                c1, c2 = st.columns(2)
                count = c1.number_input("Quantity", min_value=1, value=1)
                months = c2.number_input("Validity (Months)", min_value=1, value=12)
                
                # Pre-fill (Optional)
                st.markdown("#### Optional Pre-binding")
                client_email = st.text_input("Client Email (Leave empty for blank key)")
                note = st.text_input("Internal Note (e.g. 'Paid via Stripe')")
                
                if st.form_submit_button("🚀 Generate Keys"):
                    expiry = datetime.utcnow().date() + timedelta(days=30*months)
                    new_keys = []
                    
                    for _ in range(count):
                        k = generate_key()
                        lic = License(
                            key=k,
                            valid_until=expiry,
                            client_email=client_email if client_email else None,
                            status='active'
                        )
                        db.session.add(lic)
                        new_keys.append(k)
                    
                    db.session.commit()
                    st.success(f"Successfully generated {count} keys!")
                    st.code("\n".join(new_keys))

        with tab2:
            st.markdown("### Existing Licenses")
            
            # Search Bar
            search_q = st.text_input("Search by Key, Gym Name, or Email", placeholder="Type to search...")
            
            query = License.query
            if search_q:
                term = f"%{search_q}%"
                query = query.filter(
                    (License.key.ilike(term)) | 
                    (License.gym_name.ilike(term)) | 
                    (License.client_email.ilike(term))
                )
            
            licenses = query.order_by(License.created_at.desc()).all()
            
            # Display Table
            if licenses:
                df = pd.DataFrame([{
                    "ID": l.id,
                    "Key": l.key,
                    "Gym Name": l.gym_name or "Unclaimed",
                    "Email": l.client_email or "-",
                    "Status": l.status,
                    "Valid Until": l.valid_until,
                    "HWID Locked": "✅" if l.hardware_id else "❌"
                } for l in licenses])
                
                st.dataframe(df, use_container_width=True, hide_index=True)
                
                st.markdown("---")
                st.markdown("#### ⚡ Quick Actions")
                
                c1, c2, c3 = st.columns([2, 1, 1])
                target_key = c1.selectbox("Select Key to Modify", [l.key for l in licenses])
                target = License.query.filter_by(key=target_key).first()
                
                if target:
                    c2.info(f"Status: {target.status}")
                    
                    action = c3.radio("Action", ["Activate", "Suspend (Lock Out)", "Extend +30 Days", "Reset HWID (Allow New PC)"])
                    
                    if st.button("Apply Change"):
                        if "Activate" in action:
                            target.status = 'active'
                            st.success("License Activated.")
                        elif "Suspend" in action:
                            target.status = 'suspended'
                            st.warning("License Suspended. User will be locked out.")
                        elif "Extend" in action:
                            target.valid_until += timedelta(days=30)
                            st.success("Validity extended by 30 days.")
                        elif "Reset HWID" in action:
                            target.hardware_id = None
                            st.info("Hardware ID cleared. Key can be used on a new machine.")
                        
                        db.session.commit()
                        st.rerun()

    # ==========================================
    # 3. GYM INSPECTOR
    # ==========================================
    elif "Gym Inspector" in page:
        st.title("Gym Inspector")
        st.markdown("View detailed info about registered facilities.")
        
        gyms = License.query.filter(License.gym_name != None).all()
        
        if not gyms:
            st.warning("No gyms have registered yet.")
        else:
            selected_gym = st.selectbox("Select Gym", [f"{g.gym_name} ({g.key})" for g in gyms])
            if selected_gym:
                # Extract key from string
                key = selected_gym.split('(')[1].strip(')')
                gym = License.query.filter_by(key=key).first()
                
                if gym:
                    c1, c2 = st.columns(2)
                    with c1:
                        st.subheader(gym.gym_name)
                        st.write(f"**Email:** {gym.client_email}")
                        st.write(f"**Phone:** {gym.gym_phone or 'N/A'}")
                        st.write(f"**Address:** {gym.gym_address or 'N/A'}")
                    
                    with c2:
                        st.metric("Status", gym.status.upper())
                        st.write(f"**Valid Until:** {gym.valid_until}")
                        st.write(f"**Last Seen:** {gym.last_check.strftime('%Y-%m-%d %H:%M') if gym.last_check else 'Never'}")
                        if gym.additional_info:
                            st.info(f"Extra Info: {gym.additional_info}")

    # ==========================================
    # 4. LIVE LOGS
    # ==========================================
    elif "Live Logs" in page:
        st.title("Audit Trail")
        st.markdown("Real-time stream of server requests.")
        
        if st.button("Refresh Logs"):
            st.rerun()
            
        logs = AccessLog.query.order_by(AccessLog.timestamp.desc()).limit(100).all()
        
        data = []
        for l in logs:
            lic = License.query.get(l.license_id)
            name = lic.gym_name if lic else "Unknown"
            data.append({
                "Timestamp": l.timestamp,
                "Gym": name,
                "IP": l.ip_address,
                "Event": l.message
            })
            
        st.dataframe(pd.DataFrame(data), use_container_width=True)
