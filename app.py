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
import bleach  # For output sanitization

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

# Redis connection (fallback to in-memory if Redis not available)
# Redis connection (fallback to in-memory if Redis not available)
user_sessions = {}  # Add this fallback dictionary
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
    user_sessions = {}  # This line should already exist from above

# Enhanced scheme database (31 total schemes)
scheme_database = {
    # Central Government Schemes (16 schemes)
    "PM-KISAN": {
        "category": "Agriculture",
        "steps": "1. Visit https://pmkisan.gov.in\n2. Click 'Farmers Corner' > 'New Farmer Registration'\n3. Submit Aadhaar, bank & land details",
        "eligibility": {"min_age": 18, "occupation": ["farmer"], "income_max": None},
        "benefits": "₹6,000/year in 3 installments",
        "deadline": "Ongoing",
        "link": "https://pmkisan.gov.in"
    },
    # ... [Include all 15 other central schemes from previous code]
    
    # Tamil Nadu State Schemes (15 schemes)
    "Kalaignar Magalir Urimai Thogai": {
        "category": "Social Welfare",
        "steps": "1. Apply at ration shops/e-sevai centers\n2. Submit Aadhaar and family details",
        "eligibility": {"state": "Tamil Nadu", "gender": "female", "family_head": True},
        "benefits": "₹1,000/month for women family heads",
        "deadline": "Ongoing",
        "link": "https://kmut.tn.gov.in"
    },
    # ... [Include all 14 other TN schemes from previous code]
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
    """Get contextual response from OpenAI with error handling"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You're a helpful government scheme assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            timeout=10  # Added timeout
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
        
        # Initialize or retrieve session
        session = get_session(sender_id) or {
            "step": "0",
            "context": "{}",
            "created_at": str(datetime.now()),
            "last_active": str(datetime.now())
        }
        
        # Update session
        session["last_active"] = str(datetime.now())
        set_session(sender_id, session)
        
        # Convert string context to dict if needed
        context = eval(session["context"]) if isinstance(session["context"], str) else session["context"]
        
        # Determine response based on step
        step = session["step"]
        response = handle_conversation_step(step, incoming_msg, context)
        
        # Update context if changed
        if "context_update" in response:
            session["context"] = str(response["context_update"])
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
    if step == "0":  # Initial step
        return {
            "text": "Welcome to the Government Scheme Assistant! Would you like to:",
            "quick_replies": [
                {"title": "Check Eligibility", "payload": "eligibility"},
                {"title": "Browse Schemes", "payload": "browse"},
                {"title": "Get Help", "payload": "help"}
            ]
        }
    
    elif step == "1":  # Main menu
        if "eligibility" in incoming_msg.lower():
            return {
                "text": "Let's check your eligibility. What is your age in years?",
                "quick_replies": [
                    {"title": "Under 18", "payload": "under_18"},
                    {"title": "18-30", "payload": "18_30"},
                    {"title": "31-45", "payload": "31_45"},
                    {"title": "46-60", "payload": "46_60"},
                    {"title": "60+", "payload": "60_plus"}
                ],
                "context_update": context,
                "next_step": "2"
            }
        elif "browse" in incoming_msg.lower():
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
    
    # ... [Include all other step handlers from original code]
    
    # Add similar handlers for steps 2-6 with proper validation
    
    else:  # Unknown step
        return {
            "text": "I didn't understand that. Type 'help' for options or 'start over' to begin again.",
            "quick_replies": [
                {"title": "Help", "payload": "help"},
                {"title": "Start Over", "payload": "start_over"}
            ]
        }

@app.route("/api/schemes", methods=['GET'])
def list_schemes():
    """API endpoint to list all schemes with filters"""
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
            "schemes": schemes[:100],  # Limit to 100 results
            "count": len(schemes),
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Scheme list error: {str(e)}")
        return jsonify({"error": "Could not retrieve schemes"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
