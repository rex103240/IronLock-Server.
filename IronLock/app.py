 import os
    2 from flask import Flask, jsonify, request
    3 from datetime import datetime
    4 from models import db, License, AccessLog
    5 from sqlalchemy import text
    6 
    7 app = Flask(__name__)
    8 app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_only_change_in_prod')       
    9 app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///server.db')
   10 app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
   11 
   12 db.init_app(app)
   13 
   14 # --- SELF-REPAIRING DATABASE LOGIC ---
   15 with app.app_context():
   16     db.create_all()
   17     try:
   18         # This tells the database: "It's okay if Gym Name is empty for now"
   19         db.session.execute(text("ALTER TABLE licenses ALTER COLUMN gym_name DROP NOT NULL")) 
   20         db.session.commit()
   21         print("Database Repair: Gym Name is now optional.")
   22     except Exception as e:
   23         db.session.rollback()
   24         # If it's SQLite or already fixed, it might fail silently, which is fine
   25         print(f"Database Repair Note: {e}")
   26 
   27 @app.route('/')
   28 def home():
   29     return jsonify({"status": "IronLock Server Online", "time": datetime.utcnow()})
   30 
   31 @app.route('/api/verify', methods=['POST'])
   32 def verify_license():
   33     data = request.json
   34     key = data.get('license_key')
   35     hwid = data.get('hardware_id')
   36     claimed_name = data.get('gym_name')
   37     
   38     if not key or not hwid:
   39         return jsonify({"valid": False, "message": "Missing Data"}), 400
   40         
   41     license_obj = License.query.filter_by(key=key).first()
   42     
   43     if not license_obj:
   44         return jsonify({"valid": False, "message": "Invalid License Key"}), 401
   45     
   46     if license_obj.status != 'active':
   47         return jsonify({"valid": False, "message": "License Suspended"}), 403
   48         
   49     if license_obj.valid_until < datetime.utcnow().date():
   50         license_obj.status = 'expired'
   51         db.session.commit()
   52         return jsonify({"valid": False, "message": "License Expired"}), 403
   53         
   54     if license_obj.gym_name is None:
   55         if not claimed_name:
   56             return jsonify({"valid": True, "needs_registration": True})
   57         license_obj.gym_name = claimed_name
   58         db.session.commit()
   59     
   60     if license_obj.hardware_id is None:
   61         license_obj.hardware_id = hwid
   62         db.session.commit()
   63 
   64     log = AccessLog(license_id=license_obj.id, ip_address=request.remote_addr, message="Validation Success")
   65     license_obj.last_check = datetime.utcnow()
   66     db.session.add(log)
   67     db.session.commit()
   68     
   69     days_left = (license_obj.valid_until - datetime.utcnow().date()).days
   70     
   71     return jsonify({
   72         "valid": True,
   73         "gym_name": license_obj.gym_name,
   74         "expires_in_days": days_left
   75     })
   76 
   77 @app.route('/api/admin/create_key', methods=['POST'])
   78 def create_key():
   79     data = request.json
   80     try:
   81         new_license = License(
   82             key=data['key'],
   83             gym_name=data.get('gym_name'), 
   84             client_email=data.get('client_email'),
   85             valid_until=datetime.strptime(data['valid_until'], "%Y-%m-%d").date()
   86         )
   87         db.session.add(new_license)
   88         db.session.commit()
   89         return jsonify({"message": "Key Created Successfully"})
   90     except Exception as e:
   91         db.session.rollback()
   92         return jsonify({"message": f"Server Error: {str(e)}"}), 500
   93 
   94 if __name__ == '__main__':
   95     app.run(debug=True, port=8000)
