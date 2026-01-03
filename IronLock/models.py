from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class AdminUser(db.Model):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False) # Hashed in prod

class License(db.Model):
    __tablename__ = 'licenses'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False, index=True)
    gym_name = db.Column(db.String(100), nullable=True) # Initially NULL for unassigned keys
    client_email = db.Column(db.String(120))
    gym_address = db.Column(db.Text, nullable=True)
    gym_phone = db.Column(db.String(50), nullable=True)
    additional_info = db.Column(db.Text, nullable=True) # JSON or Text blob for hours/etc
    valid_until = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='active') # active, suspended, expired
    hardware_id = db.Column(db.String(100), nullable=True) # Locks to first device
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_check = db.Column(db.DateTime)

class AccessLog(db.Model):
    __tablename__ = 'access_logs'
    id = db.Column(db.Integer, primary_key=True)
    license_id = db.Column(db.Integer, db.ForeignKey('licenses.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45))
    message = db.Column(db.String(200))
