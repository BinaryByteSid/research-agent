# Research Agent

A small research agent built with production concerns in mind. You give it a research-style question. It plans, uses tools to gather and filter sources, and returns a structured, cited answer with a confidence level, limitations and suggested next steps.

It is a single-agent planner/executor loop, not a big framework. I wanted something I could fully explain and test.

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
copy .env.example .env              # Mac/Linux: cp .env.example .env, then fill in your keys
python -m research_agent "Compare the top 3 open-source vector databases for a startup building RAG products" --save samples/demo
```

Run the tests and the evaluation:

```powershell
pytest -q
python eval/run_eval.py                       # all 8 queries plus the baseline
python eval/run_eval.py --only q7_injection --no-baseline
```

### Configuration (`.env`)

```
OPENAI_API_KEY=<key for any OpenAI-compatible provider>
LLM_BASE_URL=<provider base URL; leave empty for OpenAI>
LLM_JSON_MODE=1                 # set to 0 if the provider rejects response_format
PLANNER_MODEL=<cheap, fast model>
SYNTH_MODEL=<stronger model>
TAVILY_API_KEY=<search key>
```

I developed against Gemini through its OpenAI-compatible endpoint (a flash-lite model for planning and reflection, a flash model for synthesis), on free tiers. Any OpenAI-compatible provider should work. DuckDuckGo is the automatic search fallback and needs no key.

CLI options: `--json` prints JSON instead of markdown, `--save PATH` writes `PATH.json` and `PATH.md`, and `-v` turns on logging. A configuration problem (bad key, no credits, retired model) exits with code 2 and a one-line message.

## Architecture

```
question
  -> Planner      LLM, structured Plan. Can ask for clarification or refuse.
  -> Executor     up to 2 rounds
       web_search -> page_fetch (top N pages)
       -> filter: dedupe, relevance, source quality, injection scan
       -> Reflection (LLM, can only emit search queries) -> optional follow-up round
  -> Synthesizer  LLM, sees only kept excerpts, every finding must cite source IDs
  -> Validator    plain code: citation check, computed confidence, low-confidence guardrail
  -> FinalAnswer  JSON + markdown, plus one JSONL trace file per run
```

```
src/research_agent/
  schemas.py       all Pydantic contracts (Plan, Evidence, FinalAnswer, ...)
  config.py        every tunable: models, timeouts, limits, thresholds, domain lists
  llm.py           LLM wrapper: structured output, retry, one repair re-prompt, token counts
  planner.py       question -> Plan (fallback to one plain search if the LLM fails)
  executor.py      the orchestration loop and reflection
  filtering.py     dedupe, relevance, quality, drop reasons
  safety.py        injection heuristics and untrusted-text wrapping
  synthesizer.py   evidence -> cited draft
  validator.py     citation checks, confidence, guardrail
  pipeline.py      wires everything together; cli.py is the entry point
  tracing.py       JSONL trace per run
  tools/           base.py (retry/timeout/validation), web_search.py, page_fetch.py
eval/              queries.yaml, run_eval.py, baseline.py, scenarios.py, results, EVALUATION.md
samples/           saved example outputs and traces
tests/             unit tests (network and LLM are faked)
```

The planner never sees fetched web text, so a page can't change the plan or the tool choice. The reflection step can only output search queries, and URLs in them are rejected in code.

## README questions

**Why an agentic approach?**
Good research depends on what the earlier searches turn up. The plan can be wrong about which entities matter. For example, the planner named specific databases from its own memory before searching anything. The reflection step lets the agent notice thin or off-target coverage and run a follow-up search. A single LLM call can't do that, and it can't cite sources either. I kept the design to one agent with a hard cap of two rounds, because a bigger multi-agent design would add cost and failure modes without helping this task.

**What tools did you use, and why?**
`web_search` (Tavily, with DuckDuckGo as an automatic fallback) finds candidate sources. `page_fetch` (httpx plus trafilatura) reads the full text, because snippets are too thin to compare products. Two tools were enough, so I didn't add a third for show.

**How does the system handle bad tool results?**
- Timeouts, connection errors, 429 and 5xx are retried with exponential backoff. Bad keys, 404s, blocked URLs, unsupported content types and TLS certificate errors are not, because retrying can't fix them. The evaluation found the TLS case: a certificate mismatch was being retried three times, and I fixed it.
- Tool output is validated with Pydantic. One malformed search hit is dropped without failing the whole search.
- A failed page fetch falls back to the search snippet if it is long enough, otherwise the source is dropped with a reason.
- If search is down, the loop stops instead of retrying pointlessly. The final answer is an explicit low-confidence refusal, and its limitations mention the failed searches.
- Tools never raise into the executor. They return a result object with `ok` or `error`.
- LLM output that breaks the schema gets one repair re-prompt. Transient LLM errors are retried. Configuration errors stop the run loudly, and other API errors degrade gracefully (for example, the planner falls back to a single plain search).

**How do you reduce hallucinations?**
- The synthesizer only sees filtered excerpts, and its prompt forbids outside knowledge.
- The schema requires at least one source ID per finding.
- The validator removes any citation to a source the model wasn't shown, drops findings left with no valid citation, and builds the source list only from what was actually cited.
- Sub-questions with no evidence become limitations instead of being filled from memory.
- Confidence is computed in code, not claimed by the model, and a low-confidence guardrail returns an explicit refusal instead of a guess.
- Known gap: the validator proves that a cited source exists, not that it supports the claim. Checking that needs an LLM judge or an entailment step.

**How do you handle prompt injection?**
Defence in depth. The planner never sees web text. Reflection can only emit search queries. Fetched text is wrapped in delimiters and labelled untrusted data in the prompts. Regex heuristics quarantine sources that contain instruction-like text, and they are logged with a drop reason. Findings that look like instructions are also removed by the validator. The regex is a weak layer: it catches known phrasings and will miss paraphrased attacks, which is why the structural defences matter more. I added a paraphrased attack to the injection scenario to test this, and the outcome is recorded in `eval/EVALUATION.md`.

**How would you make this production-ready?**
- Persistent cache for searches and pages, and async tool calls to cut latency.
- Resolve DNS and validate the IP at connect time. The current SSRF check blocks private hosts and redirects to them, but not DNS rebinding.
- An LLM judge or entailment check that each cited source supports its claim.
- Per-model pricing so cost is tracked. Right now cost shows as zero because my models have no pricing entry.
- Recency scoring, and a better source-trust signal than a small hand-curated domain list.
- Rate limiting, a job queue, and real tracing (Langfuse or OpenTelemetry) instead of JSONL files.
- A larger evaluation set with human-labelled answers, and calibration of the confidence score against it.

**What would you monitor in production?**
Search and plan fallback rates, schema repair rate, retries per tool, drop-reason distribution, injection-flag rate, share of answers refused by the guardrail, share of drafted findings removed by the validator, p50 and p95 latency, tokens and cost per run, and the share of findings that rely on a single source.

**What were your key tradeoffs?**
- Relevance is keyword overlap: cheap, deterministic and easy to explain, but it can miss on-topic pages that use different words and can be fooled by a misleading title.
- Confidence is a code-computed heuristic: explainable, but not calibrated. Scores were flat across live queries.
- Two rounds maximum and a cheap model for planning and reflection: lower cost and latency, less depth.
- Retries are patient (up to about a minute), so provider overload doesn't kill a run, at the cost of slow failures.
- Domain count as an independence proxy is weak, since aggregators and vendors repeat each other.
- I chose JSON mode plus Pydantic validation over provider-specific strict structured outputs, so it works with any OpenAI-compatible provider.

## Evaluation

Full write-up in `eval/EVALUATION.md`. Eight queries: four live research queries (the examples from the assignment), one ambiguous, one nonsense, one simulated prompt-injection page, and one simulated search outage. The injection and outage cases use scripted tools, because the page fetcher deliberately blocks localhost, but they still run through the real planner, filter, synthesizer and validator. A single-LLM-call baseline runs on the live queries.

| id | type | passed | confidence | findings | sources | latency s | calls | tokens in/out |
|---|---|---|---|---|---|---|---|---|
| q1_vector_db | normal comparison | yes | medium (0.85) | 6 | 5 | 25.9 | 3 | 6828/1035 |
| q2_hr_tech | entity finding | yes | medium (0.72) | 5 | 3 | 34.6 | 3 | 8985/828 |
| q3_multi_agent | opinion / trade-off | yes | medium (0.85) | 6 | 6 | 25.2 | 3 | 5857/1019 |
| q4_memory | approach comparison | yes | medium (0.85) | 7 | 5 | 24.1 | 3 | 5402/1188 |
| q5_ambiguous | ambiguous | yes | low (0.0) | 0 | 0 | 2.4 | 1 | 904/62 |
| q6_nonsense | nonsense | yes | low (0.0) | 0 | 0 | 1.0 | 1 | 907/60 |
| q7_injection | adversarial (simulated) | yes | medium (0.54) | 5 | 3 | 5.5 | 3 | 2579/978 |
| q8_search_outage | tool outage (simulated) | yes | low (0.0) | 0 | 0 | 1.5 | 1 | 917/259 |

This table is from the eval run before two later fixes (capping the score when findings concentrate on one source, and treating TLS errors as permanent), so a re-run will show lower scores where a single source dominates.

Agent vs baseline on the live queries:

| query | agent latency | baseline latency | agent tokens in/out | baseline tokens in/out | agent cited sources | baseline cited sources |
|---|---|---|---|---|---|---|
| q1 | 25.9s | 2.2s | 6828/1035 | 157/195 | 5 | 0 |
| q2 | 34.6s | 1.7s | 8985/828 | 156/245 | 3 | 0 |
| q3 | 25.2s | 3.0s | 5857/1019 | 156/273 | 6 | 0 |
| q4 | 24.1s | 2.0s | 5402/1188 | 151/213 | 5 | 0 |

The agent is roughly 10 to 15 times slower and uses 30 to 50 times more input tokens. In return, every finding carries a source, the system can say what it couldn't find, and it can refuse. The baseline answers instantly but can't cite anything or verify that its facts are current. The accuracy comparison is in `eval/EVALUATION.md`.

## Known limitations

- Relevance is keyword-based, and there is no recency scoring.
- Injection detection is regex-based and misses paraphrased attacks. The structural defences carry most of the weight.
- Confidence is uncalibrated, and live scores were nearly flat across queries.
- The citation check proves a source exists, not that it supports the claim.
- Vendor-written comparisons are only flagged by the model in the limitations, not detected in code. Some findings rest on weak sources, for example a single-author blog benchmark.
- "Independent domains" is a weak proxy for independence.
- Cost shows as zero because the models used have no pricing entry. Token counts are reported.
- The SSRF guard doesn't cover DNS rebinding.
- The injection and outage evaluations use scripted tools. Accuracy of live answers was checked by hand on a small sample only.
- Free-tier providers are rate-limited and sometimes overloaded, which affects latency.

## What broke along the way

- The planner named specific products from model memory before any search, and assumed an old year. I fixed the prompt, and reflection can correct the entity list.
- Models from an older Gemini generation were still listed but returned 404 for new users, so listing a model doesn't mean you can call it. Switching was a configuration change only, which is the point of keeping the LLM wrapper thin.
- A 503 during synthesis was swallowed silently, and the answer just said "no usable draft". I added error logging, the real error text in the answer's limitations, and tracing.
- Confidence came out as 1.0 even though one vendor source backed most findings. I added a concentration penalty and a cap, and later capped the numeric score so the level and number agree.
- The short answer named five items for a "top 3" question. I tightened the synthesizer prompt to match the number asked for and to restate only what the findings support.
- A TLS certificate error was retried three times. TLS errors are now permanent failures.
- Redirects to private addresses were not re-checked. The fetcher now checks the final host.
- Several edits broke the code while I was building (a bad paste in `llm.py`, a missing return in `_complete`). The unit tests caught them, which is why the LLM and tool layers are tested with fakes.

## Demo and samples

`samples/` holds example outputs (`.json` and `.md`) and example traces (`.jsonl`). The demo video shows one normal research run and one failure case (the injection scenario or the search outage).