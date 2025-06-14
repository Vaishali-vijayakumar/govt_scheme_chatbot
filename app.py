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

# Enhanced scheme database with 20 schemes (10 Central + 10 Tamil Nadu)
scheme_database = {
    # Central Government Schemes (10)
    "PM-KISAN": {
        "category": "Agriculture",
        "steps": "1. Visit https://pmkisan.gov.in\n2. Click 'Farmers Corner' > 'New Farmer Registration'\n3. Submit Aadhaar, bank & land details",
        "eligibility": {"min_age": 18, "occupation": ["farmer"], "income_max": None, "state": None},
        "benefits": "₹6,000/year in 3 installments",
        "deadline": "Ongoing",
        "link": "https://pmkisan.gov.in"
    },
    "PM-AWAS-YOJANA": {
        "category": "Housing",
        "steps": "1. Contact local municipal office\n2. Submit proof of residence and income\n3. Get approval and subsidy",
        "eligibility": {"min_age": 21, "occupation": None, "income_max": 180000, "state": None},
        "benefits": "Housing subsidy up to ₹2.67 lakh",
        "deadline": "31-12-2024",
        "link": "https://pmaymis.gov.in"
    },
    "AYUSHMAN BHARAT": {
        "category": "Healthcare",
        "steps": "1. Check eligibility at https://pmjay.gov.in\n2. Visit empaneled hospital with Aadhaar\n3. Get free treatment up to ₹5 lakh",
        "eligibility": {"min_age": None, "occupation": None, "income_max": None, "state": None},
        "benefits": "Health insurance cover of ₹5 lakh/year",
        "deadline": "Ongoing",
        "link": "https://pmjay.gov.in"
    },
    "PRADHAN MANTRI UJJWALA YOJANA": {
        "category": "Women Welfare",
        "steps": "1. Submit application with Aadhaar and BPL card\n2. Get LPG connection with subsidy",
        "eligibility": {"min_age": 18, "occupation": None, "income_max": None, "state": None},
        "benefits": "Free LPG connection with ₹1600 subsidy",
        "deadline": "Ongoing",
        "link": "https://www.pmuy.gov.in"
    },
    "STAND UP INDIA": {
        "category": "Entrepreneurship",
        "steps": "1. Approach any Scheduled Commercial Bank\n2. Submit business plan and documents\n3. Get loan approval",
        "eligibility": {"min_age": 18, "occupation": ["SC/ST", "women"], "income_max": None, "state": None},
        "benefits": "Bank loan between ₹10 lakh to ₹1 crore",
        "deadline": "Ongoing",
        "link": "https://www.standupmitra.in"
    },
    "PRADHAN MANTRI MUDRA YOJANA": {
        "category": "Small Business",
        "steps": "1. Approach any bank/MFI\n2. Submit business details and KYC\n3. Get loan up to ₹10 lakh",
        "eligibility": {"min_age": 18, "occupation": ["small business"], "income_max": None, "state": None},
        "benefits": "Collateral-free loans up to ₹10 lakh",
        "deadline": "Ongoing",
        "link": "https://www.mudra.org.in"
    },
    "PRADHAN MANTRI JEEVAN JYOTI BIMA YOJANA": {
        "category": "Insurance",
        "steps": "1. Link bank account with Aadhaar\n2. Pay premium of ₹330/year\n3. Get life cover automatically",
        "eligibility": {"min_age": 18, "occupation": None, "income_max": None, "state": None},
        "benefits": "Life insurance cover of ₹2 lakh",
        "deadline": "31-03-2024",
        "link": "https://www.jansuraksha.gov.in"
    },
    "ATAL PENSION YOJANA": {
        "category": "Pension",
        "steps": "1. Open account with any bank\n2. Choose pension amount (₹1000-5000)\n3. Start monthly contributions",
        "eligibility": {"min_age": 18, "occupation": None, "income_max": None, "state": None},
        "benefits": "Guaranteed pension after 60 years",
        "deadline": "Ongoing",
        "link": "https://www.jansuraksha.gov.in"
    },
    "PRADHAN MANTRI SHRAM YOGI MAAN-DHAN": {
        "category": "Pension",
        "steps": "1. Visit CSC center with Aadhaar\n2. Pay monthly contribution (₹55-200)\n3. Get pension after 60 years",
        "eligibility": {"min_age": 18, "occupation": ["unorganized worker"], "income_max": 15000, "state": None},
        "benefits": "Monthly pension of ₹3000 after 60",
        "deadline": "Ongoing",
        "link": "https://maandhan.in"
    },
    "PRADHAN MANTRI KISAN MAAN-DHAN YOJANA": {
        "category": "Pension",
        "steps": "1. Visit CSC center with Aadhaar\n2. Pay monthly contribution (₹55-200)\n3. Get pension after 60 years",
        "eligibility": {"min_age": 18, "occupation": ["farmer"], "income_max": None, "state": None},
        "benefits": "Monthly pension of ₹3000 after 60",
        "deadline": "Ongoing",
        "link": "https://pmkmy.gov.in"
    },
    
    # Tamil Nadu Government Schemes (10)
    "TAMIL NADU FREE ELECTRICITY": {
        "category": "Utilities",
        "steps": "1. Apply at local electricity board office\n2. Submit ration card and Aadhaar\n3. Get approval for 100 units free",
        "eligibility": {"min_age": None, "occupation": None, "income_max": 120000, "state": "Tamil Nadu"},
        "benefits": "100 units free electricity bi-monthly",
        "deadline": "Ongoing",
        "link": "https://www.tnebnet.org"
    },
    "TAMIL NADU WOMEN'S SELF HELP GROUP": {
        "category": "Women Empowerment",
        "steps": "1. Form group of 10-20 women\n2. Register at local panchayat\n3. Avail loans up to ₹10 lakh",
        "eligibility": {"min_age": 18, "occupation": ["women"], "income_max": None, "state": "Tamil Nadu"},
        "benefits": "Interest-free loans up to ₹10 lakh",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "AMMA TWO WHEELER SCHEME": {
        "category": "Transport",
        "steps": "1. Apply online at tn.gov.in\n2. Submit income certificate\n3. Get 50% subsidy up to ₹25,000",
        "eligibility": {"min_age": 18, "occupation": ["women"], "income_max": 250000, "state": "Tamil Nadu"},
        "benefits": "50% subsidy on two-wheelers",
        "deadline": "31-12-2024",
        "link": "https://www.tn.gov.in"
    },
    "TAMIL NADU FARMER'S ACCIDENTAL INSURANCE": {
        "category": "Agriculture",
        "steps": "1. Register at local agriculture office\n2. Pay premium of ₹100/year\n3. Get ₹5 lakh accidental cover",
        "eligibility": {"min_age": 18, "occupation": ["farmer"], "income_max": None, "state": "Tamil Nadu"},
        "benefits": "Accidental insurance of ₹5 lakh",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "TAMIL NADU FREE LAPTOP SCHEME": {
        "category": "Education",
        "steps": "1. Apply through college\n2. Submit marksheets and income proof\n3. Receive laptop after verification",
        "eligibility": {"min_age": 17, "occupation": ["student"], "income_max": 250000, "state": "Tamil Nadu"},
        "benefits": "Free laptop for college students",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "TAMIL NADU BUS TRAVEL CONCESSION": {
        "category": "Transport",
        "steps": "1. Apply at local bus depot\n2. Submit age proof and ID\n3. Get 50% fare concession",
        "eligibility": {"min_age": 60, "occupation": None, "income_max": None, "state": "Tamil Nadu"},
        "benefits": "50% discount on bus fares",
        "deadline": "Ongoing",
        "link": "https://www.tnstc.in"
    },
    "TAMIL NADU MARRIAGE ASSISTANCE": {
        "category": "Social Welfare",
        "steps": "1. Apply at local taluk office\n2. Submit marriage certificate\n3. Receive ₹50,000 assistance",
        "eligibility": {"min_age": 18, "occupation": None, "income_max": 72000, "state": "Tamil Nadu"},
        "benefits": "₹50,000 marriage assistance",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "TAMIL NADU FISHERMEN SUBSIDY": {
        "category": "Fisheries",
        "steps": "1. Register at fisheries department\n2. Submit fishing license\n3. Get 50% subsidy on equipment",
        "eligibility": {"min_age": 18, "occupation": ["fisherman"], "income_max": None, "state": "Tamil Nadu"},
        "benefits": "50% subsidy on fishing equipment",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "TAMIL NADU HANDLOOM WEAVERS SUBSIDY": {
        "category": "Handloom",
        "steps": "1. Register at handloom department\n2. Submit weaver ID card\n3. Get ₹25,000 subsidy",
        "eligibility": {"min_age": 18, "occupation": ["weaver"], "income_max": None, "state": "Tamil Nadu"},
        "benefits": "₹25,000 subsidy for handloom weavers",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "TAMIL NADU STARTUP SCHEME": {
        "category": "Entrepreneurship",
        "steps": "1. Register startup at tnstartup.tn.gov.in\n2. Submit business plan\n3. Get up to ₹30 lakh funding",
        "eligibility": {"min_age": 18, "occupation": ["entrepreneur"], "income_max": None, "state": "Tamil Nadu"},
        "benefits": "Funding up to ₹30 lakh for startups",
        "deadline": "31-12-2024",
        "link": "https://tnstartup.tn.gov.in"
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

def get_filtered_schemes(scheme_type):
    """Filter schemes by type (central, tn, or all)"""
    if scheme_type == "central":
        return [name for name, data in scheme_database.items() 
                if not data['eligibility'].get('state')]
    elif scheme_type == "tn":
        return [name for name, data in scheme_database.items() 
                if data['eligibility'].get('state') == "Tamil Nadu"]
    else:
        return list(scheme_database.keys())

def format_eligibility(eligibility):
    """Format eligibility criteria for display"""
    criteria = []
    if eligibility.get('min_age'):
        criteria.append(f"Minimum age: {eligibility['min_age']}")
    if eligibility.get('income_max'):
        criteria.append(f"Maximum income: ₹{eligibility['income_max']:,}")
    if eligibility.get('occupation'):
        if isinstance(eligibility['occupation'], list):
            criteria.append(f"Occupation: {', '.join(eligibility['occupation'])}")
        else:
            criteria.append(f"Occupation: {eligibility['occupation']}")
    if eligibility.get('state'):
        criteria.append(f"State: {eligibility['state']}")
    return "\n".join(criteria) if criteria else "No specific eligibility criteria"

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
            "text": "Welcome to the Government Scheme Assistant! Would you like to check:",
            "quick_replies": [
                {"title": "Central Schemes", "payload": "central"},
                {"title": "TN State Schemes", "payload": "tn"},
                {"title": "All Schemes", "payload": "all"},
                {"title": "Check Eligibility", "payload": "eligibility"}
            ],
            "next_step": STEPS["MAIN_MENU"]
        }
    
    elif step == STEPS["MAIN_MENU"]:
        if incoming_msg.lower() in ["central", "tn", "all"]:
            scheme_type = incoming_msg.lower()
            schemes = get_filtered_schemes(scheme_type)
            
            if not schemes:
                return {
                    "text": f"No {scheme_type} schemes found. Would you like to try a different category?",
                    "quick_replies": [
                        {"title": "Central Schemes", "payload": "central"},
                        {"title": "TN Schemes", "payload": "tn"},
                        {"title": "All Schemes", "payload": "all"}
                    ]
                }
            
            scheme_list = "\n\n".join([f"• {name}: {scheme_database[name]['benefits']}" 
                                      for name in schemes[:10]])
            
            return {
                "text": f"Here are {scheme_type} government schemes:\n\n{scheme_list}",
                "quick_replies": [
                    {"title": "See More", "payload": f"more_{scheme_type}"},
                    {"title": "Check Eligibility", "payload": "eligibility"},
                    {"title": "Main Menu", "payload": "menu"}
                ]
            }
            
        elif incoming_msg.lower() == "eligibility":
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
            
        elif incoming_msg.startswith("more_"):
            scheme_type = incoming_msg.replace("more_", "")
            schemes = get_filtered_schemes(scheme_type)
            scheme_list = "\n\n".join([f"• {name}: {scheme_database[name]['benefits']}" 
                                    for name in schemes[10:]])
            
            return {
                "text": f"More {scheme_type} government schemes:\n\n{scheme_list}",
                "quick_replies": [
                    {"title": "See Details", "payload": f"details_{scheme_type}"},
                    {"title": "Main Menu", "payload": "menu"}
                ]
            }
            
        elif incoming_msg.startswith("details_"):
            scheme_type = incoming_msg.replace("details_", "")
            schemes = get_filtered_schemes(scheme_type)
            
            return {
                "text": f"Select a {scheme_type} scheme to view details:",
                "quick_replies": [{"title": name, "payload": f"full_{name}"} for name in schemes[:5]] +
                                [{"title": "More Schemes", "payload": f"details_more_{scheme_type}"}]
            }
            
        elif incoming_msg.startswith("full_"):
            scheme_name = incoming_msg.replace("full_", "")
            scheme = scheme_database.get(scheme_name)
            
            if not scheme:
                return {
                    "text": "Scheme details not found. Please try another scheme.",
                    "quick_replies": [
                        {"title": "Central Schemes", "payload": "central"},
                        {"title": "TN Schemes", "payload": "tn"}
                    ]
                }
                
            return {
                "text": f"Scheme: {scheme_name}\n\n"
                       f"Category: {scheme['category']}\n"
                       f"Benefits: {scheme['benefits']}\n"
                       f"Eligibility: {format_eligibility(scheme['eligibility'])}\n"
                       f"Steps to Apply:\n{scheme['steps']}\n\n"
                       f"Apply at: {scheme['link']}",
                "quick_replies": [
                    {"title": "Apply Now", "payload": f"apply_{scheme_name}"},
                    {"title": "Other Schemes", "payload": "menu"}
                ]
            }
            
        elif incoming_msg == "menu":
            return handle_conversation_step(STEPS["WELCOME"], "", context)
            
        else:
            return {
                "text": get_ai_response(incoming_msg) or "I can help with government schemes. Please select an option:",
                "quick_replies": [
                    {"title": "Central Schemes", "payload": "central"},
                    {"title": "TN Schemes", "payload": "tn"},
                    {"title": "Check Eligibility", "payload": "eligibility"}
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
            schemes = [{"name": name, **data} for name, data in scheme_database.items() 
                      if not data['eligibility'].get('state')]
        elif scheme_type == 'tn':
            schemes = [{"name": name, **data} for name, data in scheme_database.items() 
                      if data['eligibility'].get('state') == "Tamil Nadu"]
        else:
            schemes = [{"name": name, **data} for name, data in scheme_database.items()]
            
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