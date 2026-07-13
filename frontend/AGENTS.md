# Frontend engineering instructions

## Architecture

- Use the Next.js App Router and existing component/API boundaries.
- Keep provider calls behind the FastAPI client in `lib/api.ts`; never call an
  inference provider directly from the browser.
- Preserve role-aware navigation, advisory decision language, and explicit
  human checkpoints.
- Reuse the brand tokens in `app/globals.css` and Tailwind configuration.
- Keep components focused; split files that become difficult to review.

## Product-state honesty

- Render deterministic, credential-gated, configured, and measured-live states
  distinctly.
- Never expose provider keys, tokens, internal prompts, or unredacted PII.
- Gemma multimodal copy must say deploy-on-demand and allowlist-gated unless the
  backend provides live runtime evidence.
- Resume and attrition outputs are advisory. UI actions must not imply automatic
  rejection, termination, or another adverse decision.

## Interaction requirements

- Walkthrough buttons must navigate to real mounted panels.
- Preserve keyboard-operable buttons, labels, visible focus, and at least 40px
  mobile touch targets.
- Show confidence, source/evidence, mode, and human-review state beside AI
  output when the backend provides them.
- Keep employee self-service simpler than the operator console.

## Verification

Run `npm run build`, the relevant frontend tests, and `npm audit --audit-level=high`.
Then exercise the changed path in the local browser and verify the runtime mode
shown in the UI matches the backend health/capability response.
