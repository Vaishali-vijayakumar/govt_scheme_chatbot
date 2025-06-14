from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import logging
from datetime import datetime, timedelta
import uuid
import os
from dotenv import load_dotenv
import redis
import bleach
import json
from typing import Dict, Any, List, Optional, Union

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configuration
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24).hex())
app.config['RATE_LIMIT_STRATEGY'] = 'fixed-window'
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.getenv('REDIS_URL', 'memory://')
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Redis connection
def init_redis() -> Optional[redis.Redis]:
    try:
        redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD'),
            db=0,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5
        )
        redis_client.ping()  # Test connection
        logger.info("Successfully connected to Redis")
        return redis_client
    except (redis.ConnectionError, redis.TimeoutError) as e:
        logger.warning(f"Redis connection failed: {str(e)}. Using in-memory storage.")
        return None

r = init_redis()
user_sessions = {}  # In-memory fallback storage

# Conversation steps
class ConversationSteps:
    WELCOME = "0"
    MAIN_MENU = "1"
    ELIGIBILITY_AGE = "2"
    ELIGIBILITY_INCOME = "3"
    ELIGIBILITY_OCCUPATION = "4"
    ELIGIBILITY_LOCATION = "5"
    SCHEME_RESULTS = "6"

SCHEME_DATABASE = {
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
# Type aliases
SessionData = Dict[str, Any]
ContextData = Dict[str, Any]
SchemeType = Dict[str, Any]

def get_session(session_id: str) -> Optional[SessionData]:
    """Get session from Redis or fallback to memory"""
    try:
        if r:
            session_data = r.hgetall(f"session:{session_id}")
            return session_data if session_data else None
        return user_sessions.get(session_id)
    except redis.RedisError as e:
        logger.error(f"Redis error in get_session: {str(e)}")
        return user_sessions.get(session_id)

def set_session(session_id: str, data: SessionData) -> bool:
    """Store session in Redis or memory"""
    try:
        if r:
            r.hset(f"session:{session_id}", mapping=data)
            r.expire(f"session:{session_id}", 3600)  # 1 hour expiry
            return True
        user_sessions[session_id] = data
        return True
    except redis.RedisError as e:
        logger.error(f"Redis error in set_session: {str(e)}")
        user_sessions[session_id] = data
        return False
# Add these new functions to your existing backend

def get_help_response() -> Dict[str, Any]:
    """Generate detailed help response"""
    return {
        "text": (
            "🆘 *Government Scheme Assistant Help*\n\n"
            "I can help you with:\n\n"
            "1. *Discovering Schemes* - Browse all government schemes or find ones you qualify for\n"
            "2. *Eligibility Checking* - Answer a few questions to see which schemes match your profile\n"
            "3. *Scheme Details* - Get step-by-step application instructions for any scheme\n\n"
            "Here are some things you can ask me:\n"
            "- \"What agriculture schemes are available?\"\n"
            "- \"Check my eligibility for housing schemes\"\n"
            "- \"Show me student benefits in Tamil Nadu\"\n"
            "- \"Explain PM-KISAN application process\""
        ),
        "quick_replies": [
            {"title": "🌾 Agriculture", "payload": "agriculture"},
            {"title": "🏠 Housing", "payload": "housing"},
            {"title": "🎓 Education", "payload": "education"},
            {"title": "🏥 Healthcare", "payload": "healthcare"},
            {"title": "🏠 Main Menu", "payload": "menu"}
        ]
    }

def get_scheme_by_category(category: str) -> Dict[str, Any]:
    """Get schemes filtered by category"""
    matched_schemes = []
    category = category.lower()
    
    for name, data in SCHEME_DATABASE.items():
        if category in data['category'].lower():
            matched_schemes.append((name, data))
    
    if not matched_schemes:
        return {
            "text": f"⚠️ No schemes found in {category} category. Try these instead:",
            "quick_replies": [
                {"title": "🌾 Agriculture", "payload": "agriculture"},
                {"title": "🏠 Housing", "payload": "housing"},
                {"title": "🏠 Main Menu", "payload": "menu"}
            ]
        }
    
    scheme_list = "\n\n".join(
        f"🔹 *{name}*\n   - Benefits: {data['benefits']}\n   - Eligibility: {format_eligibility(data['eligibility'])}"
        for name, data in matched_schemes[:5]
    )
    
    return {
        "text": f"📋 *{category.capitalize()} Schemes:*\n{scheme_list}",
        "quick_replies": [
            {"title": f"🔍 More {category}", "payload": f"more_{category}"},
            {"title": "✅ Check Eligibility", "payload": "eligibility"},
            {"title": "🏠 Main Menu", "payload": "menu"}
        ]
    }

def generate_eligible_schemes_response(context: ContextData) -> Dict[str, Any]:
    """Generate structured response with eligible schemes"""
    eligible_schemes = []
    
    for name, data in SCHEME_DATABASE.items():
        if is_eligible(context, data['eligibility']):
            eligible_schemes.append((name, data))
    
    if not eligible_schemes:
        return {
            "text": (
                "🤔 We couldn't find any schemes matching your profile.\n\n"
                "*Your Profile:*\n"
                f"- Age: {context.get('age', 'Not specified')}\n"
                f"- Income: ₹{context.get('income', 'Not specified'):,}\n"
                f"- Occupation: {context.get('occupation', 'Not specified').capitalize()}\n"
                f"- State: {context.get('state', 'Not specified').capitalize()}\n\n"
                "Try adjusting your criteria or browse all schemes:"
            ),
            "quick_replies": [
                {"title": "🔼 Increase Income", "payload": "increase_income"},
                {"title": "🔄 Change Occupation", "payload": "change_occupation"},
                {"title": "🌐 Browse All", "payload": "all"},
                {"title": "🏠 Main Menu", "payload": "menu"}
            ]
        }
    
    # Sort by category then by scheme name
    eligible_schemes.sort(key=lambda x: (x[1]['category'], x[0]))
    
    # Prepare structured data for frontend
    scheme_categories = {}
    for name, data in eligible_schemes:
        if data['category'] not in scheme_categories:
            scheme_categories[data['category']] = []
        scheme_categories[data['category']].append({
            "name": name,
            "benefits": data['benefits'],
            "eligibility": format_eligibility(data['eligibility']),
            "link": data['link'],
            "deadline": data['deadline']
        })
    
    # Format text response
    response_text = (
        f"🎉 *Based on your profile, you may qualify for these {len(eligible_schemes)} schemes:*\n\n"
        "*Your Profile:*\n"
        f"- Age: {context.get('age')}\n"
        f"- Income: ₹{context.get('income'):,}\n"
        f"- Occupation: {context.get('occupation').capitalize()}\n"
        f"- State: {context.get('state').capitalize()}\n\n"
    )
    
    for category, schemes in scheme_categories.items():
        response_text += f"*{category} Schemes:*\n"
        for scheme in schemes[:3]:  # Show max 3 per category in text
            response_text += (
                f"🔹 {scheme['name']}\n"
                f"   - Benefits: {scheme['benefits']}\n"
                f"   - Apply: {scheme['link']}\n\n"
            )
    
    if len(eligible_schemes) > 6:
        response_text += f"\nShowing {min(6, len(eligible_schemes))} of {len(eligible_schemes)} eligible schemes. See all in the eligibility section above."
    
    return {
        "text": response_text,
        "structured_data": {
            "eligible_schemes": eligible_schemes[:10],  # Limit to 10 for display
            "user_profile": context
        },
        "quick_replies": [
            {"title": "🔄 Check Again", "payload": "eligibility"},
            {"title": "📋 Browse All", "payload": "all"},
            {"title": "🏠 Main Menu", "payload": "menu"}
        ]
    }

# Update the handle_conversation_step function to include new features
def handle_conversation_step(step: str, incoming_msg: str, context: ContextData) -> Dict[str, Any]:
    """Enhanced conversation handler"""
    try:
        # Check for help request
        if incoming_msg.lower() in ["help", "assistance", "support"]:
            return get_help_response()
        
        # Check for category-based queries
        if incoming_msg.lower() in ["agriculture", "housing", "education", "healthcare"]:
            return get_scheme_by_category(incoming_msg.lower())
        
        # Original step handling
        if step == ConversationSteps.WELCOME:
            return welcome_step()
        elif step == ConversationSteps.MAIN_MENU:
            return main_menu_step(incoming_msg)
        elif step == ConversationSteps.ELIGIBILITY_AGE:
            return eligibility_age_step(incoming_msg, context)
        elif step == ConversationSteps.ELIGIBILITY_INCOME:
            return eligibility_income_step(incoming_msg, context)
        elif step == ConversationSteps.ELIGIBILITY_OCCUPATION:
            return eligibility_occupation_step(incoming_msg, context)
        elif step == ConversationSteps.ELIGIBILITY_LOCATION:
            # After collecting all eligibility info, generate full response
            response = eligibility_location_step(incoming_msg, context)
            if "context_update" in response:
                context = response["context_update"]
                eligible_response = generate_eligible_schemes_response(context)
                response.update(eligible_response)
            return response
        else:
            return unknown_step()
    except Exception as e:
        logger.error(f"Error in conversation step {step}: {str(e)}")
        return error_step()

def sanitize_input(text: str) -> str:
    """Sanitize user input to prevent XSS"""
    return bleach.clean(text, tags=[], strip=True)

def validate_age(age_str: str) -> bool:
    """Validate age input"""
    try:
        age = int(age_str)
        return 10 <= age <= 120
    except ValueError:
        return False

def get_filtered_schemes(scheme_type: str) -> List[str]:
    """Filter schemes by type (central, tn, or all)"""
    try:
        if scheme_type == "central":
            return [name for name, data in SCHEME_DATABASE.items() 
                   if not data['eligibility'].get('state')]
        elif scheme_type == "tn":
            return [name for name, data in SCHEME_DATABASE.items() 
                   if data['eligibility'].get('state') == "Tamil Nadu"]
        return list(SCHEME_DATABASE.keys())
    except Exception as e:
        logger.error(f"Error filtering schemes: {str(e)}")
        return []

def format_eligibility(eligibility: Dict[str, Any]) -> str:
    """Format eligibility criteria for display"""
    criteria = []
    try:
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
    except Exception as e:
        logger.error(f"Error formatting eligibility: {str(e)}")
        return "Eligibility criteria not available"

def is_eligible(context: ContextData, eligibility: Dict[str, Any]) -> bool:
    """Check if user meets all eligibility criteria for a scheme"""
    try:
        # Check age
        if 'min_age' in eligibility and context.get('age', 0) < eligibility['min_age']:
            return False
        
        # Check income
        if eligibility.get('income_max') is not None:
            if context.get('income', float('inf')) > eligibility['income_max']:
                return False
        
        # Check occupation
        if eligibility.get('occupation'):
            user_occupation = context.get('occupation', '').lower()
            if isinstance(eligibility['occupation'], list):
                if user_occupation not in [o.lower() for o in eligibility['occupation']]:
                    return False
            elif user_occupation != eligibility['occupation'].lower():
                return False
        
        # Check state
        if eligibility.get('state'):
            if context.get('state', '').lower() != eligibility['state'].lower():
                return False
        
        return True
    except Exception as e:
        logger.error(f"Eligibility check error: {str(e)}")
        return False

def get_predefined_response(message: str) -> Optional[str]:
    """Get predefined responses for common queries"""
    responses = {
        "help": "I can help you discover government schemes you may qualify for. You can:\n\n"
                "1. Browse schemes by category\n"
                "2. Check your eligibility for schemes\n"
                "3. Get details about specific schemes",
        "hi": "Hello! How can I help you today?",
        "hello": "Hello! How can I help you today?",
        "thanks": "You're welcome! Let me know if you need any more assistance.",
        "thank you": "You're welcome! Let me know if you need any more assistance."
    }
    return responses.get(message.lower())

@app.route('/health')
def health_check():
    """Endpoint for health monitoring"""
    redis_status = False
    try:
        if r:
            redis_status = r.ping()
    except redis.RedisError:
        pass
    
    return jsonify({
        "status": "healthy",
        "scheme_count": len(SCHEME_DATABASE),
        "redis_connected": redis_status,
        "timestamp": datetime.now().isoformat()
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
        if not data:
            return jsonify({"error": "Invalid request data"}), 400
            
        incoming_msg = sanitize_input(data.get('message', '').strip())
        sender_id = data.get('sender', str(uuid.uuid4()))
        payload = data.get('payload', incoming_msg)
        
        session = get_session(sender_id) or {
            "step": ConversationSteps.WELCOME,
            "context": "{}",
            "created_at": str(datetime.now()),
            "last_active": str(datetime.now())
        }
        
        if "start over" in incoming_msg.lower():
            session["step"] = ConversationSteps.WELCOME
            session["context"] = "{}"
            set_session(sender_id, session)
            return handle_conversation_step(ConversationSteps.WELCOME, "", {})
        
        try:
            context = json.loads(session["context"]) if isinstance(session["context"], str) else session["context"]
        except json.JSONDecodeError:
            context = {}
        
        response = handle_conversation_step(session["step"], payload or incoming_msg, context)
        
        if "next_step" in response:
            session["step"] = response["next_step"]
        
        if "context_update" in response:
            session["context"] = json.dumps(response["context_update"])
        
        session["last_active"] = str(datetime.now())
        set_session(sender_id, session)
        
        return jsonify({
            "text": response["text"],
            "quick_replies": response.get("quick_replies", []),
            "buttons": response.get("buttons", []),
            "session_id": sender_id
        })
    except Exception as e:
        logger.error(f"Chatbot error: {str(e)}")
        return jsonify({"error": "An error occurred. Please try again later."}), 500

def handle_conversation_step(step: str, incoming_msg: str, context: ContextData) -> Dict[str, Any]:
    """Handle conversation logic for each step with enhanced formatting"""
    try:
        if step == ConversationSteps.WELCOME:
            return welcome_step()
        elif step == ConversationSteps.MAIN_MENU:
            return main_menu_step(incoming_msg)
        elif step == ConversationSteps.ELIGIBILITY_AGE:
            return eligibility_age_step(incoming_msg, context)
        elif step == ConversationSteps.ELIGIBILITY_INCOME:
            return eligibility_income_step(incoming_msg, context)
        elif step == ConversationSteps.ELIGIBILITY_OCCUPATION:
            return eligibility_occupation_step(incoming_msg, context)
        elif step == ConversationSteps.ELIGIBILITY_LOCATION:
            return eligibility_location_step(incoming_msg, context)
        else:
            return unknown_step()
    except Exception as e:
        logger.error(f"Error in conversation step {step}: {str(e)}")
        return error_step()

def welcome_step() -> Dict[str, Any]:
    return {
        "text": "🌟 *Welcome to Government Scheme Assistant!* 🌟\n\nI can help you discover benefits you may qualify for. Choose an option:",
        "quick_replies": [
            {"title": "🔍 Browse Schemes", "payload": "browse"},
            {"title": "✅ Check Eligibility", "payload": "eligibility"},
            {"title": "ℹ️ Get Help", "payload": "help"}
        ],
        "next_step": ConversationSteps.MAIN_MENU
    }

def main_menu_step(incoming_msg: str) -> Dict[str, Any]:
    predefined_response = get_predefined_response(incoming_msg)
    if predefined_response:
        return {
            "text": predefined_response,
            "quick_replies": [
                {"title": "🔍 Browse Schemes", "payload": "browse"},
                {"title": "✅ Check Eligibility", "payload": "eligibility"},
                {"title": "🏠 Main Menu", "payload": "menu"}
            ]
        }
    
    if incoming_msg.lower() in ["central", "tn", "all"]:
        return handle_scheme_browsing(incoming_msg.lower())
    elif incoming_msg.lower() == "eligibility":
        return start_eligibility_check()
    elif incoming_msg.startswith("more_"):
        return handle_more_schemes(incoming_msg)
    elif incoming_msg.startswith("details_"):
        return handle_scheme_details(incoming_msg)
    elif incoming_msg.startswith("full_"):
        return show_full_scheme_details(incoming_msg)
    elif incoming_msg == "menu":
        return welcome_step()
    else:
        return handle_unknown_input(incoming_msg)

def handle_scheme_browsing(scheme_type: str) -> Dict[str, Any]:
    schemes = get_filtered_schemes(scheme_type)
    
    if not schemes:
        return {
            "text": f"⚠️ No {scheme_type} schemes found. Try another category:",
            "quick_replies": [
                {"title": "🇮🇳 Central", "payload": "central"},
                {"title": "🏛️ TN State", "payload": "tn"},
                {"title": "🌐 All", "payload": "all"}
            ]
        }
    
    scheme_list = "\n\n".join(
        f"🔹 *{name}*\n   - Category: {SCHEME_DATABASE[name]['category']}\n   - Benefits: {SCHEME_DATABASE[name]['benefits']}"
        for name in schemes[:5]
    )
    
    return {
        "text": f"📋 *{scheme_type.upper()} Government Schemes:*\n{scheme_list}",
        "buttons": [{
            "title": f"View {schemes[0]} Details",
            "url": SCHEME_DATABASE[schemes[0]]['link'],
            "type": "web_url"
        }] if schemes else [],
        "quick_replies": [
            {"title": "🔍 See More", "payload": f"more_{scheme_type}"},
            {"title": "✅ Check Eligibility", "payload": "eligibility"},
            {"title": "🏠 Main Menu", "payload": "menu"}
        ]
    }

def start_eligibility_check() -> Dict[str, Any]:
    return {
        "text": "📝 *Let's check your eligibility*\n\nWhat is your age in years? (Type number or select):",
        "quick_replies": [
            {"title": "👶 Under 18", "payload": "17"},
            {"title": "👦 18-30", "payload": "25"},
            {"title": "👨 31-45", "payload": "38"},
            {"title": "👴 46-60", "payload": "53"},
            {"title": "🧓 60+", "payload": "65"}
        ],
        "next_step": ConversationSteps.ELIGIBILITY_AGE
    }

def eligibility_age_step(incoming_msg: str, context: ContextData) -> Dict[str, Any]:
    try:
        if incoming_msg.isdigit():
            age = int(incoming_msg)
        else:
            age_str = ''.join(filter(str.isdigit, incoming_msg))
            age = int(age_str) if age_str else 0
            
        if not validate_age(str(age)):
            return {
                "text": "⚠️ Please enter a valid age between 10 and 120 years",
                "quick_replies": [
                    {"title": "👶 Under 18", "payload": "17"},
                    {"title": "👦 18-30", "payload": "25"},
                    {"title": "⬅️ Back", "payload": "menu"}
                ]
            }
        
        context['age'] = age
        return {
            "text": "💰 *What is your approximate annual family income?*",
            "quick_replies": [
                {"title": "≤ ₹1L", "payload": "100000"},
                {"title": "₹1L-3L", "payload": "200000"},
                {"title": "₹3L-5L", "payload": "400000"},
                {"title": "₹5L-10L", "payload": "750000"},
                {"title": "≥ ₹10L", "payload": "1000000"},
                {"title": "⬅️ Back", "payload": "menu"}
            ],
            "context_update": context,
            "next_step": ConversationSteps.ELIGIBILITY_INCOME
        }
    except Exception as e:
        logger.error(f"Age step error: {str(e)}")
        return error_step()

def eligibility_income_step(incoming_msg: str, context: ContextData) -> Dict[str, Any]:
    try:
        if incoming_msg.isdigit():
            income = int(incoming_msg)
        else:
            income_str = ''.join(filter(str.isdigit, incoming_msg))
            income = int(income_str) if income_str else 0
            
        if income <= 0:
            return {
                "text": "⚠️ Please enter a valid income amount",
                "quick_replies": [
                    {"title": "≤ ₹1L", "payload": "100000"},
                    {"title": "₹1L-3L", "payload": "200000"},
                    {"title": "⬅️ Back", "payload": "menu"}
                ]
            }
        
        context['income'] = income
        return {
            "text": "💼 *What is your occupation/profession?*",
            "quick_replies": [
                {"title": "👨‍🌾 Farmer", "payload": "farmer"},
                {"title": "👨‍🎓 Student", "payload": "student"},
                {"title": "👨‍💼 Business", "payload": "business"},
                {"title": "👨‍💻 Employee", "payload": "employee"},
                {"title": "👩‍⚕️ Healthcare", "payload": "healthcare"},
                {"title": "Other", "payload": "other"},
                {"title": "⬅️ Back", "payload": "menu"}
            ],
            "context_update": context,
            "next_step": ConversationSteps.ELIGIBILITY_OCCUPATION
        }
    except Exception as e:
        logger.error(f"Income step error: {str(e)}")
        return error_step()

def eligibility_occupation_step(incoming_msg: str, context: ContextData) -> Dict[str, Any]:
    try:
        occupation = incoming_msg.lower()
        context['occupation'] = occupation
        
        return {
            "text": "📍 *Which state do you live in?*",
            "quick_replies": [
                {"title": "Tamil Nadu", "payload": "tamil nadu"},
                {"title": "Andhra Pradesh", "payload": "andhra pradesh"},
                {"title": "Karnataka", "payload": "karnataka"},
                {"title": "Kerala", "payload": "kerala"},
                {"title": "Other State", "payload": "other"},
                {"title": "⬅️ Back", "payload": "menu"}
            ],
            "context_update": context,
            "next_step": ConversationSteps.ELIGIBILITY_LOCATION
        }
    except Exception as e:
        logger.error(f"Occupation step error: {str(e)}")
        return error_step()

def eligibility_location_step(incoming_msg: str, context: ContextData) -> Dict[str, Any]:
    try:
        state = incoming_msg.lower()
        context['state'] = state
        
        eligible_schemes = []
        for name, data in SCHEME_DATABASE.items():
            if is_eligible(context, data['eligibility']):
                eligible_schemes.append((name, data))
        
        if eligible_schemes:
            eligible_schemes.sort(key=lambda x: x[1]['category'])
            
            scheme_list = []
            for name, data in eligible_schemes[:10]:
                scheme_list.append(
                    f"\n\n⭐ *{name}* ({data['category']})\n"
                    f"   - Benefits: {data['benefits']}\n"
                    f"   - Eligibility: {format_eligibility(data['eligibility'])}\n"
                    f"   - Deadline: {data['deadline']}"
                )
            
            buttons = [{
                "title": f"Apply for {name}",
                "url": data['link'],
                "type": "web_url"
            } for name, data in eligible_schemes[:3]]
            
            return {
                "text": f"🎉 *Based on your profile, you may qualify for these schemes:*" + 
                       "".join(scheme_list) +
                       "\n\nWould you like to:",
                "buttons": buttons,
                "quick_replies": [
                    {"title": "🔄 Check Again", "payload": "eligibility"},
                    {"title": "📋 Browse All", "payload": "all"},
                    {"title": "🏠 Main Menu", "payload": "menu"}
                ],
                "next_step": ConversationSteps.SCHEME_RESULTS
            }
        else:
            return {
                "text": "🤔 We couldn't find any schemes matching your profile. Try adjusting your criteria or browse all schemes:",
                "quick_replies": [
                    {"title": "🔼 Increase Income Limit", "payload": "increase_income"},
                    {"title": "🔄 Change Occupation", "payload": "change_occupation"},
                    {"title": "🌐 Browse All", "payload": "all"},
                    {"title": "🏠 Main Menu", "payload": "menu"}
                ]
            }
    except Exception as e:
        logger.error(f"Location step error: {str(e)}")
        return error_step()

def handle_more_schemes(incoming_msg: str) -> Dict[str, Any]:
    try:
        scheme_type = incoming_msg.replace("more_", "")
        schemes = get_filtered_schemes(scheme_type)
        
        if len(schemes) <= 5:
            return handle_scheme_browsing(scheme_type)
        
        scheme_list = "\n\n".join(
            f"🔹 *{name}*\n   - Benefits: {SCHEME_DATABASE[name]['benefits']}"
            for name in schemes[5:10]
        )
        
        return {
            "text": f"📋 *More {scheme_type.upper()} Schemes:*\n{scheme_list}",
            "quick_replies": [
                {"title": "📄 View Details", "payload": f"details_{scheme_type}"},
                {"title": "⬅️ Back", "payload": scheme_type},
                {"title": "🏠 Main Menu", "payload": "menu"}
            ]
        }
    except Exception as e:
        logger.error(f"More schemes error: {str(e)}")
        return error_step()

def handle_scheme_details(incoming_msg: str) -> Dict[str, Any]:
    try:
        scheme_type = incoming_msg.replace("details_", "")
        schemes = get_filtered_schemes(scheme_type)
        
        return {
            "text": f"🔎 Select a {scheme_type} scheme for full details:",
            "quick_replies": [{"title": name, "payload": f"full_{name}"} for name in schemes[:5]] +
                            [{"title": "⬅️ Back", "payload": scheme_type}]
        }
    except Exception as e:
        logger.error(f"Scheme details error: {str(e)}")
        return error_step()

def show_full_scheme_details(incoming_msg: str) -> Dict[str, Any]:
    try:
        scheme_name = incoming_msg.replace("full_", "")
        scheme = SCHEME_DATABASE.get(scheme_name)
        
        if not scheme:
            return {
                "text": "⚠️ Scheme details not available. Please select another:",
                "quick_replies": [
                    {"title": "🇮🇳 Central Schemes", "payload": "central"},
                    {"title": "🏛️ TN Schemes", "payload": "tn"},
                    {"title": "🏠 Main Menu", "payload": "menu"}
                ]
            }
            
        return {
            "text": (
                f"📄 *{scheme_name}*\n"
                f"   - Category: {scheme['category']}\n"
                f"   - Benefits: {scheme['benefits']}\n"
                f"   - Eligibility:\n      {format_eligibility(scheme['eligibility']).replace('\n', '\n      ')}\n"
                f"   - Deadline: {scheme['deadline']}\n"
                f"   - Steps:\n      {scheme['steps'].replace('\n', '\n      ')}"
            ),
            "buttons": [{
                "title": "🖥️ Apply Online",
                "url": scheme['link'],
                "type": "web_url"
            }],
            "quick_replies": [
                {"title": "🔙 Back", "payload": f"details_{'tn' if scheme['eligibility'].get('state') else 'central'}"},
                {"title": "🏠 Main Menu", "payload": "menu"}
            ]
        }
    except Exception as e:
        logger.error(f"Full scheme details error: {str(e)}")
        return error_step()

def handle_unknown_input(incoming_msg: str) -> Dict[str, Any]:
    predefined_response = get_predefined_response(incoming_msg)
    if predefined_response:
        return {
            "text": predefined_response,
            "quick_replies": [
                {"title": "🔍 Browse Schemes", "payload": "browse"},
                {"title": "✅ Check Eligibility", "payload": "eligibility"},
                {"title": "🏠 Main Menu", "payload": "menu"}
            ]
        }
    
    return {
        "text": "🤖 I didn't understand that. Please choose an option:",
        "quick_replies": [
            {"title": "🔍 Browse Schemes", "payload": "browse"},
            {"title": "✅ Check Eligibility", "payload": "eligibility"},
            {"title": "🆘 Help", "payload": "help"},
            {"title": "🏠 Main Menu", "payload": "menu"}
        ]
    }

def unknown_step() -> Dict[str, Any]:
    return {
        "text": "🔄 It seems we need to start over. Please choose an option:",
        "quick_replies": [
            {"title": "🔍 Browse Schemes", "payload": "browse"},
            {"title": "✅ Check Eligibility", "payload": "eligibility"},
            {"title": "🏠 Main Menu", "payload": "menu"}
        ],
        "next_step": ConversationSteps.WELCOME
    }

def error_step() -> Dict[str, Any]:
    return {
        "text": "⚠️ Something went wrong. Let's start over. Choose an option:",
        "quick_replies": [
            {"title": "🔍 Browse Schemes", "payload": "browse"},
            {"title": "✅ Check Eligibility", "payload": "eligibility"},
            {"title": "🏠 Main Menu", "payload": "menu"}
        ],
        "next_step": ConversationSteps.WELCOME
    }

@app.route("/api/schemes", methods=['GET'])
def list_schemes():
    """API endpoint to list all schemes"""
    try:
        scheme_type = request.args.get('type', 'all')
        schemes = get_filtered_schemes(scheme_type)
        
        return jsonify({
            "schemes": [{"name": name, **SCHEME_DATABASE[name]} for name in schemes],
            "count": len(schemes),
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Scheme list error: {str(e)}")
        return jsonify({"error": "Could not retrieve schemes"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get('DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
