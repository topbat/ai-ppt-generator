# Model Selection and PPT-MASTER Queue Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add environment-driven three-model selection to both generation entrances, lock template-fill visual style, expose PPT-MASTER model and full stage history, and queue work above a three-job concurrency limit.

**Architecture:** A shared backend model catalog parses `.env` and validates all submitted model values. Normal generation persists the chosen model and passes it explicitly through `JobContext` to the LLM gateway; PPT-MASTER stores stage history inside its existing JSON parameters and uses Celery worker concurrency three for queue admission. Frontend controls consume option endpoints and contain no model-name constants.

**Tech Stack:** FastAPI, Pydantic Settings, SQLAlchemy/PostgreSQL, Celery/Redis, React 18, TypeScript, Ant Design, Vitest, Docker Compose.

---

### Task 1: Environment-driven model catalog

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Modify: `deploy/.env.example`
- Modify locally: `backend/.env`, `deploy/.env`
- Test: `backend/tests/test_model_selection.py`

**Steps:**
1. Write tests requiring ordered deduplication, allowed-model validation, and configured default validation.
2. Run `python -m pytest tests/test_model_selection.py -q` and confirm failure because the catalog does not exist.
3. Add `LLM_SELECTABLE_MODELS` and `LLM_DEFAULT_SELECTABLE_MODEL` settings plus parsing helpers.
4. Add the confirmed three models to example and local environment files.
5. Re-run the focused test and commit.

### Task 2: Normal generation persistence and strict model routing

**Files:**
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/core/database.py`
- Modify: `backend/app/schemas/dto.py`
- Modify: `backend/app/api/jobs_api.py`
- Modify: `backend/app/pipeline/context.py`
- Modify: `backend/app/pipeline/orchestrator.py`
- Modify: `backend/app/ai/gateway.py`
- Modify: `backend/app/ai/agents/*.py`
- Modify: `backend/app/pipeline/stages/*.py`
- Test: `backend/tests/test_model_selection.py`

**Steps:**
1. Add failing tests for required API model validation, DTO exposure, incremental schema registration, and gateway override routing.
2. Run the focused tests and verify the expected failures.
3. Add nullable `GenerationJob.model`, incremental migration, required request field, `/jobs/options`, persistence/retry propagation, and DTO output.
4. Add `JobContext.model` and explicitly pass the override to every LLM call.
5. Make model override routing retry only the selected model.
6. Run focused and full backend tests, then commit.

### Task 3: New-generation model selector

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/pages/JobNew.tsx`
- Create: `frontend/src/utils/modelOptions.ts`
- Test: `frontend/src/utils/modelOptions.test.ts`

**Steps:**
1. Install Vitest and add a `test` script.
2. Write a failing pure-logic test for selecting the configured default and rejecting absent defaults.
3. Run `npm test -- --run` and verify failure.
4. Implement types/options loading, a required Ant Design model selector in step 3, and submit the chosen model.
5. Run unit tests and `npm run build`, then commit.

### Task 4: PPT-MASTER model validation and template style lock

**Files:**
- Modify: `backend/app/pptmaster/catalog.py`
- Modify: `backend/app/pptmaster/prompt.py`
- Modify: `backend/app/api/pptmaster_api.py`
- Modify: `backend/tests/test_pptmaster.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/pages/PptMaster.tsx`
- Modify: `frontend/src/utils/modelOptions.ts`
- Test: `frontend/src/utils/modelOptions.test.ts`

**Steps:**
1. Add failing backend tests for model options/validation and forced `template` style with a preservation prompt.
2. Add failing frontend tests for template-route style locking.
3. Implement backend model validation, option exposure, style override, and prompt contract.
4. Replace free-text model input with a required select and lock the visual-style control for `template_fill`.
5. Run focused tests and frontend build, then commit.

### Task 5: PPT-MASTER stage history and list presentation

**Files:**
- Modify: `backend/app/pptmaster/service.py`
- Modify: `backend/app/api/pptmaster_api.py`
- Modify: `backend/tests/test_pptmaster.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/pages/PptMaster.tsx`
- Modify: `frontend/src/utils/modelOptions.ts`
- Test: `frontend/src/utils/modelOptions.test.ts`

**Steps:**
1. Add failing tests for consecutive stage deduplication, DTO history extraction, and ` --> ` tooltip formatting.
2. Implement centralized history append in `_update` and initialize history when a task starts.
3. Add explicit `stage_history` to DTO, a dedicated model column, and a Tooltip around running-stage text.
4. Run backend/frontend focused tests and commit.

### Task 6: Three-job PPT-MASTER concurrency

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/Dockerfile`
- Modify: `backend/.env.example`
- Modify: `deploy/.env.example`
- Modify locally: `backend/.env`, `deploy/.env`
- Modify: `backend/tests/test_pptmaster.py`
- Modify: `docs/05-PPTMASTER-INTEGRATION.md`

**Steps:**
1. Add a failing Dockerfile/config test requiring environment-controlled concurrency with default 3 and prefetch 1.
2. Run it and verify failure.
3. Add `PPTMASTER_MAX_CONCURRENT_JOBS=3` and use it in the worker shell command.
4. Document that additional tasks remain pending in Redis rather than being rejected.
5. Run focused tests and commit.

### Task 7: Regression, documentation, and runtime verification

**Files:**
- Modify: `README.md`
- Modify: `docs/03-IMPLEMENTATION.md`

**Steps:**
1. Update API/config/runtime documentation.
2. Run `python -m compileall -q app`.
3. Run `python -m pytest -q` and `python tests/test_pptmaster.py`.
4. Run `npm test -- --run` and `npm run build`.
5. Run `git diff --check` and inspect the final diff.
6. Rebuild and start `api`, `worker`, `pptmaster-worker`, and `frontend`; verify API health and both Worker ready logs.
7. Commit the final documentation and report verification evidence.
