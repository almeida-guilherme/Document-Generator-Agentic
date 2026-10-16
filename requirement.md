# Open requirements

What is still missing, by when it matters. Today the app has **one user**, so the items under "Before more users" can wait until that changes.

## Before putting it on a server

- [ ] **HTTPS and hosting.** A server with a domain, a reverse proxy that handles HTTPS and large uploads (e.g. Caddy), `PDD_COOKIE_SECURE=true`. The app runs as a single process (the job queue lives in it), with `data/` on a persistent disk. Prepared for AWS Lightsail in `deploy/LIGHTSAIL.md` (Docker + Caddy); not deployed yet.
- [ ] **Backups of `data/`.** It holds the database (accounts, projects, encrypted API keys), every uploaded recording and every generated document. Also keep `data/secret_key` (or set `PDD_SECRET_KEY`): without it, sessions end and saved API keys can't be read.
- [ ] **Close sign-up.** With one user: `PDD_ALLOW_SIGNUP=false` once the account exists (accounts can still be made with `python -m web.create_user`). Otherwise anyone who finds the address can create an account.
- [ ] **OpenAI spending.** New accounts run on the server's key (`OPENAI_API_KEY`) unless `PDD_ALLOW_SERVER_KEY=false`. Set a monthly budget limit in the OpenAI dashboard either way.

## Before more users

- [ ] **Login rate limiting.** Nothing slows down repeated wrong passwords today.
- [ ] **Password reset by email.** Today an administrator resets passwords with `python -m web.create_user <email>`. Needs an email service.
- [ ] **Email verification** on sign-up.
- [ ] **Privacy and consent (LGPD).** Recordings show screens, names and faces and are sent to OpenAI. Needs a privacy notice, users confirming they may upload what they upload, and a retention rule (today recordings are kept until the project is deleted).
- [ ] **Retention setting.** Delete uploaded recordings (and optionally frames) after N days, keeping the document.
- [ ] **More than one project at a time.** One worker processes projects in turn; a 40-minute recording takes about 20 minutes. More workers or a real job queue when several people use it at once.
- [ ] **Monitoring.** Error reporting and an alert when runs fail.
- [ ] **Company rules.** Check with the employer before colleagues upload company or client recordings.

## Product

- [ ] **Phase 4: ROI analysis.** Decide how its inputs are given: a form/file filled in by the user, or estimated by the AI with its assumptions marked.
- [ ] **Phase 5: evaluation set.** A few hand-checked recordings with the expected steps, to measure quality and catch regressions. Today only two recordings have been checked by eye.
- [ ] **Steady step count.** The same recording gives 10–14 steps across runs.
- [ ] **Correcting a template's analysis.** The Templates page shows what was kept, removed and filled, but a wrong decision can't be changed there yet; the analysis also varies slightly between runs.
- [ ] **Table of contents page numbers** in template documents: Word fills them when the document is opened (it asks to update fields); LibreOffice shows the table of contents without them.
- [ ] **Other AI providers** (Anthropic, Gemini). Only OpenAI keys can run the pipeline; the provider list offers only OpenAI.
- [ ] **"Forgot your password?" link** from the design, once password reset exists.
