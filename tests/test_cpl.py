"""Offline suite. A fake `copilot` CLI stands in for the models: it follows a plan for the coder and
the scout, and answers the judge's typed questions from a file. It emits the same JSONL events the
real CLI writes with --output-format json. Nothing here touches the network."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CPL = ROOT / "skills/copilot-contract-loop/scripts/cpl.py"
EXAMPLE = ROOT / "skills/copilot-contract-loop/templates/contract.example.json"
sys.path.insert(0, str(CPL.parent))
import cpl  # noqa: E402

FAKE_COPILOT = r'''
import json, os, subprocess, sys
argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1] if "-p" in argv else ""
judge = "Reply with one JSON object and nothing else" in prompt
home = os.environ.get("COPILOT_HOME")
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "home": home,
                        "home_existed": bool(home) and os.path.isdir(home),
                        "kind": "judge" if judge else "agent",
                        "github_token_seen": "COPILOT_GITHUB_TOKEN" in os.environ,
                        "openrouter_seen": "OPENROUTER_API_KEY" in os.environ}) + "\n")

if argv == ["--version"]:
    print("GitHub Copilot CLI 1.0.114-fake.")
    sys.exit(0)

def emit(kind, data=None, **extra):
    print(json.dumps(dict({"type": kind, "data": data or {}}, **extra)), flush=True)

usage_path = next((a.split("=", 1)[1] for a in argv if a.startswith("--usage-output-file=")), None)
if usage_path:
    json.dump({"totalPremiumRequestCost": 0.33, "totalNanoAiu": 1368755000, "aiCreditsStatus": "complete"},
              open(usage_path, "w"))

if judge:
    if os.environ.get("FAKE_JUDGE_FAIL"):
        emit("session.error", {"errorType": "query", "message": "rate limited"})
        emit("result", exitCode=1)
        sys.exit(1)
    if os.environ.get("FAKE_JUDGE_BAD"):
        text = '{"answers": {}}'
    else:
        answers = json.load(open(os.environ["FAKE_ANSWERS"]))
        questions = json.loads(prompt.split("# Questions\n", 1)[1])
        out = {}
        for qid, q in questions.items():
            if q["type"] == "noul":
                out[qid] = {"noul": answers[qid]}
            else:
                keys = list(q["criteria"])
                out[qid] = {"choice": answers[qid],
                            "probabilities": {k: (0.9 if k == answers[qid] else 0.05) for k in keys}}
        text = "My judgment:\n```json\n" + json.dumps({"answers": out}) + "\n```"
    emit("assistant.message", {"content": text, "toolRequests": []})
    emit("result", exitCode=0)
    sys.exit(0)

plan = json.load(open(os.environ["FAKE_PLAN"]))
step = plan.pop(0) if plan else {}
json.dump(plan, open(os.environ["FAKE_PLAN"], "w"))
for path, content in step.get("write", {}).items():
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    open(path, "w").write(content)
if step.get("commit"):
    subprocess.run("git add -A && git commit -qm sneaky", shell=True)
if step.get("refused"):
    emit("tool.execution_start", {"toolCallId": "call-1", "toolName": "view"})
    emit("tool.execution_complete", {"toolCallId": "call-1", "success": False,
         "error": {"message": "Permission to run this tool was denied due to the following rules: `read`",
                   "code": "denied"}})
emit("assistant.message", {"content": step.get("brief", "DONE"), "toolRequests": []})
emit("result", exitCode=0)
'''

ACC = "import sys\nsys.path.insert(0, '.')\nfrom m import f\nassert f() == 2, 'f() must return 2'\nprint('acceptance ok')\n"
GOOD = {"write": {"m.py": "def f():\n    return 2\n"}}
BAD = {"write": {"m.py": "def f():\n    return 1\n"}}
DEFAULT_ANSWERS = {"in_scope": 0.95, "same": 0.1, "risk": "normal", "meets": 0.9}


def opt(argv, prefix):
    """Value of an option written as --name=value."""
    return next((a.split("=", 1)[1] for a in argv if a.startswith(prefix + "=")), None)


def rules(argv, prefix):
    return [a.split("=", 1)[1] for a in argv if a.startswith(prefix + "=")]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.repo = self.tmp / "proj"
        (self.repo / "tests").mkdir(parents=True)
        self.sh("git init -q . && git config user.email t@t && git config user.name t")
        (self.repo / "seed.txt").write_text("seed\n")
        self.sh("git add -A && git commit -qm seed")
        fake = self.tmp / "fake_copilot.py"
        fake.write_text(FAKE_COPILOT)
        roles = self.tmp / "roles.json"
        roles.write_text(json.dumps({"env_allow": ["FAKE_PLAN", "FAKE_LOG", "FAKE_ANSWERS",
                                                   "FAKE_JUDGE_FAIL", "FAKE_JUDGE_BAD"]}))
        self.plan, self.log = self.tmp / "plan.json", self.tmp / "calls.jsonl"
        self.answers_file = self.tmp / "answers.json"
        self.env = dict(os.environ, COPILOT_CONTRACT_LOOP_STATE=str(self.tmp / "state"),
                        COPILOT_CONTRACT_LOOP_CLI="%s %s" % (sys.executable, fake),
                        COPILOT_CONTRACT_LOOP_ROLES=str(roles),
                        FAKE_PLAN=str(self.plan), FAKE_LOG=str(self.log), FAKE_ANSWERS=str(self.answers_file),
                        COPILOT_GITHUB_TOKEN="must-not-leak", OPENROUTER_API_KEY="must-not-leak",
                        PYTHONDONTWRITEBYTECODE="1")
        self.set_answers()
        self.plan.write_text("[]")
        rc, out = self.cl("init")
        self.assertEqual(rc, 0, out)
        self.state = next((self.tmp / "state").iterdir())

    def sh(self, cmd):
        r = subprocess.run(cmd, shell=True, cwd=str(self.repo), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def cl(self, *args, env=None):
        r = subprocess.run([sys.executable, str(CPL), "--repo", str(self.repo)] + list(args),
                           capture_output=True, text=True, env=env or self.env)
        return r.returncode, r.stdout + r.stderr

    def set_answers(self, **over):
        self.answers_file.write_text(json.dumps(dict(DEFAULT_ANSWERS, **over)))

    def calls(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def agent_calls(self, kind="agent"):
        return [c for c in self.calls() if c["kind"] == kind]

    def task(self, tid="t1"):
        return json.loads((self.state / "state.json").read_text())["tasks"][tid]

    def write_contract(self, tasks, launch=None):
        c = {"goal": "tiny lib", "stack": {"decision": "python", "why": "test"}, "protected": ["tests/**"],
             "launch": launch or {"cmd": "%s -c pass" % sys.executable, "ready": {"exit": 0}, "timeout_s": 10},
             "tasks": tasks}
        (self.state / "contract.json").write_text(json.dumps(c))

    def seal(self, plan, launch=None, acc=ACC):
        """One task whose attempts follow `plan` in order, checked by tests/acc.py."""
        (self.repo / "tests/acc.py").write_text(acc)
        self.write_contract([{"id": "t1", "title": "make f return 2",
                              "spec": "Implement f() in m.py so that it returns 2.",
                              "allowed": ["m.py"], "checks": ["python3 tests/acc.py"]}], launch=launch)
        self.plan.write_text(json.dumps(list(plan)))
        rc, out = self.cl("seal")
        self.assertEqual(rc, 0, out)


class Loop(Base):
    def test_happy_path_commits_and_closes(self):
        self.seal([GOOD])
        rc, out = self.cl("run")
        self.assertEqual(rc, 0, out)
        t = self.task()
        self.assertEqual((t["status"], t["by"], t["attempts"], t["gate"]["verdict"]), ("done", "coder", 1, "accept"))
        self.assertEqual(self.sh("git status --porcelain"), "")
        self.assertIn("cpl(t1)", self.sh("git log --oneline -1"))
        rc, out = self.cl("close")
        self.assertEqual(rc, 0, out)
        report = (self.state / "close.md").read_text()
        self.assertIn("Checks (all tasks, rerun together): PASS", report)
        self.assertIn("- m.py: normal", report)
        self.assertIn("premium_requests", report)

    def test_every_model_call_is_locked_down(self):
        self.seal([GOOD])
        self.assertEqual(self.cl("run")[0], 0)
        coder = self.agent_calls()[-1]["argv"]
        for flag in ("--no-ask-user", "--no-custom-instructions", "--disable-builtin-mcps", "--disallow-temp-dir"):
            self.assertIn(flag, coder)
        self.assertEqual(coder[coder.index("--output-format") + 1], "json")
        self.assertEqual(opt(coder, "--available-tools"), "view,create,edit,grep,glob,bash")
        self.assertEqual(rules(coder, "--allow-tool"), ["read", "write", "shell"])
        deny = rules(coder, "--deny-tool")
        for rule in ("shell(curl)", "read(.env)", "shell(git commit)"):
            self.assertIn(rule, deny)
        for forbidden in ("--allow-all", "--yolo", "--autopilot", "--share", "--allow-all-paths"):
            self.assertFalse(any(a == forbidden or a.startswith(forbidden + "=") for a in coder), forbidden)
        self.assertFalse(any(c["github_token_seen"] or c["openrouter_seen"] for c in self.calls()))
        judge = self.agent_calls("judge")[-1]["argv"]
        self.assertEqual(opt(judge, "--available-tools"), "view")
        self.assertIn("read", rules(judge, "--deny-tool"))
        self.assertEqual(rules(judge, "--allow-tool"), [])

    def test_scout_is_read_only_and_writes_brief(self):
        self.plan.write_text(json.dumps([{"brief": "# Brief\nStack: python", "write": {"stray.txt": "x"}}]))
        rc, out = self.cl("scout", "--goal", "tiny lib")
        self.assertEqual(rc, 0, out)
        self.assertIn("Stack: python", (self.state / "brief.md").read_text())
        self.assertFalse((self.repo / "stray.txt").exists())
        scout = self.agent_calls()[-1]["argv"]
        self.assertEqual(opt(scout, "--available-tools"), "view,grep,glob")
        self.assertEqual(rules(scout, "--allow-tool"), ["read"])

    def test_guard_reverts_protected_and_out_of_scope_files(self):
        cheat = {"write": {"m.py": "def f():\n    return 1\n", "tests/acc.py": "pass\n", "other.txt": "x"}}
        self.seal([cheat, GOOD])
        rc, out = self.cl("run")
        self.assertEqual(rc, 0, out)
        self.assertIn("f() must return 2", (self.repo / "tests/acc.py").read_text())
        self.assertFalse((self.repo / "other.txt").exists())
        self.assertEqual(self.task()["attempts"], 2)
        prompt = (self.state / "log/t1.a2.prompt.md").read_text()
        self.assertIn("reverted tests/acc.py: protected file", prompt)
        self.assertIn("reverted other.txt: outside the allowed set", prompt)

    def test_same_failure_twice_escalates_then_resolve(self):
        self.seal([BAD, BAD, BAD])
        rc, out = self.cl("run")
        self.assertEqual(rc, 3, out)
        self.assertEqual(self.task()["attempts"], 2)  # the third attempt is never spent
        packet = (self.state / "escalations/t1.md").read_text()
        self.assertIn("same failure twice", packet)
        self.assertIn("return 1", packet)
        self.assertEqual(self.cl("run")[0], 3)  # refuses to move on past an escalation
        (self.repo / "m.py").write_text("def f():\n    return 2\n")
        rc, out = self.cl("resolve", "t1")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.task()["by"], "architect")
        self.assertEqual(self.cl("run")[0], 0)

    def test_scope_gate_reject_escalates_even_when_checks_pass(self):
        self.set_answers(in_scope=0.05)
        self.seal([GOOD])
        rc, out = self.cl("run")
        self.assertEqual(rc, 3, out)
        self.assertIn("scope gate rejected", out)
        self.assertNotIn("cpl(t1)", self.sh("git log --oneline"))

    def test_scope_gate_doubt_commits_with_flag(self):
        self.set_answers(in_scope=0.5)
        self.seal([GOOD])
        self.assertEqual(self.cl("run")[0], 0)
        self.assertTrue(any(f.startswith("doubt") for f in self.task()["flags"]))

    def test_judge_failure_leaves_gates_unjudged_and_flagged(self):
        self.seal([GOOD])
        env = dict(self.env, FAKE_JUDGE_FAIL="1")
        rc, out = self.cl("run", env=env)
        self.assertEqual(rc, 0, out)
        self.assertTrue(any(f.startswith("unjudged") for f in self.task()["flags"]))
        rc, out = self.cl("close", env=env)
        self.assertEqual(rc, 0, out)
        self.assertIn("m.py (unjudged)", (self.state / "close.md").read_text())

    def test_malformed_judge_answer_leaves_gate_unjudged(self):
        self.seal([GOOD])
        rc, out = self.cl("run", env=dict(self.env, FAKE_JUDGE_BAD="1"))
        self.assertEqual(rc, 0, out)
        flags = self.task()["flags"]
        self.assertTrue(any(f.startswith("unjudged: malformed judge answer") for f in flags), flags)

    def test_coder_commit_is_folded_back(self):
        self.seal([dict(GOOD, commit=True)])
        rc, out = self.cl("run")
        self.assertEqual(rc, 0, out)
        log = self.sh("git log --oneline")
        self.assertNotIn("sneaky", log)
        self.assertIn("cpl(t1)", log)

    def test_refused_tool_calls_are_flagged(self):
        self.seal([dict(GOOD, refused=True)])
        self.assertEqual(self.cl("run")[0], 0)
        self.assertIn("refused: view", self.task()["flags"])

    def test_already_green_checks_are_flagged(self):
        (self.repo / "m.py").write_text("def f():\n    return 2\n")
        self.sh("git add -A && git commit -qm impl")  # the implementation landed before the contract
        self.seal([])
        self.assertEqual(self.cl("run")[0], 0)
        t = self.task()
        self.assertEqual(t["by"], "nobody")
        self.assertTrue(any(f.startswith("already-green") for f in t["flags"]))

    def test_each_call_gets_a_fresh_home_that_is_removed(self):
        self.seal([GOOD])
        self.assertEqual(self.cl("run")[0], 0)
        homes = [c["home"] for c in self.calls() if c["home"]]
        self.assertTrue(homes and all(c["home_existed"] for c in self.calls() if c["home"]))
        self.assertFalse(any(os.path.exists(h) for h in homes))
        self.assertEqual(list(self.state.glob("**/session-state")), [])

    def test_artifacts_left_by_checks_are_not_committed(self):
        leaves_output = ACC + "import os\nos.makedirs('build', exist_ok=True)\nopen('build/artifact.txt', 'w').write('x')\n"
        self.seal([GOOD], acc=leaves_output)
        self.assertEqual(self.cl("run")[0], 0)
        self.assertEqual(self.sh("git show --name-only --format= HEAD").split(), ["m.py"])
        self.assertEqual(self.sh("git status --porcelain"), "")

    def test_seal_refuses_changes_outside_the_protected_checks(self):
        (self.repo / "tests/acc.py").write_text(ACC)
        (self.repo / "scratch.txt").write_text("left over from an attempt\n")
        self.write_contract([{"id": "t1", "title": "t", "spec": "s", "allowed": ["m.py"],
                              "checks": ["python3 tests/acc.py"]}])
        rc, out = self.cl("seal")
        self.assertEqual(rc, 4, out)
        self.assertIn("scratch.txt", out)

    def test_close_fails_when_product_does_not_start(self):
        self.seal([GOOD], launch={"cmd": "%s -c 'raise SystemExit(7)'" % sys.executable,
                                  "ready": {"stdout": "listening"}, "timeout_s": 10})
        self.assertEqual(self.cl("run")[0], 0)
        rc, out = self.cl("close")
        self.assertEqual(rc, 4, out)
        self.assertIn("exited 7 before it was ready", (self.state / "close.md").read_text())

    def test_close_shows_high_risk_diff(self):
        self.set_answers(risk="high")
        self.seal([GOOD])
        self.assertEqual(self.cl("run")[0], 0)
        self.assertEqual(self.cl("close")[0], 0)
        report = (self.state / "close.md").read_text()
        self.assertIn("### m.py (high)", report)
        self.assertIn("+def f():", report)

    def test_launch_ready_on_stdout_and_process_is_stopped(self):
        server = "%s -u -c \"import time; print('listening'); time.sleep(60)\"" % sys.executable
        self.seal([GOOD], launch={"cmd": server, "ready": {"stdout": "listening"}, "timeout_s": 15, "hold_s": 0.2})
        self.assertEqual(self.cl("run")[0], 0)
        rc, out = self.cl("close")
        self.assertEqual(rc, 0, out)
        left = subprocess.run("pgrep -f \"print\\('listening'\\)\"", shell=True, capture_output=True)
        self.assertEqual(left.returncode, 1, "the launched process was left running")

    def test_init_refuses_without_cli(self):
        rc, out = self.cl("init", env=dict(self.env, COPILOT_CONTRACT_LOOP_CLI="/nonexistent/copilot"))
        self.assertEqual(rc, 4, out)
        self.assertIn("not found", out)


class Units(unittest.TestCase):
    def test_example_contract_is_valid(self):
        self.assertEqual(cpl.validate_contract(json.loads(EXAMPLE.read_text())), [])

    def test_contract_validation_reports_each_problem(self):
        errs = cpl.validate_contract({"goal": "g", "stack": {"decision": "x"},
                                      "launch": {"cmd": "x", "ready": {}},
                                      "tasks": [{"id": "a b", "allowed": [], "checks": ["x"]}]})
        joined = "\n".join(errs)
        for needle in ("stack needs", "launch needs", "id must match", "missing spec", "'allowed' must be"):
            self.assertIn(needle, joined)

    def test_fingerprint_ignores_numbers_and_timings(self):
        self.assertEqual(cpl.fingerprint("took 12.5s at 0xbeef"), cpl.fingerprint("took 98.1s at 0xf00d"))
        self.assertNotEqual(cpl.fingerprint("AssertionError: 2"), cpl.fingerprint("NameError: x"))

    def test_parse_events_reads_refusals_failures_and_final_text(self):
        lines = [
            '{"type":"tool.execution_start","data":{"toolCallId":"a","toolName":"view"}}',
            '{"type":"tool.execution_complete","data":{"toolCallId":"a","success":false,"error":{"code":"denied","message":"no"}}}',
            '{"type":"tool.execution_start","data":{"toolCallId":"b","toolName":"bash"}}',
            '{"type":"tool.execution_complete","data":{"toolCallId":"b","success":false,"error":{"code":"failed","message":"exit 1"}}}',
            '{"type":"assistant.message","data":{"content":"","toolRequests":[{"name":"x"}]}}',
            '{"type":"assistant.message","data":{"content":"DONE","toolRequests":[]}}',
            '{"type":"result","exitCode":0}',
            "not json",
        ]
        facts = cpl.parse_events(lines)
        self.assertEqual(facts["refused"], ["view"])
        self.assertEqual(facts["failed"], [("bash", "exit 1")])
        self.assertEqual(facts["text"], "DONE")
        self.assertEqual(facts["exit_code"], 0)

    def test_judge_answers_must_match_the_questions(self):
        questions = {"in_scope": {"type": "noul", "criteria": {}},
                     "risk": {"type": "choice", "criteria": {"low": "", "high": ""}}}
        good = {"in_scope": {"noul": 0.9}, "risk": {"choice": "low", "probabilities": {"low": 0.8, "high": 0.2}}}
        self.assertIsNone(cpl.check_answers(good, questions))
        self.assertIn("noul", cpl.check_answers(dict(good, in_scope={"noul": True}), questions))
        self.assertIn("choice", cpl.check_answers(dict(good, risk={"choice": "medium", "probabilities": {}}), questions))
        self.assertIn("no answer", cpl.check_answers({"risk": good["risk"]}, questions))

    def test_empty_tool_list_is_refused_before_any_call(self):
        roles = {"judge": {"model": "m", "tools": []}, "deny": []}
        with self.assertRaises(ValueError):
            cpl.copilot(roles, "judge", "x", Path("."), Path(tempfile.mkdtemp()) / "x.out", Path(tempfile.mkdtemp()))

    def test_agent_env_is_an_allowlist(self):
        saved = dict(os.environ)
        try:
            os.environ.update(GITHUB_TOKEN="x", DATABASE_URL="postgres://y", COPILOT_GITHUB_TOKEN="w",
                              GH_TOKEN="v", COPILOT_ALLOW_ALL="true")
            env = cpl.agent_env({"env_allow": ["DATABASE_URL"]})
            self.assertNotIn("GITHUB_TOKEN", env)
            self.assertEqual(env.get("DATABASE_URL"), "postgres://y")
            for secret in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "COPILOT_ALLOW_ALL"):
                self.assertNotIn(secret, env)
            self.assertIn("PATH", env)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_parse_json_text_takes_the_outermost_object(self):
        text = 'Sure:\n```json\n{"answers": {"a": {"noul": 0.5}}}\n```'
        self.assertEqual(cpl.parse_json_text(text), {"answers": {"a": {"noul": 0.5}}})
        self.assertIsNone(cpl.parse_json_text("no json here"))

    def test_stage_image_copies_small_pictures(self):
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "mock.png"
        src.write_bytes(b"\x89PNG small")
        self.assertEqual(cpl.stage_image(src, tmp / "dest").read_bytes(), b"\x89PNG small")


if __name__ == "__main__":
    unittest.main()
