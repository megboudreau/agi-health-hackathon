"""Flask app: a search box where a clinician types a scenario and gets cited codes."""
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

# Import after load_dotenv so the Anthropic client picks up ANTHROPIC_API_KEY.
from app import rag  # noqa: E402

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/lookup", methods=["POST"])
def api_lookup():
    question = (request.json or {}).get("question", "").strip()
    if not question:
        return jsonify({"error": "Empty question."}), 400
    try:
        response = rag.lookup(question)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 500

    usage = response.usage
    return jsonify(
        {
            "answer": rag.render_answer(response),
            "usage": {
                "input_tokens": usage.input_tokens,
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
                "cache_creation_input_tokens": getattr(
                    usage, "cache_creation_input_tokens", 0
                ),
                "output_tokens": usage.output_tokens,
            },
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
