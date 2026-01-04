import os
import base64
from flask import Flask, jsonify, request
from datetime import datetime
from models import db, License, AccessLog
from sqlalchemy import text
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_only_change_in_prod')

# Load Private Key for Signing
PRIVATE_KEY = None
try:
    key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'private_key.pem')
    with open(key_path, "rb") as key_file:
        PRIVATE_KEY = serialization.load_pem_private_key(
            key_file.read(),
            password=None
        )
    print("Security: Private Key Loaded Successfully.")
except Exception as e:
    print(f"Security Warning: Could not load private key: {e}")

# Fix for Render/Neon: SQLAlchemy needs 'postgresql://' not 'postgres://'
uri = os.environ.get("DATABASE_URL", "sqlite:///server.db")
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Safe Database Initialization
with app.app_context():
    try:
        db.create_all()
        # Only try to alter if we are on a real database (Postgres)
        if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI']:
            # Auto-Migration for new fields
            try:
                db.session.execute(text("ALTER TABLE licenses ALTER COLUMN gym_name DROP NOT NULL"))
            except: pass
            
            try:
                db.session.execute(text("ALTER TABLE licenses ADD COLUMN gym_address TEXT"))
                db.session.execute(text("ALTER TABLE licenses ADD COLUMN gym_phone VARCHAR(50)"))
                db.session.execute(text("ALTER TABLE licenses ADD COLUMN additional_info TEXT"))
            except: pass
            
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Startup Info: {e}")

@app.route('/')
def home():
    return jsonify({"status": "IronLock Server Online", "time": datetime.utcnow()})

@app.route('/api/verify', methods=['POST'])
def verify_license():
    try:
        data = request.json
        key = data.get('license_key')
        hwid = data.get('hardware_id')
        claimed_name = data.get('gym_name')
        client_email = data.get('email')
        
        # New Data Points
        gym_address = data.get('gym_address')
        gym_phone = data.get('gym_phone')
        gym_open = data.get('gym_open_time')
        gym_close = data.get('gym_close_time')
        currency = data.get('currency')
        
        if not key or not hwid:
            return jsonify({"valid": False, "message": "Missing Data"}), 400
            
        license_obj = License.query.filter_by(key=key).first()
        
        if not license_obj:
            return jsonify({"valid": False, "message": "Invalid License Key"}), 401
        
        if license_obj.status != 'active':
            return jsonify({"valid": False, "message": "License Suspended"}), 403
            
        if license_obj.valid_until < datetime.utcnow().date():
            license_obj.status = 'expired'
            db.session.commit()
            return jsonify({"valid": False, "message": "License Expired"}), 403
            
        # 1. BIND OR UPDATE GYM NAME
        # If DB has no name, or an empty name, take the one from the client
        if not license_obj.gym_name or license_obj.gym_name.strip() == "":
            if not claimed_name:
                return jsonify({"valid": True, "needs_registration": True})
            license_obj.gym_name = claimed_name
            db.session.commit()
        
        # 2. BIND EMAIL & OTHER DETAILS (Update if missing or empty)
        if not license_obj.client_email and client_email:
            license_obj.client_email = client_email
        
        if not license_obj.gym_address and gym_address:
            license_obj.gym_address = gym_address
            
        if not license_obj.gym_phone and gym_phone:
            license_obj.gym_phone = gym_phone
            
        if not license_obj.additional_info and (gym_open or currency):
            license_obj.additional_info = f"Open: {gym_open}-{gym_close} | Currency: {currency}"
            
        db.session.commit()

        # 3. BIND HWID
        if license_obj.hardware_id is None:
            license_obj.hardware_id = hwid
            db.session.commit()
        elif license_obj.hardware_id != hwid:
            return jsonify({"valid": False, "message": "License used on another device (HWID Mismatch)"}), 403

        # Log the actual action message from client (e.g. "Admin Login")
        action_msg = data.get('message', "Validation Success")
        log = AccessLog(license_id=license_obj.id, ip_address=request.remote_addr, message=action_msg)
        license_obj.last_check = datetime.utcnow()
        db.session.add(log)
        db.session.commit()
        
        # --- DIGITAL SIGNING ---
        signature_b64 = None
        expires_str = license_obj.valid_until.strftime("%Y-%m-%d")
        
        if PRIVATE_KEY:
            # Data to sign: Key + HWID + Expiry (Ensures none of these can be tampered)
            payload_str = f"{license_obj.key}|{hwid}|{expires_str}"
            signature = PRIVATE_KEY.sign(
                payload_str.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            signature_b64 = base64.b64encode(signature).decode('utf-8')
        # -----------------------

        return jsonify({
            "valid": True,
            "gym_name": license_obj.gym_name,
            "expires_in_days": (license_obj.valid_until - datetime.utcnow().date()).days,
            "signature": signature_b64,
            "expiry_date": expires_str
        })
    except Exception as e:
        return jsonify({"valid": False, "message": f"System Error: {str(e)}"}), 500

@app.route('/api/admin/create_key', methods=['POST'])
def create_key():
    data = request.json
    try:
        # Check if key already exists
        if License.query.filter_by(key=data['key']).first():
            return jsonify({"message": "Error: Key already exists"}), 400
            
        new_license = License(
            key=data['key'],
            gym_name=data.get('gym_name'), 
            client_email=data.get('client_email'),
            valid_until=datetime.strptime(data['valid_until'], "%Y-%m-%d").date()
        )
        db.session.add(new_license)
        db.session.commit()
        return jsonify({"message": "Key Created Successfully"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Server Error: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)