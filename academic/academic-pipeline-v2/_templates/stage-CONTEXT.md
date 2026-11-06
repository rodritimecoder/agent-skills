# {{FOLDER}} — {{TITLE}}

One job: produce the {{TITLE}} artefacts for stage {{STAGE}}.

**Actor:** {{ACTOR}}
**Step type:** {{STEP_TYPE}}
**Proof:** {{PROOF}}

## Inputs
{{READS}}

## Process
1. Read the inputs above. Do not load the whole workspace.
2. Produce the outputs below, following the checks in this contract.
3. Write `05_verify/step_{{STAGE_PADDED}}.json` so the step can be replayed and audited.

## Outputs
{{WRITES}}

## Human check
{{CHECKS}}

Sign-off: {{HUMAN}}
