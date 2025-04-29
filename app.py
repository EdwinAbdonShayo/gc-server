from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import spacy
from textblob import TextBlob
from flask_socketio import SocketIO, emit
import os
import json
import traceback  # <-- ADD THIS

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')  # safer for production

print("✅ Flask app initialized.")

nlp = spacy.load("NLP/GC_model3.0")
print("✅ spaCy model loaded successfully.")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "commands.db")  # <- fix: you had a broken DB_PATH!

# Setup DB
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            sender TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("✅ Database initialized.")

init_db()

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"message": "🏓 Pong! Server is alive."}), 200

@app.route('/send-command', methods=['POST'])
def send_command():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        print(f"📥 User said: {user_message}")

        # Spell correction
        blob = TextBlob(user_message)
        corrected_message = str(blob.correct())
        print(f"📝 Corrected message: {corrected_message}")

        # Log user message
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO messages (text, sender) VALUES (?, ?)", (user_message, "user"))
        conn.commit()

        # NER
        doc = nlp(corrected_message)
        entities = [{"text": ent.text, "label": ent.label_} for ent in doc.ents]
        print("🔍 Entities extracted:", entities)

        if not entities:
            response_text = "I couldn't detect any useful info. Please try rephrasing the command."
        else:
            object_ = next((e["text"] for e in entities if e["label"] == "OBJECT"), None)
            locations = [e["text"] for e in entities if e["label"] == "LOCATION"]

            if not object_:
                response_text = "I didn't catch what item you're referring to. Could you name it again?"
            else:
                # Load products.json
                try:
                    with open(os.path.join(BASE_DIR, "products.json"), "r") as f:
                        products = json.load(f)
                except Exception as e:
                    print("❌ Failed to load products.json:", e)
                    return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

                search_term = object_.lower()
                matched_product_id = None

                for product in products:
                    if search_term in product["product_name"].lower():
                        matched_product_id = product["product_id"]
                        break
                    if any(search_term in keyword.lower() for keyword in product["keywords"]):
                        matched_product_id = product["product_id"]
                        break

                if matched_product_id:
                    payload_item = {"product_id": matched_product_id}
                    if len(locations) >= 1:
                        payload_item["location1"] = locations[0]
                    if len(locations) >= 2:
                        payload_item["location2"] = locations[1]

                    payload = [payload_item]

                    socketio.emit('robot_command', {"command": "start", "payload": payload})
                    response_text = f"✅ Sent command to move '{object_}' from {payload_item.get('location1')} to {payload_item.get('location2', '[unspecified]')}"
                else:
                    response_text = f"🧠 I understood you meant '{object_}', but couldn’t match it to any known item."

        # Save bot response
        cursor.execute("INSERT INTO messages (text, sender) VALUES (?, ?)", (response_text, "bot"))
        conn.commit()
        conn.close()

        return jsonify({"response": response_text})

    except Exception as e:
        print("❌ Error in /send-command:", e)
        return jsonify({
            "error": str(e),
            "trace": traceback.format_exc()
        }), 500

@app.route('/get-messages', methods=['GET'])
def get_messages():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT text, sender FROM messages ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        return jsonify([{"text": row[0], "sender": row[1]} for row in rows])
    except Exception as e:
        print("❌ Error fetching messages:", e)
        return jsonify({
            "error": str(e),
            "trace": traceback.format_exc()
        }), 500

@socketio.on("status_update")
def handle_status_update(data):
    message = data.get("message", "")
    print(f"📬 Robot status update: {message}")

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO messages (text, sender) VALUES (?, ?)", (message, "robot"))
        conn.commit()
        conn.close()
    except Exception as e:
        print("❌ Failed to save status update:", e)

@socketio.on("error_report")
def handle_error_report(data):
    error = data.get("error", "")
    print(f"🚨 Robot error reported: {error}")

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO messages (text, sender) VALUES (?, ?)", (f"ERROR: {error}", "robot"))
        conn.commit()
        conn.close()
    except Exception as e:
        print("❌ Failed to save error report:", e)

if __name__ == '__main__':
    # socketio.run(app, host='0.0.0.0', port=5000, debug=True)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
