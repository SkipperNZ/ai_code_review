# Обновление корпоративной версии AICR для Nessy

Этот файл — задание для рабочего GLM, который вмерживает доработку в существующий проект с корпоративным GitLab и агентом Nessy на основе Qwen Code. Корпоративная ветка здесь недоступна: имена её модулей, SDK, команды и конфигурацию сначала установи по её коду. Описанные ниже Python-интерфейсы принадлежат этому прототипу, а не неизвестному корпоративному SDK.

## Короткое задание

Сохрани работающие GitLab collector, historical snapshots, корпоративный агент, авторизацию и model/provider settings. Добавь поверх них новый detector контекстной зависимости: E → независимые L/R → присоединение H → отбор H=R≠L → V → controls. Перенеси новые schemas/prompts, offline human-аудит и проверки. Не заменяй корпоративную адаптацию исходной GitHub/Pi реализацией.

Самая важная точка: новый `src/aicr/ambiguity.py` импортирует **отдельный** `execute_pi` из `src/aicr/pi_runtime.py`. Не полагайся на автоматическое подключение старой адаптации: новый transport может обойти изменения в runner.py или оказаться несовместимым с заменённым worker. Его transport, doctor и frozen execution нужно явно проверить и соединить с существующим корпоративным runtime.

Порядок работы: исследовать текущие адаптеры → добавить contracts/core → подключить transport/preflight → согласовать GitLab inputs → добавить CLI/audit → проверить fixtures и SDK → выполнить небольшой smoke. Не переписывай одновременно весь старый pipeline и не обучай classifier в рамках этого обновления.

## 1. От какой версии считать изменения

| Роль | Upstream ref |
| --- | --- |
| Предыдущая исходная версия | `4741f1f144603622ccfa13d3845e12aa35f8be44` |
| Добавление нового detector/audit | `224c107` |
| Финальные runtime fixes и protocol 1.0.2 | `1bb6ae299b2f2b96fc8d50c69053ac661d7c5948` |
| Версия алгоритма | `ambiguity-1.0.2` |
| Portable source с этим runtime | `0.3.1`; пакет `0.3.2` дополнительно содержит эту инструкцию |

Это ориентиры исходного проекта, не утверждение о commit history корпоративной ветки. Если исходные refs доступны локально, изучи `git diff --name-status 4741f1f 1bb6ae2` и затем diff нужного файла. Если refs отсутствуют, сравни с предоставленным source package. Работай в отдельной ветке по правилам корпоративного репозитория и сохрани пользовательские изменения. Не делай wholesale checkout старых файлов поверх адаптации. Если часть доработки уже перенесена, дополни её до нужного поведения без дублирования модулей.

## 2. Что изменилось по смыслу

Раньше основной `run` делал общий review judge: local/static/agent assessments, severity, complexity, correctness и post-hoc triage. Новая задача — установить, когда **готовое замечание невозможно надёжно оценить по его локальному входу**, а дополнительный контекст меняет или разрешает оценку. Рабочие генератор, ordinal heads severity/complexity, reaction/acceptance head, метаранкер и posting policy остаются существующими компонентами.

Новая общая шкала L/R/H — `comment-endorsement-v1`: `accept / reject / unknown`. Это не severity, не complexity и не уверенное угадывание мотива человеческой реакции. Raw thumbs сопоставляются с этой шкалой только как явный proxy.

| Проход | Доступный вход | Tools |
| --- | --- | --- |
| E | Только comment: выделить точный excerpt основного замечания | Нет |
| L | Comment + фиксированный exact snippet + excerpt из E, без rationale E | Нет |
| R | Тот же начальный вход + свободный поиск в historical snapshot | Только read-only snapshot tools |
| H join | После независимых L/R, только в координаторе | Не model call |
| L_repeat | В точности тот же вход и rubric, что у L, без его ответа | Нет |
| V | Comment/claim/local + code-only leads из R; независимый поиск | Только read-only snapshot tools |
| L_plus_context | Исходный local input + выбранные V decisive code chunks | Нет |

Каждый model pass — новая независимая сессия. R не получает L или H. V не получает H, verdict/rationale/relation R или ответ L; leads — только canonical code chunks. C не получает verdict/rationale V. Не переиспользуй старый chat/session с накопленной историей.

Правило кандидата: H и R известны, H=R и H≠L. Валидный L=unknown допустим (`resolved_local_uncertainty`); противоположный известный L — `reversed_local_judgment`. Технический отказ не является unknown-оценкой.

`model_supported_context_dependency` требует одновременно: V=context_dependency_supported; V независимо совпал с R; decisive evidence полностью вне local input; L_repeat совпал с L; L_plus_context совпал с R. При разногласии/отказе оставь соответствующий outcome. Не упрощай до одного сравнения L/R/H и не удаляй controls ради получения большего числа positives.

## 3. Карта файлов для переноса

| Файл/группа | Что делать в корпоративной ветке |
| --- | --- |
| `src/aicr/ambiguity_contracts.py` | Добавить: SCALE/PROTOCOL, exact snippet, candidate rule, validators и H mapping |
| `src/aicr/ambiguity.py` | Добавить coordinator; соединить imports/calls с корпоративными transport, doctor и freeze helpers |
| `src/aicr/ambiguity_audit.py` | Добавить offline packets/scorer; сохранить отдельность H и context-reference |
| `src/aicr/pi_runtime.py` | Эталон transport boundary, **не обязательный runtime**; адаптировать к уже работающему агенту |
| `prompts/ambiguity-claim.txt`, `ambiguity-assess.txt`, `ambiguity-verify.txt` | Добавить без подмены старых prompts; передавать выбранный prompt целиком |
| `schemas/ambiguity-claim.schema.json`, `ambiguity-assessment.schema.json`, `ambiguity-verification.schema.json` | Новые model output contracts; старый assessment compiler к ним не применять |
| `schemas/ambiguity-human.schema.json` | H endorsement input, отдельный от model output |
| `schemas/ambiguity-audit-annotation.schema.json` | Независимые local/repository human annotations |
| `src/aicr/cli.py` | Вмержить новые subcommands, сохранив существующие GitLab команды и конфигурацию |
| `src/aicr/snapshots.py`, `schemas/records.schema.json` | Перенести смысл partial/omissions и optional collection_policy, сохранив GitLab fetching |
| `worker/main.ts` | Upstream изменил только поддержку optional job.task. Не заменять им корпоративный worker целиком |
| `scripts/make_ambiguity_demo.py`, `make_ambiguity_controls.py` | Добавить controlled fixtures; они не запускают свой код и не требуют GitHub/GitLab |
| `scripts/resume_ambiguity.py` | Адаптировать frozen resume: stock helper содержит Pi/node_modules/package-lock проверки |
| `tests/test_ambiguity.py`, `test_ambiguity_audit.py` | Перенести независимые от Pi protocol/audit проверки; согласовать monkeypatch imports |
| `tests/test_ambiguity_pi.py` | Эталон integration scenarios; написать эквивалент для корпоративного runtime |
| `tests/test_contracts.py` | Добавлены проверки partial при omission; сохранить существующие локальные tests |
| `tests/test_pi_integration.py` | Здесь лишь замена personal default.json на публичный config template; не возвращать Pi в корпоративные tests |
| `scripts/import_public_capture.py`, `tests/test_capture_import.py` | Опциональны: offline public GitHub capture. Не заменяют GitLab collector |
| `scripts/package_source.py` | Необязательная упаковка. В upstream template config включён в пакет; personal default.json не используется как источник |
| `docs/15-context-dependence.md` … `18-ambiguity-pilot.md` | Спецификация, runbook, human-аудит и результаты исходного pilot |

Upstream этой доработки **не менял** `github.py`, `runner.py`, `context.py`, `contracts.py`, `io.py`, `audit.py`, `package.json`, `package-lock.json`, `requirements.txt`. Поэтому их корпоративные изменения сохраняй. При этом coordinator импортирует helpers из runner, contracts/io/audit: совместимость этих импортов нужно проверить. Новое имя команды или пакета не является поводом возвращать upstream dependencies и конфиги поверх корпоративных.

## 4. Подключение корпоративного агента

### Boundary

В прототипе функция имеет сигнатуру:

```python
execute_pi(job: dict, config: dict, directory: Path,
           execution_root: Path | None = None) -> dict
```

Это наш интерфейс, не метод Qwen Code. Можно сохранить имя как compatibility wrapper либо дать нейтральное имя `execute_agent` и согласованно обновить imports/calls/tests. Внутри используй уже существующий рабочий SDK/CLI вызов Nessy. Не выдумывай методы, package names или flags неизвестного корпоративного SDK и не переустанавливай уже адаптированный runtime.

Job содержит `task`, непрозрачные `sample_id/run_id`, `mode`, `context`, `system_prompt`, `schema`, `snapshot`, `limits`, `model` и host-only `runtime_dir`. Новый путь не обязан передавать прежний `diff`. Строковый JSON parsing не должен предполагать старые claims/severity/utility/publish поля: decoder и validator выбираются по **переданной schema**. Обязательный универсальный результат transport выглядит так:

```python
{
    "transport_status": None,  # либо, например, "timeout"
    "wall_seconds": 1.25,
    "events": [],             # нормализованный trace
    "final": {
        "status": "candidate",  # ещё НЕ H=R≠L candidate
        "assessment": {...},    # JSON по переданной schema
        "shown_chunks": [...],  # canonical plain-text chunks
        "requests": 1,
        "tool_calls": 0,
        "generated_tokens": 100,
        "format_repair": False
    }
}
```

Это иллюстрация структуры, не готовая заглушка: значения counters/usage/status нужно получать из исполнения. Если SDK не сообщает usage, явно сохраняй measurement unavailable и согласуй агрегацию, не выдавай придуманный ноль за измеренное число токенов. При отсутствии финального ответа `final` может быть None; при ошибке не создавай фиктивный assessment/decision.

Координатор сохраняет canonical response после validators. Transport должен также записывать `input.json` без полного snapshot и секретов, `trace.jsonl`, `stderr.txt` или согласованный diagnostic artifact, `shown-chunks.json`, `raw-candidate.json` при наличии JSON. Сохранить timeout/abort, budgets, redaction и разные attempts. Schema repair может чинить формат; менять фактический verdict ради совпадения с H нельзя.

### Tool access и blinding

- `mode=local` означает отсутствие доступа к repo: не только запрет tool calls в prompt, но отсутствие таких возможностей у сессии. L_plus_context при этом обязан видеть **все** переданные дополнительные chunks.
- `mode=agent` разрешает list/read/search/diff только по зафиксированному historical snapshot. Не использовать текущий checkout/default branch как fallback. Новому job не гарантирован diff; отсутствие diff не разрешает читать актуальный MR.
- Отключить automatic project instructions/AGENTS/skills/extensions и доступ к реальной рабочей папке, shell, edit, произвольному network/repo crawling вне snapshot. Использовать механизм ограничений, реально доступный в вашей сборке агента, а не выдуманные CLI flags.
- Не отправлять модели job целиком. snapshot — host-side источник tools; runtime_dir/config/credentials — служебные поля. В модель идут явные task, blinded identity, context, выбранные prompt/schema и результаты разрешённых tools.
- Проверь автоматические SDK-вставки: cwd, имя каталога/проекта, memory, environment metadata. Реальный runtime_dir содержит outer run name; он не должен становиться подсказкой. Рабочая директория model session должна быть нейтральной и изолированной.
- В 1.0.2 видимый run ID зависит только от PROTOCOL и snapshot hash. H, его hash и описательное имя запуска не должны менять E/L/R request, включая автоматически добавленные SDK поля. Outer manifest отдельно хранит human hashes для provenance.

Canonical chunk имеет source_chunk_id, snapshot_id, commit_sha, path, start_line/end_line и **ненумерованный** excerpt. Используй `contracts.chunk` или точный эквивалент: source_chunk_id — первые 24 hex SHA256 от `snapshot_id + '\n' + path + '\n' + start + '\n' + end + '\n' + excerpt`. Показывать строки с номерами можно; хешировать numbered display вместо исходного текста нельзя. Registry shown_chunks включает начальные chunks и действительно показанные tool results. Inventory пути без прочитанного кода не являются evidence.

В V поле decisive_links допускает supports/refutes и целиком outside-local chunks. Context_links — отдельный массив для local/background citations. Новый ID для перекрывающихся строк не является новым контекстом. Валидность цитаты не доказывает правильность её смысловой интерпретации.

### Doctor, freeze и resume — обязательные точки

`ambiguity.py` импортирует doctor/code_hash/source_files/select_samples из runner. Сохрани или подключи корпоративные реализации. Наш stock doctor читает Pi package.json и вызывает /models: не копируй эту зависимость, если вашего backend она не касается. Нужны проверка доступности реального runtime/model и как минимум ok/deployment_fingerprint для coordinator. Fingerprint версии/метаданных не объявлять fingerprint весов.

source_files/freeze должны включать новый корпоративный adapter, tool implementation, prompts/schemas и реальные dependency locks. Нельзя хешировать только Pi worker, а запускать другой изменяемый агент. Уважай execution_root при исполнении frozen кода; не подтягивай незаметно live-версию adapter из другой папки. Секреты в bundle не входят.

`_LOADED_SOURCE_HASH` специально запрещает новый run после изменения исходников внутри уже запущенного Python процесса. После редактирования запускай свежий CLI/interpreter, не удаляй guard. SDK/model/tooling changes требуют нового run identity. Старые Pi runs не продолжаются под прежним ID с новым корпоративным SDK. Сохрани реальные корпоративные resume/integrity механизмы; stock resume_ambiguity.py нельзя переносить как есть без адаптации Pi-specific checks.

## 5. Согласование с готовым GitLab adapter

Не меняй корпоративный collector ради GitHub discovery. Новый coordinator читает уже нормализованные `normalized/samples.jsonl`, `snapshots/<snapshot_id>.json` и отдельно `signals/user-signals.jsonl` либо H JSONL.

Проверь необходимые поля sample: id, repo_id, created_at, strict_eligible, comment_text, path, original_line, original_commit_id, snapshot_id. Это **проекция нужных полей**, не замена полной storage schema. Provider gitlab и comment_kind note уже допускаются records.schema.json. Legacy имя pr_number не требует возвращать GitHub; сохрани действующее представление MR в вашем adapter.

Ограничения coordinator: sample/snapshot IDs `[A-Za-z0-9_-]{1,100}`, original SHA — 40 lowercase hex, путь — безопасный repo-relative POSIX. Snapshot id/SHA и hashes текстов обязаны совпадать с sample. Номер MR/позиция заметки не заменяют исторический SHA и проверенную строку.

Предпочтительный exact local input — `student_snippet={path,start_line,end_line,excerpt?}`: тот диапазон, который реально доступен локальному judge/student. Код проверяет excerpt и anchor по историческому blob. Fallback — один точный RIGHT-side diff hunk; старое окно ±12/±70 здесь не используется. Нет молчаливого усечения; более 160 строк по умолчанию даёт input_unavailable. При неизвестной версии body/blob/anchor не изобретай t0 и не подставляй main. LEFT-side и иные виды snippet требуют отдельного корректного source mapping/contract, а не подмены правой стороны.

Храни generator rationale и аспекты в source records, если они уже есть, но в этом протоколе **не добавляй их в L/R model input**. Их inclusion — отдельное версионированное условие, потому что пользователь зафиксировал comment+snippet.

При сборке snapshot отмечай partial при пропущенных файлах: budget, sensitive/unsafe paths, symlink, binary/non-UTF8. Upstream optional collection_policy=historical-text-2 описывает именно эти правила. Если у вас своя policy version, сохрани её с совместимой schema; не присваивай этот marker без реализации правил. Старые captures/frozen runs не переписывай. Partial snapshot не позволяет доказывать глобальное отсутствие callers/guards.

### H и независимая разметка

| Источник | Как использовать |
| --- | --- |
| GitLab thumbs | Только явный reaction-proxy: human positive→accept, negative→reject |
| Отсутствие/неполнота/конфликт реакций | Unknown; не dislike |
| Bot/self reactions | Исключить |
| Ручной endorsement | JSONL по ambiguity-human.schema.json, scale_id=comment-endorsement-v1 |
| Явный acceptance event | Только с известной корпоративной семантикой и source_kind=explicit_acceptance_proxy |
| Context-dependency human reference | Отдельные local/repository annotations по ambiguity-audit-annotation.schema.json |

Если ваш GitLab adapter использует другие raw названия emoji/actor types, нормализуй их в существующий signal contract: content +1/-1, actor User/Bot, is_self, reactions_complete, reactor_key. Сопоставление брать из вашего adapter/API, не угадывать. Resolved discussion, закрытый MR или отсутствие acceptance сами по себе не дают accept/reject.

H никогда не входит в prompt/tools/trace input. Model-supported outcome не переписывает H и не становится human gold. Старые полные human assessments, H endorsement и новые context-reference annotations — три разных формата, не делай неявный cast между ними. Classifier пока не обучать.

## 6. CLI и результаты

Вмержить команды: ambiguity-run, ambiguity-evaluate, ambiguity-export-audit, ambiguity-audit-read, ambiguity-score-audit. Глобальные --config/--data идут до subcommand. Сохрани корпоративные defaults, endpoint, secret refs и команды GitLab; personal LAN/model settings из исходного прототипа не переносить.

Offline evaluate/audit/read/score не требуют model endpoint или файла model config. Старые run/evaluate/triage остаются совместимыми; их publish/severity schema не подменяет ambiguity contracts.

Сохранить manifest, frozen execution, human-inputs, case-hashes, stage attempts, raw/validated responses и evidence; итоговые ambiguity-cases/candidates/metrics и SUMMARY. Технические input_unavailable/claim_unavailable/assessment_unavailable отделены от модельного unresolved. В executed_now новые запросы считаются отдельно от cumulative metrics. Resume завершённого run: stages_executed_now=0 и model_requests_now=0; failures повторяются только явно.

Human-аудит экспортирует candidates и controls. Проверяющему передавать только local/ либо repository/ с annotation schema, а private index/корневой manifest оставить координатору. Repo reader умеет работать с отдельно переданной repository/. Неполный аудит не выдаёт recall; synthetic reference не становится human reference даже от смены имени поля. Подробности — docs/17-ambiguity-human-audit.md.

## 7. Проверка по шагам

1. До merge запусти и сохрани результат существующих корпоративных tests/smoke, определи реальные adapter/preflight/freeze файлы.
2. Добавь contracts/core и сохрани unit cases для всех сочетаний L/R/H, unknown/technical failure, exact snippet, forged/unshown/overlapping evidence, независимости H и run name.
3. Проверь audit export/import: в public packets нет H/predictions; неверные цитаты/дубли/ложная слепота отвергаются; synthetic не попадает в human metrics. Offline команды работают без model config.
4. Через **настоящий корпоративный SDK путь** со scripted provider/эквивалентом проверь guard и unguarded, native tools, malformed JSON, endpoint failure, timeout, budget, blinding и final parser под разными schemas. Один HTTP mock без corporate session/tool loop недостаточен. Pi loopback tests — эталон сценариев, не доказательство работы корпоративного runtime.
5. Запусти два fixture generators, затем bounded smoke на корпоративной модели. Fixture code не исполнять. Не требуй совпадения всех модельных ответов с upstream результатами: различие фиксируется как результат, а synthetic references остаются synthetic.
6. Выполни маленький GitLab pilot на 1–3 известных исторических комментариях. Проверь exact body/snippet/SHA, отдельное хранение H, trace/tool evidence, source validity и внешние/неразрешимые случаи.
7. Проверь frozen resume с нулём новых generations и отказ при изменении inputs/bundle. Запусти все сохранившиеся корпоративные tests. Не включай Pi/npm обратно только для получения исторического числа 119.

Минимальный reference unit запуск на Linux после согласования imports/config template (это не полный acceptance suite корпоративного adapter):

```bash
mkdir -p .cache
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_ambiguity.py tests/test_ambiguity_audit.py tests/test_contracts.py \
  --basetemp .cache/pytest-upgrade
PYTHONPATH=src .venv/bin/python scripts/make_ambiguity_controls.py
```

Fixture run на Linux с **вашим** конфигом и уже подключённым corporate transport:

```bash
PYTHONPATH=src .venv/bin/python -m aicr --config configs/work.local.json \
  --data data/ambiguity-controls-v1 ambiguity-run --name corp-controls --limit 4 \
  --human data/ambiguity-controls-v1/human/synthetic-references.jsonl --synthetic-demo
```

Имя конфига здесь пример, используй существующий рабочий config. На Windows эквиваленты — .venv/Scripts/python.exe, ./aicr.ps1 и создание .cache через PowerShell. Не запускать большой corpus ради проверки merge.

## 8. Что считать готовым и что вернуть пользователю

Готово, когда старый корпоративный сценарий сохранён, новый pipeline реально использует корпоративный агент, соблюдает таблицу доступов/независимость и проходит adapter fixtures + маленький GitLab smoke. Нельзя считать готовностью одни import checks, один удачный JSON или только fake-Python judge tests.

В итоговом сообщении перечисли изменённые модули, как подключены transport/doctor/frozen bundle, какие checks реально прошли и где лежит новый run. Раздели synthetic/model-generated/human результаты; назови remaining blockers, если SDK не позволяет нужную изоляцию. Human precision/recall, classifier training и улучшение production ranking сейчас не заявлять. Ключи, внутренние данные, URL и traces не публиковать в личный GitHub.

Дополнительные источники в пакете: docs/15-context-dependence.md (постановка), docs/16-ambiguity-runbook.md (протокол 1.0.2), docs/17-ambiguity-human-audit.md (reference), docs/18-ambiguity-pilot.md (исследовательские ограничения). Реальный pilot на GitHub проводился на 1.0.1, финальный 1.0.2 отдельно проверен на двух synthetic controls; результаты нельзя выдавать за уже выполненную проверку корпоративного агента или GitLab.
