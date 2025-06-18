from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import os
from datetime import timedelta
from models import db, User, Scheme, Application
from auth import hash_password, check_password
import uuid

load_dotenv()

app = Flask(__name__)
CORS(app, supports_credentials=True)

# Configuration
app.config['MONGO_URI'] = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/myscheme')
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET', 'super-secret-key')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=5)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit

# Initialize extensions
db.init_app(app)
jwt = JWTManager(app)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.route('/')
def home():
    return jsonify({"message": "Welcome to MyScheme API"})

# Auth Routes
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    aadhar = data.get('aadhar')
    phone = data.get('phone')
    
    if not all([name, email, password, aadhar, phone]):
        return jsonify({"error": "All fields are required"}), 400
    
    if User.find_by_email(email):
        return jsonify({"error": "Email already exists"}), 400
    
    hashed_pw = hash_password(password)
    user = User(name=name, email=email, password=hashed_pw, 
                aadhar=aadhar, phone=phone, role='user')
    user.save()
    
    access_token = create_access_token(identity={
        'id': str(user.id),
        'role': user.role
    })
    
    return jsonify({
        "token": access_token,
        "user": {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role
        }
    }), 201

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    user = User.find_by_email(email)
    if not user or not check_password(password, user.password):
        return jsonify({"error": "Invalid credentials"}), 401
    
    access_token = create_access_token(identity={
        'id': str(user.id),
        'role': user.role
    })
    
    return jsonify({
        "token": access_token,
        "user": {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role
        }
    })

@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def get_current_user():
    current_user = get_jwt_identity()
    user = User.find_by_id(current_user['id'])
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role
    })

# Scheme Routes
@app.route('/api/schemes', methods=['GET'])
def get_schemes():
    schemes = Scheme.get_all()
    return jsonify([scheme.to_dict() for scheme in schemes])

@app.route('/api/schemes/<scheme_id>', methods=['GET'])
def get_scheme(scheme_id):
    scheme = Scheme.find_by_id(scheme_id)
    if not scheme:
        return jsonify({"error": "Scheme not found"}), 404
    return jsonify(scheme.to_dict())

@app.route('/api/schemes', methods=['POST'])
@jwt_required()
def create_scheme():
    current_user = get_jwt_identity()
    if current_user['role'] != 'admin':
        return jsonify({"error": "Admin access required"}), 403
    
    data = request.get_json()
    required_fields = ['name', 'description', 'eligibility', 'benefits', 'documentsRequired']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400
    
    scheme = Scheme(
        name=data['name'],
        description=data['description'],
        eligibility=data['eligibility'],
        benefits=data['benefits'],
        documentsRequired=data['documentsRequired'],
        link=data.get('link', '')
    )
    scheme.save()
    
    return jsonify(scheme.to_dict()), 201

# Application Routes
@app.route('/api/applications', methods=['POST'])
@jwt_required()
def create_application():
    current_user = get_jwt_identity()
    
    if 'files' not in request.files:
        return jsonify({"error": "No files uploaded"}), 400
    
    files = request.files.getlist('files')
    data = request.form
    scheme_id = data.get('schemeId')
    answers = data.get('answers')
    
    if not scheme_id:
        return jsonify({"error": "Scheme ID is required"}), 400
    
    scheme = Scheme.find_by_id(scheme_id)
    if not scheme:
        return jsonify({"error": "Scheme not found"}), 404
    
    filenames = []
    for file in files:
        if file.filename == '':
            continue
        filename = secure_filename(f"{uuid.uuid4()}-{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        filenames.append(filename)
    
    application = Application(
        user_id=current_user['id'],
        scheme_id=scheme_id,
        answers=answers,
        documents=filenames,
        status='pending'
    )
    application.save()
    
    return jsonify(application.to_dict()), 201

@app.route('/api/applications/user', methods=['GET'])
@jwt_required()
def get_user_applications():
    current_user = get_jwt_identity()
    applications = Application.find_by_user(current_user['id'])
    return jsonify([app.to_dict() for app in applications])

@app.route('/api/applications/admin', methods=['GET'])
@jwt_required()
def get_all_applications():
    current_user = get_jwt_identity()
    if current_user['role'] != 'admin':
        return jsonify({"error": "Admin access required"}), 403
    
    applications = Application.get_all()
    return jsonify([app.to_dict() for app in applications])

@app.route('/api/applications/<app_id>/status', methods=['PUT'])
@jwt_required()
def update_application_status(app_id):
    current_user = get_jwt_identity()
    if current_user['role'] != 'admin':
        return jsonify({"error": "Admin access required"}), 403
    
    data = request.get_json()
    status = data.get('status')
    if status not in ['pending', 'approved', 'rejected']:
        return jsonify({"error": "Invalid status"}), 400
    
    application = Application.find_by_id(app_id)
    if not application:
        return jsonify({"error": "Application not found"}), 404
    
    application.status = status
    application.save()
    
    return jsonify(application.to_dict())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
