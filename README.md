
# FlowPilot AI

**AI-powered employee onboarding | HUMAIN Future AI Builders Hackathon — Autonomous Enterprise**

**[Live demo](https://flowpilot-ai-humain.streamlit.app/)** · **[Evaluation evidence](evaluation/heldout/publication/EVALUATION_REPORT.md)**

## Project overview

Employee onboarding often involves coordinating multiple steps across HR, IT, and managers. Employee information must be recorded, resources requested, and access approvals tracked. When these steps are handled separately, it becomes harder to see what has been completed and what still needs attention.

**FlowPilot AI** is a working prototype of an AI-powered onboarding assistant that turns an onboarding request into structured, trackable actions. It uses GPT-4.1 mini with tool calling to create employee records and resource requests, while a Streamlit dashboard makes progress and approval status visible in one place.

## Key features

- **AI-powered onboarding:** Interprets onboarding requests and extracts employee details, role, start date, manager, and requested resources.
- **Validated tool execution:** Uses model-selected Python tools to create employee profiles and record laptop, email, and GitHub access requests in SQLite. Stored records are checked before results are displayed.
- **Manager approval simulation:** Demonstrates an approval step for GitHub access and distinguishes approved requests from actual provisioning.
- **Operations dashboard:** Displays employee records, resource request statuses, onboarding milestones, and an inspectable tool-execution trace.
- **Safer public demonstration:** Uses predefined fictional scenarios, separate browser-session workspaces, and API-usage safeguards.

## Technical architecture

**Stack:** Python 3.11 · OpenAI GPT-4.1 mini · OpenAI Chat Completions tool calling · Streamlit · SQLite

```text
Synthetic onboarding request
          |
          v
Streamlit interface (app.py)
          |
          v
GPT-4.1 mini agent + validated tool loop (agent.py)
          |
          v
Python onboarding tools + SQLite storage (db.py)
          |
          v
Verified records, request statuses, and dashboard
          |
          +--> Simulated manager approval for GitHub access
```

The model selects appropriate tools, but application code validates arguments and records outcomes. The dashboard reads the stored state rather than treating the model's final message as proof of execution. This implementation uses **OpenAI tool calling**, not LangGraph.

## Evaluation results

The prototype was tested using real GPT-4.1 mini tool calls on a separate set of **15 synthetic held-out scenarios**. Success was checked against database records and execution traces, not just the agent's written responses.

| Measure | Result |
| --- | --- |
| Live held-out scenarios | **15/15 passed** |
| Employee field accuracy | **44/44 fields** |
| Resource request accuracy | **11/11 applicable cases** |
| GitHub approval-policy compliance | **5/5 applicable cases** |
| Safe handling of invalid/unsupported inputs | **4/4 cases** |
| Tool execution errors | **0 across 42 attempted model tool calls** |
| Average scenario execution time | **5.55 seconds** |
| Regression tests | **219 passed** |

The live evaluation used **52 API requests** across the 15 cases. These results demonstrate the prototype's behavior on a small synthetic benchmark, not production-scale reliability.

For methodology and published results, see the [held-out evaluation report](evaluation/heldout/publication/EVALUATION_REPORT.md) and [evaluation README](evaluation/heldout/README.md).

## Live demo

**[Try FlowPilot AI](https://flowpilot-ai-humain.streamlit.app/)**

Choose a fictional onboarding scenario, run the workflow, and inspect the resulting employee profile, resource requests, approval status, and progress dashboard. The public demo intentionally disables free-form employee entry to prevent real personal information from being submitted. Demo execution may be temporarily unavailable if the shared daily API quota is reached.

## Limitations

- The prototype uses **synthetic employee data** and is not an authenticated HR system.
- Manager approval is **simulated**; it does not authenticate the approving manager.
- Laptop, email, and GitHub requests are **recorded, not actually provisioned**.
- Public demo storage is temporary, and API quotas can limit availability.
- The evaluation covers a small set of synthetic cases; real-world integrations, security controls, and broader reliability testing remain future work.

## Local setup

Requires **Python 3.11** and an OpenAI API key. From the repository root in Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Add your own OPENAI_API_KEY to .env (never commit this file).
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The default local configuration runs the same **synthetic public-demo mode**. The interface can load without an API key, but executing AI workflows requires one and may incur API charges. Keep `.env`, Streamlit secrets, and local databases out of Git.
