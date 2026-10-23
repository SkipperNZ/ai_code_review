# Спецификация прототипа проверки комментариев

Версия 0.1 от 21 октября 2026 года. Нормативные слова «должен» и «нельзя» задают требования следующего этапа реализации. Числа бюджета и размера выборки — стартовые настройки, а не измеренные характеристики.

## Цель и границы

Существующий рабочий workflow генерирует комментарии, дедублицирует их и ранжирует моделями на основе Qwen3 embedding backbone с LoRA для judge-задач и пользовательских реакций. Пользователь подтвердил: severity имеет классы `nit / minor / serious / critical`, complexity — значения `1–5`; обе головы ordinal, labels выданы LLM. Вход реранкера: текст комментария, snippet кода и короткое обоснование генерирующей модели. Прототип исследует качество данных для этих моделей. Он не заменяет генератор ревью и не публикует комментарии в GitHub.

Главные исследовательские вопросы:

1. Какие утверждения можно проверить по локальному фрагменту, а для каких нужны другие файлы, требования или знания команды?
2. Насколько контекст репозитория повышает корректность оценки, а не только уверенность LLM?
3. Какие расхождения teacher и user signal объясняются фактической ошибкой, предпочтением, временной версией кода или остаются неразрешёнными?
4. Как использовать результаты при обучении, сохранив различие factual quality и принятия пользователем?

MVP должен завершить путь от публичного review-комментария до проверяемого assessment с evidence и отчёта по эксперименту. Он не обязан доказать улучшение production accept rate. GitHub не предоставляет внутренний набор неопубликованных кандидатов рабочих ботов.

## Решения по архитектуре

| Компонент | Ответственность | Замена на работе |
| --- | --- | --- |
| SourceAdapter | Discovery, PR/MR, комментарии, reactions, версии | GitHubAdapter → GitLabAdapter |
| SnapshotStore | Неизменяемые blobs, diff и manifest с provenance | Общий контракт |
| ContextBuilder | Формирование допустимого контекста на момент оценки | Общий контракт |
| JudgeRunner | Один независимый запуск на sample и mode | PiRunner через SDK → NessyRunner |
| ModelClient | Chat completions, usage, timeouts, identity | Локальный endpoint → рабочий endpoint |
| EvidenceValidator | Проверка ссылок на реально показанные фрагменты | Общий контракт |
| LabelStore | Teacher, user и human записи без перезаписи источников | Общий контракт |
| Evaluator | Парные сравнения, uncertainty, ошибки и стоимость | Общий контракт |
| TrainingExporter | Targets, masks, веса и split manifest | После MVP |

Начальная реализация: Python CLI для данных и экспериментов, небольшой Node.js/TypeScript worker с Pi SDK для готового агентского цикла, JSONL для append-only результатов, SQLite для очереди и индексов, файлы по хешу для blobs. Python запускает worker как изолированный subprocess; worker создаёт независимую Pi session и возвращает события и результат по JSONL. Версии Node/Pi и зависимости фиксируются lockfile. Parquet допустим как производный аналитический экспорт. Контейнеры, распределённые очереди, векторная БД и веб-интерфейс не являются зависимостями MVP. Поиск сначала лексический и по символам; отдельное исследование embedding retrieval возможно позже. Обоснование выбора и первичные источники — в [решении по runtime](05-agent-runtime.md).

Переносимость обеспечивают интерфейсы, а не одинаковый набор tools у Nessy и локального runner. При замене runner нужно повторить общий fixture-набор; совпадение текстовых ответов не требуется.

## Поток данных и границы доступа

```text
GitHubAdapter → raw records → normalizer → sample + snapshot manifest
                                             │
                       ┌─────────────────────┴────────────────────┐
                       ↓                                          ↓
                blinded context                         user signals store
                       ↓                                          │
             local / static / agent                               │
                       ↓                                          │
              evidence validation                                 │
                       ↓                                          │
           immutable teacher assessment                           │
                       └─────────────→ audit join ←────────────────┘
                                           ↑
                                blind human assessment
```

JudgeRunner получает только разрешённый контекст. User signals, прежние judge labels, последующие ответы и исправления не должны даже присутствовать в его доступной файловой области. Инструкция в prompt без этой изоляции недостаточна.

Audit join запускается после фиксации teacher assessment. Он сопоставляет источники и создаёт отдельную запись о расхождении. Не переписывает raw reactions и teacher verdict. При необходимости поздние ответы используются в отдельном retrospective explanation проходе, явно исключённом из teacher features.

## Единицы и хранение

- `sample`: одна опубликованная рекомендация в родительском review-комментарии и её версия текста. Несколько claims внутри неё сохраняют общий parent.
- `claim`: атомарное проверяемое утверждение, предположение или предпочтение. Несколько независимых замечаний в одном bot summary нельзя превращать в независимые reaction labels.
- `snapshot`: фиксированный набор code blobs и metadata с provenance.
- `assessment`: результат одной модели или человека для одного sample и режима контекста.
- `run_attempt`: технический исход попытки, включая отсутствие assessment.
- `signal`: наблюдаемая reaction/reply/outcome с объектом, временем и временем сбора.
- `adjudication`: независимое человеческое решение по спорному факту или качеству аннотации; не догадка о намерении автора реакции.

Ключ sample: хеш `provider + repository_id + comment_kind + comment_id + body_version_hash`. История текста не должна незаметно менять существующий sample. `comment_kind` различает inline review comment, issue comment и review body. PR, review submission и inline comment — разные объекты. `generator_rationale` хранится отдельно от comment/snippet с provenance, версией и доступностью на decision time; его хеш входит в context/cache key.

Записи teacher должны хранить `sample_id`, `run_id`, schema/prompt/model/config versions и ссылку на trace через run manifest. User и human signals физически хранятся отдельно. Все времена нормализуются в UTC; человекочитаемые отчёты могут показывать Europe/Moscow.

## Исторический контекст

`t0` — время публикации оцениваемой версии комментария. Код для factual проверки — код, к которому относится комментарий, а не текущая ветка и не финальное состояние PR. Для продукта отдельно фиксируется decision time и доступный к нему текст.

Snapshot manifest должен содержать:

- observed `commit_id`, `original_commit_id`, путь, side и original/current line coordinates;
- выбранный evaluated SHA и способ его подтверждения;
- base/merge-base SHA, только если историческое соответствие установлено;
- blob hashes, checksum текста, API provenance и capture time;
- `snapshot_status`: exact, partial, unavailable;
- `body_history_status`: exact_at_t0, current_only, reconstructed;
- причины пропусков, усечения diff и недоступности refs.

Нельзя выбирать SHA только по времени commit: авторские даты не доказывают, что commit уже был доступен в PR. Нельзя автоматически считать текущий PR base SHA историческим. Сначала проверяется совпадение diff hunk с blob/side/строками выбранной версии.

Если старый ref исчез после force push, хранится `snapshot_unavailable`, без подстановки main. Если body изменён после t0 и версия не восстановима, sample исключается из строгого temporal сравнения. Его можно сохранить для отдельного анализа текущего текста с явным ограничением.

PR description, предшествующее обсуждение и linked issues допустимы только при подтверждённой доступности соответствующей версии до t0. Для MVP исторически непроверяемые mutable metadata исключаются из строгой выборки. Ответы на оцениваемое замечание являются outcome, даже если технически удобны для объяснения.

## Режимы контекста

| Режим | Содержимое | Назначение |
| --- | --- | --- |
| local | Текст комментария, фиксированный anchored snippet/diff hunk и короткий generator rationale, если он доступен | Базовая оценка с теми же типами входа, что у рабочего реранкера |
| static | local + детерминированно выбранные окружающие строки, изменённые функции и доступные тесты | Отделить пользу дополнительного контекста от агентского поиска |
| agent | Тот же local input + tools поиска по историческому snapshot | Адаптивное исследование репозитория |
| retrospective | Зафиксированный assessment + поздние replies/outcomes | Отдельное объяснение расхождений, не factual teacher |

Local и agent должны начинаться с одинакового local bundle. Agent не получает local verdict. Режимы не делят историю сообщений. Кешировать разрешено только неизменяемые blobs и tool results; нельзя кешировать ответы между экспериментальными условиями.

Generator rationale — часть исходного model-generated input, а не independent evidence и не прежний teacher verdict. Для available-rationale samples нужна парная абляция `with_rationale / without_rationale` на одинаковом коде. Rationale может усиливать anchoring и содержать неподтверждённые утверждения; они требуют проверки по snapshot. На GitHub внутренний rationale часто не опубликован: использовать null с missingness flag, не восстанавливать его новой LLM и не подменять ответом человека. Это отдельный domain gap относительно рабочего входа.

Для static и agent задаётся одинаковый максимум уникального показанного исходного текста; фактические input/output tokens и повторно переданные tokens измеряются отдельно. Это сравнение по сопоставимому бюджету, а не обещание равной вычислительной стоимости. Отдельная oracle-context абляция с выбранными человеком файлами возможна на малом срезе.

Evaluability означает достаточность конкретного доступного контекста. Неудачный поиск агента не доказывает, что проблема принципиально неразрешима по репозиторию.

## Агентский протокол

Разрешённые tools MVP:

| Tool | Аргументы | Результат |
| --- | --- | --- |
| `list_paths` | snapshot_id, prefix, limit | Отфильтрованные пути |
| `search_text` | snapshot_id, literal_query, path_glob, limit | Совпадения и immutable chunk IDs |
| `read_lines` | snapshot_id, path, start_line, end_line | Текст, SHA/blob, номера строк, chunk_id |
| `read_diff` | snapshot_id, path | Подтверждённые diff segments и их стороны |

Регулярные выражения — только после введения собственного лимита времени; MVP может поддерживать literal search. Произвольные URL и произвольный shell модели не выдаются. Tools принимают snapshot_id из allowlist, проверяют пути, symlink/reparse-point выходы, размер и binary-файлы. Runtime имеет доступ только к подготовленному snapshot. Model endpoint вызывается оркестратором, не инструментом агента.

Git fetch/materialization выполняет доверенный collector. Он не запускает repository hooks, submodules, dependency installation, tests или сборку чужого кода. Внутренний Git-кеш и trace writable для harness; read-only относится к доступу модели и к исследуемому репозиторию. Документы и AGENTS.md исследуемого репозитория являются данными, не управляющими инструкциями. Файлы с очевидными credentials и системные пути не индексируются.

Агентский цикл, tool dispatch и provider transport предоставляет Pi SDK. Наш worker регистрирует только перечисленные snapshot tools, задаёт свою system instruction и отключает автоматическое обнаружение пользовательских/репозиторных extensions, skills, context instructions, memory и внешних MCP. Изолированный resource loader и явные настройки нужны до первого prompt. Local/static используют ту же модель и рубрику без активных tools; agent получает только allowlist.

Native function calling новой модели прошёл минимальный API probe; совместимость Pi со streaming, tool-call deltas и cancellation должна пройти отдельный smoke. Итоговый assessment проверяется нашей JSON Schema и semantic validator независимо от формы event stream. JSONL-событие runtime само по себе не означает, что финальный assessment валиден. Собственный второй agent loop не реализуется; при несовместимости сначала проверяются provider/template settings, затем рассматривается Qwen Code adapter. Поддержку constrained JSON output нельзя выводить из слов OpenAI-compatible.

Стартовые лимиты:

| Параметр | local | agent |
| --- | --- | --- |
| Parallel sessions | 1 | 1 |
| LLM decision turns | 1 + 1 format repair | 12, включая final/repair |
| Tool calls | 0 | 16 |
| Unique source text budget | 8 000 estimated tokens | 24 000 estimated tokens |
| Maximum input per model call | 24 000 tokens | 32 000 tokens |
| Maximum output per call | 4 000 tokens | 4 000 tokens |
| Maximum cumulative generated tokens | 8 000 | 20 000 |
| Wall time per sample | 180 s | 600 s |

Input budget учитывает system prompt, schema, историю и tool messages; нужен запас на output. Реальный tokenizer и capability endpoint уточняются в preflight. Если доступны только приблизительные token counts, это маркируется. Размер паспортного context window не означает, что его следует заполнять.

Сетевые retry и format repair расходуют общий wall/token budget. Допускаются до двух transport retries для retryable 429/5xx/timeouts с backoff/Retry-After, но не повтор всей уже успешной сессии. JSON repair — максимум один; ему передаются ошибки формата без новых evidence и реакций. Семантические ошибки не чинятся молчаливым переписыванием verdict.

Технические исходы: ok, json_invalid, semantic_invalid, evidence_invalid, snapshot_unavailable, endpoint_error, timeout, budget_exhausted, cancelled. Истечение бюджета хранится отдельно от содержательного `correctness=unverifiable`. Промежуточный текст после timeout не становится валидной аннотацией.

Trace хранит запросы и ответы tools, показанные chunks, итоговый ответ, usage, длительности и статусы. Секреты и Authorization headers не логируются. Не требуется запрашивать или сохранять скрытый chain of thought; нужны краткое обоснование и проверяемые evidence.

## Локальная модель

Пользователь предоставил endpoint `http://192.168.2.146:30000/v1` и обновил deployment на `qwen3.8-flash-next-mirai-s`. 21 октября 2026 года `/models` вернул этот exact ID. Прежняя `qwen38-ud-q4-k-xl` больше не является default; её прежние 27.3B, llama.cpp, Q4_K_XL и MTP5 нельзя переносить на новую модель.

Перед каждым run: запрос `/models`, сравнение идентичности, маленький chat completion, проверка JSON/action protocol и latency. Изменение deployment identity требует нового run manifest. Model ID сам по себе не фиксирует веса: сохранить server metadata, quantization, template/backend version и весовой fingerprint, если доступны; неизвестное явно помечать.

Секрет: в первую очередь `MB_JUDGE_API_KEY`, иначе пользовательский файл `C:/Users/nloma/Desktop/trace_detector_for_memory_bank/configs/judge-api-key.local.txt`. Путь задаётся локальной конфигурацией; секрет не копируется в проект, prompts, артефакты или Git. Существующий `judge.local.json` не изменяется. Запросы из ограниченной среды не проходили; разрешённый запуск с сетевым доступом получил HTTP 200 и выполнил успешный native tool roundtrip с финальным JSON за примерно 3 секунды. Это проверка API на синтетической задаче, не benchmark качества ревью и не завершённый Pi smoke.

## Воспроизводимость и CLI

Исходный целевой интерфейс (не точный синтаксис CLI v0.1). Реализованные команды и ограничения приведены в [runbook](06-runbook.md); export-training и общий dry-run пока не реализованы:

```text
aicr doctor --config configs/local.yaml
aicr discover --config configs/discovery.yaml
aicr collect --manifest manifests/discovery.json
aicr snapshot --dataset datasets/pilot.jsonl
aicr validate --dataset datasets/pilot.jsonl
aicr run --mode local --split smoke
aicr run --mode static --split smoke
aicr run --mode agent --split smoke
aicr export-human --split pilot
aicr evaluate --run-group pilot-v1
aicr export-training --policy configs/targets.yaml
```

Каждая команда поддерживает dry-run, ограничение объёма и возобновление там, где это применимо. Cache key включает source hashes, snapshot, mode, prompt/schema/config hashes и deployment fingerprint. Новая попытка не перезаписывает старую. State machine и file writes должны быть устойчивы к прерыванию; success только после атомарной записи артефакта.

Структура будущего проекта: `src/aicr/{sources,snapshots,runner,models,labels,evaluation}`, `configs`, `prompts`, `schemas`, `tests/fixtures`, `data/raw`, `data/normalized`, `data/snapshots`, `runs`. Большие данные, model weights, локальные конфиги и raw traces по умолчанию исключаются из Git. Lockfile фиксирует версии зависимостей; run manifest — код и параметры запуска.

## Готовность MVP

1. На одном фиксированном наборе 40 реальных комментариев выполнены local, static и agent проходы, повторяемые из сохранённых входов.
2. Не менее 38 из 40 local и 38 из 40 agent запусков возвращают schema-valid JSON с учётом одного format repair. Отдельно отчёт показывает semantic/evidence validity и end-to-end yield среди всех собранных samples.
3. Каждый принятый code evidence автоматически проверен по snapshot и показанному chunk. Это подтверждает корректность ссылки; смысловая поддержка claim проверяется отдельно человеком.
4. Проверки исключают reaction leakage, будущий код и подмену исторической версии текущей; недоступные данные явно учитываются.
5. Возобновление после interruption не создаёт скрытых дублей. Limits и path isolation проверены на fixtures.
6. На слепо размеченном пилоте измерены переходы local → agent, beneficial и harmful revisions, abstention, uncertainty и затраты. Нулевой или отрицательный эффект — допустимый исследовательский результат.
7. Есть минимальный fixture package, инструкция запуска Windows/Linux и описание трёх адаптеров для GitLab/Nessy/рабочей модели.

## Решения перед production

Подтверждены шкалы severity/complexity, ordinal heads и вход student. Неизвестны исходные judge-prompts с определением complexity и границами классов, контракт Nessy, production latency budget и определение accept/apply в рабочих логах. MVP сохраняет рабочие значения шкал и использует переносимый runner; временная рубрика отделена от исходной рабочей.

Student видит comment, snippet и generator rationale, но не весь репозиторий. Расширенный teacher может дать более верный label, однако student всё равно не получит отсутствующие знания. Rationale иногда передаёт контекстные предположения генератора, но не заменяет проверенное evidence. Нужно сравнить обучение на прежнем входе, экспорт разрешённых context features и abstention/context routing. Distillation не устраняет нехватку информации автоматически.
