# Запуск прототипа

Проверенная среда: Windows, Node 24.18.0, Python 3.13.0, Pi SDK `@earendil-works/pi-coding-agent` 1.3.0. Python управляет данными и очередью; агентский цикл, native tool calls и SSE выполняет Pi. Модель — сетевой deployment пользователя, не модель Codex.

## Установка

Из корня проекта на новой машине:

```powershell
if (-not (Test-Path configs/default.json)) {
    Copy-Item configs/default.example.json configs/default.json
}
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci --ignore-scripts --no-audit --no-fund
```

На текущем десктопе `ensurepip` в базовом Python не сработал; окружение создано с `--without-pip --system-site-packages` и использует уже установленные зависимости. Это ограничение текущей установки, не обязательная настройка проекта. requirements.txt фиксирует фактически проверенные версии.

На Linux создать venv тем же способом; команды Python запускать как `PYTHONPATH=src .venv/bin/python -m aicr ...`. Node worker использует встроенное выполнение TypeScript, отдельная сборка не нужна.

При клонировании на Linux сначала выполнить `cp configs/default.example.json configs/default.json`, если рабочего конфига ещё нет. В portable ZIP файл default.json уже подготовлен. Шаблон не содержит LAN-адреса и пути к пользовательскому ключу; рабочие configs/default.json и *.local.json игнорируются Git.

## Подключение модели

В рабочей копии `configs/default.json` содержит LAN URL, exact model ID, лимиты и seed PR. В portable ZIP URL заменён на localhost, model ID — на SET_MODEL_ID, путь к ключу очищен: подключение нужно настроить заново. Ключ берётся из `MB_JUDGE_API_KEY`, иначе из указанного пользовательского файла. Не вставлять ключ в JSON. Для другой машины сделать игнорируемый `configs/workstation.local.json` и изменить URL, ID и путь к ключу. Глобальные аргументы идут **перед** подкомандой:

```powershell
.\aicr.ps1 --config configs/workstation.local.json doctor
```

Doctor проверяет `/models` и сохраняет metadata без ключа. Сервер не сообщает криптографический fingerprint весов; model ID не доказывает неизменность весов. Контекст 32768 в конфиге — консервативный бюджет клиента, а не измеренная ёмкость модели. Новые настройки или исходники дают новый run ID.

Pi 1.3.0 дополнительно ограничивает max_tokens доступным клиентским контекстом с резервом 4096. Поэтому фактически отправленный лимит может быть ниже настроенных 8192; смотреть события request_payload. На этом десктопе отдельно проверен `configs/context64k.local.json`: окно клиента 65536 при объявленном сервером 131072, два диагностических cases прошли без repair. Этот локальный профиль исключён из portable ZIP. Для другого deployment сначала проверить его реальную конфигурацию; не переносить числовой лимит автоматически. Запуск профиля: `./aicr.ps1 --config configs/context64k.local.json run --name context64k --limit 3 --modes agent`.

Reasoning задаётся явно через `chat_template_kwargs.enable_thinking`. Проверка показала, что клиентский `thinkingLevel=off` в Pi сам по себе не отключает reasoning этого сервера. В default config reasoning включён, output limit увеличен до 8192. Отключение ускорило synthetic local, но synthetic agent стал многократно вызывать инструменты и исчерпал бюджет; поэтому отключённый режим не выбран по одному показателю скорости. В traces сохраняется только число reasoning-символов, не внутренний текст рассуждений.

## Данные и прогон

Сначала проверить небольшой run и его failures. Полный smoke запускается отдельно: `./aicr.ps1 run --name smoke-v1 --limit 40 --modes local static agent`. Перед повтором существующего корпуса проверить manifest и queue; не пересоздавать capture ради продолжения незавершённого прогона.

```powershell
.\aicr.ps1 doctor
.\aicr.ps1 collect
.\aicr.ps1 snapshot --max-snapshots 30
.\aicr.ps1 validate
.\aicr.ps1 run --name first-three --limit 3 --modes local agent
.\aicr.ps1 evaluate runs/<run-id>
.\.venv\Scripts\python.exe scripts/audit_run.py runs/<run-id>
.\aicr.ps1 export-human --limit 240
```

`collect` читает только публичные PR из явного seed list. GitHub token опционален через `GITHUB_TOKEN`; без него API ограничивает число запросов. Кеш API лежит в `data/raw/github`. Текущая версия не обновляет существующий кеш автоматически: это фиксированный capture, а не мониторинг реакций. Для нового capture задать новый `--data data/capture-2`. Повторный collect заново нормализует samples; после него повторить snapshot.

В v0.1 collector поддерживает **inline review comments**, top-level сообщения выбранных bot accounts. Review summaries, issue comments, replies и explicit accept/apply пока не нормализуются. Их реакции нельзя автоматически приписывать отдельным замечаниям. Корпус smoke найден до run вручную через поиск публичных PR. Для последующих captures есть CLI:

```powershell
.\aicr.ps1 --data data/capture-2 discover --query '"coderabbitai" is:merged' --limit 20
.\aicr.ps1 --data data/capture-2 collect --discovery data/capture-2/manifests/discovery.json
```

Discovery выдаёт кандидатов, не подтверждение наличия inline bots или reactions. Это bounded search со смещением отбора, не случайная выборка GitHub. Реальный короткий запрос discovery прошёл; его capture отделён от smoke.

`snapshot` скачивает архив по exact `original_commit_id`, читает текстовые файлы в память и сохраняет их в JSON. Архив не распаковывается в исполняемый checkout, чужой код не запускается. RIGHT-side строки исходного diff проверяются по blob; LEFT-side и несовпадения явно исключаются. При лимите файлов/размера snapshot становится partial. Проверяемость утверждения об отсутствии чего-либо при partial snapshot ограничена.

`--strict` допускает только samples с неизменённым текстом комментария и проверенным историческим anchor. Остальные пригодны для инженерной проверки, но не для строгой ретроспективной оценки. Большинство CodeRabbit comments редактировались, и GitHub API не возвращает прежний body.

Режимы:

| Режим | Контекст |
| --- | --- |
| local | Comment, доступный generator rationale и окно ±12 строк вокруг anchor |
| static | Окно ±70 строк того же файла; без динамического поиска |
| agent | То же начальное окно, затем инструменты Pi по историческому snapshot |

На публичных данных generator rationale неизвестен и остаётся null. Static — простой baseline расширенного окна; импорты и тесты заранее к нему не добавляются. Это явно ограниченная версия предложенного статического retrieval.

## Продолжение и диагностика

Повторить ту же run-команду с теми же данными/кодом/настройками: завершённые задания будут пропущены. Для явного повтора завершённых failures добавить `--retry-failed`; новая попытка сохраняется отдельно. В новой версии оставшийся после обрыва статус running обрабатывается отдельно: если result.json уже атомарно записан, очередь восстанавливает его статус без генерации; если результата нет, создаётся следующая attempt. Прежние frozen bundles сохраняют прежнюю логику и для running могут требовать `--retry-failed`.

Одновременно разрешён один координатор очереди; OS lock снимается и при аварийном завершении процесса. Внутри run сохраняется `execution/` с исходниками, prompts и schemas; Node worker выполняется из этой копии. Изменение исходного дерева во время уже запущенной очереди не меняет её worker. Для следующего эксперимента после правки Python запускать свежий CLI-процесс, чтобы manifest не описывал новую версию файлов при старых импортированных модулях. Изменение snapshot между задачами приводит к явному отказу.

`evaluate` и offline audit используют последнюю завершённую attempt для пары sample/mode. При ручных retries исходные attempts остаются на диске, но последний success может заменить failure в сводке. Поэтому число повторов и first-attempt yield нужно учитывать отдельно при таком эксперименте. В основном frozen smoke все пары выполняются одной внешней attempt; разрешён только один внутренний format repair.

Для каждой попытки: `input.json`, `trace.jsonl`, `shown-chunks.json`, `raw-candidate.json`, `candidate.json`, `result.json`, а при успешной валидации — `assessment.json`. Trace записывается после завершения или внешнего timeout, поэтому во время одного запроса файл может ещё отсутствовать. Публикаций комментариев и изменений репозитория нет.

Внутренний model response contract отделён от итогового assessment v0.1. Конфиг `response_contract` выбирает `compact-0.2.1` (показанный source_chunk_id, relation и опциональный subrange) либо `compact-0.3.0` (только source_chunk_id и relation, цитата целого показанного chunk). Для каждого варианта сохраняются свой prompt и schema. Неподдержанный контракт вызывает отказ. Subrange в 0.3.0 является schema error, а не молча удаляемым полем.

Harness присваивает служебные IDs, копирует точные цитаты из snapshot и вычисляет общий correctness по заранее заданной таблице агрегации. Verdict каждого claim, severity, utility и uncertainty остаются модельными; компилятор их не исправляет. Неизвестный chunk или диапазон вне показанного фрагмента приводит к отказу. Повторное использование одного фрагмента разными claims допустимо и не требует от модели дублировать идентификаторы. У preference evidence_links можно опустить; это означает пустой список. Для factual claims поле обязательно.

Вход `blinded-context-0.2` содержит дату комментария и статус истории его текста. Модель получает numbered_excerpt, но canonical цитаты и chunk IDs не содержат добавленных номеров. `input.json` сохраняет canonical вход; точное display-преобразование находится в frozen worker. `request_payload` в новых traces содержит только метаданные фактического запроса: max_tokens, размер сообщений и число tools. Эти показатели помогают разбирать обрывы, но char count не является числом tokens.

Причина изменения: диагностический полный JSON-контракт заставлял модель переписывать код и согласовывать повторные IDs; он дал ошибочные цитаты и cross-claim ссылки. Raw response и canonical record сохраняются раздельно. `raw_schema_valid` измеряет формат ответа модели, `schema_valid` — формат итоговой записи. Canonical evidence validity подтверждает выбранный источник и точность подставленной цитаты, а не смысловую поддержку claim. Эти показатели нельзя напрямую сравнивать с прежним процентом точного переписывания цитат моделью.

Если рабочие исходники уже изменились, старую очередь можно продолжить на сохранённом Python/TypeScript bundle:

```powershell
.\.venv\Scripts\python.exe scripts/resume_frozen.py runs/<run-id> --dry-run
.\.venv\Scripts\python.exe scripts/resume_frozen.py runs/<run-id> --retry-failed
```

Dry-run проверяет hashes и читает queue без model requests. Resume требует прежнего capture и deployment metadata; при изменении отказывается от старого run. Запускать после остановки другого координатора. Snapshot и source integrity проверены на настоящем smoke bundle; логика skip/retry дополнительно покрыта fixtures.

Статусы `json_invalid`, `semantic_invalid`, `evidence_invalid`, `budget_exhausted`, `timeout`, `endpoint_error` не превращаются в labels. Один format repair допустим для неразбираемого JSON или нарушения JSON Schema; worker проверяет схему через AJV до завершения Pi session. Модели предлагается сохранить judgments и исправить только структуру. Межполевые semantic failures и неизвестные источники не отправляются на repair. Все ответы до и после repair остаются в trace.

`scripts/audit_run.py` работает без сети и генераций. Он сохраняет `attempt-summary.csv` и `diagnostics.json` со списком отказов и сравнением выбранных полей до/после format repair. Сравниваются только доступные с обеих сторон поля; неразбираемый исходный JSON остаётся непроверяемой парой. Отсутствие изменений этих полей не доказывает смысловую эквивалентность всего текста. Скрипт не меняет assessments.

Latency p50 — медиана, p95 — nearest-rank: элемент с номером `ceil(0.95 × n)` в отсортированных временах завершённых попыток, включая failures. Незавершённые попытки не имеют измеренного времени; их число видно в planned/completed. Доля валидных outputs использует полный planned denominator.

`./aicr.ps1 triage runs/<run-id> --mode agent` строит offline список для ручного аудита реакций. Он сохраняет исходные signals, допускает только успешные assessments, явно отмечает missing context и наблюдаемые расхождения. Расхождение не является corrected label. Подробности и порядок раскрытия — в [протоколе ручного аудита](08-human-audit.md).

`./aicr.ps1 compare runs/<baseline> runs/<candidate> --mode agent` сохраняет comparison-agent.json и COMPARISON-agent.md в candidate run. Сравниваются только общие samples с неизменными hashes capture/snapshot; pending не засчитываются как успехи или регрессии. Выборка прежних ошибок является development regression set, а не независимым holdout. Это offline-команда без запросов модели.

Бюджеты в default config: 8 запросов модели, 16 выполненных tool calls, 600 s на agent, 180 s на local/static, 20k generated tokens, до 8192 tokens на ответ, ограничение исходного текста и размера tool output. Перед последними запросами tool phase закрывается; агенту предлагается дать финал с явной неопределённостью по нерешённым условиям. Расход входа ограничивается символами, а не точным tokenizer; при переполнении контекста provider error остаётся техническим отказом. Token usage берётся у backend. Денежная стоимость и энергопотребление локальной модели не измерены; нулевые SDK cost placeholders нельзя читать как нулевую цену вычислений.

## Проверки

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q --basetemp .cache/pytest
npm.cmd run typecheck
npm.cmd run test:worker
```

Pi integration fixtures поднимают loopback HTTP mock на случайном порту и выполняют настоящий SDK. Интернет, GitHub и Qwen этим тестам не нужны, но среда должна разрешать localhost-соединения. В Codex sandbox они блокировались; тесты прошли в разрешённом процессе. Для нового реального endpoint:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/probe_pi.py
```

Probe синтетический и хранится отдельно от публичного корпуса. Его корректный ответ проверяет работу механизма, но не измеряет качество модели на review comments.
