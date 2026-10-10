# TIBOQ

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

Windows PowerShell, from the repository root:

```powershell
py -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install -r .\backend\requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
```

Run the backend and frontend in separate terminals. The supplied cloud setup is Linux amd64.

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

On Windows PowerShell, Terminal 1 can use the portable launcher, which resolves the virtual environment and local Whisper model relative to the repository:

```powershell
.\start_backend.ps1
```

If local script execution is restricted, run it for this process only:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_backend.ps1
```

In Terminal 2:

```powershell
$env:NPM_CONFIG_UPDATE_NOTIFIER = 'false'
npm run preview --prefix frontend
```

Open **`http://127.0.0.1:5173`** in a current browser. The backend always binds to **127.0.0.1:8000**. Use the exact `127.0.0.1` frontend origin; a `localhost` alias, custom origin, or LAN address is deliberately rejected by CORS/origin checks.

For frontend development use `NPM_CONFIG_UPDATE_NOTIFIER=false npm run dev --prefix frontend` instead of preview. HMR and its injected websocket client are disabled to preserve the strict local-backend-only `connect-src` policy; reload the page after changes. Never run preview and dev on the same port simultaneously. After frontend edits, rebuild before using preview.

On first launch, choose a password or passphrase of at least 12 characters. The app then offers an optional 256-bit recovery key. Store that one-time Base32 key somewhere private and separate from the device; the app stores only an encrypted wrapper and cannot display the key again. If recovery is declined, the app warns that forgotten-password recovery is impossible. Unlocking returns an in-memory session token; the frontend does not persist it to browser storage. Closing or refreshing the frontend requires another unlock.

### Password recovery

1. At initial setup, choose **Create recovery key**, then copy or print the one-time key and confirm that it was stored safely. Choosing **Continue without recovery** is allowed but leaves no forgotten-password path.
2. If the password is forgotten, select **Forgot password? Use recovery key** on the lock screen. Enter the recovery key and a new password of at least 12 characters.
3. Recovery immediately invalidates the old password and old recovery key. Generate and store the offered replacement key to retain a recovery path.
4. While unlocked, open **Recovery** in the sidebar to create a key after previously declining or to regenerate it. Regeneration requires the current password and invalidates the old key immediately.

Recovery attempts are throttled with an increasing delay stored in the local vault. A checksum catches common recovery-key typing errors before decryption. Passwords and recovery keys are never stored or logged.

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
2. Optionally highlight a term or short phrase (up to 80 characters) inside the **Patient encounter notes** textbox and click **Look up in library**. This performs a deterministic exact-phrase scan of the unlocked local index, favors definition-like sentences, and returns a verbatim cited passage or **Not covered by your library** without calling the answer model.
3. Click **Structure from text**. Missing data remains null / Not stated. The model gets a strict JSON schema and one retry for invalid output. A deterministic source check removes unsupported excerpts, stripped qualifiers, and ungrounded vitals.
4. Review or edit **every** amber field. Numeric warnings need explicit source confirmation. These are plausibility checks, not prescribing/lab interpretation.
5. Remove identifier warnings (recommended), or explicitly choose **Keep**. The heuristic scan is a warning aid, not an anonymization guarantee.
6. Optionally **Check completeness** against your indexed notes and guidelines.
7. Click **Confirm and save**. Export PDF only after saving; edits create a new saved draft. Clear discards the unsaved workspace. PDF export always uses the selected saved version.
8. **Lock vault** discards the unsaved UI and clears the session key/index. Inactivity also locks. Only encrypted saved drafts survive.

### Library

Choose up to ten PDF/DOCX/TXT/MD/image files, set **My notes / Guideline / Textbook**, and optionally enable best-effort local OCR. For every identifier warning, choose **Keep** or **Remove** before **Proceed and index**; removed text is replaced before encryption and indexing. **Keep all** and **Remove all** provide a starting point that you can adjust item by item. You may cancel or exclude individual files; unfinished uploads are not saved. If a batch partly succeeds, completed files remain in the library; exclude those before retrying failed files.

Uploads are bounded to 20 MB/file, 30 MB combined, 32 MB including request framing, 500 pages per PDF, 2,000 chunks per document, and 2,000,000 extracted characters; multipart content stays in memory. OCR uses Tesseract through stdin/stdout, avoiding plaintext image temporary files. Originals are not retained. Parsed text, filenames, tags, timestamps, and vectors are encrypted in SQLite. The index is reconstructed in memory at unlock, then cleared at lock.

PDF citations use real page numbers, including pages skipped for having no text. DOCX uses heading-based **sections**, since reliable page layout is unavailable without a document renderer. TXT/MD form-feed characters delimit pages; otherwise the location is page 1. Chunks are approximately 400 tokens using a character estimate with 50-token overlap, never crossing source pages/sections.

Ask embeds every chunk in the selected source types, ranks them by cosine similarity, and uses keyword overlap only as a small optional boost. Nomic embeddings use matching `search_document:` and `search_query:` prefixes; run **Reindex** once after upgrading an existing vault to this version. The top retrieved chunk IDs and similarity scores are returned in an internal `_debug` field for local diagnostics and are not displayed in the normal UI.

The answer model receives only the retrieved chunks, labeled with short source IDs, and must return strict schema-bound JSON. It is prompted to keep answers to three short sentences. The backend matches the answer's factual terms against the retrieved text, rejects answers without source support, selects the strongest supporting chunk, and attaches an exact source excerpt itself. This keeps citations verifiable even when a small model omits a source ID or paraphrases instead of copying a quote. Truncated, malformed, timed-out, or unsupported model responses are retried once and then shown as a retryable **local model error**; they are never converted to **Not covered by your library**. That exact response is reserved for an empty scoped library or a valid model `not_covered` result. Click citations to inspect the supporting passage. Completeness emits only “Consider documenting…” prompts from explicit `Document:`, `Record:`, or `Consider documenting:` checklist lines; it never supplies diagnoses.

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

Ordinary tests use controlled local-model responses to exercise failure handling and grounding. They test numeric boundaries, identifier regexes, password and recovery failure, recovery checksums and throttling, DEK-wrapper tampering, legacy-vault migration and rollback, per-payload salts and authenticated metadata, encrypted chunks/records, index rebuild at unlock, page-preserving parsing/chunking, embedding-first retrieval, malformed/truncated output, citation validation, explicit-save gates, PDF text/pages, blocked external sockets, local-only STT configuration, and missing-model errors. Real-model tests are opt-in; skipping them does **not** verify inference.

After Ollama is running and both models are pulled:

```bash
RUN_LIVE_MODEL_TESTS=1 python -m pytest -m live -q
```

The live RAG suite builds four synthetic documents through the real embedding/indexing pipeline. It checks a zero-keyword-overlap paraphrase, a valid uncovered question, five repeated answers, verbatim citations, completion metadata, token-cap headroom, and the configured total timeout. With `RUN_LIVE_MODEL_TESTS=1`, missing Ollama services or models fail the suite instead of skipping it. Raw model text appears only in a failed live-test assertion and is never logged by the application.

Whisper accuracy requires testing with your own fictional multilingual recordings after its weights are present. Browser permissions and microphone hardware cannot be established by mocked STT tests.

### Validation in the cloud workspace

The ordinary backend suite and frontend production build are the required local checks. Opt-in live-model and browser checks require the separately prepared local models and browser permissions; a skipped live test does not verify inference, audio hardware, or OCR installation.

Real local Qwen structuring and nomic-backed cited Q&A passed the opt-in integration checks. Multilingual Whisper small was downloaded, SHA-256 verified, and exercised on public English reference audio with the external-socket guard active. Real Tesseract OCR also passed on an in-memory synthetic image. Runtime ONNX telemetry is explicitly disabled; PyAV 14.2 and ONNX Runtime 1.22 are pinned for the tested speech pipeline.

Initial model downloads were denied by the cloud egress policy. After adding the required setup-only domains, all weights were obtained successfully. Environment settings retain these preparation domains, `WHISPER_MODEL_PATH`, and complete install/startup instructions. Saving configuration does not prove publication; the app itself never uses those remote domains. Generic Taglish accuracy still needs testing with representative fictional recordings; language auto-detection is enabled.

## Security and safety design

- Runtime Python sockets allow loopback only via an audit guard; native audio decoding permits only in-memory formats and pipe/data protocols (no HTTP/TCP or referenced local files); HTTP clients disable proxy inheritance and redirects. The app uses only local Ollama endpoints and never calls pull/download APIs.
- The fixed frontend origin, loopback peer/Host checks, in-memory bearer sessions, and strict CSP restrict browser access. There are no CDN assets, analytics, remote fonts, service workers, or automatic update checks. Icons and fonts are bundled.
- LLM and uploaded text are untrusted. SOAP validation uses strict Pydantic types, explicit numeric evidence and verbatim-source checks. Unambiguous labeled numeric values are recovered deterministically even if the model omitted them; competing values stay empty. Assessment/plan require explicit source labels; unsupported content is removed with a warning. This conservatively favors empty fields over guesses. It does not prove semantic fidelity; review remains mandatory.
- Physiologic ranges: HR 20–250; SpO2 50–100%; temperature 30–43 °C; RR 4–60; BP systolic 50–300 / diastolic 20–200, with systolic above diastolic. Dose and recognized lab numbers always require confirmation; the tool never determines an appropriate dose or interprets a lab.
- Vault content is encrypted with a random 256-bit data-encryption key (DEK). PBKDF2-HMAC-SHA256 runs 600,000 rounds with a per-vault salt at the password boundary; HKDF-SHA256 with the `kubli-kek-password-v1` purpose label derives a key-encryption key that wraps the DEK with AES-256-GCM. The password and its derived material are not stored.
- The optional recovery key contains 256 random bits plus a checksum and is displayed as grouped Base32. HKDF-SHA256 with the distinct `kubli-kek-recovery-v1` label derives a second key-encryption key that wraps the same DEK. Only that wrapper is stored. Password recovery and recovery-key regeneration re-wrap the DEK, so vault content does not need bulk re-encryption.
- Each content payload keeps the existing scheme: a fresh 16-byte salt and 12-byte IV, HKDF-SHA256 from the DEK with purpose-bound associated data, then AES-256-GCM. Bucket and opaque item ID are authenticated associated data. SQLite exposes settings needed for key derivation plus opaque UUIDs, bucket types, ciphertext lengths and counts; filenames, records, source text, and embeddings stay inside encrypted payloads.
- On the first successful unlock of an older direct-password-key vault, TIBOQ authenticates and decrypts the old format, creates and integrity-checks `vault.sqlite3.pre-envelope-v1.bak`, then migrates all content and key settings in one SQLite transaction. A failure rolls the transaction back. WN01 content payloads remain readable and are upgraded to WN02 after authentication.
- The in-session DEK uses a mutable bytearray and is overwritten on lock on a best-effort basis; the in-memory index is also cleared. Python cannot guarantee forensic erasure of every immutable temporary, clipboard copy, print spool, or OS swap page.
- Access/error logs are disabled in the supported launcher; validation errors omit input values. The app never logs encounter text, passwords, transcripts or uploaded content. Do not add debug/request-body logging.

## Known limitations

- Optional quiz mode is omitted. OCR and dictation are included; OCR and multilingual speech recognition can still misread content.
- All default model weights are prepared in this cloud workspace. New devices must download or copy them before going offline.
- Conservative verbatim extraction may leave explicitly stated facts blank when phrasing/units are ambiguous, and cannot prove the model understood negation perfectly. Always review.
- No unit conversion; age is years and temperature is Celsius. No clinical dose checking or diagnosis. Lab recognition is limited to common labeled values.
- Identifier regexes can miss names, addresses, unusual dates, and other identifying details. A clean scan is not proof of anonymization.
- Citation fidelity is deterministic; relevance still needs human judgment. Embedding retrieval can rank a semantically unrelated chunk among the top results, so the answer model still has to return a valid `not_covered` result when evidence is absent. Completeness recognizes explicit checklist lines and simple field/term coverage, so false positives/negatives are possible.
- A single local vault/session is supported. Unlocking invalidates an earlier session. Recovery can replace a forgotten password, but ordinary password change, multi-user management, synchronization, backup UI, and official-record integrations are not implemented.
- Device binding is not implemented. Anyone who obtains a copy of the encrypted vault and knows the password or recovery key can attempt to unlock that copy. Recovery protects against a forgotten password; it does not protect a compromised logged-in device, clipboard, printout, keylogger, or malware.
- Losing both the password and recovery key makes the encrypted data unrecoverable. A declined or discarded replacement key leaves no recovery path. The automatic pre-migration database copy is a migration rollback aid, not a user backup system.
- The pre-migration backup remains encrypted under the password that was valid before migration. After confirming the migrated vault works and arranging your own trusted backup, remove that rollback copy if retaining an old-password-encrypted snapshot is not acceptable.
- Locking discards unsaved drafts. Memory clearing is best effort; full-disk encryption and OS swap policy are outside the app's control.
- Exported PDFs are **unencrypted**. One-page export reduces font size to a minimum of 8pt; oversized drafts or unsupported glyphs fail clearly instead of truncating content.
- DOCX sections approximate locations; chunk token counts are estimates. Parsing is bounded, not a full sandbox for hostile documents. Local source parsing should use trusted files.
- The offline panel cannot prove how separately launched Ollama or other OS programs are configured. Its loopback model calls and guarded backend are verifiable; external adapter/firewall isolation provides stronger device-level evidence.
