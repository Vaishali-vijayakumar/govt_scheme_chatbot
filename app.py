from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import logging
from datetime import datetime, timedelta
import uuid
import os
from dotenv import load_dotenv
import openai
import redis
import bleach

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Configuration
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24).hex())
app.config['RATE_LIMIT_STRATEGY'] = 'fixed-window'

# Initialize services
openai.api_key = os.getenv('OPENAI_API_KEY')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Session storage initialization
user_sessions = {}  # In-memory fallback storage

# Redis connection
try:
    r = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        password=os.getenv('REDIS_PASSWORD'),
        db=0,
        decode_responses=True
    )
    r.ping()  # Test connection
except redis.ConnectionError:
    logger.warning("Redis not available, using in-memory storage")
    r = None

# Conversation steps
STEPS = {
    "WELCOME": "0",
    "MAIN_MENU": "1",
    "ELIGIBILITY_AGE": "2",
    "ELIGIBILITY_INCOME": "3",
    "ELIGIBILITY_OCCUPATION": "4",
    "ELIGIBILITY_LOCATION": "5",
    "SCHEME_RESULTS": "6"
}

# Enhanced scheme database
scheme_database = {
    "PM-KISAN": {
        "category": "Agriculture",
        "steps": "1. Visit https://pmkisan.gov.in\n2. Click 'Farmers Corner' > 'New Farmer Registration'\n3. Submit Aadhaar, bank & land details",
        "eligibility": {"min_age": 18, "occupation": ["farmer"], "income_max": None},
        "benefits": "₹6,000/year in 3 installments",
        "deadline": "Ongoing",
        "link": "https://pmkisan.gov.in"
    },
    "PM-AWAS-YOJANA": {
        "category": "Housing",
        "steps": "1. Contact local municipal office\n2. Submit proof of residence and income\n3. Get approval and subsidy",
        "eligibility": {"min_age": 21, "occupation": None, "income_max": 180000},
        "benefits": "Housing subsidy up to ₹2.67 lakh",
        "deadline": "31-12-2024",
        "link": "https://pmaymis.gov.in"
    }
}

def get_session(session_id):
    """Get session from Redis or fallback to memory"""
    if r:
        session_data = r.hgetall(f"session:{session_id}")
        return session_data if session_data else None
    return user_sessions.get(session_id)

def set_session(session_id, data):
    """Store session in Redis or memory"""
    if r:
        r.hset(f"session:{session_id}", mapping=data)
        r.expire(f"session:{session_id}", 3600)  # 1 hour expiry
    else:
        user_sessions[session_id] = data

def sanitize_input(text):
    """Sanitize user input to prevent XSS"""
    return bleach.clean(text, tags=[], strip=True)

def validate_age(age_str):
    """Validate age input"""
    try:
        age = int(age_str)
        return 10 <= age <= 120
    except ValueError:
        return False

def get_ai_response(prompt):
    """Get contextual response from OpenAI"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You're a helpful government scheme assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            timeout=10
        )
        return response.choices[0].message['content']
    except Exception as e:
        logger.error(f"AI Error: {str(e)}")
        return None

@app.route('/health')
def health_check():
    """Endpoint for health monitoring"""
    return jsonify({
        "status": "healthy",
        "scheme_count": len(scheme_database),
        "redis_connected": bool(r)
    }), 200

@app.route("/")
def index():
    """Serve the frontend"""
    return render_template("index.html")

@app.route("/api/chat", methods=['POST'])
@limiter.limit("10 per minute")
def chatbot():
    try:
        data = request.get_json()
        incoming_msg = sanitize_input(data.get('message', '').strip())
        sender_id = data.get('sender', str(uuid.uuid4()))
        payload = data.get('payload', incoming_msg)  # Get payload if available
        
        # Initialize or retrieve session
        session = get_session(sender_id) or {
            "step": STEPS["WELCOME"],
            "context": "{}",
            "created_at": str(datetime.now()),
            "last_active": str(datetime.now())
        }
        
        # Handle reset command
        if "start over" in incoming_msg.lower():
            session["step"] = STEPS["WELCOME"]
            session["context"] = "{}"
            set_session(sender_id, session)
            return handle_conversation_step(session["step"], "", {})
        
        # Convert string context to dict if needed
        context = eval(session["context"]) if isinstance(session["context"], str) else session["context"]
        
        # Get response for current step
        response = handle_conversation_step(session["step"], payload or incoming_msg, context)
        
        # Update session if step should change
        if "next_step" in response:
            session["step"] = response["next_step"]
        
        # Update context if changed
        if "context_update" in response:
            session["context"] = str(response["context_update"])
        
        # Always update last active time
        session["last_active"] = str(datetime.now())
        set_session(sender_id, session)
        
        return jsonify({
            "text": response["text"],
            "quick_replies": response.get("quick_replies", []),
            "buttons": response.get("buttons", [])
        })
    except Exception as e:
        logger.error(f"Chatbot error: {str(e)}")
        return jsonify({"text": "An error occurred. Please try again later."}), 500

def handle_conversation_step(step, incoming_msg, context):
    """Handle conversation logic for each step"""
    if step == STEPS["WELCOME"]:
        return {
            "text": "Welcome to the Government Scheme Assistant! Would you like to:",
            "quick_replies": [
                {"title": "Check Eligibility", "payload": "eligibility"},
                {"title": "Browse Schemes", "payload": "browse"},
                {"title": "Get Help", "payload": "help"}
            ],
            "next_step": STEPS["MAIN_MENU"]
        }
    
    elif step == STEPS["MAIN_MENU"]:
        if incoming_msg.lower() == "eligibility":
            return {
                "text": "Let's check your eligibility. What is your age in years? (You can type the number or select an option)",
                "quick_replies": [
                    {"title": "Under 18", "payload": "17"},
                    {"title": "18-30", "payload": "25"},
                    {"title": "31-45", "payload": "38"},
                    {"title": "46-60", "payload": "53"},
                    {"title": "60+", "payload": "65"}
                ],
                "next_step": STEPS["ELIGIBILITY_AGE"]
            }
        elif incoming_msg.lower() == "browse":
            schemes = list(scheme_database.keys())[:5]
            return {
                "text": "Here are some key government schemes:\n\n" +
                        "\n".join([f"• {name}: {scheme_database[name]['benefits']}" for name in schemes]),
                "quick_replies": [{"title": name, "payload": f"details_{name}"} for name in schemes] +
                                [{"title": "See More", "payload": "more_schemes"}]
            }
        else:
            return {
                "text": get_ai_response(incoming_msg) or "I can help with government schemes. Please ask about eligibility, benefits, or application process.",
                "quick_replies": [
                    {"title": "Check Eligibility", "payload": "eligibility"},
                    {"title": "Browse Schemes", "payload": "browse"}
                ]
            }
    
    elif step == STEPS["ELIGIBILITY_AGE"]:
        try:
            # Check if it's a quick reply payload (which should be a number)
            if incoming_msg.isdigit():
                age = int(incoming_msg)
            else:
                # Try to extract number from text
                age = int(''.join(filter(str.isdigit, incoming_msg)))
            
            if not validate_age(str(age)):
                return {"text": "Please enter a valid age between 10 and 120 years"}
            
            context['age'] = age
            return {
                "text": "What is your approximate annual family income in ₹?",
                "quick_replies": [
                    {"title": "Under 1L", "payload": "100000"},
                    {"title": "1L-3L", "payload": "200000"},
                    {"title": "3L-5L", "payload": "400000"},
                    {"title": "5L-10L", "payload": "750000"},
                    {"title": "10L+", "payload": "1000000"}
                ],
                "context_update": context,
                "next_step": STEPS["ELIGIBILITY_INCOME"]
            }
        except:
            return {"text": "Please enter a valid age number (e.g., 25) or select an option"}
    
    elif step == STEPS["ELIGIBILITY_INCOME"]:
        try:
            if incoming_msg.isdigit():
                income = int(incoming_msg)
            else:
                income = int(''.join(filter(str.isdigit, incoming_msg)))
            context['income'] = income
            return {
                "text": "What is your occupation/profession?",
                "quick_replies": [
                    {"title": "Farmer", "payload": "farmer"},
                    {"title": "Student", "payload": "student"},
                    {"title": "Business", "payload": "business"},
                    {"title": "Employee", "payload": "employee"},
                    {"title": "Other", "payload": "other"}
                ],
                "context_update": context,
                "next_step": STEPS["ELIGIBILITY_OCCUPATION"]
            }
        except:
            return {"text": "Please enter a valid income amount (e.g., 250000) or select an option"}
    
    elif step == STEPS["ELIGIBILITY_OCCUPATION"]:
        context['occupation'] = incoming_msg.lower()
        return {
            "text": "Which state do you live in?",
            "quick_replies": [
                {"title": "Tamil Nadu", "payload": "tamil nadu"},
                {"title": "Other State", "payload": "other"}
            ],
            "context_update": context,
            "next_step": STEPS["ELIGIBILITY_LOCATION"]
        }
    
    elif step == STEPS["ELIGIBILITY_LOCATION"]:
        context['state'] = incoming_msg.lower()
        
        # Find matching schemes
        eligible_schemes = []
        for name, data in scheme_database.items():
            eligible = True
            
            # Check age
            if 'min_age' in data['eligibility'] and context.get('age', 0) < data['eligibility']['min_age']:
                eligible = False
            
            # Check income
            if data['eligibility'].get('income_max') and context.get('income', 0) > data['eligibility']['income_max']:
                eligible = False
            
            # Check occupation
            if data['eligibility'].get('occupation'):
                if isinstance(data['eligibility']['occupation'], list):
                    if context.get('occupation') not in data['eligibility']['occupation']:
                        eligible = False
                elif context.get('occupation') != data['eligibility']['occupation']:
                    eligible = False
            
            # Check state
            if data['eligibility'].get('state'):
                if context.get('state') != data['eligibility']['state'].lower():
                    eligible = False
            
            if eligible:
                eligible_schemes.append(name)
        
        if eligible_schemes:
            scheme_list = "\n\n".join([
                f"• {name}:\n  Benefits: {scheme_database[name]['benefits']}\n  Apply: {scheme_database[name]['link']}"
                for name in eligible_schemes
            ])
            return {
                "text": f"Based on your details, you may be eligible for these schemes:\n\n{scheme_list}\n\nWould you like to check eligibility for other schemes?",
                "quick_replies": [
                    {"title": "Yes", "payload": "eligibility"},
                    {"title": "No", "payload": "no"}
                ],
                "next_step": STEPS["MAIN_MENU"]
            }
        else:
            return {
                "text": "We couldn't find any schemes matching your profile. Would you like to try different criteria?",
                "quick_replies": [
                    {"title": "Try Again", "payload": "eligibility"},
                    {"title": "Browse All", "payload": "browse"}
                ],
                "next_step": STEPS["MAIN_MENU"]
            }
    
    else:
        return {
            "text": "I didn't understand that. Type 'help' for options or 'start over' to begin again.",
            "quick_replies": [
                {"title": "Help", "payload": "help"},
                {"title": "Start Over", "payload": "start_over"}
            ],
            "next_step": STEPS["WELCOME"]
        }

@app.route("/api/schemes", methods=['GET'])
def list_schemes():
    """API endpoint to list all schemes"""
    try:
        scheme_type = request.args.get('type', 'all')
        
        if scheme_type == 'central':
            schemes = [name for name, data in scheme_database.items() 
                      if not data['eligibility'].get('state')]
        elif scheme_type == 'tn':
            schemes = [name for name, data in scheme_database.items() 
                      if data['eligibility'].get('state') == "Tamil Nadu"]
        else:
            schemes = list(scheme_database.keys())
            
        return jsonify({
            "schemes": schemes[:100],
            "count": len(schemes),
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Scheme list error: {str(e)}")
        return jsonify({"error": "Could not retrieve schemes"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)