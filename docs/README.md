# Documentation index

This folder documents the integrated Delhi Bus Atlas application. Start with the system overview, then follow the workflow and the relevant subsystem guide.

| Guide | What it covers |
|---|---|
| [Architecture](ARCHITECTURE.md) | Components, responsibilities and data boundaries |
| [System workflow](SYSTEM_WORKFLOW.md) | From source data to a running journey planner |
| [AI pipeline](AI_PIPELINE.md) | Matching, cell construction, training, evaluation and export |
| [Data dictionary](DATA_DICTIONARY.md) | Runtime databases, model artifacts and key fields |
| [API reference](API_REFERENCE.md) | Local HTTP endpoints and parameters |
| [Installation and operation](INSTALLATION.md) | Run, verify and rebuild the project |
| [Model card](MODEL_CARD.md) | Intended use, metrics, assumptions and limitations |

## Diagrams

- [System architecture](diagrams/architecture.mmd)
- [End-to-end workflow](diagrams/system-workflow.mmd)
- [Journey planning flow](diagrams/journey-planning.mmd)

## Existing project notes

- [Main README](../README.md): quick start and user-facing behavior
- [AI package README](../ai/README.md): implementation-level model rebuild instructions
- [AI results](../ai/RESULTS.md): evaluation table and recorded verification results
- [Technical note](../Technical%20note.md): original technical write-up
- [Demo walkthrough](../Demo%20walkthrough.md): saved demo walkthrough
- [Verification log](../Verification.txt): recorded project checks

Documentation describes the current repository implementation. Re-check code and rebuild outputs after changing the pipeline, database schema or API.
