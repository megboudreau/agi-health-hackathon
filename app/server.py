"""Flask app: medication analysis + mid-visit drug check."""
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

from app import analyze as analyzer  # noqa: E402
from app import formulary

formulary.load()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    text = request.form.get("text", "")
    patient_context = request.form.get("patient_context", "").strip()
    context_files = []
    for storage in request.files.getlist("context_files"):
        if not storage.filename:
            continue
        context_files.append((storage.filename, storage.read(), storage.mimetype))
    files = []
    for storage in request.files.getlist("files"):
        if not storage.filename:
            continue
        files.append((storage.filename, storage.read(), storage.mimetype))

    try:
        answer, usage = analyzer.analyze(
            text, files,
            patient_context=patient_context,
            context_files=context_files,
        )
        print(f"[analyze] in={usage.input_tokens} out={usage.output_tokens}", flush=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502

    return jsonify({
        "answer": answer,
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
    })


@app.route("/api/explain", methods=["POST"])
def api_explain():
    item = request.form.get("item", "").strip()
    if not item:
        return jsonify({"error": "No item provided"}), 400
    try:
        explanation, usage = analyzer.explain(item)
        print(f"[explain] in={usage.input_tokens} out={usage.output_tokens}", flush=True)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502
    return jsonify({"explanation": explanation})


@app.route("/api/check-drug", methods=["POST"])
def api_check_drug():
    new_drug = request.json.get("drug", "").strip()
    current_analysis = request.json.get("analysis", "").strip()
    if not new_drug:
        return jsonify({"error": "No drug provided"}), 400

    # Normalize input (handles EN or FR drug names) via Haiku
    names = analyzer.resolve_drug(new_drug)
    english_name = names.get("english", new_drug)
    french_name = names.get("french", new_drug)
    print(f"[check-drug] normalized: {new_drug!r} → EN={english_name!r} FR={french_name!r}", flush=True)

    # RAMQ formulary lookup — try raw input, then normalized names
    formulary_result = (
        formulary.search(new_drug) or
        formulary.search(english_name) or
        formulary.search(french_name)
    )

    # Translate French indication texts to English
    if formulary_result and formulary_result.get("codes"):
        french_texts = [c["indication"] for c in formulary_result["codes"]]
        en_texts = analyzer.translate_indications(french_texts)
        for i, code in enumerate(formulary_result["codes"]):
            if i < len(en_texts):
                code["indication"] = en_texts[i]

    # Targeted Claude interaction check using the English INN name
    try:
        analysis, usage = analyzer.check_drug(english_name, current_analysis)
        print(f"[check-drug] {english_name} in={usage.input_tokens} out={usage.output_tokens}", flush=True)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502

    return jsonify({
        "formulary": formulary_result,
        "analysis": analysis,
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
    })


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
