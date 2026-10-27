# Перенос рабочего прототипа

Для текущего detector сохранить [независимый human-аудит](17-ambiguity-human-audit.md): H для отбора и reference контекстной зависимости — разные записи. Offline packets/scorer не требуют Pi, GitHub API или model endpoint. GitHub connector capture можно импортировать `scripts/import_public_capture.py <capture.json> --data <новая-папка> --bot <bot-login>`: нужны явные public metadata и ограниченные API pages, сетевой budget равен нулю.

Перед переносом прочитать [уточнённый протокол от 27 октября](15-context-dependence.md). Нужны независимые L по comment+snippet и R через free planning по репозиторию, сопоставление с H, затем целевая проверка кандидатов H=R≠L. Текущий общий assessment contract и tools — инфраструктура; целевой pipeline уже реализован в ambiguity.py; [его контракт и запуск](16-ambiguity-runbook.md). Рабочие severity/complexity-, reaction/acceptance-классификаторы, метаранкер и post-processing уже существуют и не заменяются прототипом.

Начать с README, runbook и `schemas/assessment.schema.json`. Скопировать исходники, schemas, prompts, tests, примеры и lockfiles. `data/`, `runs/`, `.venv`, `node_modules`, ключи и локальные конфиги не нужны в исходном пакете. GitHub данные остаются публичным экспериментом, а не рабочими labels.

## Границы адаптеров

Для нового протокола точка координации — `src/aicr/ambiguity.py`, а transport boundary — `src/aicr/pi_runtime.py:execute_pi`. Corporate runner должен принимать тот же blinded job (task, context, schema, snapshot, limits), возвращать assessment и canonical shown_chunks, statuses/usage/trace и выполнять каждый E/L/R/V/control в отдельной сессии. Не переносить в L автоматический repo crawling, AGENTS discovery или общую память предыдущих проходов. H и scores рабочего ранкера остаются в post-hoc хранилище.

Новые model contracts — `schemas/ambiguity-claim.schema.json`, `ambiguity-assessment.schema.json`, `ambiguity-verification.schema.json`. Нормализованный человеческий endorsement имеет отдельную `ambiguity-human.schema.json`; thumb proxy должен оставаться помеченным proxy. В `execute_pi` итоговый event содержит status, assessment, shown_chunks, requests, tool_calls, generated_tokens и format_repair; Python проверяет schema, источники и cross-field rules. Это описание нашего boundary, а не выдуманные методы Nessy. Fixtures для нового пути — `tests/test_ambiguity.py` и `tests/test_ambiguity_pi.py`.

| Интерфейс | Вход → выход | Что заменить |
| --- | --- | --- |
| Source | Seed PR → sample + отдельный signal + capture audit | `github.py`: GitLab MR notes/discussions, bot identity, diff refs, award reactions |
| Snapshot | Repository + original SHA → immutable text blobs | `snapshots.py`: исторические GitLab blobs/archive; проверка diff anchor обязательна |
| Runner | Blinded context + read-only snapshot + schema + budgets → candidate + trace + status | `worker/main.ts`: Nessy SDK/CLI, если он поддерживает нужные ограничения |
| Model | Model settings + secret env reference → completions/tools/usage | Конфиг provider; `/models`, native tool calls, SSE, JSON и abort проверить заново |

Названия Nessy методов здесь намеренно не выдуманы: нужен реальный контракт рабочего runtime. Его адаптер должен проходить тот же fixture suite, включая отказ endpoint, malformed JSON, budget, timeout и невозможность прочесть путь вне snapshot.

Стабильные записи описаны в `schemas/records.schema.json`; успешный assessment имеет отдельную строгую схему. Все evidence обязаны ссылаться на действительно показанный chunk, точный commit/path/диапазон и точную цитату. `validate_assessment` проверяет происхождение и межполевую согласованность, **не истинность смысла**.

Для model output используй `schemas/judge-response.schema.json`, затем `materialize.compile_response`. Модель выбирает anchors и relation внутри claim; deterministic compiler создаёт canonical assessment с точными цитатами и IDs. Сохраняй raw и compiled outputs раздельно. Не подменяй этим semantic verification и не исправляй verdict модели при компиляции. Human annotations по-прежнему используют полную assessment schema.

## Что сохранить при адаптации

1. Собрать body history и diff refs до model run. Если версия body на t0 неизвестна, отметить current_only; не подставлять нынешний main.
2. Изолировать user signals, исходные judge labels и поздние replies от независимого teacher. `build_context` строит allowlist, а не удаляет отдельные известные запрещённые ключи.
3. Оставить unknown и preference самостоятельными состояниями. Нет реакции ≠ отрицательная реакция. Несогласие teacher с пользователем ≠ доказанная ошибка пользователя.
4. Сохранить шкалы severity `nit/minor/serious/critical`, complexity `1..5`. Заменить временную complexity-рубрику реальным рабочим judge prompt и повысить rubric version.
5. Сохранять исходный generator rationale отдельно, с provenance. Это гипотеза генератора, не доказательство.
6. Failures не экспортировать как отрицательные labels. Новая попытка не должна перезаписывать предыдущую; run identity зависит от данных, snapshot hashes, исходников, prompt/schema/config и deployment metadata.

## Ограничения изоляции

В Pi отключены builtin shell/edit/read, extensions, skills, AGENTS и автообнаружение конфигурации репозитория. Доступны только `list_paths`, `read_lines`, `search_text`, `read_diff`; они работают с in-memory snapshot. Чужие инструкции внутри кода и комментариев считаются данными.

Это ограничение возможностей агента, не полноценная OS sandbox. Процесс Node технически работает от пользователя и получает credential модели через environment. Для работы с внутренними данными добавить OS/container isolation, ограничения egress и правила логирования по требованиям организации. Не давать Nessy общую shell-команду в качестве замены этих четырёх tools.

## Следующий эксперимент

Сначала независимая ручная оценка и новый holdout по PR/репозиториям. Основной GitHub capture смещён к CodeRabbit и не содержит наблюдаемых human thumbs. [Отдельная проверка Sourcery](11-reaction-probe.md) содержит 2 human likes и показывает необходимость исключать self/bot reactions. Этих данных недостаточно для noise rate, accept rate или uplift рабочей reaction-head. Статический baseline пока является расширенным окном одного файла.

Student получает comment + snippet + rationale. Если teacher нашёл решающее условие в другом модуле, это не гарантирует, что student сможет выучить его из прежнего входа. После ручного аудита сравнить контекстные признаки, router/abstention и контролируемую distillation; LoRA training и production ranking находятся за пределами текущего прототипа.

Нормализация текста пока удаляет только часть bot metadata. В 5 из 40 smoke comments остаются встроенные `[P2]/[P3]`; такой вход не подходит для независимого теста severity. Перед следующим capture расширить версионируемую нормализацию и проверить её отдельно, сохранив raw body. Не переписывать старый capture или frozen run. [Десять диагностических случаев](10-smoke-cases.md) показывают также ошибки spans, ограничения publish-правила и разницу между источником evidence и доказательством смысла.

## Небольшие задачи для следующего агента

1. **Ссылки на evidence.** Нумерованный display, отдельные canonical chunks и учёт объёма отображения реализованы в [итерации укрепления](14-hardening.md). Применять её результаты с учётом версии response contract: выбор subrange и ссылка на целый chunk имеют разную сложность. Проверка происхождения цитаты не проверяет, подтверждает ли она утверждение.
2. **Существенность claims и action.** Prompt теперь согласован с validator: publish требует все factual claims supported. Материальность отдельных утверждений ещё не размечена. Если нужна новая taxonomy существенности, сначала подготовить размеченные человеком примеры и проверки publish/rewrite/request_context; не ослаблять правило ради yield и не переписывать старые assessments.
3. **Внешние зависимости и время.** [Пример checkout v6](12-reaction-followup.md) требует сведений о внешнем релизе на дату комментария. Timestamp и body-history status уже включены в `blinded-context-0.2`. Для внешнего retrieval нужны разрешённые источники, temporal cutoff и отдельный evidence contract. До этого unresolved external fact должен оставаться неопределённым; отсутствие версии в snapshot не является доказательством её отсутствия в мире. Инструменты теперь помогают отличать неверный путь от пустого поиска, но агент всё ещё должен прочитать существующий файл, прежде чем ссылаться на его содержание.
4. **Реакции и ручная проверка.** Использовать `triage` после независимой оценки. Расхождение teacher/user не преобразовывать в исправленный target. Новая выборка должна содержать достаточно human positive/negative, известный observation horizon и отдельный holdout. Capture-ы Sourcery целенаправленно выбраны по реакциям и не дают population noise rate.

Каждую задачу выполнять отдельным изменением с подходящими fixtures и новым run identity при изменении model input/runtime. Для первого рабочего переноса важнее сохранить исходный контракт и пройти те же инженерные проверки, чем одновременно менять taxonomy, runtime и стратегию обучения.
