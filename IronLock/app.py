import os
from flask import Flask, jsonify, request
from datetime import datetime
from models import db, License, AccessLog

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_only_change_in_prod')
# Use PostgreSQL URL if available, else local sqlite for dev
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///server.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Helper to init DB
with app.app_context():
    db.create_all()

@app.route('/')
def home():
    return jsonify({"status": "IronLock Server Online", "time": datetime.utcnow()})

@app.route('/api/verify', methods=['POST'])
def verify_license():
    data = request.json
    key = data.get('license_key')
    hwid = data.get('hardware_id')
    
    if not key or not hwid:
        return jsonify({"valid": False, "message": "Missing Data"}), 400
        
    license_obj = License.query.filter_by(key=key).first()
    
    # 1. Check Existence
    if not license_obj:
        return jsonify({"valid": False, "message": "Invalid License Key"}), 401
    
    # 2. Check Status
    if license_obj.status != 'active':
        return jsonify({"valid": False, "message": "License Suspended"}), 403
        
    # 3. Check Expiry
    if license_obj.valid_until < datetime.utcnow().date():
        license_obj.status = 'expired'
        db.session.commit()
        return jsonify({"valid": False, "message": "License Expired"}), 403
        
    # 4. Hardware Lock (Optional: Bind to first seen device)
    if license_obj.hardware_id is None:
        license_obj.hardware_id = hwid
        db.session.commit()
    # elif license_obj.hardware_id != hwid:
    #     # Strict mode: Reject if hardware ID doesn't match
    #     # For now, we allow multiple devices per gym as per your request
    #     pass

    # Log the check
    log = AccessLog(license_id=license_obj.id, ip_address=request.remote_addr, message="Validation Success")
    license_obj.last_check = datetime.utcnow()
    db.session.add(log)
    db.session.commit()
    
    days_left = (license_obj.valid_until - datetime.utcnow().date()).days
    
    return jsonify({
        "valid": True,
        "gym_name": license_obj.gym_name,
        "expires_in_days": days_left
    })

# Admin Endpoint to Create Keys (Protected in Prod)
@app.route('/api/admin/create_key', methods=['POST'])
def create_key():
    # In real life, protect this with an Admin Password check!
    data = request.json
    new_license = License(
        key=data['key'],
        gym_name=data['gym_name'],
        client_email=data.get('client_email'),
        valid_until=datetime.strptime(data['valid_until'], "%Y-%m-%d").date()
    )
    db.session.add(new_license)
    db.session.commit()
    return jsonify({"message": "Key Created Successfully"})

if __name__ == '__main__':
    app.run(debug=True, port=8000)
