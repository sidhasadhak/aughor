# The knowledge base — KB-0 … KB-4 (2026-08-24)

> **Status: SHIPPED.** [#391](https://github.com/sidhasadhak/aughor/pull/391) (`1ea8ef1`) and
> [#392](https://github.com/sidhasadhak/aughor/pull/392) (`1354306`).
> Prompted by a user observation while comparing against VoltAgent: *"RAG knowledge base is
> either missing or hidden."*
>
> It was neither. It was **built, running, and telling people the wrong thing.**

---

## 0 · What was actually true, measured before anything was built

| claim | measurement |
|---|---|
| Chat could reach documents | **No.** 16 tools on the converse roster, not one reached the document store. `search_graph` is the knowledge GRAPH — entities and relationships — not documents |
| Deep analysis could | **Yes, all along.** `build_external_context_section` injects passages into investigations, scoped per agent, fail-closed |
| The corpus size | Registry claimed **92** chunks; the store held **79**; **41** of those belonged to documents nothing lists; one document claimed 59 and held 5. **Searchable AND controllable: 38** |
| Where embeddings come from | A **local Ollama** (`localhost:11434`, `nomic-embed-text`). Not present on Vercel — so the knowledge base was a laptop feature |
| Uploaded documents | **11, all auto-generated schema doctrees. Zero user uploads.** `/documents/upload` existed and had never been used |

The recurring shape: **both ends of a feature existed and the middle did not**, or a surface
rendered a *claim* as a *fact*.

---

## 1 · What shipped

### KB-0 — an empty result had four causes and one appearance
`search_documents` ended `except Exception: return []`. *Nothing matched* · *nothing indexed*
· *store unavailable* · *embedder unreachable* were indistinguishable, and they call for
opposite responses. `knowledge_status()` answers which; `why_empty()` is empty when the plane
is healthy, because then an empty result really does mean no match.

`ready` deliberately means *a search can run AND has something to search*: a working embedder
over an empty corpus is healthy and useless.

**The drift check** compares registry against store and reports both directions. Orphans are
the worse half — returned by search, while `delete_document` works off the registry and
per-agent scoping filters `doc_id in allowed`, which a document nobody can list can never be.
**Searchable, undeletable, unbindable.**

Reported, never repaired. A test asserts that **by AST, not substring** — this module's own
docstrings name `delete_document` while explaining that it does not call it.

### KB-1 / KB-2 — chunking as data, visible before you commit
Three module constants and one magic number: a floor of **50 characters**, inside a list
comprehension, below which a chunk was **discarded**. A document of short paragraphs lost
content silently and still reported a count for what survived.

Every default reproduces the old behaviour exactly, and a test holds it — the corpus was
indexed under those constants.

`POST /documents/preview` chunks **without embedding**: no vector, no registry entry, no
doc_id. Safe to call repeatedly, and it works **while the embedder is down**.

### KB-3 — the panel stops rendering a claim as a fact
`DocumentUploader` existed and was mounted in ConfigurePanel and CatalogScreen. It showed
`chunk_count` from the registry, so it reported **59 chunks** for a document holding 5. Now
`"5 chunks indexed of 59 claimed"`, store first, plus a banner naming the cause when the
plane is not ready — and saying the embedder is **local**, which is what explains a deployed
instance behaving differently from a laptop.

Banners appear only when something is wrong.

### KB-4 — embeddings join the provider ladder
`AUGHOR_EMBED_BACKEND`, **default `ollama`**. Hosted backends resolve through
`provider.endpoint_for()` — the ladder's own precedence and secretvault decryption — so a key
set once in Settings serves chat and embeddings.

**No hosted backend ships a model id.** A rot-guard enforces it, including in prose.

🔑 **The width guard is the load-bearing part.** `ensure_collection` silently no-ops on an
existing collection *whatever its width*, so a changed model would fail at upsert with a
driver error and at **search** with an empty list. Indexing refuses first. The dimension is
**probed, never declared**.

### The re-index path
🔑 **For an UPLOAD the source of truth is the STORE.** `index_file` unlinks the upload, so a
chunk's only surviving copy is its `text` payload. It recovers what the store holds and
**nothing more**.

🔑 **For a SCHEMA DOC it is not — and this was stated wrongly here first.** The ontology
compiles schema docs to a doc tree on disk before anything is embedded, so the artifact,
not the collection, is their source. Measured after the repair below: a store holding 5
chunks for a document whose artifact held **59 table docs, every one embeddable**. Counting
those 54 as unrecoverable was a claim about uploads applied to something that is not one,
and it read as *gone forever* while the source sat in `data/ontology_docs`.
`POST /documents/restore-doctrees` puts them back; `plan()` now reports the two separately.

⚠️ The restore is scoped to connections that **still exist**. An artifact outlives its
connection — a fixture connection's tree was on disk here after its documents were purged —
and a restore that ignored the registry would resurrect exactly what the purge removed.
Those trees are reported under `skipped` with the reason, never dropped quietly.

**Nothing is destroyed before its replacement exists**: read → embed everything → only then
drop, recreate, write. `dry_run` defaults true; orphans survive unless asked for; a truncated
scan refuses outright.

---

## 2 · Gemini Embedding 2, measured

`models/gemini-embedding-2` **works** through Google's OpenAI-compatible endpoint and returns
**3072 dimensions** against a stored 768. Adopting it costs a full collection rebuild — which
the corpus needs anyway.

⚠️ `AUGHOR_EMBED_BACKEND` is read **inside the API process**. Setting it on a `curl` does
nothing; restart uvicorn with it set.

Finding this exposed a defect worth its own line: **an undecryptable key was being sent to
providers as if it were one.** `decrypt_secret` returns undecryptable values as-is —
deliberate, so one bad record cannot take down a read path — and `enc:v1:…` reached Google,
which replied *"Please pass a valid API key"*. The key was fine; `AUGHOR_SECRET_KEY` was
absent. That message sends a person to rotate a working key.

---

## 3 · Open

| | |
|---|---|
| ~~**The corpus is not repaired**~~ | ✅ **Done 2026-08-24.** Rebuilt onto a 3072-dimension hosted embedder: 38 chunks re-embedded, 41 orphans purged, the 59-claiming document corrected to 5, in 3.4 s. `ready: true`, zero orphans, and a real search returns the right column at 0.76 |
| **`consistency.ok` means consistent, not complete** | After the repair the plane reports perfect health while holding **5 of 59 tables** for the main workspace connection — it will answer from 8% of that schema and flag nothing. `restore-doctrees` closes the gap; nothing yet *notices* it |
| **`keys_set` has no third state** | `current_config()["keys_set"]` reports `true` for an undecryptable key. Both answers are lies; needs a third state and a UI change |
| **No curation surface beyond the panel** | No chunk settings in the UI, no preview, no embedding choice — the API has all three |
| **Where a Knowledge page belongs in nav** | Documents are reachable only via Configure and Catalog. A product call, not made |
| **Ingestion in practice** | `/documents/upload` still has zero real uses. Every indexed document is generated |
