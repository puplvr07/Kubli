# WardNote

An offline encounter-drafting and study companion for medical students and interns. Type or dictate a presentation, review a SOAP draft, and explicitly confirm it before saving to an encrypted local vault. Import your own sources for cited questions and documentation prompts.

**Draft-support tool. Not a diagnostic tool and not the official medical record.**

This is a hackathon prototype. Use fictional/de-identified encounters for demonstrations. Included checklists are **SAMPLE ONLY, not real clinical guidance**.

## Repository

```text
backend/
  app/main.py             Loopback FastAPI server, session lifecycle, privacy boundary
  app/schemas.py          Strict SOAP and request schemas
  app/routers/            Records/PDF, library/completeness, demo, transcription
  app/services/           LLM, grounding, numeric checks, crypto/vault, parsing/RAG, STT
  scripts/                Explicit pre-demo Whisper download utility
  tests/                  pytest unit/API tests and opt-in real-model integration tests
  requirements.txt
frontend/
  src/pages/              Lock, Main, Library, Ask
  src/components/         Editable review form, recorder, citation context, offline proof
  public/fonts/           Bundled DejaVu fonts and license
  package.json
  package-lock.json
guidelines/               Three fictional sample checklists and one sample notes file
```

## Prerequisites

- Python **3.11+** (tested with 3.12), Node **20.19+ or 22.12+** (tested with 24), npm.
- A locally installed [Ollama](https://ollama.com/download), running on **127.0.0.1:11434**. Use a current supported release; cloud smoke checks used the 0.6.8 binary.
- Enough disk/RAM for Qwen 3B, nomic embeddings and multilingual Whisper small; allow several GB of model storage and at least 8 GB RAM. CPU operation is supported.
- Optional local Tesseract for image/scanned-PDF OCR. On Debian/Ubuntu: `sudo apt install tesseract-ocr`.

**Downloads are an explicit preparation step, before processing any encounters.** The running application never pulls models, uses cloud inference, or sends uploads/transcripts to an external destination. Once dependencies and weights are installed, internet is unnecessary. Package installation and the separate download utility do require internet.

## Exact setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
```

Windows: activate using `.venv\Scripts\activate`; run the backend/frontend in separate terminals. The supplied cloud setup is Linux amd64.

Start Ollama in its own terminal (or use its desktop service). Keep it bound to loopback and do not enable debug logging:

```bash
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NOHISTORY=1 ollama serve
```

Then prepare the two local Ollama models:

```bash
ollama pull qwen2.5:3b-instruct
ollama pull nomic-embed-text
ollama list
```

Prepare multilingual speech recognition **before going offline**:

```bash
source .venv/bin/activate
cd backend
python scripts/download_whisper.py --model small
cd ..
```

The download utility writes `.wardnote/models/whisper-small` at the repository root. It is a separate setup program, never called by the app. Model files must be a faster-whisper/CTranslate2 model, not an original Whisper `.pt` file.

## Run

Terminal 1, from the repository root:

```bash
source .venv/bin/activate
export WHISPER_MODEL_PATH="$PWD/.wardnote/models/whisper-small"
cd backend
python -m app.main
```

Terminal 2, from the repository root:

```bash
NPM_CONFIG_UPDATE_NOTIFIER=false npm run preview --prefix frontend
```

Open **`http://127.0.0.1:5173`** in a current browser. The backend always binds to **127.0.0.1:8000**. Use the exact `127.0.0.1` frontend origin; a `localhost` alias, custom origin, or LAN address is deliberately rejected by CORS/origin checks.

For frontend development use `NPM_CONFIG_UPDATE_NOTIFIER=false npm run dev --prefix frontend` instead of preview. HMR and its injected websocket client are disabled to preserve the strict local-backend-only `connect-src` policy; reload the page after changes. Never run preview and dev on the same port simultaneously. After frontend edits, rebuild before using preview.

On first launch, choose a password of at least ten characters. There is no password recovery. The app stores a salt and an encrypted known verifier, not your password or a password hash. Unlocking returns an in-memory session token; the frontend does not persist it to browser storage. Closing/refreshing the frontend requires another unlock.

Supported environment variables (set before starting the backend):

| Variable | Default / meaning |
| --- | --- |
| `OLLAMA_MODEL` | `qwen2.5:3b-instruct` — must already be pulled locally |
| `EMBED_MODEL` | `nomic-embed-text` — reindex after changing this |
| `RAG_TOP_K` | `6` — number of in-scope chunks sent to the answer model; allowed range 1–50 |
| `RAG_NUM_PREDICT` | `256` — maximum generated tokens for cited answers; allowed range 32–4096 |
| `RAG_TIMEOUT_SECONDS` | `60` — total time allowed for an answer and its validation retry; allowed range 1–600 |
| `WHISPER_MODEL` | `small` — multilingual cached model; never downloaded at runtime |
| `WHISPER_MODEL_PATH` | Optional path to an already downloaded faster-whisper model directory |
| `WHISPER_CACHE_DIR` | Optional existing cache directory when using `WHISPER_MODEL` |
| `AUTO_LOCK_MINUTES` | `5` — allowed range 0.1–60 minutes |
| `WARDNOTE_DATA_DIR` | Repository `.wardnote/` — local encrypted vault directory |

CPU int8 is enforced for STT. Ollama's host is fixed in application code to loopback, so a remote `OLLAMA_HOST` cannot redirect patient content. No dotenv loader is used; export variables in the launching shell. Model/data directories must stay on your own local disk.

## Workflow

1. Type an encounter, or **Dictate encounter → Stop**. Correct the editable transcript.
2. Click **Structure from text**. Missing data remains null / Not stated. The model gets a strict JSON schema and one retry for invalid output. A deterministic source check removes unsupported excerpts, stripped qualifiers, and ungrounded vitals.
3. Review or edit **every** amber field. Numeric warnings need explicit source confirmation. These are plausibility checks, not prescribing/lab interpretation.
4. Remove identifier warnings (recommended), or explicitly choose **Keep**. The heuristic scan is a warning aid, not an anonymization guarantee.
5. Optionally **Check completeness** against your indexed notes and guidelines.
6. Click **Confirm and save**. Export PDF only after saving; edits create a new saved draft. Clear discards the unsaved workspace. PDF export always uses the selected saved version.
7. **Lock vault** discards the unsaved UI and clears the session key/index. Inactivity also locks. Only encrypted saved drafts survive.

### Library

Choose up to ten PDF/DOCX/TXT/MD/image files, set **My notes / Guideline / Textbook**, and optionally enable best-effort local OCR. Review extracted identifier warnings before **Proceed and index**. You may cancel or exclude individual files; unconfirmed uploads are not saved. If a batch partly succeeds, completed files remain in the library; exclude those before retrying failed files.

Uploads are bounded to 20 MB/file, 30 MB combined, 32 MB including request framing, 500 pages per PDF, 2,000 chunks per document, and 2,000,000 extracted characters; multipart content stays in memory. OCR uses Tesseract through stdin/stdout, avoiding plaintext image temporary files. Originals are not retained. Parsed text, filenames, tags, timestamps, and vectors are encrypted in SQLite. The index is reconstructed in memory at unlock, then cleared at lock.

PDF citations use real page numbers, including pages skipped for having no text. DOCX uses heading-based **sections**, since reliable page layout is unavailable without a document renderer. TXT/MD form-feed characters delimit pages; otherwise the location is page 1. Chunks are approximately 400 tokens using a character estimate with 50-token overlap, never crossing source pages/sections.

Ask embeds every chunk in the selected source types, ranks them by cosine similarity, and uses keyword overlap only as a small optional boost. Nomic embeddings use matching `search_document:` and `search_query:` prefixes; run **Reindex** once after upgrading an existing vault to this version. The top retrieved chunk IDs and similarity scores are returned in an internal `_debug` field for local diagnostics and are not displayed in the normal UI.

The answer model receives only the retrieved chunks and must return strict schema-bound JSON. Answered responses are limited to three sentences and require a known chunk ID plus a short quote that is verified after whitespace normalization and case folding. Truncated, malformed, timed-out, or unverifiable model responses are retried once and then shown as a retryable **local model error**; they are never converted to **Not covered by your library**. That exact response is reserved for an empty scoped library or a valid model `not_covered` result. Click citations to inspect the supporting passage. Completeness emits only “Consider documenting…” prompts from explicit `Document:`, `Record:`, or `Consider documenting:` checklist lines; it never supplies diagnoses.

Deletion removes the document and its chunks. Reindex replaces vectors only after all embedding calls succeed. Changing embedding models requires reindexing. Sample library imports are idempotent by sample filename.

## Tests

From the repository root:

```bash
source .venv/bin/activate
python -m pytest backend/tests -q
python -m pip check
npm run build --prefix frontend
npm audit --prefix frontend
```

Ordinary tests use controlled local-model responses to exercise failure handling and grounding. They test numeric boundaries, identifier regexes, wrong-password failure, per-payload salts and authenticated metadata, encrypted chunks/records, index rebuild at unlock, page-preserving parsing/chunking, embedding-first retrieval, malformed/truncated output, citation validation, explicit-save gates, PDF text/pages, blocked external sockets, local-only STT configuration, and missing-model errors. Real-model tests are opt-in; skipping them does **not** verify inference.

After Ollama is running and both models are pulled:

```bash
RUN_LIVE_MODEL_TESTS=1 python -m pytest -m live -q
```

The live RAG suite builds four synthetic documents through the real embedding/indexing pipeline. It checks a zero-keyword-overlap paraphrase, a valid uncovered question, five repeated answers, verbatim citations, completion metadata, token-cap headroom, and the configured total timeout. With `RUN_LIVE_MODEL_TESTS=1`, missing Ollama services or models fail the suite instead of skipping it. Raw model text appears only in a failed live-test assertion and is never logged by the application.

Whisper accuracy requires testing with your own fictional multilingual recordings after its weights are present. Browser permissions and microphone hardware cannot be established by mocked STT tests.

### Validation in the cloud workspace

All 35 backend tests passed with live-model checks enabled; the frontend production build, dependency checks, and real Chromium UI checks also passed. Browser checks exercised unlock, individual review, explicit save, PDF download, upload review, missing embedding-model errors, source refusal, locking and wrong-password handling, with no external browser requests or CSP violations. Actual MediaRecorder WebM audio also passed through the restricted local decoder and Whisper transcription. Optional OCR was exercised with an in-memory sample image.

Real local Qwen structuring and nomic-backed cited Q&A passed the opt-in integration checks. Multilingual Whisper small was downloaded, SHA-256 verified, and exercised on public English reference audio with the external-socket guard active. Real Tesseract OCR also passed on an in-memory synthetic image. Runtime ONNX telemetry is explicitly disabled; PyAV 14.2 and ONNX Runtime 1.22 are pinned for the tested speech pipeline.

Initial model downloads were denied by the cloud egress policy. After adding the required setup-only domains, all weights were obtained successfully. Environment settings retain these preparation domains, `WHISPER_MODEL_PATH`, and complete install/startup instructions. Saving configuration does not prove publication; the app itself never uses those remote domains. Generic Taglish accuracy still needs testing with representative fictional recordings; language auto-detection is enabled.

## Two-minute demo

Do setup and model downloads in advance. Use a fresh vault and fictional data only.

- **0:00–0:15:** Unlock. Expand **Offline proof**: loopback binding, model names, no external application HTTP routes, local document/chunk count.
- **0:15–0:35:** Toggle **Demo mode**. It loads a prewritten fictional presentation and indexes the three SAMPLE ONLY checklists plus notes. This explicitly labeled preset is not live AI output. If needed, use **Load sample library** in My library to retry indexing.
- **0:35–0:55:** Click **Structure from text** for real local generation. Optionally dictate one sentence; typed/demo input works if the microphone fails.
- **0:55–1:15:** Edit HR to `400` to show the deterministic warning, then restore it to `88`. Review each amber field. Show the identifier warning by typing `Patient name: Jane Doe` in HPI, then remove the flagged name. Nothing has been saved yet.
- **1:15–1:35:** Run **Check completeness**, open a citation, and show its highlighted exact source. Confirm and save; export the one-page draft PDF.
- **1:35–1:50:** Ask “What does SOAP stand for?” Open the citation. Ask an unrelated question, e.g. “What is the insulin regimen?” to show **Not covered by your library**.
- **1:50–2:00:** Turn on **airplane mode** (disconnect Wi-Fi/Ethernet too if your OS leaves either enabled). Re-run the SOAP question and inspect Offline proof. The local UI, vault and already loaded models still work. Lock the vault to finish.

Do not use Chromium's network-emulation “offline” mode as a substitute: it blocks loopback requests too, unlike disabling external adapters. The offline proof panel reports the app's enforced routes and counters; it is not an OS packet capture and cannot audit unrelated processes. Configure Ollama locally, disable its debug logs/history, and preload all weights before demonstrating isolation.

## Security and safety design

- Runtime Python sockets allow loopback only via an audit guard; native audio decoding permits only in-memory formats and pipe/data protocols (no HTTP/TCP or referenced local files); HTTP clients disable proxy inheritance and redirects. The app uses only local Ollama endpoints and never calls pull/download APIs.
- The fixed frontend origin, loopback peer/Host checks, in-memory bearer sessions, and strict CSP restrict browser access. There are no CDN assets, analytics, remote fonts, service workers, or automatic update checks. Icons and fonts are bundled.
- LLM and uploaded text are untrusted. SOAP validation uses strict Pydantic types, explicit numeric evidence and verbatim-source checks. Unambiguous labeled numeric values are recovered deterministically even if the model omitted them; competing values stay empty. Assessment/plan require explicit source labels; unsupported content is removed with a warning. This conservatively favors empty fields over guesses. It does not prove semantic fidelity; review remains mandatory.
- Physiologic ranges: HR 20–250; SpO2 50–100%; temperature 30–43 °C; RR 4–60; BP systolic 50–300 / diastolic 20–200, with systolic above diastolic. Dose and recognized lab numbers always require confirmation; the tool never determines an appropriate dose or interprets a lab.
- AES-256-GCM uses a 32-byte key, fresh 16-byte payload salt and fresh 12-byte IV. PBKDF2-HMAC-SHA256 runs 600,000 rounds to derive the vault key from the password and vault salt, and another 600,000 rounds per payload to derive independent keys from the vault key. Bucket/id are authenticated associated data. This **two-stage password-derived scheme** enables random salts per record/chunk while keeping only the derived vault key in session memory, rather than retaining the password.
- The verifier is a small known encrypted blob. All sensitive list metadata is inside encrypted payloads. SQLite exposes only opaque UUIDs, bucket types, ciphertext lengths and counts. The master bytearray is overwritten and the index cleared at lock; Python cannot guarantee forensic erasure of every immutable temporary or OS swap page.
- Access/error logs are disabled in the supported launcher; validation errors omit input values. The app never logs encounter text, passwords, transcripts or uploaded content. Do not add debug/request-body logging.

## Known limitations

- Optional quiz mode is omitted. OCR and dictation are included; OCR and multilingual speech recognition can still misread content.
- All default model weights are prepared in this cloud workspace. New devices must download or copy them before going offline.
- Conservative verbatim extraction may leave explicitly stated facts blank when phrasing/units are ambiguous, and cannot prove the model understood negation perfectly. Always review.
- No unit conversion; age is years and temperature is Celsius. No clinical dose checking or diagnosis. Lab recognition is limited to common labeled values.
- Identifier regexes can miss names, addresses, unusual dates, and other identifying details. A clean scan is not proof of anonymization.
- Citation fidelity is deterministic; relevance still needs human judgment. Embedding retrieval can rank a semantically unrelated chunk among the top results, so the answer model still has to return a valid `not_covered` result when evidence is absent. Completeness recognizes explicit checklist lines and simple field/term coverage, so false positives/negatives are possible.
- A single local vault/session is supported. Unlocking invalidates an earlier session. No multi-user management, password change/recovery, synchronization, backup UI, or official-record integrations.
- Locking discards unsaved drafts. Memory clearing is best effort; full-disk encryption and OS swap policy are outside the app's control.
- Exported PDFs are **unencrypted**. One-page export reduces font size to a minimum of 8pt; oversized drafts or unsupported glyphs fail clearly instead of truncating content.
- DOCX sections approximate locations; chunk token counts are estimates. Parsing is bounded, not a full sandbox for hostile documents. Local source parsing should use trusted files.
- The offline panel cannot prove how separately launched Ollama or other OS programs are configured. Its loopback model calls and guarded backend are verifiable; external adapter/firewall isolation provides stronger device-level evidence.
