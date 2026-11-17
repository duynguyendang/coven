# Coven Product Requirements — Fully Autonomous Council (v5, corrected)

**Status:** DRAFT. Supersedes v4 (`coven-improve-plan-2026-11-16.md`), which stays as written.
**Date:** 2026-11-16. **Baseline:** HEAD `97df5696` plus the uncommitted working tree of 16:00 VN
(see §2), checked by reading the files and running `make verify` (310 Node tests, Python suite green).
**Window:** Nov 16 – Dec 4, 2026.

## 1. What changed from v4, and why

| v4 | v5 | Why |
| --- | --- | --- |
| "EC2 deployment" | **AWS Lightsail** `nano_3_0` (512 MB, Singapore), SQLite file on the VM disk, Caddy | That is what runs; sizing and D1 depend on it |
| §4 lists 9 open flaws | 6 of the 9 are fixed in the working tree, not yet deployed (§2) | Building them again would waste the window |
| FR-REL-02 blames render / handler / store | Root cause is **DNS**: the `sslip.io` AAAA lookup times out for 10 s on the WSL/Windows resolver, on every new connection; in the container a request takes 136 ms | Fixing the server would not have helped |
| FR-REL-04: "one message" only | One message **and the message is kept**: the host pauses, backs off, retries, answers when Kiro is back | Today's fix closes the message with one plain error; "your message is kept" would be false copy |
| FR-AUT-06 removes the human plan gate | Kept, but **behind a per-project setting, off by default**, and only after an admin scope and a credit budget exist (§4) | With board writes on the read scope and a public `dev` password, removing gates first opens the repo to anyone |
| FR-AUT-05 Accept on the read scope | Accept / Request changes need the **admin scope** (NFR-SEC7) | Accept merges and pushes |
| No cost control | **Credit budget + concurrency caps** (FR-SAFE-02) before any self-started work | Scout + Chair tick + auto plan gate can spend credits with nobody watching |
| Scout = a 13th model agent | Scout = **deterministic code in the host tick**; the Chair (a model) is called only on a finding | The three triggers are measurable; a model adds cost and changes four files the harness checks, for nothing |
| Chair runs every 15 min | Status summary is **computed**, not generated; the Chair model runs only when there is something to decide | 96 model runs a day while idle |
| Elf asks up to 3 questions | Elf **states assumptions and proceeds**; the person may correct with one sentence | Questions to the person are a gate in the middle |
| FR-FLT-03 "a LIVE run during working hours" | Dropped; replaced by "LIVE shows a working host within 15 s" | It is an operating habit that burns credits, not a product requirement |
| FR-AUT-08 bí kíp on the CSD memory layer | **Cut** from this window | No memory layer exists in code (`docs/internal` is git-ignored drafts) |
| FR-HARD-03 split `host.py` optional, last | **Before** the autonomy work, one module | Scout, backoff and Accept would add to a 120 KB file |
| Footer: "The host applies only what you approved" | Rejected | False: the Dev commits on its branch without approval, and `--auto-merge` merges without a person |
| "Six stale never claims" | Checked: the README and ADD claims found are scoped and true today (the Dev never pushes; `work submit` never pushes). Re-check after FR-AUT-05 | Do not edit true sentences |

## 2. Current state (verified)

**Done in the working tree, not committed, not deployed:**
- **One error per message, in plain words.** `host.py` remembers the messages it handled, because the reply goes through the relay and can arrive after the next tick. `council.plain_error`: no JSON, no `-32000`. The UI collapses old repeats ("(4 tries)").
- **Route changes and sidebar count.** A route change draws the new panel at once. Chat and board load in parallel. A session shows its timeline before its council. The sidebar's chat count is the number of messages.
- **Small UI fixes from the 14:54 review.** Session tiles are links. The Credits tile is always shown. The composer has a visible "Send as" label. A witch's task opens the task dialog. "from plan" is a link. Each witch's "Never" is on her card.
- **Look.** Flat surfaces with one pumpkin brand colour, no gradients and no glow. Lilac is used only at the front door. The sign-in is a dark stage with a lilac panel, the serif headline "Kiro, meet your Coven." types itself, and the ghost peeks, ducks on a wrong password and bobs while connecting. The chat ghost thinks while a message waits and shrugs on an error. New messages slide in. Empty states have voice lines. There is a copy-command button and a Pause live button. All motion stops under reduced motion. `docs/DESIGN.md` matches the code.
- **Truthful footer and sign-in tagline.** They say that hosts build on `coven/` branches, tick `tasks.md` and, with `--auto-merge`, merge and push.
- **First-run seed.** A labelled seed puts a council conversation in `atlas-api`: Black Hat objects and the Chair overrules in part.

**Still open:**
1. The Worker exceeds the Cloudflare free-plan row-read limit. Every Durable Object start reads all events (`SqlStore.hydrate`).
2. Lightsail is reached through `sslip.io` (the DNS delay), and its password is the public `dev`.
3. There is no CI (`.github/` does not exist), and `tests/test_host_live.py` failed once on timing today.
4. Board decisions (`/v1/board/{plan,done,retry,dispatch,push}`) need only the read scope (NFR-SEC7 is Partial).
5. There is no credit or concurrency budget beyond slots and `DEFAULT_REVIEW_LIMIT = 3`.
6. The council is reactive: there is no scan and no tick-driven initiative.
7. There is one host.

## 3. Autonomy model

Same as v4 §3: the person is at two ends, the idea and the final evaluation. Corrections:

- **Final evaluation is the default merge gate.** The `--auto-merge` mode stays as an option, opted into per host (FR-AM3), for people who want the council to merge on three passes (D6).
- **"Chair proposes + guard checks" replaces the person's plan approval only where the project opts in** (`COVEN_PLAN_GATE=chair`). The guard checks what code can check: at most 5 tasks, narrow repo-relative paths, one verify command each, the budget left, no rejected sibling plan. It cannot judge intent. That is why the final evaluation stays.
- **No self-started work spends credits beyond the budget** (FR-SAFE-02).

## 4. Requirements, in dependency order

### Phase 0: ship what is done and stop the bleeding (Nov 16–17)

- **FR-REL-00 — Ship the working tree.** Commit the changes in §2 (after review), deploy to Lightsail, restart the host so it runs the new Python. Done when: live, the chat shows one plain error per failed message and the 14:54 checklist passes.
- **FR-REL-01 — One official URL, with a real name.** Lightsail is official (D1). Put a domain on it (an A record), which also removes the DNS delay. The Worker either answers a short "moved to <url>" from the Worker itself, with no Durable Object read, or is deleted. Done when: 3 cold loads of chat, board and sessions finish under 3 s from a fresh browser.
- **FR-SAFE-01 — A real password.** Replace `dev` on Lightsail; `run-host.sh` reads `COVEN_TOKEN` from the environment or the saved login, with no default password in the script. Done when: `dev` gets 401.
- **FR-REL-05 — CI.** A GitHub Actions workflow on Python 3.12 and Node 22.18 runs `make verify`. Fix the `test_host_live` timing flake first. Done when: 10 consecutive green runs, and a broken test turns the run red.

### Phase 1: safety foundations (Nov 17–19)

- **FR-SAFE-02 — Budget.** A per-project daily credit budget and a cap on concurrent builds (`COVEN_BUDGET_CREDITS`, `COVEN_MAX_BUILDS`), counted from `usage.credits` the host already reports. When it is reached, the host stops self-started work, says so once on the board, and still answers people. Done when: a fake runner that reports credits stops at the cap with one note.
- **FR-SAFE-03 — Admin scope (closes NFR-SEC7).** `COVEN_ADMIN_TOKEN`. Plan decisions, Accept / Request changes, push, done, retry and dispatch need it; reading and chatting keep the read scope. Done when: those endpoints answer 403 with the read token. Update ADD §6 and the requirements.
- **FR-REL-04 — Kiro down: pause, keep, resume.** On a model-unavailable failure the host posts one `working` status on the message ("Kiro models are unavailable right now; the council is paused and your message is kept"). It does not close the message, backs off (1, 2, 4, 8, then 15 min), retries, and answers when a run succeeds. Every other host-wide dispatch waits in the same backoff. Done when: in a fake-runner test, 1 status message and 0 error messages while down, and the answer arrives after recovery with no person acting.
- **FR-AUT-07 — Host self-check on start.** Check `python3`, `node` ≥ 22.18 and `node_modules` in worktrees. Fix what can be fixed (link `node_modules`, `npm ci`); otherwise say it once. Done when: a fresh worktree passes verify unaided.
- **FR-HARD-03 — Split `host.py` (moved up).** Extract chat requests and triage (`execute_request`, `execute_triage`, `open_requests`) into `src/coven/requests.py`, with the tests moved. No behaviour change. Done when: `make verify` is green and `host.py` is at least 15 % smaller.

### Phase 2: the final evaluation gate (Nov 19–23)

- **FR-AUT-05 — Accept / Request changes.**
  - **Where:** in the task dialog for a submitted branch whose three reviews passed. Admin scope.
  - **New contract:** `POST /v1/board/accept`, which makes a web-only event `task_accept` (`{task, branch, host_id, decision: accept|changes, reason?, author}`). It is refused from `/v1/events`, like `push_request`, and goes into ADD §6.
  - **On Accept:** the host that holds the branch runs the FR-AM4 qualification. That means a clean merge, `make verify` on the merged tree and no person's rejection. Then it pushes the base (never forced), deletes the branch and records `task_merged`, which gets a `decided_by: person`, `author` variant. A failed qualification holds the task with its reason and never half-merges.
  - **On Request changes:** the task goes back to the Dev with the reason, at most 2 reworks, then holds.
  - **Docs:** ADD §4.3.1, README and requirements FR-ST2, FR-H14 and FR-AM. Update the human-merge patch note to this model.
- **FR-AUT-06 — Opt-in Chair plan gate.** `COVEN_PLAN_GATE=chair` on a project. A Chair `chair_proposal` that passes the guard (§3) turns a plan into build tasks, recorded as a `plan_decision` with `author: grey-witch` and the guard result. Without the setting, nothing changes. Rewrite ADD §4.3.1 to cover both. Done when: with it off, the behaviour is as today; with it on, every build has a proposal and a guard pass in its record, and a build is refused when the budget is spent.

### Phase 3: initiative (Nov 23–27)

- **FR-AUT-01/02 — Scout scan (code, no model).** Every N ticks the host scans the board and runs, then posts a board note for each finding. That is a new note kind `finding` in `NOTE_KINDS` (both copies and ADD §6), with evidence: ref, age, last error, link. Dedupe by task key, a cooldown of 24 h per subject, and at most 3 open findings per project. Triggers:
  1. A task that failed or was blocked more than 4 h ago and was not retried.
  2. A build task claimed with no `task_status` for 30 min.
  3. `make verify` red on the base, from CI status or the host's own check.

  A finding is not a build: the Chair reads it on her next decision. Done when: a planted failed task gives one finding within one scan and none again within 24 h; a clean board for a day gives 0 findings. Drop v4's "session with 0 tool calls" trigger: it is telemetry noise (the smoke session).
- **FR-AUT-03 — Chair round.** Every 15 min the host computes a status line (counts, stuck items, budget left) and posts it only when it changed. The Chair model runs only for an open finding, a stuck item past its limit, or a person's message. Done when: an idle hour means 0 model runs and at most 4 status notes; one planted stuck item means one Chair decision.
- **FR-AUT-04 — Idea to brief.** For a raw idea, the Elf writes a brief (in scope, out of scope, done criteria, assumptions). She asks the person nothing unless the idea cannot be scoped; a correction is one sentence. Done when: a one-sentence idea gives a brief in one round with no question.

### Phase 4: fleet honesty (Nov 27–Dec 1)

- **FR-FLT-01 — Second host:** a real machine (D4) or a host marked `source: "seed"` that the DEMO DATA bar labels.
- **FR-FLT-02 — Credits:** the Credits tile and burn per session from `usage.credits` (already built; check it against a real run), plus spend against the budget (FR-SAFE-02).
- **FR-FLT-03 (rewritten) — Liveness:** a working host's session reads LIVE within 15 s of its first tool call.

### Phase 5: hardening (Dec 1–4)

- **FR-HARD-01 — Truth pass:** after FR-AUT-05/06, README, ADD and DESIGN.md say what ships. Re-check every "never" sentence against the code.
- **FR-HARD-02 — Bug bash** on the official URL, CI green.
- Cut first if short: Phase 4 real host (use the labelled one), then FR-AUT-04.

## 5. Non-functional requirements (changes only)

- **NFR-COST-01 (new):** self-started model runs are counted and capped (FR-SAFE-02); an idle day with no findings costs 0 credits.
- **NFR-SEC-01:** decisions need the admin scope (FR-SAFE-03) before Accept ships; the public URL never runs on `dev`.
- **NFR-A11Y-01:** drop "without full innerHTML replacement". The app re-renders by design. Keep the chat's `aria-live` thread and the focus and draft keeping that already exist.
- Otherwise as v4 §6.

## 6. Copy

- **Tagline (shipped):** "Watch every Kiro session live, and let the witches work: your hosts build each task on its own branch, tick `tasks.md`, and merge what every reviewer passed." It is true for `--auto-merge`; after FR-AUT-05 it becomes "…and merge what you accept."
- **Footer (shipped):** says what the page and cloud do not change, and what hosts do.
- **Rejected:** v4's footer ("applies only what you approved"), which is false. Tagline A ("One Kiro, eleven witches…") is true, if you prefer it (D5).
- **Kiro-down text:** the "your message is kept" wording ships with FR-REL-04, not before.

## 7. Decisions needed

- **D1:** Lightsail official, Worker redirect or delete? And which domain name?
- **D2:** settled. Pumpkin is shipped and documented.
- **D3:** settled by this draft. The Scout is code, not a witch.
- **D4:** a real second host (which machine?) or a labelled one?
- **D5:** keep the shipped tagline, or tagline A?
- **D6:** the person's Accept as the default merge gate, with `--auto-merge` as the opt-in? (This draft assumes yes.)
- **D7 (new):** daily credit budget per project, and the max number of concurrent builds.
