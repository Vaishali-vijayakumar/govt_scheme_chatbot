from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import logging
from datetime import datetime, timedelta
import uuid
import os
from dotenv import load_dotenv
import openai

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Configuration
app.secret_key = os.getenv('SECRET_KEY', 'supersecretkey')

# Initialize services
openai.api_key = os.getenv('OPENAI_API_KEY')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Session management
user_sessions = {}

# Enhanced scheme database
scheme_database = {
    # Add these schemes to your existing scheme_database dictionary (after the current schemes)

    # Additional Central Government Schemes
    "PM Matsya Sampada Yojana": {
        "category": "Fisheries",
        "steps": "1. Register at fisheries department\n2. Submit project proposal\n3. Get approval for subsidy",
        "eligibility": {"occupation": ["fisherman", "fish farmer"], "min_age": 18},
        "benefits": "Up to 40% subsidy for aquaculture projects",
        "deadline": "2024-12-31",
        "link": "https://dof.gov.in/pmmsy"
    },
    "PM Formalization of Micro Food Enterprises (PM FME)": {
        "category": "Food Processing",
        "steps": "1. Register on FME portal\n2. Submit business details\n3. Get training and certification",
        "eligibility": {"business_type": ["food processing"], "employees_max": 10},
        "benefits": "Credit linked capital subsidy up to ₹10 lakh",
        "deadline": "2024-03-31",
        "link": "https://mofpi.nic.in/pmfme"
    },
    "PM Kisan Maan Dhan Yojana": {
        "category": "Pension",
        "steps": "1. Visit CSC center\n2. Submit Aadhaar and bank details\n3. Pay monthly contribution",
        "eligibility": {"occupation": ["farmer"], "age_range": [18, 40]},
        "benefits": "₹3,000/month pension after 60 years",
        "deadline": "Ongoing",
        "link": "https://pmkmy.gov.in"
    },
    "Sukanya Samriddhi Yojana": {
        "category": "Savings",
        "steps": "1. Open account at post office/bank\n2. Submit birth certificate\n3. Make regular deposits",
        "eligibility": {"gender": "female", "max_age": 10, "account_opener": "parent/guardian"},
        "benefits": "High interest rate (7.6%) with tax benefits",
        "deadline": "Ongoing",
        "link": "https://www.indiapost.gov.in"
    },
    "PM Swanidhi Yojana": {
        "category": "Urban Development",
        "steps": "1. Apply through municipal corporation\n2. Submit vendor certificate\n3. Get loan approval",
        "eligibility": {"occupation": ["street vendor"], "urban": True},
        "benefits": "₹10,000 working capital loan",
        "deadline": "2024-12-31",
        "link": "https://pmsvanidhi.mohua.gov.in"
    },
    "National Apprenticeship Promotion Scheme (NAPS)": {
        "category": "Employment",
        "steps": "1. Register on portal\n2. Find employer\n3. Complete apprenticeship",
        "eligibility": {"min_age": 16, "qualification": ["8th pass", "10th pass", "diploma", "graduate"]},
        "benefits": "Stipend + government contribution",
        "deadline": "Ongoing",
        "link": "https://www.apprenticeshipindia.gov.in"
    },
    "Pradhan Mantri Mudra Yojana": {
        "category": "Loans",
        "steps": "1. Approach participating bank/NBFC\n2. Submit business plan\n3. Get loan approval",
        "eligibility": {"business_type": ["micro enterprise"], "loan_amount": ["up to 10L"]},
        "benefits": "Collateral-free loans up to ₹10 lakh",
        "deadline": "Ongoing",
        "link": "https://www.mudra.org.in"
    },
    "Atal Pension Yojana": {
        "category": "Pension",
        "steps": "1. Open account at bank/post office\n2. Choose pension amount\n3. Make regular contributions",
        "eligibility": {"age_range": [18, 40], "bank_account": True},
        "benefits": "Guanteed pension ₹1,000-5,000/month after 60",
        "deadline": "Ongoing",
        "link": "https://www.jansuraksha.gov.in"
    },
    "PM Garib Kalyan Anna Yojana": {
        "category": "Food Security",
        "steps": "1. Possess ration card\n2. Visit fair price shop\n3. Collect free grains",
        "eligibility": {"ration_card": True, "category": ["priority", "antyodaya"]},
        "benefits": "5kg free grains per person/month",
        "deadline": "2024-12-31",
        "link": "https://dfpd.gov.in"
    },
    "Digital India Bhashini": {
        "category": "Technology",
        "steps": "1. Register on portal\n2. Complete training\n3. Contribute translations",
        "eligibility": {"language_skills": True, "min_age": 18},
        "benefits": "Earnings for language contributions",
        "deadline": "Ongoing",
        "link": "https://www.bhashini.gov.in"
    },

    # Additional Tamil Nadu Government Schemes
    "Moovalur Ramamirtham Ammal Scheme": {
        "category": "Education",
        "steps": "1. Apply through school\n2. Submit income certificate\n3. Receive assistance",
        "eligibility": {"state": "Tamil Nadu", "gender": "female", "education": ["12th pass"]},
        "benefits": "₹1,000/month for higher education",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "Namma Veettu Thozhilalan Scheme": {
        "category": "Employment",
        "steps": "1. Register at employment office\n2. Submit unemployment proof\n3. Receive allowance",
        "eligibility": {"state": "Tamil Nadu", "unemployed": True, "min_age": 21},
        "benefits": "₹2,000/month unemployment allowance",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "Green Tamil Nadu Mission": {
        "category": "Environment",
        "steps": "1. Register as volunteer\n2. Participate in plantation drives\n3. Maintain plants",
        "eligibility": {"state": "Tamil Nadu", "min_age": 18},
        "benefits": "Incentives for successful plantations",
        "deadline": "Ongoing",
        "link": "https://www.forests.tn.gov.in"
    },
    "Thayumanavar Scheme": {
        "category": "Healthcare",
        "steps": "1. Register at primary health center\n2. Submit age proof\n3. Receive health card",
        "eligibility": {"state": "Tamil Nadu", "min_age": 60},
        "benefits": "Free healthcare for seniors",
        "deadline": "Ongoing",
        "link": "https://www.tnhealth.tn.gov.in"
    },
    "Dr. Muthulakshmi Reddy Maternity Benefit Scheme": {
        "category": "Women Welfare",
        "steps": "1. Register at health center during pregnancy\n2. Submit hospital records\n3. Receive amount",
        "eligibility": {"state": "Tamil Nadu", "gender": "female", "pregnant": True},
        "benefits": "₹18,000 maternity assistance",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "Farmers Accident Relief Scheme": {
        "category": "Agriculture",
        "steps": "1. Register at agriculture office\n2. Pay premium\n3. Claim in case of accident",
        "eligibility": {"state": "Tamil Nadu", "occupation": ["farmer"], "min_age": 18},
        "benefits": "₹5 lakh accident insurance",
        "deadline": "Ongoing",
        "link": "https://www.tnagrisnet.tn.gov.in"
    },
    "Free Bus Travel for Women": {
        "category": "Transport",
        "steps": "1. Apply for pink pass\n2. Submit ID proof\n3. Get travel pass",
        "eligibility": {"state": "Tamil Nadu", "gender": "female"},
        "benefits": "Free travel in government buses",
        "deadline": "Ongoing",
        "link": "https://www.tnstc.in"
    },
    "Amma Cement Scheme": {
        "category": "Housing",
        "steps": "1. Apply at ration shop\n2. Submit construction proof\n3. Purchase cement at subsidy",
        "eligibility": {"state": "Tamil Nadu", "construction": True, "ration_card": True},
        "benefits": "Cement at ₹300/bag (max 750 bags)",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "Amma Water Scheme": {
        "category": "Water Supply",
        "steps": "1. Apply at municipal office\n2. Submit residence proof\n3. Get water connection",
        "eligibility": {"state": "Tamil Nadu", "urban_poor": True},
        "benefits": "Free drinking water connection",
        "deadline": "Ongoing",
        "link": "https://www.twadboard.tn.gov.in"
    },
    "Tamil Nadu Solar Rooftop Scheme": {
        "category": "Energy",
        "steps": "1. Apply on TANGEDCO portal\n2. Get technical approval\n3. Install with subsidy",
        "eligibility": {"state": "Tamil Nadu", "electricity_consumer": True},
        "benefits": "20-40% subsidy on solar plants",
        "deadline": "2024-03-31",
        "link": "https://www.tangedco.gov.in"
    },
    "PM-KISAN": {
        "category": "Agriculture",
        "steps": "1. Visit https://pmkisan.gov.in\n2. Click 'Farmers Corner' > 'New Farmer Registration'\n3. Submit Aadhaar, bank & land details",
        "eligibility": {"min_age": 18, "occupation": ["farmer"], "income_max": None},
        "benefits": "₹6,000/year in 3 installments",
        "deadline": "Ongoing",
        "link": "https://pmkisan.gov.in"
    },
    "Ayushman Bharat (PMJAY)": {
        "category": "Healthcare",
        "steps": "1. Check eligibility at https://pmjay.gov.in\n2. Visit empanelled hospital with ID proof",
        "eligibility": {"income_max": 150000, "family_structure": ["all"]},
        "benefits": "Health insurance up to ₹5 lakh per family/year",
        "deadline": "Ongoing",
        "link": "https://pmjay.gov.in"
    },
    "Pradhan Mantri Awas Yojana (PMAY)": {
        "category": "Housing",
        "steps": "1. Apply via municipal corporation/gram panchayat\n2. Submit required documents\n3. Wait for verification",
        "eligibility": {"income_max": 180000, "house_ownership": False},
        "benefits": "Up to ₹2.67 lakh subsidy for urban areas",
        "deadline": "2024-12-31",
        "link": "https://pmaymis.gov.in"
    },
    "Ujjwala Yojana": {
        "category": "Social Welfare",
        "steps": "1. Submit application at LPG distributor\n2. Provide BPL certificate and Aadhaar",
        "eligibility": {"gender": "female", "bpl_status": True},
        "benefits": "Free LPG connection with cylinder",
        "deadline": "Ongoing",
        "link": "https://www.pmuy.gov.in"
    },
    "Stand-Up India": {
        "category": "Entrepreneurship",
        "steps": "1. Apply through participating banks\n2. Submit business plan and documents",
        "eligibility": {"gender": ["female", "sc/st"], "min_age": 18},
        "benefits": "Loan from ₹10 lakh to ₹1 crore",
        "deadline": "Ongoing",
        "link": "https://www.standupmitra.in"
    },
    "PM SVANidhi": {
        "category": "Urban Development",
        "steps": "1. Apply through municipal corporation\n2. Submit vendor certificate and Aadhaar",
        "eligibility": {"occupation": ["street vendor"], "urban": True},
        "benefits": "₹10,000 working capital loan",
        "deadline": "2024-12-31",
        "link": "https://pmsvanidhi.mohua.gov.in"
    },
    
    # Tamil Nadu State Schemes
    "Kalaignar Magalir Urimai Thogai": {
        "category": "Social Welfare",
        "steps": "1. Apply at ration shops/e-sevai centers\n2. Submit Aadhaar and family details",
        "eligibility": {"state": "Tamil Nadu", "gender": "female", "family_head": True},
        "benefits": "₹1,000/month for women family heads",
        "deadline": "Ongoing",
        "link": "https://kmut.tn.gov.in"
    },
    "CMCHIS": {
        "category": "Healthcare",
        "steps": "1. Enroll at designated camps\n2. Submit ration card and Aadhaar",
        "eligibility": {"state": "Tamil Nadu", "income_max": 75000},
        "benefits": "Health insurance up to ₹5 lakh/year",
        "deadline": "Ongoing",
        "link": "https://www.cmchistn.gov.in"
    },
    "Free Laptop Scheme": {
        "category": "Education",
        "steps": "1. No separate application needed\n2. Schools/colleges will distribute",
        "eligibility": {"state": "Tamil Nadu", "education": ["12th", "college"]},
        "benefits": "Free laptop for students",
        "deadline": "Annual",
        "link": "https://www.tn.gov.in"
    },
    "Uzhavar Pathukappu Thittam": {
        "category": "Agriculture",
        "steps": "1. Register at agriculture department office\n2. Submit land records",
        "eligibility": {"state": "Tamil Nadu", "occupation": ["farmer"]},
        "benefits": "₹5,000 aid during natural calamities",
        "deadline": "Ongoing",
        "link": "https://www.tnagrisnet.tn.gov.in"
    },
    "Amma Two-Wheeler Scheme": {
        "category": "Social Welfare",
        "steps": "1. Apply through transport department\n2. Submit income certificate",
        "eligibility": {"state": "Tamil Nadu", "gender": "female", "income_max": 250000},
        "benefits": "50% subsidy up to ₹25,000",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    },
    "Chief Minister's Breakfast Scheme": {
        "category": "Education",
        "steps": "1. Automatic enrollment for government school students\n2. No application needed",
        "eligibility": {"state": "Tamil Nadu", "education": ["school"]},
        "benefits": "Free nutritious breakfast",
        "deadline": "Ongoing",
        "link": "https://www.tn.gov.in"
    }
}

def get_ai_response(prompt):
    """Get contextual response from OpenAI"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You're a helpful government scheme assistant. Provide concise, accurate information about Indian government schemes."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message['content']
    except Exception as e:
        logger.error(f"AI Error: {str(e)}")
        return None

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/chat", methods=['POST'])
def chatbot():
    try:
        data = request.get_json()
        incoming_msg = data.get('message', '').strip()
        sender_id = data.get('sender', str(uuid.uuid4()))
        
        # Initialize or retrieve session
        if sender_id not in user_sessions:
            user_sessions[sender_id] = {
                "step": 0,
                "context": {},
                "created_at": datetime.now(),
                "last_active": datetime.now()
            }
        
        session = user_sessions[sender_id]
        session['last_active'] = datetime.now()
        
        # Determine response
        if session['step'] == 0:
            response = {
                "text": "Welcome to the Government Scheme Assistant! Would you like to:\n1. Check eligibility\n2. Browse schemes\n3. Get application help",
                "quick_replies": [
                    {"title": "Check Eligibility", "payload": "eligibility"},
                    {"title": "Browse Schemes", "payload": "browse"},
                    {"title": "Get Help", "payload": "help"}
                ]
            }
            session['step'] = 1
        
        elif session['step'] == 1:
            if "eligibility" in incoming_msg.lower():
                response = {
                    "text": "Let's check your eligibility. What is your age in years?",
                    "quick_replies": [
                        {"title": "Under 18", "payload": "under_18"},
                        {"title": "18-30", "payload": "18_30"},
                        {"title": "31-45", "payload": "31_45"},
                        {"title": "46-60", "payload": "46_60"},
                        {"title": "60+", "payload": "60_plus"}
                    ]
                }
                session['step'] = 2
            elif "browse" in incoming_msg.lower():
                schemes = list(scheme_database.keys())[:5]
                response = {
                    "text": "Here are some key government schemes:\n\n" +
                            "\n".join([f"• {name}: {scheme_database[name]['benefits']}" for name in schemes]),
                    "quick_replies": [{"title": name, "payload": f"details_{name}"} for name in schemes] +
                                    [{"title": "See More", "payload": "more_schemes"}]
                }
            else:
                response = {
                    "text": get_ai_response(incoming_msg) or "I can help with government schemes. Please ask about eligibility, benefits, or application process.",
                    "quick_replies": [
                        {"title": "Check Eligibility", "payload": "eligibility"},
                        {"title": "Browse Schemes", "payload": "browse"}
                    ]
                }
        
        elif session['step'] == 2:  # Age
            try:
                age = int(''.join(filter(str.isdigit, incoming_msg)))
                session['context']['age'] = age
                response = {
                    "text": "What is your approximate annual family income in ₹?",
                    "quick_replies": [
                        {"title": "Under 1L", "payload": "income_1L"},
                        {"title": "1L-3L", "payload": "income_1_3L"},
                        {"title": "3L-5L", "payload": "income_3_5L"},
                        {"title": "5L-10L", "payload": "income_5_10L"},
                        {"title": "10L+", "payload": "income_10L_plus"}
                    ]
                }
                session['step'] = 3
            except:
                response = {"text": "Please enter a valid age number (e.g., 25)"}
        
        elif session['step'] == 3:  # Income
            session['context']['income'] = incoming_msg
            response = {
                "text": "What is your occupation?",
                "quick_replies": [
                    {"title": "Farmer", "payload": "occupation_farmer"},
                    {"title": "Student", "payload": "occupation_student"},
                    {"title": "Business", "payload": "occupation_business"},
                    {"title": "Unemployed", "payload": "occupation_unemployed"},
                    {"title": "Other", "payload": "occupation_other"}
                ]
            }
            session['step'] = 4
        
        elif session['step'] == 4:  # Occupation
            session['context']['occupation'] = incoming_msg.lower()
            response = {
                "text": "Which state do you reside in?",
                "quick_replies": [
                    {"title": "Tamil Nadu", "payload": "state_tn"},
                    {"title": "Other State", "payload": "state_other"}
                ]
            }
            session['step'] = 5
        
        elif session['step'] == 5:  # State
            session['context']['state'] = "Tamil Nadu" if "tamil" in incoming_msg.lower() else "Other"
            
            # Find eligible schemes
            eligible_schemes = []
            for name, data in scheme_database.items():
                eligible = True
                
                # Check age
                if data['eligibility'].get('min_age') and session['context'].get('age', 0) < data['eligibility']['min_age']:
                    eligible = False
                
                # Check income
                if data['eligibility'].get('income_max') and session['context'].get('income', '').startswith(('income_3', 'income_5', 'income_10')) and data['eligibility']['income_max'] < 300000:
                    eligible = False
                
                # Check occupation
                if data['eligibility'].get('occupation') and session['context'].get('occupation') not in data['eligibility']['occupation']:
                    eligible = False
                
                # Check state
                if data['eligibility'].get('state') and session['context'].get('state') != data['eligibility']['state']:
                    eligible = False
                
                if eligible:
                    eligible_schemes.append(name)
            
            if eligible_schemes:
                response_text = "Based on your profile, you may be eligible for:\n\n" + \
                                "\n".join([f"• {name}: {scheme_database[name]['benefits']}" for name in eligible_schemes[:5]])
                
                if len(eligible_schemes) > 5:
                    response_text += "\n\n...and more"
                
                response = {
                    "text": response_text,
                    "quick_replies": [{"title": name, "payload": f"details_{name}"} for name in eligible_schemes[:5]] +
                                      [{"title": "Start Over", "payload": "start_over"}]
                }
            else:
                response = {
                    "text": "No schemes found matching your profile. Try adjusting your criteria or browse all schemes.",
                    "quick_replies": [
                        {"title": "Browse All Schemes", "payload": "browse"},
                        {"title": "Start Over", "payload": "start_over"}
                    ]
                }
            session['step'] = 6
        
        elif session['step'] == 6 and incoming_msg.startswith("details_"):
            scheme_name = incoming_msg[8:]
            if scheme_name in scheme_database:
                scheme = scheme_database[scheme_name]
                response = {
                    "text": f"📋 {scheme_name}\n\nBenefits: {scheme['benefits']}\n\nEligibility:\n" +
                            "\n".join([f"• {key}: {value}" for key, value in scheme['eligibility'].items()]) +
                            f"\n\nApplication Steps:\n{scheme['steps']}",
                    "buttons": [{"title": "Apply Online", "url": scheme['link']}],
                    "quick_replies": [
                        {"title": "Check Another Scheme", "payload": "browse"},
                        {"title": "Start Over", "payload": "start_over"}
                    ]
                }
            else:
                response = {"text": "Scheme not found. Please try another one."}
        
        else:
            response = {
                "text": "I didn't understand that. Type 'help' for options or 'start over' to begin again.",
                "quick_replies": [
                    {"title": "Help", "payload": "help"},
                    {"title": "Start Over", "payload": "start_over"}
                ]
            }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Chatbot error: {str(e)}")
        return jsonify({"text": "An error occurred. Please try again later."}), 500

@app.route("/api/schemes", methods=['GET'])
def list_schemes():
    """API endpoint to list all schemes"""
    return jsonify({
        "central_schemes": [name for name, data in scheme_database.items() if not data['eligibility'].get('state')],
        "tn_schemes": [name for name, data in scheme_database.items() if data['eligibility'].get('state') == "Tamil Nadu"]
    })

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
