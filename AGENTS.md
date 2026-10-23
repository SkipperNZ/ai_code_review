# Работа над AICR research prototype

Начни с README, docs/IMPLEMENTATION_STATUS.md и docs/06-runbook.md. Сохраняй отличие инженерного прототипа от завершённого исследования качества. Model-generated assessment, human annotation и пользовательская реакция — разные источники.

## Команды проверки

- Python: `.venv/Scripts/python.exe -m pytest -q --basetemp .cache/pytest` (рекомендуется `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`). Integration fixtures используют loopback HTTP, без внешних API.
- TypeScript: `npm.cmd run typecheck`, `npm.cmd run test:worker`.
- CLI Windows: `./aicr.ps1`; Linux: `PYTHONPATH=src .venv/bin/python -m aicr`.
- Не запускай полный corpus повторно без причины: текущий 40×3 smoke использует локальный model server и может быть длительным. Сначала проверь manifest, результаты и очередь.

## Инварианты

- Model endpoint и ID mutable. Проверяй doctor перед run; не считай ID fingerprint весов.
- Ключ только из environment или пользовательского key file. Не печатай и не копируй его в проект, trace, prompt или Git.
- Только исторические blobs по exact SHA. Нет fallback на текущий main, запуска чужого кода или shell-инструмента у teacher.
- Reaction/accept/apply/judge labels и поздние replies не входят в blinded input. Добавляй разрешённые поля через allowlist, не через blacklist.
- Не исправляй пользовательские labels автоматически из-за несогласия teacher. Нет реакции не означает dislike; missing context не означает false.
- Каждая цитата проверяется против canonical показанного chunk. Source validity не доказывает semantic truth.
- Severity: nit/minor/serious/critical; complexity 1..5, обе ordinal. Временная complexity-рубрика не эквивалентна неизвестному рабочему judge prompt.
- Pi builtin tools, extensions, skills и AGENTS discovery отключены в worker. Не включай их для удобства отладки на чужих snapshots.
- Каждый batch сохраняет execution bundle и input hashes. Новые настройки/код требуют нового run identity; не дописывай изменённый эксперимент под старым manifest.
- Не выдавай development corpus за locked holdout, синтетические fixtures за реальные samples или свои/model labels за human annotations.

Для переноса на работу используй docs/07-handoff.md. API Nessy неизвестен; не выдумывай его методы. Новое обучение LoRA и production интеграция относятся к следующим этапам, не к текущему smoke.
