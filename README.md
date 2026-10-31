
# FlowPilot AI

**AI-Powered Employee Onboarding | HUMAIN Future AI Builders Hackathon**

**Challenge:** Autonomous Enterprise

FlowPilot AI is an agentic employee onboarding prototype designed to simplify and coordinate onboarding tasks across HR, IT, and management.

Traditional onboarding often involves disconnected processes, manual coordination, and delays in requesting equipment, creating accounts, and obtaining approvals.

FlowPilot AI addresses these challenges through an AI-powered workflow that interprets onboarding requests, executes validated tools, tracks resource requests, and provides a centralized dashboard for monitoring progress.

**Live Demo:** https://flowpilot-ai-humain.streamlit.app/

## 1. Key Features

- **AI-powered onboarding:** Uses GPT-4.1 mini to interpret onboarding instructions and identify employee details and required resources.
- **Autonomous tool execution:** The agent selects and executes validated Python tools to create employee profiles and register resource requests.
- **Manager approval simulation:** GitHub access requests follow an approval workflow, demonstrating how human oversight can be incorporated into agentic systems.
- **Centralized dashboard:** Displays employee records, resource requests, approval statuses, and onboarding progress.
- **Execution transparency:** Provides an inspectable tool execution trace to show how the agent processes requests and performs actions.
- **Safety controls:** Uses fictional demo scenarios, input validation, execution limits, and session-separated workspaces.

## 2. Technical Architecture

FlowPilot AI is built using:

| Technology | Purpose |
| --- | --- |
| Python | Core application logic and tool implementation |
| GPT-4.1 mini | Natural-language interpretation and tool selection |
| OpenAI API | LLM-powered tool calling |
| Streamlit | Interactive web application and dashboard |
| SQLite | Employee records, resource requests, and workflow state |
| Pytest | Automated regression and validation tests |

### Agent Workflow

1. **Receive request:** The user selects a predefined fictional onboarding scenario in the public demo.
2. **Interpret request:** GPT-4.1 mini processes the onboarding instructions and determines which tools are needed.
3. **Execute tools:** The agent invokes validated Python functions to create employee records and resource requests.
4. **Apply workflow rules:** GitHub access requires simulated manager approval before its status can advance.
5. **Store results:** Employee and resource information is saved in SQLite.
6. **Display outcomes:** The dashboard retrieves stored records and presents onboarding progress, request statuses, and execution details.

The system uses OpenAI's native tool-calling capabilities with a bounded execution loop. It does not depend on LangGraph.

## 3. Evaluation Results

FlowPilot AI was evaluated using live LLM execution, held-out synthetic scenarios, and automated regression testing.

| Evaluation Metric | Result |
| --- | --- |
| Live held-out scenarios | **15/15 passed (100%)** |
| Employee field accuracy | **44/44 fields** |
| Resource request accuracy | **11/11 applicable cases** |
| GitHub approval-policy compliance | **5/5 applicable cases** |
| Safe invalid/unsupported request handling | **4/4 cases** |
| Tool execution errors | **0/42 attempted tool calls** |
| Automated regression tests | **219 passed** |
| Average execution time | **5.55 seconds per scenario** |
| Total live evaluation API requests | **52** |

The live evaluation used GPT-4.1 mini with real API calls. Results were verified against stored database records and tool execution traces, rather than relying solely on the agent's written responses.

The 15 held-out scenarios covered straightforward onboarding, language variations, challenging requests, and invalid or unsupported inputs.

**Evaluation evidence:**
- [Held-out evaluation report](evaluation/heldout/publication/EVALUATION_REPORT.md)
- [Machine-readable evaluation results](evaluation/heldout/publication/summary.json)
- [Evaluation methodology](evaluation/heldout/README.md)

These results demonstrate performance on a small synthetic benchmark and should not be interpreted as production-scale reliability.

## 4. Live Demo

**Try FlowPilot AI:** https://flowpilot-ai-humain.streamlit.app/

The public demo allows users to:

- Select fictional employee onboarding scenarios.
- Execute AI-powered onboarding workflows.
- View employee profiles and resource requests.
- Inspect onboarding progress and approval statuses.
- Review the agent's execution trace.

For security and cost control, the public demo uses predefined fictional scenarios rather than unrestricted text input. The onboarding request text box is therefore read-only in public mode.

No real employee accounts, GitHub permissions, or equipment are provisioned.

## 5. Limitations and Future Improvements

FlowPilot AI is a functional hackathon prototype, not a production HR platform.

**Current limitations:**
- Uses synthetic employee data and predefined public demo scenarios.
- Manager approval is simulated and does not authenticate real managers.
- Resource provisioning is simulated; no external HR, IT, or GitHub accounts are modified.
- SQLite demo storage is temporary and may reset when the application restarts or redeploys.
- Evaluation was conducted on a limited synthetic dataset.

**Future improvements:**
- Integrate enterprise HR and IT systems.
- Add authenticated, role-based manager approvals.
- Support real resource provisioning through secure APIs.
- Introduce durable cloud storage and audit logging.
- Expand evaluation to more diverse and realistic onboarding requests.

## 6. Local Setup

### Requirements

- Python 3.11
- An OpenAI API key

### Installation

Clone the repository:

```powershell
git clone https://github.com/RazanAlgadhi/flowpilot-ai.git
cd flowpilot-ai
```

Create a virtual environment and install dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create a local environment file:

```powershell
Copy-Item .env.example .env
```

Add your OpenAI API key to `.env`:

```dotenv
OPENAI_API_KEY="your-api-key-here"
```

Launch the application:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The application will open in your browser.

**Note:** Public synthetic mode is enabled by default. Running AI workflows requires a valid API key and may incur API usage charges. Never commit `.env` or other credential files to GitHub.

---

**FlowPilot AI — Making employee onboarding more coordinated, transparent, and efficient through agentic AI.**
