# FAST-NUCES Agentic AI — SpaceMolt Seven-Day MAS Assignment

Read the PDF assignment first. This starter contains **protocol demonstrations, not the MAS solution**. You must implement your own coordinator, resource agent, trading agent, real SpaceMolt MCP actions, persistent recovery, and two-pilot strategy.

## 1. Seven-day challenge
Two students, two newly registered SpaceMolt pilots, common `nebula` starting empire, and seven consecutive calendar days. No daily milestones. Use any MAS framework or custom architecture. **The grading targets are public platform statistics, summed across both pilots.** Do not spend time writing a custom leaderboard or grade evaluator.

## 2. Install on Windows Anaconda Prompt / CMD
Extract this folder anywhere, then navigate to it (replace the example path with your own):

```cmd
cd /d C:\MAS\SpaceMolt_MAS_Starter
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
python -m scripts.verify_local
```

If `py -3.11` is unavailable, `python -m venv .venv` works with Python 3.11+. If Anaconda shows `(.venv) (base)`, that is fine; run `where python` to verify the first executable is in `.venv`.

## 3. Create two fresh SpaceMolt pilots
- Visit https://spacemolt.com/dashboard and obtain a registration code.
- Choose unique names such as `AI26-G01-A` and `AI26-G01-B`. **Replace G01 with your assigned group ID.**
- Register the two pilots using the website client or optional HTTP bootstrap helper. Example:

```cmd
python examples\pilot_setup.py register --username AI26-G01-A --empire nebula
python examples\pilot_setup.py register --username AI26-G01-B --empire nebula
python examples\pilot_setup.py status --username AI26-G01-A
```

The registration code is only for account creation. The helper stores the generated pilot password in Windows Credential Manager through `keyring`; it does not print secrets. `register` permanently creates a pilot, so never blindly retry if the server response is ambiguous. **This HTTP helper is for account setup only; your assessed gameplay must use MCP.** If registration or session details change, use current official https://spacemolt.com/docs/getting-started .

## 4. Test MCP tool discovery (no login or gameplay)

```cmd
python scripts\preflight.py
python examples\mcp_discover.py
```

Expected: tool names and tool input schemas. In MCP SDK v2, `streamable_http_client` yields `(read, write)` and `Tool.input_schema` is the correct attribute. The example does not log in or move your pilot. Discover actual action parameters; do not invent parameter names.

## 5. Test A2A with separate worker processes
Open three Anaconda Prompt windows. Activate `.venv` in each.

**Window A:** `python examples\a2a_worker.py --role mining --port 9999`

**Window B:** `python examples\a2a_worker.py --role trading --port 9998`

**Window C:**

```cmd
python examples\a2a_client.py --url http://127.0.0.1:9999
python examples\a2a_client.py --url http://127.0.0.1:9998
```

Expected: the clients discover each worker's Agent Card and receive `TASK_STATE_COMPLETED` with `acknowledged_only`. **No mining/trading occurs in this demo.** Ctrl+C stops each server. Students build the real orchestration themselves.

## 6. Test Groq planning (optional provider)
Use a **new, private** Groq key from https://console.groq.com/keys . Do not paste it into your submission or screenshot. Example for a local terminal: `set /p GROQ_API_KEY=Enter key:` (input is visible; hide your terminal when recording). Run:

```cmd
python -m examples.groq_plan
python scripts\budget.py
```

This calls `openai/gpt-oss-20b`, writes a redacted event record, and increments shared request/token accounting. It **does not perform gameplay**. Groq availability and API limits can change; use a permitted alternate model/provider if needed.

## 7. Preview your platform score at any time
Visit **each pilot's public SpaceMolt profile** and add their displayed statistics (e.g. `credits earned`, `credits spent`, `ore mined`, `trades completed`, `distance traveled`, `systems explored`). If the sale is shown in **Exchange Items Sold** rather than **Trades Completed**, count it under `exchange-sales` instead. Example:

```cmd
python -m scripts.platform_score --earned 2000 --spent 900 --ore 30 --trades 1 --exchange-sales 0 --distance 900 --systems 2
```

The score preview is an offline calculator based on the published marking bands; it is not an authenticated game-data source. TAs check the live profiles and confirm any exchange sale. There are no baseline files or custom telemetry submissions for competition grading.

## 8. What YOU must build (not included)
1. One strategic coordinator plus substantive acquisition and trading/logistics agents.
2. At least two independent A2A services with actual task/result handoff, not acknowledgements.
3. Authenticated SpaceMolt MCP gameplay tools with schema-aware validation, ship safety checks, and game-confirmed actions.
4. Real mining, logistics, and legitimate revenue-generating workflow.
5. Persistence across restarts, retry/idempotency safeguards, budgets and meaningful structured logs.
6. A small baseline implementation and comparison with your multi-agent system.
7. A live group demo: both pilots' public profiles, task delegation, MCP operations, failure/restart recovery, both students' explanations.

## 9. Files supplied
- `examples/pilot_setup.py`: optional HTTP-only account registration and read-only status.
- `examples/mcp_discover.py`: read-only MCP tool inspection.
- `examples/a2a_worker.py`, `examples/a2a_client.py`: real protocol exchanges but acknowledgement-only.
- `examples/groq_plan.py`: one real LLM planning call, no gameplay.
- `scripts/budget.py`, `scripts/evidence.py`, `scripts/runtime.py`: reusable accounting and log utilities; not a complete MAS.
- `scripts/platform_score.py`: simple statistics-to-marks preview.
- `scripts/verify_local.py`: offline QA.

## 10. Troubleshooting
- `No module named 'a2a'` or `groq`: verify `.venv` then run `python -m pip install -r requirements.txt`.
- Import error for `get_message_text`: use the supplied import from `a2a.helpers` and check `a2a-sdk` version.
- MCP unpack `expected 3 got 2`: install the pinned `mcp==2.3.0` and use `(read,write)`.
- MCP `inputSchema` error: use `tool.input_schema`.
- A2A port in use: terminate the old worker or select another port and pass the new `--url`.
- HTTP registration code error: refresh code from dashboard; do not expose it.
- Groq 401: rotate key; Groq 429: respect rate limits and use backoff.
- Never turn a failed API response into a fake success; record it, check current game state, and stop unsafe retries.

## Official sources
- https://spacemolt.com/docs/getting-started
- https://spacemolt.com/docs/guides/miner
- https://spacemolt.com/docs/guides/trader
- https://spacemolt.com/leaderboard
- https://spacemolt.com/data
- https://console.groq.com/docs/rate-limits
