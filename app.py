import os
import logging

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from groq import Groq

from config import Config
from auth import require_api_key
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("docqa")

Config.validate()

app = Flask(__name__)
app.config["API_SECRET_KEY"] = Config.API_SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_FILE_SIZE_MB * 1024 * 1024

CORS(
    app,
    origins=Config.ALLOWED_ORIGINS.split(",") if Config.ALLOWED_ORIGINS != "*" else "*",
)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[Config.RATE_LIMIT_DEFAULT],
    storage_uri=Config.REDIS_URL or "memory://",
)
if not Config.REDIS_URL:
    logger.warning(
        "No REDIS_URL set — rate limiting uses in-process memory, which only "
        "works correctly with a single server instance. Set REDIS_URL before "
        "scaling to multiple instances."
    )

# Schema setup can be skipped in unit tests that don't touch a real DB.
if not os.environ.get("SKIP_DB_INIT"):
    db.init_db()

# Embedding model runs locally — no API cost, no external dependency at query time.
embedder = SentenceTransformer("all-MiniLM-L6-v2")
groq_client = Groq(api_key=Config.GROQ_API_KEY)

ALLOWED_EXTENSIONS = {"pdf"}
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def chunk_text(text):
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c.strip() for c in chunks if c.strip()]


def get_tenant_id():
    """Lets one deployment serve multiple clients without their documents
    mixing. Defaults to 'default' if the caller doesn't set it."""
    return request.headers.get("X-Tenant-ID", "default")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/upload", methods=["POST"])
@require_api_key
@limiter.limit(lambda: Config.RATE_LIMIT_UPLOAD)
def upload():
    tenant_id = get_tenant_id()

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "Only PDF files are supported"}), 400

    filename = secure_filename(file.filename)

    try:
        reader = PdfReader(file.stream)
    except Exception:
        logger.exception("Failed to parse uploaded PDF")
        return jsonify({"error": "Could not read this PDF — it may be corrupted or encrypted"}), 400

    full_text = ""
    for page in reader.pages:
        full_text += (page.extract_text() or "") + "\n"

    if not full_text.strip():
        return jsonify({"error": "Could not extract any text — is this a scanned/image PDF?"}), 400

    chunks = chunk_text(full_text)
    if not chunks:
        return jsonify({"error": "Document produced no usable content"}), 400

    try:
        embeddings = embedder.encode(chunks).tolist()
        db.insert_chunks(tenant_id, filename, chunks, embeddings)
    except Exception:
        logger.exception("Failed to index document for tenant=%s", tenant_id)
        return jsonify({"error": "Internal error while indexing the document"}), 500

    logger.info("Indexed %s for tenant=%s (%d chunks)", filename, tenant_id, len(chunks))
    return jsonify({"message": f"Uploaded and indexed {filename}", "chunks_created": len(chunks)})


@app.route("/ask", methods=["POST"])
@require_api_key
@limiter.limit(lambda: Config.RATE_LIMIT_ASK)
def ask():
    tenant_id = get_tenant_id()
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()

    if not question:
        return jsonify({"error": "No question provided"}), 400
    if len(question) > 2000:
        return jsonify({"error": "Question too long (max 2000 characters)"}), 400

    try:
        question_embedding = embedder.encode([question]).tolist()[0]
        rows = db.search_chunks(tenant_id, question_embedding, top_k=5)
    except Exception:
        logger.exception("Retrieval failed for tenant=%s", tenant_id)
        return jsonify({"error": "Internal error while searching documents"}), 500

    if not rows:
        return jsonify({"answer": "No documents have been uploaded yet for this account.", "sources": []})

    context = "\n\n---\n\n".join(r[0] for r in rows)
    sources = sorted({r[1] for r in rows})

    system_prompt = (
        "You are a document assistant. Answer the user's question using ONLY the "
        "context below, which comes from documents they uploaded. If the answer "
        "isn't in the context, say so clearly instead of guessing. Be concise.\n\n"
        f"CONTEXT:\n{context}"
    )

    try:
        completion = groq_client.chat.completions.create(
            model=Config.GROQ_MODEL,
            max_tokens=1000,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        )
        answer_text = completion.choices[0].message.content
    except Exception:
        logger.exception("Groq API call failed")
        return jsonify({"error": "The AI service is temporarily unavailable — try again shortly"}), 502

    return jsonify({"answer": answer_text, "sources": sources})


@app.route("/reset", methods=["POST"])
@require_api_key
def reset():
    tenant_id = get_tenant_id()
    db.reset_tenant(tenant_id)
    logger.info("Cleared documents for tenant=%s", tenant_id)
    return jsonify({"message": f"Cleared documents for tenant '{tenant_id}'"})


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": f"File too large — max {Config.MAX_FILE_SIZE_MB}MB"}), 413


@app.errorhandler(429)
def rate_limited(e):
    return jsonify({"error": "Rate limit exceeded — slow down and try again"}), 429


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(e):
    logger.exception("Unhandled server error")
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
