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
    # Central Government Schemes (15)
    "PM-KISAN": {
        "category": "Agriculture",
        "steps": "1. Visit https://pmkisan.gov.in\n2. Click 'New Farmer Registration'\n3. Submit Aadhaar and land details",
        "eligibility": {"min_age": 18, "occupation": ["farmer"], "income_max": None, "state": None},
        "benefits": "₹6,000/year direct benefit transfer",
        "deadline": "Ongoing",
        "link": "https://pmkisan.gov.in"
    },
    "PM Awas Yojana": {
        "category": "Housing",
        "steps": "1. Check eligibility at pmaymis.gov.in\n2. Submit documents to local authority\n3. Receive subsidy in bank account",
        "eligibility": {"min_age": 21, "income_max": 180000, "state": None},
        "benefits": "₹2.67 lakh subsidy for home construction",
        "deadline": "31-12-2024",
        "link": "https://pmaymis.gov.in"
    },
    "Ayushman Bharat": {
        "category": "Healthcare",
        "steps": "1. Check eligibility at pmjay.gov.in\n2. Visit empaneled hospital with Aadhaar",
        "eligibility": {"income_max": 500000, "state": None},
        "benefits": "₹5 lakh/year health insurance coverage",
        "deadline": "Ongoing",
        "link": "https://pmjay.gov.in"
    },
    "Ujjwala Yojana": {
        "category": "Women Welfare",
        "steps": "1. Submit Aadhaar and BPL card\n2. Get LPG connection at CSC center",
        "eligibility": {"gender": "female", "state": None},
        "benefits": "Free LPG connection + ₹1600 subsidy",
        "deadline": "Ongoing",
        "link": "https://www.pmuy.gov.in"
    },
    "Mudra Loan": {
        "category": "Entrepreneurship",
        "steps": "1. Approach any bank\n2. Submit business plan\n3. Get loan up to ₹10 lakh",
        "eligibility": {"min_age": 18, "state": None},
        "benefits": "Collateral-free loans for small businesses",
        "deadline": "Ongoing",
        "link": "https://www.mudra.org.in"
    },
    "Stand Up India": {
        "category": "Entrepreneurship",
        "steps": "1. Apply through bank\n2. Submit SC/ST/women certificate",
        "eligibility": {"min_age": 18, "category": ["SC/ST", "women"], "state": None},
        "benefits": "₹10 lakh to ₹1 crore business loans",
        "deadline": "Ongoing",
        "link": "https://www.standupmitra.in"
    },
    "PM SVANidhi": {
        "category": "Urban Welfare",
        "steps": "1. Apply through municipal corporation\n2. Submit vendor certificate",
        "eligibility": {"occupation": ["street vendor"], "state": None},
        "benefits": "₹10,000 working capital loan",
        "deadline": "31-12-2024",
        "link": "https://pmsvanidhi.mohua.gov.in"
    },
    "Kisan Credit Card": {
        "category": "Agriculture",
        "steps": "1. Apply at any bank\n2. Submit land documents\n3. Get credit card",
        "eligibility": {"occupation": ["farmer"], "state": None},
        "benefits": "Up to ₹3 lakh credit at 4% interest",
        "deadline": "Ongoing",
        "link": "https://www.agricoop.nic.in"
    },
    "PM Matsya Sampada": {
        "category": "Fisheries",
        "steps": "1. Register at fisheries department\n2. Submit project proposal",
        "eligibility": {"occupation": ["fisherman"], "state": None},
        "benefits": "Up to ₹10 lakh subsidy for fishing equipment",
        "deadline": "31-03-2025",
        "link": "https://dof.gov.in"
    },
    "PM Formalization Scheme": {
        "category": "Small Business",
        "steps": "1. Register at udyamregistration.gov.in\n2. Submit GST certificate",
        "eligibility": {"business_size": "micro/small", "state": None},
        "benefits": "₹50,000-5 lakh for business formalization",
        "deadline": "31-03-2025",
        "link": "https://udyamregistration.gov.in"
    },
    "Sukanya Samriddhi": {
        "category": "Child Welfare",
        "steps": "1. Open account at post office/bank\n2. Deposit minimum ₹250/year",
        "eligibility": {"gender": "female", "max_age": 10, "state": None},
        "benefits": "7.6% interest + tax benefits",
        "deadline": "Ongoing",
        "link": "https://www.indiapost.gov.in"
    },
    "PM Kisan Maandhan": {
        "category": "Pension",
        "steps": "1. Visit CSC center\n2. Pay ₹55-200/month\n3. Get pension at 60",
        "eligibility": {"occupation": ["farmer"], "min_age": 18, "max_age": 40, "state": None},
        "benefits": "₹3000/month pension after 60",
        "deadline": "Ongoing",
        "link": "https://pmkmy.gov.in"
    },
    "Atal Pension Yojana": {
        "category": "Pension",
        "steps": "1. Open account at bank\n2. Choose pension amount\n3. Auto-debit premium",
        "eligibility": {"min_age": 18, "max_age": 40, "state": None},
        "benefits": "₹1000-5000/month pension",
        "deadline": "Ongoing",
        "link": "https://www.jansuraksha.gov.in"
    },
    "PM Jeevan Jyoti Bima": {
        "category": "Insurance",
        "steps": "1. Link bank account\n2. Pay ₹330/year premium",
        "eligibility": {"min_age": 18, "max_age": 50, "state": None},
        "benefits": "₹2 lakh life insurance cover",
        "deadline": "31-03-2025",
        "link": "https://www.jansuraksha.gov.in"
    },
    "PM Suraksha Bima": {
        "category": "Insurance",
        "steps": "1. Link bank account\n2. Pay ₹12/year premium",
        "eligibility": {"min_age": 18, "max_age": 70, "state": None},
        "benefits": "₹2 lakh accidental insurance",
        "deadline": "31-03-2025",
        "link": "https://www.jansuraksha.gov.in"
    },

    # Tamil Nadu State Schemes (15)
    "Amma Two Wheeler": {
        "category": "Women Welfare",
        "steps": "1. Apply at tn.gov.in\n2. Submit income certificate\n3. Get 50% subsidy",
        "eligibility": {"gender": "female", "income_max": 250000, "state": "Tamil Nadu"},
        "benefits": "50% subsidy (up to ₹25,000) on two-wheelers",
        "deadline": "31-12-2024",
        "link": "https://www.tn.gov.in"
    },
    "Free Electricity": {
        "category": "Utilities",
        "steps": "1. Apply at TANGEDCO office\n2. Submit ration card",
        "eligibility": {"income_max": 120000, "state": "Tamil Nadu"},
        "benefits": "100 free units bi-monthly",
        "deadline": "Ongoing",
        "link": "https://www.tnebnet.org"
    },
    "Amma Cement": {
        "category": "Housing",
        "steps": "1. Buy from TANCEM depots\n2. Show Aadhaar card",
        "eligibility": {"state": "Tamil Nadu"},
        "benefits": "₹300/bag cement subsidy",
        "deadline": "Ongoing",
        "link": "https://www.tancem.tn.gov.in"
    },
    "Amma Salt": {
        "category": "Food",
        "steps": "1. Visit PDS shops\n2. Show ration card",
        "eligibility": {"state": "Tamil Nadu"},
        "benefits": "1kg iodized salt for ₹10",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "Free Bus Travel": {
        "category": "Transport",
        "steps": "1. Apply at bus depot\n2. Submit age proof",
        "eligibility": {"min_age": 60, "state": "Tamil Nadu"},
        "benefits": "Free travel in govt buses",
        "deadline": "Ongoing",
        "link": "https://www.tnstc.in"
    },
    "Free Laptop": {
        "category": "Education",
        "steps": "1. Apply through college\n2. Submit marksheets",
        "eligibility": {"occupation": ["student"], "income_max": 250000, "state": "Tamil Nadu"},
        "benefits": "Free laptop for college students",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "Marriage Assistance": {
        "category": "Social Welfare",
        "steps": "1. Apply at taluk office\n2. Submit marriage certificate",
        "eligibility": {"income_max": 72000, "state": "Tamil Nadu"},
        "benefits": "₹50,000 financial assistance",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "Fishermen Subsidy": {
        "category": "Fisheries",
        "steps": "1. Register at fisheries dept\n2. Submit license",
        "eligibility": {"occupation": ["fisherman"], "state": "Tamil Nadu"},
        "benefits": "50% subsidy on fishing equipment",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "Weavers Subsidy": {
        "category": "Handloom",
        "steps": "1. Register at handloom dept\n2. Submit ID card",
        "eligibility": {"occupation": ["weaver"], "state": "Tamil Nadu"},
        "benefits": "₹25,000 subsidy for looms",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "Startup TN": {
        "category": "Entrepreneurship",
        "steps": "1. Register at tnstartup.tn.gov.in\n2. Submit business plan",
        "eligibility": {"max_age": 45, "state": "Tamil Nadu"},
        "benefits": "Up to ₹30 lakh funding",
        "deadline": "31-12-2024",
        "link": "https://tnstartup.tn.gov.in"
    },
    "Farmers Accident Insurance": {
        "category": "Agriculture",
        "steps": "1. Register at agriculture office\n2. Pay ₹100 premium",
        "eligibility": {"occupation": ["farmer"], "state": "Tamil Nadu"},
        "benefits": "₹5 lakh accidental insurance",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "Amma Baby Kit": {
        "category": "Child Welfare",
        "steps": "1. Apply at govt hospital\n2. Submit birth certificate",
        "eligibility": {"state": "Tamil Nadu"},
        "benefits": "Free baby care kit worth ₹3000",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "Green House Scheme": {
        "category": "Agriculture",
        "steps": "1. Apply at horticulture dept\n2. Submit land documents",
        "eligibility": {"land_min": 0.5, "state": "Tamil Nadu"}, # 0.5 acres
        "benefits": "50% subsidy for greenhouses",
        "deadline": "31-03-2025",
        "link": "https://www.tn.gov.in"
    },
    "Moovalur Ramamirtham Scheme": {
        "category": "Women Education",
        "steps": "1. Apply through school\n2. Submit income certificate",
        "eligibility": {"gender": "female", "income_max": 120000, "state": "Tamil Nadu"},
        "benefits": "₹1000/month for girl students",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "CM Breakfast Scheme": {
        "category": "Education",
        "steps": "1. Enroll in govt school\n2. Attend morning classes",
        "eligibility": {"state": "Tamil Nadu"},
        "benefits": "Free nutritious breakfast",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
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
        payload = data.get('payload', incoming_msg)
        
        session = get_session(sender_id) or {
            "step": STEPS["WELCOME"],
            "context": "{}",
            "created_at": str(datetime.now()),
            "last_active": str(datetime.now())
        }
        
        if "start over" in incoming_msg.lower():
            session["step"] = STEPS["WELCOME"]
            session["context"] = "{}"
            set_session(sender_id, session)
            return handle_conversation_step(session["step"], "", {})
        
        context = eval(session["context"]) if isinstance(session["context"], str) else session["context"]
        
        response = handle_conversation_step(session["step"], payload or incoming_msg, context)
        
        if "next_step" in response:
            session["step"] = response["next_step"]
        
        if "context_update" in response:
            session["context"] = str(response["context_update"])
        
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
            "text": "Welcome to Government Scheme AI Assistant! I can help you discover benefits you may qualify for.",
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
            
            scheme_list = "\n".join([f"\n• {name}: {scheme_database[name]['benefits']}" 
                                  for name in schemes[:10]])
            
            return {
                "text": f"Here are {scheme_type} government schemes:{scheme_list}",
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
            if incoming_msg.isdigit():
                age = int(incoming_msg)
            else:
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
        try:
            context['state'] = incoming_msg.lower()
            
            eligible_schemes = []
            for name, data in scheme_database.items():
                eligible = True
                
                if 'min_age' in data['eligibility'] and context.get('age', 0) < data['eligibility']['min_age']:
                    eligible = False
                
                if data['eligibility'].get('income_max') and context.get('income', 0) > data['eligibility']['income_max']:
                    eligible = False
                
                if data['eligibility'].get('occupation'):
                    if isinstance(data['eligibility']['occupation'], list):
                        if context.get('occupation') not in data['eligibility']['occupation']:
                            eligible = False
                    elif context.get('occupation') != data['eligibility']['occupation']:
                        eligible = False
                
                if data['eligibility'].get('state'):
                    if context.get('state') != data['eligibility']['state'].lower():
                        eligible = False
                
                if eligible:
                    eligible_schemes.append(name)
            
            if eligible_schemes:
                scheme_list = "\n".join([
                    f"\n• {name}: {scheme_database[name]['benefits']}\n  Apply: {scheme_database[name]['link']}"
                    for name in eligible_schemes
                ])
                return {
                    "text": f"Based on your details, you may be eligible for these schemes:{scheme_list}\n\nWould you like to check eligibility for other schemes?",
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
        except Exception as e:
            logger.error(f"Eligibility check error: {str(e)}")
            return {
                "text": "An error occurred while checking eligibility. Please try again.",
                "quick_replies": [
                    {"title": "Try Again", "payload": "eligibility"},
                    {"title": "Main Menu", "payload": "menu"}
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