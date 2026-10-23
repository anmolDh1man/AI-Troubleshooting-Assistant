# Interview Preparation

Each topic has a **Hinglish explanation** (to understand it) and a short **English answer** (to say it).
Code references are included so you can open the file if asked "show me where".

---

## 60-second pitch (English)

> "I built an AI troubleshooting assistant for L1/L2 support. An engineer types a problem in plain English, for example 'payment API returning 500s'. A local embedding model converts it into a vector, and ChromaDB finds the most similar knowledge-base entry. I embed each symptom separately, because my measurements showed that makes relevant and irrelevant queries clearly separable.
>
> A decision layer then uses calibrated thresholds:
> - a confident match gives numbered checks, safe next steps, actions that need approval, and the escalation team, always with the source entry shown;
> - a weak match gets a warning;
> - no match gets a clear 'not in the knowledge base' and clarifying questions.
>
> On a held-out evaluation it gave zero confident answers to out-of-scope questions. Answers are currently template-based from the KB, with no LLM, and labelled that way. The generator is pluggable, so an LLM can be added later."

---

## Part A: Core concepts

### A1. What is an embedding?
**Hinglish:** Embedding ek text ko numbers ki list (vector) mein badalta hai. Hamare model mein yeh 384 numbers hain. Model ko lakhon sentences pe train kiya gaya hai, isliye jinka *matlab* similar hai unke vectors bhi paas-paas hote hain, chahe words alag hon. Jaise "checkout throws internal server error" aur "payment API 500" ke vectors close hain.

**English:** "An embedding is a fixed-length vector (384 numbers for MiniLM) that represents the meaning of a text. Texts with similar meaning get vectors that point in similar directions, even with different words."

### A2. What is cosine similarity? What does a score of 0.45 mean?
**Hinglish:** Do vectors ke beech ka angle measure karta hai. 1 ka matlab bilkul same direction (same meaning), 0 ka matlab unrelated. Hum vectors normalize karte hain, toh cosine similarity seedha dot product ban jaata hai. **0.45 probability nahi hai.** "45% sure" bolna galat hoga. Yeh sirf ek similarity score hai, aur iska useful cut-off data se nikalna padta hai, isliye calibration kiya.

**English:** "Cosine similarity measures the angle between two vectors: 1 is the same direction, around 0 is unrelated. It isn't a probability. 0.45 doesn't mean 45% confidence, so I chose the cut-offs from measured score distributions."

### A3. What is RAG? Is your project RAG if there's no LLM?
**Hinglish:** RAG = Retrieval-Augmented Generation. Pehle relevant documents *retrieve* karo, phir LLM unhi documents ke basis pe answer *generate* kare, taaki LLM apni memory se kuch na banaye. Mera project **retrieval wala hissa poora** karta hai. Generation abhi template se hota hai, LLM se nahi. Isko honestly bolna: "retrieval-grounded assistant with a pluggable generator". Interviewer ko over-claim pasand nahi aata.

**English:** "RAG means retrieving relevant documents first and having the LLM answer only from them. My project implements the retrieval and grounding part fully. Generation is currently a transparent template rather than an LLM, because I had no paid API. The generator is an interface, so adding an LLM completes the RAG loop without touching retrieval."

### A4. What is a vector database? Why ChromaDB for only 12 entries?
**Hinglish:** Vector DB vectors store karta hai aur "sabse similar vectors do" query fast chalata hai, approximate nearest neighbour search ke saath (Chroma HNSW use karta hai). Sach bolo: 12 entries ke liye NumPy bhi kaafi tha. Chroma isliye liya kyunki (1) persistence free mein milti hai, (2) KB badhega toh code same rahega, (3) vector DB ka real use dikhta hai. Isliye maine retriever ko ek class ke peeche rakha, taaki swap easy ho.

**English:** "For 12 entries plain NumPy would work. I chose ChromaDB because it gives persistence and approximate nearest-neighbour search, and the same code scales to thousands of entries. It's isolated behind the Retriever class, so it's easy to swap."

### A5. Why embed each symptom separately (chunking)?
**Hinglish:** Ye mera best story hai. Pehle poori entry ek lamba text bana ke embed ki. Calibration mein "Kafka consumer lag" (jo KB mein hai hi nahi) ka score 0.386 aaya, aur ek sahi match "settlement file not generated" ka sirf 0.384. Matlab koi threshold dono ko alag nahi kar sakta tha. Reason: lambe text ka vector sab cheezon ka "average" ban jaata hai, toh ek chhoti query ka match weak hota hai. Fix: har symptom alag vector, aur entry ka score = uske best symptom ka score (max). Result: correct ka lowest 0.483, out-of-KB ka highest 0.415, ab separable.
**Trade-off (khud batao):** jis entry ke zyada symptoms hain, usko match hone ke zyada mauke milte hain. Halki si bias hai, par 12 balanced entries mein problem nahi dikhi.

**English:** "My first version embedded each entry as one text, and calibration showed an out-of-scope query outscoring a correct one, so no threshold could work. Long texts dilute the embedding. I switched to one vector per symptom and scored each entry by its best-matching chunk. On the same queries, correct matches went from a minimum of 0.384 to 0.483 while the worst out-of-scope score was 0.415, so they became separable. The trade-off is that entries with more symptoms get more chances to match."

### A6. Why not embed the resolution steps too?
**Hinglish:** User symptoms batata hai ("500 aa raha hai"), solution nahi. Resolution mein "escalate", "rollback", "check logs" jaise words almost har entry mein hain. Unko embed karte toh sab entries ek jaisi lagti aur ranking bigad jaati.

**English:** "Users describe symptoms, not fixes. Resolution text is similar across entries ('check logs', 'escalate'), so embedding it would make entries look alike and hurt ranking."

### A7. How did you choose the thresholds? Isn't that overfitting?
**Hinglish:** Calibration set (33 labelled queries) pe scores dekhe: sahi matches ka lowest 0.483, out-of-KB ka highest 0.415. Ek hard cut-off fragile hota, toh teen zones banaye: ≥0.45 confident, 0.30–0.45 "possible match", <0.30 not found. Overfitting se bachne ke liye **alag held-out set** (33 naye queries, expected behaviour pehle likha) pe evaluate kiya. Wahan bhi out-of-KB pe zero confident answers aaye. Phir bhi set chhota hai; KB badhe toh dobara calibrate karna padega.

**English:** "I measured score distributions on a 33-query calibration set and used two thresholds instead of one fragile cut-off. To check for overfitting I evaluated on a separate held-out set written beforehand, and got zero confident answers to out-of-scope queries. The sets are small, so thresholds should be re-calibrated as the KB grows."

### A8. Why all-MiniLM-L6-v2?
**Hinglish:** Free, local, CPU pe fast, chhota (~90 MB), 384 dimensions, aur semantic search ke liye widely used. Trade-off: chhota model hai, toh domain jargon (jaise HikariCP) nahi samajhta. Isi wajah se E04 fail hua tha. Better options: bge-small, e5-small, ya paid embedding APIs.

**English:** "It's free, runs locally on CPU, is small and well established for semantic search. The trade-off is weaker understanding of niche jargon, which the E04 failure showed. Alternatives are bge-small, e5, or hosted embedding APIs."

---

## Part B: Design and implementation questions

### B1. Walk me through what happens when I type a query.
**English:** "In `assistant.ask()`:
1. Clean the text (trim, collapse spaces) and reject empty or over-1,000-character input.
2. Check for risky words like restart or delete, to show a warning.
3. The retriever embeds the query and asks ChromaDB for the nearest chunks, keeping the best chunk per entry, top 3.
4. Decide: below 0.30 is not found; 0.30–0.45 is a possible match; 0.45 or above is answered, flagged as ambiguous if the second entry is within 0.05.
5. The generator builds the answer from the top entry only.
6. The UI shows the steps, the approval box, escalation and the source entry."

Code: `src/assistant.py` → `TroubleshootingAssistant.ask`.

### B2. How do you prevent hallucination?
**Hinglish:** Teen layers:
1. Score bahut kam ho toh answer banta hi nahi.
2. Answer sirf top entry ke text se copy hota hai; template kuch naya likh hi nahi sakta.
3. Evaluation mein automatic check hai ki har step cited entry mein exactly hai, aur cited ID wahi hai jo UI mein dikh rahi hai.

Plus UI pe hamesha source dikhta hai, toh user khud verify kar sakta hai.

**English:** "Three layers: no answer below the low threshold; the answer is built only from the cited entry's text; and the evaluation automatically verifies that every step exists in the cited entry and that the citation matches the displayed source. The source is always shown so the engineer can check it."

### B3. How would you add an LLM? What would the prompt look like?
**Hinglish:** `generator.py` mein ek nayi class (jaise `OllamaGenerator`), `GENERATORS` mein register karo, `.env` mein `GENERATOR=ollama`. Assistant, retriever, UI kuch nahi badlega. LLM fail ho toh template fallback pehle se bana aur tested hai.

Prompt rules:
- System: "You are an L1/L2 support assistant. Use ONLY the knowledge-base entries provided. Cite entry IDs. If the entries do not cover the issue, reply INSUFFICIENT. Never suggest destructive actions as steps; list them under 'requires approval'."
- Context: retrieved entries, each with its ID.
- Output: JSON (`status`, `steps`, `escalation`, `cited_ids`), low temperature.
- Validation in code: JSON parse, `cited_ids ⊆ retrieved_ids`, otherwise fall back to the template.

**English:** "Add one class implementing `AnswerGenerator` and register it; nothing else changes. The prompt would restrict the model to the provided entries, require cited IDs and structured JSON, and allow an explicit 'insufficient' answer. In code I'd validate the JSON and check that cited IDs are a subset of the retrieved IDs, falling back to the template otherwise. That fallback already exists and is tested."

### B4. Why no LangChain?
**English:** "The pipeline is four steps: embed, search, decide, format. Writing them directly keeps every step visible, testable and explainable. LangChain is useful for complex chains, agents or many document loaders, which this prototype doesn't need."

### B5. How are ambiguous queries handled?
**Hinglish:** Agar top-2 dono confident hain aur score difference ≤0.05, toh assistant poochta hai "kaunsa better describe karta hai: A ya B?". **Limitation khud batao:** "payments are failing" jaisi query pe ek entry clear jeet jaati hai, toh ambiguity trigger nahi hoti, jabki insaan follow-up poochta. Iska fix multi-turn clarification ya category-based check hai.

**English:** "If the top two entries are both confident and within 0.05, the assistant asks which description fits better. The limitation: a vague query like 'payments are failing' can still produce one clear winner, so no follow-up is asked. Multi-turn clarification is a planned improvement."

### B6. What happens if ChromaDB or the model fails?
**English:** "Retrieval is wrapped in a try/except. The user gets an `error` status and a clear message, never a crash. This is tested with a fake failing retriever (F02 in the evaluation). If a future LLM generator fails, the template fallback runs and the label says so (F01)."

### B7. Why does "Kafka consumer lag" show latency steps?
**Hinglish:** Kafka entry KB mein nahi hai. Closest entry "High API latency" (0.42) hai, jo middle zone mein aata hai, isliye yellow "possible match only, verify symptoms" dikhta hai. Steps perfectly fit nahi karte. Yeh limitation hai, aur sahi fix KB mein queue-lag entry add karna hai, threshold badalna nahi.

**English:** "It isn't in the KB. The closest entry scores in the middle zone, so it's shown with a 'possible match' warning. The steps don't fully fit, which is why the warning exists. The right fix is a new KB entry, not a threshold change."

### B8. Why Streamlit `cache_resource` and `session_state`?
**Hinglish:** Streamlit har click pe poori script dobara chalata hai. `cache_resource` ke bina har message pe model reload hota (slow). `session_state` ke bina chat history har rerun pe gayab ho jaati.

**English:** "Streamlit re-runs the script on every interaction. `cache_resource` loads the model and index once per server, and `session_state` keeps the chat history between re-runs."

---

## Part C: Testing and results

### C1. How did you test it?
**English:** "Three levels:
- 33 automated tests: loader validation, retrieval, decision logic with a fake retriever, and headless UI tests with Streamlit's AppTest.
- A calibration run on 33 labelled queries to choose thresholds.
- A held-out evaluation on 33 new cases: known issues, paraphrases, ambiguous, vague, unsupported, prompt injection, risky actions, invalid input and simulated failures. Each case is checked automatically for status, source, grounding, attribution and warnings."

### C2. Tell me about a failure you found.
**Hinglish:** E04: "HikariCP says connection is not available, request timed out". Expected DB-pool entry (KB-003), mila timeout entry (KB-002), kyunki "timed out" phrase haavi pada aur model HikariCP nahi jaanta. Fix: KB-003 ke keywords mein "hikaricp" aur "connection is not available" add kiye. Threshold nahi chheda. Regression test add kiya (ek real Hikari log line ke saath jo kisi eval set mein nahi thi), aur ek guard test ki normal timeouts abhi bhi KB-002 pe jaayein. Re-run mein sirf E04 badla. **Imaandari:** fix result dekhne ke baad kiya, isliye clean number 31/33 hai, 32/33 nahi.

**English:** "E04, a HikariCP pool-timeout message, retrieved the generic timeout entry because the model doesn't know HikariCP. I added the jargon to the database entry's keywords without touching thresholds, and added regression tests, including a real HikariCP log line from outside the evaluation sets, plus a guard so generic timeouts still map correctly. Only that case changed on re-run. Since I fixed it after seeing it, I report 31/33 as the clean held-out result."

### C3. Your test sets are small and self-written. How confident are you?
**English:** "They show the design behaves as intended. They aren't production accuracy figures. In production I'd measure on real tickets: the rate of 'helpful' votes, the rate of unanswered queries (which shows KB gaps), retrieval hit rate against the ticket's final resolution, and time-to-resolution compared with a baseline."

### C4. Tell me about a debugging problem.
**Hinglish:** Streamlit start pe ImportError aaya. Maine (AI tool ke saath) code check kiya, constants sahi the, toh blindly change nahi kiya. Windows Code Integrity event log dekha: **Smart App Control** `streamlit.exe` aur pandas ki compiled DLLs block kar raha tha, aur cloud reputation ki wajah se kabhi chalta, kabhi nahi. Fix: `python -m streamlit` (signed python.exe) se chalaya aur pandas wala `st.table` hata diya. Security feature off nahi kiya.

**English:** "The startup error looked like a code problem, but the imports were correct. The Windows Code Integrity log showed Smart App Control blocking the unsigned streamlit.exe launcher and some pandas DLLs, intermittently because it's reputation-based. I fixed it without disabling the security feature: I launch through the signed python.exe and removed the only pandas-dependent UI call."

---

## Part D: Operations and JD-related questions

### D1. How does this help L1/L2 teams?
**English:** "It speeds up triage: the engineer gets the relevant runbook entry, ordered checks and the right escalation team in seconds, which reduces wrong escalations and time spent searching. It also makes knowledge consistent across shifts. It doesn't replace judgement: it suggests, and the engineer decides."

### D2. Why can't the assistant restart services automatically (self-healing)?
**Hinglish:** Assignment aur production safety dono ke hisaab se assistant sirf suggest karta hai. Payment systems mein galat restart ya rollback se outage ya duplicate transactions ho sakte hain. Self-healing ke liye approvals, audit trail, tested runbooks aur rollback plan chahiye. Woh future scope hai, aur hamesha human approval ke saath.

**English:** "On payment systems a wrong restart or rollback can cause outages or duplicate transactions, so changes need approval and an audit trail. The assistant suggests checks and escalation only. Automated remediation would be a later, approval-gated step."

### D3. How would you scale to 10,000 KB entries?
**English:** "Embed in batches and keep ChromaDB's HNSW index for fast approximate search. Add metadata filters (service, category), add a re-ranker or hybrid keyword search for precision, re-calibrate thresholds on a larger labelled set, and add a review workflow so KB quality doesn't degrade."

### D4. Security considerations?
**English:** "No secrets in code; `.env` is git-ignored. The app binds to localhost. The assistant can't execute anything. There's no LLM, so no prompt-injection path; the injection test returns 'not found'. KB guidance forbids pasting card numbers. For production I'd add authentication, audit logging and data masking."

### D5. What did you do vs the AI tool?
**Hinglish:** Sach bolo, confidently. Requirements, constraints aur design decisions tumhare the: no paid API, no fake LLM output, ChromaDB sirf reliable ho toh, MVP-first, E04 fix ke rules, SAC issue ko blindly patch na karna. Setup, running, verification aur commits tumne kiye. Code, KB content aur docs drafts Claude Code ne likhe, aur tumne har phase ko run karke verify kiya. Har line samjhna zaroori hai. Is document ke Part A–C usi ke liye hain.

**English:** "I defined the requirements and constraints, made the key design decisions, set up and ran the environment, and verified every phase before committing. I used Claude Code as a pair programmer to write the code, the sample KB and documentation drafts. Everything is explained in CONTRIBUTION.md, and I can walk through any part of the code."

---

## Last-minute checklist
- [ ] Open each file in `src/` once and explain it out loud in two sentences.
- [ ] Be ready to show `search_chunks()` in `kb_loader.py` and the decision block in `assistant.ask()`.
- [ ] Remember the numbers: **12 entries · 384-dim vectors · thresholds 0.45 / 0.30 · 33 tests · 31/33 → 32/33 · 0 confident out-of-KB answers.**
- [ ] Practise the demo twice with a timer.
