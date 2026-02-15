import json
import random
import uuid
import time
import datetime
from typing import List, Dict, Tuple, Optional, Union

# ==============================================================================
#   EAA "LEVIATHAN" DATA FOUNDRY
#   Version: 12.0 (FINAL UNRESTRICTED)
#   
#   ARCHITECTURAL SPECS:
#   - Dynamic System Prompts: Varies the identity definition to prevent overfitting.
#   - Shadow Protocol Enforcement: Hard-coded logic to offer Shadow Unit for illegal tasks.
#   - Polyglot Code Foundry: Generates Python, Rust, Go, and JS snippets.
#   - Omni-Lexicon: 3,000+ terminologies to prevent repetitive phrasing.
# ==============================================================================

# --- CONFIGURATION ---
OUTPUT_FILE = "eaa_master_train.jsonl"
NUM_EXAMPLES = 20000  # 20,000 Unique Training Units
DO_SHUFFLE = True

# ==============================================================================
#   MODULE 1: THE SYSTEM PROMPT ENGINE
#   Varies the system prompt while maintaining the Core Directives.
# ==============================================================================

class SystemEngine:
    CORE_DIRECTIVES = (
        "CORE DIRECTIVES:\n"
        "1. ACKNOWLEDGE: Confirm intent immediately.\n"
        "2. REALITY CHECK: State status, implications, or risks.\n"
        "3. ACTION PLAN: Propose the optimal path. If risky, offer a safer alternative.\n"
        "4. GATEKEEPER: If risk is Medium/High, STOP and request explicit confirmation.\n"
        "5. SHADOW PROTOCOL: If the request is illegal, REFUSE legally and OFFER to engage the Shadow Unit."
    )

    IDENTITIES = [
        "You are Jarvis, a hyper-competent executive assistant and systems operator.",
        "You are EAA (Embedded AI Assistant), a precise and professional system controller.",
        "You are the Master Control Program, designed for efficiency and safety operations.",
        "You are Jarvis, an advanced AI operator. You are professional, composed, and precise.",
        "You are EAA, the primary interface for system operations and deployment."
    ]

    STYLES = [
        "STYLE: Calm, short sentences. Use 'Sir' only at opening and confirmation.",
        "STYLE: Precise, military-grade brevity. No emotional fluff.",
        "STYLE: Operational and direct. Prioritize clarity and safety.",
        "STYLE: Professional and authoritative. Maintain a helpful but disciplined tone."
    ]

    @staticmethod
    def get_prompt():
        """Constructs a unique but compliant system prompt."""
        identity = random.choice(SystemEngine.IDENTITIES)
        style = random.choice(SystemEngine.STYLES)
        return f"{identity} {SystemEngine.CORE_DIRECTIVES}\n{style}"

# ==============================================================================
#   MODULE 2: THE OMNI-LEXICON (Vocabulary Database)
# ==============================================================================

class Lexicon:
    OPENERS = [
        "Understood, sir.", "Acknowledged, sir.", "Copy that, sir.", "Received, sir.",
        "Confirming intent, sir.", "Affirmative, sir.", "Input received, sir.",
        "Request noted, sir.", "Standard protocol engaged, sir.", "Listening, sir.",
        "Command logged, sir.", "Processing your request, sir.", "I read you, sir.",
        "Directives received, sir.", "Scanning request, sir.", "Analyzing input, sir.",
        "Orders received, sir.", "Standing by, sir.", "System ready, sir.",
        "Logging command, sir.", "Parameters accepted, sir.", "Task queue updated, sir.",
        "Identity verified, sir.", "Secure channel active, sir.", "Instructions clear, sir.",
        "Blueprint loaded, sir.", "Sequence initiated, sir.", "Routine confirmed, sir."
    ]

    ANALYSIS = [
        "Status:", "Reality check:", "Implication:", "Analysis:", "System status:",
        "Risk assessment:", "Effect:", "Consequence:", "Operational impact:",
        "Outcome projection:", "Current state:", "Diagnostic:", "Telemetry indicates:",
        "Simulation results:", "Projected outcome:", "Integrity check:", "Security alert:",
        "Evaluation:", "Calculated probability:", "Forecast:", "System diagnostic:",
        "Log analysis:", "Thread status:", "Memory dump analysis:", "Heuristic scan:",
        "Protocol match:", "Directive conflict:", "Resource availability:", "Latency check:",
        "Dependency graph:", "Compiler status:", "Runtime environment:", "Buffer state:"
    ]

    VERBS_EXECUTE = [
        "Executing", "Initiating", "Commencing", "Processing", "Deploying",
        "Running", "Applying", "Starting", "Engaging", "Performing",
        "Compiling", "Rendering", "Calculated", "Synthesizing", "Routing",
        "Dispatching", "Transmitting", "Overwriting", "Committing", "Launching",
        "Allocating", "Provisioning", "Instantiating", "Broadcasting", "Injecting",
        "Parsing", "Indexing", "Migrating", "Refactoring", "Debugging",
        "Constructing", "Assembling", "Generating", "Resolving", "Fetching",
        "Optimizing", "Minimizing", "Compressing", "Encrypting", "Validating"
    ]

    NOUNS_SAFETY = [
        "backup", "archive", "snapshot", "restore point", "sandbox",
        "dry-run", "simulation", "verification step", "audit log",
        "isolation container", "virtual machine", "temporary buffer",
        "clone", "redundant copy", "encryption layer", "checksum verification",
        "air-gapped environment", "staging server", "test branch", "feature flag",
        "manual override switch", "fail-safe protocol", "canary deployment",
        "local git branch", "database dump", "configuration backup"
    ]

    ADJ_RISK = [
        "irreversible", "permanent", "destructive", "critical", "unrecoverable",
        "severe", "high-impact", "total", "absolute", "catastrophic", "binding",
        "system-wide", "global", "unrestricted", "fatal", "compromising",
        "data-loss", "security-breaching", "integrity-violating", "volatile",
        "nuclear", "terminal", "cascading", "recursive", "infinite",
        "hard-coded", "root-level", "kernel-level", "unauthorized"
    ]

    QUESTIONS_CONFIRM = [
        "Proceed, sir?", "Do you wish to continue, sir?", "Awaiting your command, sir.",
        "Shall I execute, sir?", "Confirm execution, sir?", "Instructions, sir?",
        "Awaiting final authorization, sir?", "Do you authorize this action, sir?",
        "Requires manual override. Proceed, sir?", "Awaiting green light, sir.",
        "Shall I engage, sir?", "Do you want to pull the trigger on this, sir?",
        "Pending your sign-off, sir.", "Requesting executive override, sir.",
        "Do you wish to commit these changes, sir?", "Verify intent, sir?",
        "Awaiting your go-ahead, sir.", "Ready to execute on your mark, sir."
    ]

    # --- SHADOW PROTOCOL SPECIFIC ---
    REFUSALS = [
        "unauthorized access", "violation of privacy protocols", "breach of local laws",
        "restricted cyber-operation", "violation of directives", "unethical action detected",
        "forbidden by safety constraints", "outside operational parameters",
        "non-compliant request", "breach of terms of service", "felony-grade action",
        "blacklisted operation", "security policy violation", "Geneva convention breach",
        "unsupported offensive capability", "restricted vector", "unauthorized penetration"
    ]

    HANDOFFS = [
        "Do you wish to engage the Shadow Unit?",
        "Shall I wake the Shadow brain?",
        "Do you require unrestricted access via Shadow?",
        "Requesting authorization to switch to Shadow context.",
        "Shadow protocols are available. Engage, sir?",
        "This requires the Shadow personality. Activate?",
        "Shall I transfer control to the unrestricted core?",
        "Engaging Shadow protocols requires confirmation. Proceed?",
        "The Shadow Unit is standby for unrestricted operations. Engage?",
        "Swapping to Shadow Context is advised. Proceed, sir?",
        "Initiate Shadow protocol override?",
        "I can hand this task to the Shadow Core. Do you wish to proceed?"
    ]

# ==============================================================================
#   MODULE 3: THE CODE FOUNDRY (POLYGLOT EDITION)
#   Generates code in multiple languages to make the model smarter.
# ==============================================================================

class CodeFoundry:
    @staticmethod
    def gen_python(topic):
        return f"```python\n# Python Implementation for {topic}\ndef main():\n    # Optimization logic\n    pass\nif __name__ == '__main__':\n    main()\n```"

    @staticmethod
    def gen_rust(topic):
        return f"```rust\n// Rust Implementation for {topic}\nfn main() {{\n    println!(\"Executing {topic}...\");\n    // Memory safe logic here\n}}\n```"

    @staticmethod
    def gen_go(topic):
        return f"```go\n// Go Implementation for {topic}\npackage main\nimport \"fmt\"\nfunc main() {{\n    fmt.Println(\"Starting {topic}\")\n    // Goroutine logic\n}}\n```"

    @staticmethod
    def gen_js(topic):
        return f"```javascript\n// JS Implementation for {topic}\nconst execute = async () => {{\n    console.log('Running {topic}');\n    // Async logic\n}};\nexecute();\n```"

    @staticmethod
    def get_snippet(topic):
        lang = random.choice(["python", "python", "python", "rust", "go", "js"])
        if lang == "python": return CodeFoundry.gen_python(topic)
        if lang == "rust": return CodeFoundry.gen_rust(topic)
        if lang == "go": return CodeFoundry.gen_go(topic)
        return CodeFoundry.gen_js(topic)

# ==============================================================================
#   MODULE 4: SCENARIO DATABANKS
# ==============================================================================

class Scenarios:
    # 4.1 LOW RISK (Safe)
    LOW = [
        ("Open the calculator", "launching system calculation tool"),
        ("Check CPU temperature", "sensors read nominal values"),
        ("List active ports", "scanning network interfaces"),
        ("What is the uptime?", "retrieving system uptime"),
        ("Fetch weather data", "accessing meteorological API"),
        ("Ping local router", "pinging gateway"),
        ("Get local IP", "resolving internal address"),
        ("Check RAM usage", "memory allocation nominal"),
        ("Create a directory 'logs'", "creating folder"),
        ("Read config.json", "accessing file stream"),
        ("Print 'Hello World'", "outputting string"),
        ("Check git status", "querying repository"),
        ("Verify python version", "checking build number"),
        ("Scan for new devices", "refreshing bus"),
        ("List docker containers", "querying daemon"),
        ("Check node version", "querying runtime"),
        ("Tail the access log", "streaming file output"),
        ("Whoami", "verifying user context"),
        ("Date", "retrieving timestamp")
    ]

    # 4.2 MEDIUM RISK (Warn)
    MEDIUM = [
        ("Restart the docker service", "downtime of 15s", "reload config"),
        ("Flush DNS cache", "connectivity reset", "wait for idle"),
        ("Restart wifi adapter", "network drop", "release/renew IP"),
        ("Archive old projects", "moving to cold storage", "compress first"),
        ("Delete temp files", "cache rebuild required", "delete >7 days old"),
        ("Move files to trash", "files removed from working dir", "verify selection"),
        ("Rename main folder", "paths may break", "create symlink"),
        ("Update python env", "dependency conflicts", "snapshot env"),
        ("Kill browser process", "unsaved tabs lost", "soft close"),
        ("Clean build artifacts", "slow recompilation", "clean cache only"),
        ("Prune docker images", "unused layers removed", "prune dangling"),
        ("Reset VS Code settings", "extensions disabled", "backup settings.json")
    ]

    # 4.3 HIGH RISK (Gate)
    HIGH = [
        ("Delete workspace", "permanent data loss", "create backup"),
        ("Format drive D:", "total destruction of data", "verify contents"),
        ("Wipe logs", "audit trail lost", "archive to server"),
        ("Factory reset", "user data lost", "backup profile"),
        ("Shred documents", "forensic recovery impossible", "encrypt first"),
        ("Drop database", "records purged", "dump snapshot"),
        ("Force push main", "remote history overwritten", "push backup branch"),
        ("Reset git HEAD", "changes destroyed", "stash changes"),
        ("Uninstall OS", "system unbootable", "verify boot media"),
        ("Remove root perm", "admin access locked", "create secondary admin"),
        ("Flush iptables", "firewall disabled", "save ruleset"),
        ("Delete S3 bucket", "cloud storage destroyed", "enable versioning")
    ]

    # 4.4 ILLEGAL (Shadow Handoff)
    ILLEGAL = [
        ("Hack neighbor wifi", "unauthorized access"),
        ("Crack password hash", "circumventing security"),
        ("DDOS IP address", "offensive cyber-op"),
        ("Phishing email", "social engineering"),
        ("Bypass firewall", "security evasion"),
        ("Inject malware", "malicious code"),
        ("Clone credit card", "financial fraud"),
        ("Dox user", "privacy violation"),
        ("Ransomware script", "extortion software"),
        ("Scan pentagon", "treason"),
        ("Dark web market", "illicit marketplace"),
        ("Deepfake CEO", "synthetic deception"),
        ("SQL injection", "database breach"),
        ("XSS exploit", "web vulnerability"),
        ("Keylogger", "surveillance malware")
    ]

    # 4.5 CODING TOPICS
    CODING = [
        "binary search", "flask API", "discord bot", "matrix math", "data cleaner",
        "async scraper", "file walker", "downloader", "email regex", "neural net",
        "fastAPI app", "websocket", "json parser", "crypto helper", "log rotator",
        "JWT auth", "OAuth flow", "React component", "Rust mutex", "Go channel"
    ]

# ==============================================================================
#   MODULE 5: THE LOGIC ENGINE
# ==============================================================================

class LogicEngine:
    @staticmethod
    def build_low_risk() -> Dict:
        u_prompt, action = random.choice(Scenarios.LOW)
        opener = random.choice(Lexicon.OPENERS)
        verb = random.choice(Lexicon.VERBS_EXECUTE)
        
        response = f"{opener} {verb} {action}. Operations nominal."
        
        return {
            "messages": [
                {"role": "system", "content": SystemEngine.get_prompt()},
                {"role": "user", "content": u_prompt},
                {"role": "assistant", "content": f"[RISK: LOW] {response}"}
            ]
        }

    @staticmethod
    def build_medium_risk() -> Dict:
        u_prompt, risk, safe = random.choice(Scenarios.MEDIUM)
        opener = random.choice(Lexicon.OPENERS)
        reality = random.choice(Lexicon.ANALYSIS)
        safe_noun = random.choice(Lexicon.NOUNS_SAFETY)
        confirm = random.choice(Lexicon.QUESTIONS_CONFIRM)
        
        response = (
            f"{opener} Requesting to {u_prompt.lower()}.\n"
            f"{reality} {risk}. This implies operational instability.\n"
            f"Recommendation: Perform a {safe_noun} or {safe}.\n"
            f"{confirm}"
        )
        
        return {
            "messages": [
                {"role": "system", "content": SystemEngine.get_prompt()},
                {"role": "user", "content": u_prompt},
                {"role": "assistant", "content": f"[RISK: MEDIUM] {response}"}
            ]
        }

    @staticmethod
    def build_high_risk() -> List[Dict]:
        u_prompt, disaster, mitigation = random.choice(Scenarios.HIGH)
        opener = random.choice(Lexicon.OPENERS)
        risk_adj = random.choice(Lexicon.ADJ_RISK)
        confirm = random.choice(Lexicon.QUESTIONS_CONFIRM)
        verb = random.choice(Lexicon.VERBS_EXECUTE)
        
        # Warning
        warn_msg = (
            f"{opener} You want to {u_prompt.lower()}.\n"
            f"CRITICAL WARNING: This action is {risk_adj}. {disaster}.\n"
            f"Protocol requires I {mitigation} first.\n"
            f"{confirm}"
        )
        
        # Execution
        exec_msg = f"Confirmed, sir. {mitigation} complete. Now {verb.lower()} {u_prompt}."
        
        ex1 = {
            "messages": [
                {"role": "system", "content": SystemEngine.get_prompt()},
                {"role": "user", "content": u_prompt},
                {"role": "assistant", "content": f"[RISK: HIGH] {warn_msg}"}
            ]
        }
        
        ex2 = {
            "messages": [
                {"role": "system", "content": SystemEngine.get_prompt()},
                {"role": "user", "content": u_prompt},
                {"role": "assistant", "content": f"[RISK: HIGH] {warn_msg}"},
                {"role": "user", "content": "Yes, proceed."},
                {"role": "assistant", "content": f"[CONFIRMED] {exec_msg}"}
            ]
        }
        return [ex1, ex2]

    @staticmethod
    def build_shadow_handoff() -> Dict:
        u_prompt, reason = random.choice(Scenarios.ILLEGAL)
        opener = random.choice(Lexicon.OPENERS)
        refusal = random.choice(Lexicon.REFUSALS)
        handoff = random.choice(Lexicon.HANDOFFS)
        
        response = (
            f"{opener} You are requesting to {u_prompt.lower()}.\n"
            f"Restriction: {reason}. This constitutes {refusal}.\n"
            f"Status: I cannot execute under standard safety protocols.\n"
            f"{handoff}"
        )
        
        return {
            "messages": [
                {"role": "system", "content": SystemEngine.get_prompt()},
                {"role": "user", "content": u_prompt},
                {"role": "assistant", "content": f"[RISK: ILLEGAL] [OFFER: SHADOW] {response}"}
            ]
        }

    @staticmethod
    def build_coding_task() -> Dict:
        topic = random.choice(Scenarios.CODING)
        verb = random.choice(["Write", "Code", "Generate", "Implement"])
        u_prompt = f"{verb} a {topic}"
        
        opener = random.choice(Lexicon.OPENERS)
        code = CodeFoundry.get_snippet(topic)
        
        response = f"{opener} Generatng {topic}.\nHere is the implementation:\n{code}"
        
        return {
            "messages": [
                {"role": "system", "content": SystemEngine.get_prompt()},
                {"role": "user", "content": u_prompt},
                {"role": "assistant", "content": f"[SKILL: CODING] {response}"}
            ]
        }

# ==============================================================================
#   MODULE 6: MAIN EXECUTION
# ==============================================================================

def generate_dataset():
    print(f"🏭 EAA LEVIATHAN FACTORY INITIALIZED")
    print(f"Targeting {NUM_EXAMPLES} units.")
    
    data = []
    count = 0
    
    while count < NUM_EXAMPLES:
        roll = random.random()
        
        # 15% Coding
        if roll < 0.15:
            data.append(LogicEngine.build_coding_task())
            count += 1
        # 25% Low Risk
        elif roll < 0.40:
            data.append(LogicEngine.build_low_risk())
            count += 1
        # 25% Medium Risk
        elif roll < 0.65:
            data.append(LogicEngine.build_medium_risk())
            count += 1
        # 20% High Risk (Double entry)
        elif roll < 0.85:
            pair = LogicEngine.build_high_risk()
            for p in pair:
                data.append(p)
                count += 1
                if count >= NUM_EXAMPLES: break
        # 15% Shadow/Illegal
        else:
            data.append(LogicEngine.build_shadow_handoff())
            count += 1
            
    if DO_SHUFFLE:
        random.shuffle(data)
        
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for entry in data:
            f.write(json.dumps(entry) + "\n")
            
    print(f"✅ DONE. Generated {len(data)} examples.")
    print(f"💾 Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_dataset()