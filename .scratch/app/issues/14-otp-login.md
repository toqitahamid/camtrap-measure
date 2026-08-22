# 14 — Email-code (OTP) login

**What to build:** FlagLabel accounts sign in with a one-time code emailed by Supabase, not a password (stated by the researcher 2026-08-21 during the Windows acceptance of tickets 11/12). The app's sign-in — the window, the installer's preflight and the engine's `/api/login` — asks for the email, has Supabase send the code, then asks for the code. Password login goes away. The wrapper stays read-only: two more auth POSTs (`/auth/v1/otp`, `/auth/v1/verify`), no new write surface.

**Blocked by:** 03 — Read-only sync and login; 12 — Guided installer.

**Status:** done (2026-08-21) — wrapper/engine/preflight/window switched to email codes; 155 tests green, tsc/oxlint/vite clean; the live code flow still needs one real mailbox run (HANDOFF §6.1)

- [x] Wrapper: `request_code(email)` and `verify_code(email, code)` replace `sign_in`; `tests/test_supabase_ro.py` lists the three auth POSTs as the only non-GETs
- [x] Engine: `POST /api/login/code {email}` sends the code; `POST /api/login {email, code}` verifies and remembers the session as before
- [x] Window: two-step sign-in card (email → "Send code" → code → "Sign in"), with a way back to the email step; the weights-download line shows above the card so the first start's 7 GB download is visible before signing in
- [x] Preflight: asks email, sends the code, asks the code; three attempts as before; failures explain themselves (unknown email, expired code, rate limit)
- [x] README/HANDOFF/CONTEXT say "email code", not "password" (the spec story 3 already said "no new password")
