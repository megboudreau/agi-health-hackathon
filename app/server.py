"""Flask app: a no-login page to analyze a patient's medication list."""
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

# Import after load_dotenv so the Anthropic client picks up ANTHROPIC_API_KEY.
from app import analyze as analyzer  # noqa: E402

app = Flask(__name__)
# Anthropic request limit is 32 MB; cap uploads a little under that.
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    text = request.form.get("text", "")
    files = []
    for storage in request.files.getlist("files"):
        if not storage.filename:
            continue
        files.append((storage.filename, storage.read(), storage.mimetype))

    try:
        answer, usage = analyzer.analyze(text, files)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # surface API errors to the UI rather than a 500 page
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502

    return jsonify(
        {
            "answer": answer,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            },
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
