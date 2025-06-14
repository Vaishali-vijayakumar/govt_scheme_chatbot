from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

user_data = {}

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
        user_data[sender] = {'step': 0}

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

        response_text = "🎯 Based on your profile, you may be eligible for:\n"

        if occ == 'farmer':
            response_text += "- 🌾 PM-KISAN (₹6000/year)\n- 🏠 PMAY Gramin (Rural Housing)\n"
        if age >= 60:
            response_text += "- 👵 Indira Gandhi National Old Age Pension\n"
        if occ == 'widow':
            response_text += "- 👩‍🦳 Widow Pension Scheme\n"
        if occ == 'unemployed' and age <= 30:
            response_text += "- 🧑‍💻 PMEGP Loan\n- 📚 National Career Service\n"
        if caste in ['SC', 'ST']:
            response_text += "- 🏫 SC/ST Scholarships\n- 🏠 Dr. Ambedkar Housing\n"
        if caste == 'OBC':
            response_text += "- 📘 OBC Scholarships\n"
        if income < 15000:
            response_text += "- 🏥 Ayushman Bharat - PMJAY\n"
        if occ == 'student' and age <= 25:
            response_text += "- 🎓 NMMS + State Fee Waivers\n"

        if "tamil nadu" in state:
            response_text += "- 🧕 Kalaignar Magalir Urimai Thogai\n- 🎓 Free Laptop Scheme\n"
        elif "uttar pradesh" in state:
            response_text += "- 👩‍🦳 UP Widow Pension\n- 📘 Kanya Vidya Dhan\n"
        elif "karnataka" in state:
            response_text += "- 👩‍🎓 Yuva Nidhi\n"
        elif "bihar" in state:
            response_text += "- 👧 Kanya Utthan Yojana\n"

        response_text += "\n📋 Want to apply? Type: Apply PM-KISAN, Apply Ayushman, etc."
        user_data[sender]['step'] = 0

    return jsonify({"reply": response_text})

if __name__ == "__main__":
    app.run(debug=True)
