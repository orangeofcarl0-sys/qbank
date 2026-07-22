# qbank-digitize manual test checklist

- [ ] The Skill researches available source and qbank artifacts before asking questions.
- [ ] Each round contains at most three material questions with recommended bounded choices.
- [ ] It distinguishes source facts, classifications, constants, generated labels,
      allowed empty values, and review-required fields.
- [ ] A supplied classification table is checked for duplicate, overlap, conflict,
      unreachable, and unknown cases.
- [ ] A representative sample covers layout, formula, figure, composite, OCR, and answer paths.
- [ ] Full-corpus execution waits for explicit sample approval.
- [ ] The decision packet records profile, mapping version, source scope, sample,
      unresolved review queue, batch bounds, acceptance criteria, and authorization.
- [ ] qbank commands, writes, validation, and repository handoff are delegated to `$qbank`.
- [ ] The communication Skill contains only a routing reference, not digitization field logic.

Record the prompt, inspected artifacts, question rounds, profile diff, calibration coverage,
decision packet, and any unexpected coupling to `$qbank`.
