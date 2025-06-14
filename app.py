from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

user_data = {}

# Tamil & English scheme apply steps
scheme_steps = {
    "PM-KISAN": "📌 Visit https://pmkisan.gov.in\n🧾 Click 'Farmers Corner' > 'New Farmer Registration'\n📄 Submit Aadhaar, bank & land details.",
    "Ayushman Bharat": "📌 Visit https://pmjay.gov.in\n🧾 Check your name under eligibility.\n🏥 Visit nearest empanelled hospital with ID proof.",
    "Kalaignar Magalir Urimai Thogai": "📌 Apply via Tamil Nadu e-Sevai centers or https://kmut.tn.gov.in\n🧾 Aadhaar-linked bank account required.\n📄 Submit ration card, income certificate.",
    "Old Age Pension": "📌 Apply at your local Panchayat/Revenue Office.\n📄 Submit Age proof, income proof & Aadhaar.",
    "Widow Pension Scheme": "📌 Submit application at Social Welfare Department or online (state portals).\n📄 Required: Death Certificate of spouse, Aadhaar, income proof.",
    "Free Laptop Scheme": "📌 School/college will register eligible students.\n🧾 No separate application needed. Contact institution head.",
    "PMEGP Loan": "📌 Visit https://www.kviconline.gov.in/pmegp\n📄 Register, fill online form with Aadhaar, project details\n🏦 Submit via your preferred bank/financial institution.",
    "SC/ST Scholarships": "📌 Visit https://scholarships.gov.in\n🧾 Select Post/Pre Matric Scholarship.\n📄 Submit caste certificate, Aadhaar, income proof, marksheets.",
    "OBC Scholarships": "📌 Apply via https://scholarships.gov.in or TN e-district portal\n📄 Need caste/income proof, marksheets, bank details.",
    "NMMS": "📌 Application through school\n🧾 Attend exam conducted by education department\n📄 Aadhaar, income certificate, marksheets needed.",
    "CMCHIS": "📌 Enroll at TN e-Sevai centers or special camps\n🧾 Submit Aadhaar, ration card\n🏥 Get e-card, use at empanelled hospitals.",
    "PMAY Gramin": "📌 Visit https://pmayg.nic.in\n🧾 Apply via Panchayat/online.\n📄 Aadhaar, income, land ownership proof needed.",
    "National Apprenticeship Promotion Scheme": "📌 Register at https://apprenticeshipindia.gov.in\n📄 Aadhaar, qualification, bank details required.\n🏢 Find and apply to listed employers.",
    "Uzhavar Pathukappu Thittam": "📌 Tamil Nadu Agriculture Department\n🧾 For registered TN farmers.\n📄 Aadhaar, chitta copy, bank passbook.",
    "Destitute Women Pension": "📌 Apply through TN Social Welfare Dept.\n📄 Widow certificate, income proof, Aadhaar.\n👩‍🦳 For deserted/divorced women."
}

def respond(en_text, ta_text=None):
    return en_text + (f"\n{ta_text}" if ta_text else "")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=['POST'])
def chatbot():
    data = request.get_json()
    incoming_msg = data.get('message', '').strip()
    sender = data.get('sender', 'default_user')
    response_text = ""

    if sender not in user_data:
        user_data[sender] = {'step': 0, 'eligible_schemes': []}

    step = user_data[sender]['step']

    if step == 0:
        response_text = "🙏 வணக்கம்! I’ll help you check eligibility for govt schemes. Shall we begin? (Yes/No)"
        user_data[sender]['step'] = 1

    elif step == 1:
        if 'yes' in incoming_msg.lower():
            response_text = "📌 Please tell me your age (in years):"
            user_data[sender]['step'] = 2
        else:
            response_text = "Okay. Type 'Hi' anytime to start again."
            user_data[sender]['step'] = 0

    elif step == 2:
        try:
            user_data[sender]['age'] = int(incoming_msg)
            response_text = "💰 What is your monthly family income (in ₹)?"
            user_data[sender]['step'] = 3
        except ValueError:
            response_text = "❗ Please enter a valid number for age."

    elif step == 3:
        try:
            user_data[sender]['income'] = int(incoming_msg.replace("₹", "").replace(",", "").strip())
            response_text = "🏷️ Caste? (SC/ST/OBC/General):"
            user_data[sender]['step'] = 4
        except ValueError:
            response_text = "❗ Please enter a valid number for income."

    elif step == 4:
        user_data[sender]['caste'] = incoming_msg.upper()
        response_text = "📍 State and District? (e.g., Tamil Nadu, Thanjavur):"
        user_data[sender]['step'] = 5

    elif step == 5:
        user_data[sender]['location'] = incoming_msg
        response_text = "👩‍🌾 Occupation? (Farmer/Student/Widow/Unemployed/etc.):"
        user_data[sender]['step'] = 6

    elif step == 6:
        user_data[sender]['occupation'] = incoming_msg
        age = user_data[sender]['age']
        income = user_data[sender]['income']
        caste = user_data[sender]['caste']
        occ = user_data[sender]['occupation'].lower()
        state = user_data[sender]['location'].lower()

        eligible = []
        schemes = respond("🎯 Based on your profile, you may be eligible for:\n\n", "🎯 உங்கள் விவரங்களைப் பொறுத்து, நீங்கள் பெறக்கூடிய திட்டங்கள்:\n\n")

        if occ == 'farmer':
            eligible += ["PM-KISAN", "PMAY Gramin"]
            schemes += respond("🌾 PM-KISAN: ₹6000/year support to farmers.\n", "🌾 PM-KISAN: ஆண்டுக்கு ₹6000 நிலத்தடி விவசாயிகளுக்காக.\n")
            schemes += respond("🏠 PMAY Gramin: Rural housing subsidy up to ₹1.2 lakh.\n", "🏠 கிராமப்புற வீட்டு மானியம் ₹1.2 லட்சம் வரை.\n")
            if "tamil nadu" in state:
                eligible.append("Uzhavar Pathukappu Thittam")
                schemes += respond("🌱 Uzhavar Pathukappu Thittam: Farmer insurance + aid in TN.\n", "🌱 உழவர் பாதுகாப்புத் திட்டம்: விவசாயிகளுக்கான பாதுகாப்பு.\n")

        if age >= 60:
            eligible.append("Old Age Pension")
            schemes += respond("👵 Old Age Pension: ₹200–₹500/month for senior citizens.\n", "👵 மூப்புப் பென்ஷன் ₹200–₹500 மாதம்.\n")

        if occ == 'widow':
            eligible.append("Widow Pension Scheme")
            schemes += respond("👩‍🦳 Widow Pension: ₹300–₹500/month support.\n", "👩‍🦳 விதவை பென்ஷன் ₹300–₹500 மாதம்.\n")
            if "tamil nadu" in state:
                eligible.append("Destitute Women Pension")
                schemes += respond("👩‍🦳 Destitute Women Pension: ₹1000/month for TN deserted/divorced women.\n", "👩‍🦳 விதவை/தொழிலிழந்த பெண்களுக்கு ₹1000 உதவித் தொகை.\n")

        if occ == 'unemployed' and age <= 30:
            eligible.append("PMEGP Loan")
            schemes += respond("🧑‍💻 PMEGP Loan: Business loan + subsidy.\n", "🧑‍💻 PMEGP: தொழில் தொடங்க கடன் + மானியம்.\n")
            eligible.append("National Apprenticeship Promotion Scheme")
            schemes += respond("🛠️ NAPS: Skill training + stipend.\n", "🛠️ தேசிய பயிற்சி ஊக்கத்திட்டம்.\n")

        if caste in ['SC', 'ST']:
            eligible.append("SC/ST Scholarships")
            schemes += respond("🏫 SC/ST Scholarships: Central/state education aid.\n", "🏫 SC/ST கல்வி உதவித்தொகை.\n")

        if caste == 'OBC':
            eligible.append("OBC Scholarships")
            schemes += respond("📘 OBC Scholarships: For school/college students.\n", "📘 OBC கல்வி உதவித்தொகை.\n")

        if income < 15000:
            eligible.append("Ayushman Bharat")
            schemes += respond("🏥 Ayushman Bharat (PMJAY): ₹5L health insurance.\n", "🏥 ஆயுஷ்மான் பாரத்: ₹5 லட்சம் மருத்துவ காப்பீடு.\n")

        if occ == 'student' and age <= 25:
            eligible.append("NMMS")
            schemes += respond("🎓 NMMS: Monthly stipend for school students.\n", "🎓 NMMS: பள்ளி மாணவர்களுக்கு மாத உதவித்தொகை.\n")

        if "tamil nadu" in state:
            eligible += ["Kalaignar Magalir Urimai Thogai", "Free Laptop Scheme", "CMCHIS"]
            schemes += respond("🧕 Kalaignar Magalir Urimai Thogai: ₹1000/month for women heads.\n", "🧕 மகளிர் உரிமை தொகை ₹1000 மாதம்.\n")
            schemes += respond("🎓 Free Laptop Scheme: Govt students in Class 11/College.\n", "🎓 இலவச லாப்டாப் அரசு பள்ளி/கல்லூரிக்கு.\n")
            schemes += respond("🛏️ CMCHIS: TN health insurance ₹5L/year.\n", "🛏️ முதல்வரின் மருத்துவ காப்பீடு ₹5 லட்சம்.\n")

        user_data[sender]['eligible_schemes'] = eligible
        schemes += "\n📥 Would you like steps to apply for any of these? (Yes/No)"
        response_text = schemes.strip()
        user_data[sender]['step'] = 7

    elif step == 7:
        if 'yes' in incoming_msg.lower():
            response_text = "✍️ Please type the name of the scheme you'd like to apply for (e.g., PM-KISAN):"
            user_data[sender]['step'] = 8
        else:
            response_text = "✅ Okay. You can type 'Hi' anytime to check again."
            user_data[sender]['step'] = 0

    elif step == 8:
        scheme = incoming_msg.strip().upper()
        matched = None
        for key in scheme_steps:
            if key.lower() in scheme.lower():
                matched = key
                break

        if matched:
            response_text = f"📝 Steps to apply for {matched}:\n{scheme_steps[matched]}"
        else:
            response_text = "❗ Sorry, I don’t have steps for that scheme yet. Try another or type 'Hi' to restart."
        user_data[sender]['step'] = 0

    return jsonify({"reply": response_text})

if __name__ == "__main__":
    app.run(debug=True)
