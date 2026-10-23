# Результаты инженерного прототипа

Этот отчёт фиксирует исходный завершённый smoke. Последующая инженерная итерация с новым отображением контекста и контрактом evidence описана отдельно в [14-hardening.md](14-hardening.md); прежние результаты не заменяются новыми.

22 октября 2026. Реализован переносимый прототип на Pi SDK 1.3.0 и локальной `qwen3.8-flash-next-mirai-s`. Полный основной smoke завершён. **Агентский режим пока не подходит для массовой автоматической переразметки:** только 18 из 40 результатов прошли все проверки контракта. Качество фактических выводов и естественный шум пользовательских реакций не измерены.

## Основной эксперимент

Run: `smoke-compact-e998172b268c`, response contract `compact-0.2.1`. 40 публичных inline review comments, каждый оценён в трёх режимах. Для всех 120 пар sample/mode выполнена одна внешняя попытка; допускается один внутренний format repair локальной моделью.

| Режим | Завершено | Raw schema valid после repair | Принято всеми validators | Межполевой отказ | Evidence отказ | p50 / p95, с |
| --- | --- | --- | --- | --- | --- | --- |
| Local: короткий snippet | 40 | 40 | 39 (97,5%) | 1 | 0 | 46,8 / 65,3 |
| Static: расширенное окно того же файла | 40 | 40 | 36 (90%) | 4 | 0 | 61,6 / 74,8 |
| Agent: поиск и чтение snapshot | 40 | 40 | 18 (45%) | 14 | 8 | 68,2 / 99,4 |

Всего принято 93 из 120 assessments. Нет endpoint errors, timeouts или budget exhaustion. В `agent` canonical schema/evidence прошли 32/40; raw model schema и готовая canonical запись — разные стадии. Размерный/форматный engineering gate (40 samples, ≥95% raw schema validity после разрешённого repair) пройден; он не является порогом качества разметки.

`semantic_valid` в коде означает межполевую согласованность по правилам, **не** истинность вывода. `evidence_valid` проверяет показанный источник, commit/path/строки и точность цитаты, но не доказывает, что цитата логически подтверждает claim. Поэтому 97,5% local нельзя читать как accuracy или доказательство превосходства над agent.

Format repair потребовался в 2 local, 4 static и 6 agent случаях. У 10 из 12 пар исходный и исправленный JSON были доступны для сравнения: выбранные сравниваемые judgments не изменились. Для двух исходный JSON не разбирался. Это не доказательство смысловой эквивалентности всего ответа.

На уровне backend основной прогон сделал 42 local + 44 static + 250 agent запросов генерации, agent выполнил 329 tool calls. Backend сообщил суммарно 673 973 generated tokens. Эти вычисления выполнены локальной Qwen; это не счётчик лимита Codex. Денежная стоимость и энергопотребление не измерялись. SDK cost placeholders равны нулю и не используются как оценка стоимости.

## Какие данные использованы

| Репозиторий / PR | В smoke |
| --- | --- |
| [sveltejs/svelte #18042](https://github.com/sveltejs/svelte/pull/18042) | 8 |
| [OpenCut-app/OpenCut #479](https://github.com/OpenCut-app/OpenCut/pull/479) | 9 |
| [rmems/synthetic-factory #134](https://github.com/rmems/synthetic-factory/pull/134) | 9 |
| [rjmurillo/ai-agents #5078](https://github.com/rjmurillo/ai-agents/pull/5078) | 4 |
| [LAF-US/loganfinney #19](https://github.com/LAF-US/loganfinney/pull/19) | 1 |
| [mokaradag/MERGEN-Bilge #705](https://github.com/mokaradag/MERGEN-Bilge/pull/705) | 9 |

Авторы smoke: CodeRabbit 37, CodeAnt 2, Vercel 1. Основной capture содержит 342 комментария / 6 репозиториев, 19 исторических snapshots; anchors проверены у всех 342. У трёх PR сбор ограничен пагинацией. Это удобная инженерная выборка, а не репрезентативный corpus review-ботов.

У 40 smoke samples: 5 `strict_eligible` по истории body и anchor; 35 `current_only` из-за недоступной истории редактирования комментария. Snapshot exact у 18 и partial у 22. Среди пяти strict samples все проверки прошли у local 5, static 4, agent 2; объём слишком мал для вывода о качестве. В 5/40 текстов остаются `[P2]/[P3]`, поэтому независимая оценка severity на этом входе невозможна. Generator rationale в публичных данных недоступен и остаётся null.

В основном capture и smoke нет наблюдаемых human thumbs. Отдельные [reaction-probe](11-reaction-probe.md) и [reaction-followup](12-reaction-followup.md) суммарно содержат 13 комментариев Sourcery: 3 positive, 2 negative, 8 без наблюдаемой пользовательской thumb-реакции. 26 bot/self events исключены. Human signal здесь операционально означает GitHub actor type=User, не являющийся автором-ботом; это не независимая человеческая экспертиза правильности комментария. Эти captures отобраны целенаправленно и не измеряют распространённость шума.

## Что показал прогон

Основные отказы agent: `publish` при непроверенных factual claims; partially-supported claims без supports evidence; выбранный span вне показанного chunk или на пустой строке. Они сохранены для диагностики, а не превращены в отрицательные training labels. Показ номеров строк и согласованность material claims/action вынесены в [следующие задачи](07-handoff.md).

Для 18 пар с валидными local и agent assessments: 8 сохранили общий verdict, 6 перешли partially_supported → supported, 2 unverifiable → partially_supported, ещё 2 unverifiable → supported. Это наблюдаемые изменения модели на отфильтрованных парах, не доказанное улучшение. Человеческого reference нет, а пары с отказом исключены из этой таблицы переходов. [Первые десять случаев](10-smoke-cases.md) разобраны без отбора по удачности ответа.

Команда `triage` строит post-hoc список для ручного аудита: исходный signal, валидный assessment, missing context и наблюдаемое расхождение. Она не меняет исходные реакции и не выводит намерения пользователя. Failed assessments остаются unavailable. Confidence teacher некалиброван и не используется как training weight.

## Проверка запуска и переноса

Отдельный run `reaction-demo-aa1873b6e430` выполнил ещё 4 оценки двух Sourcery comments с человеческими дизлайками: local 2/2 и agent 2/2 прошли validators без repair. Agent оставил центральный вопрос о существовании checkout v6 непроверенным и выбрал request_context; для теста builtins предложил rewrite. Исходные negative signals не менялись, triage отметил context_unresolved и preference_present.

Однако в объяснении builtins обнаружено смешение глобального `__builtins__` с атрибутом функции. Отдельный probe на CPython 3.13 и [официальная документация](https://docs.python.org/3.13/reference/datamodel.html#function.__builtins__) подтверждают различие. Кроме того, нужный test runner был доступен в snapshot, но агент его не прочитал. Это конкретный пример того, почему `ok` не гарантирует factual quality. Подробности и границы проверки — в [разборе двух дизлайков](12-reaction-followup.md); это assistant diagnosis, не human reference.

В input этих исходных frozen runs timestamp комментария и body-history status не передавались teacher отдельными полями, хотя сохранялись в capture и manifest. В следующей итерации они добавлены в allowlist `blinded-context-0.2`; см. [14-hardening.md](14-hardening.md). Исходные frozen runs не изменялись.

- 41 Python tests прошли, включая 8 сценариев с настоящим Pi SDK и локальным HTTP mock; TypeScript typecheck и 3 теста инструментов прошли.
- Реальный frozen resume после 120 результатов сохранил run identity, пропустил все попытки и выполнил **0 новых оценок**. Предыдущие failures также не перезапущены.
- Источники, prompt, schemas, dependency lock, selected samples и snapshots зафиксированы execution bundle и hashes. Weight fingerprint сервер не предоставляет; имя модели не доказывает неизменность весов.
- Подготовлены 240 основных и 12 дополнительных слепых human packets. Они не заполнены; независимый locked holdout ещё не собран.
- Рабочие данные, LoRA training, production ranking, accept/apply labels и настоящий Nessy/GitLab adapter не входят в завершённый инженерный этап.

Основные артефакты: `runs/smoke-compact-e998172b268c/metrics.json`, `SUMMARY.md`, `diagnostics.json`, `attempt-summary.csv`, `cases.jsonl`, `audit-links-agent.jsonl`; traces и raw/canonical candidates лежат в каталогах attempts. Исходный переносимый ZIP содержит code, schemas, prompts, tests, документацию и lockfiles. Captures, traces, зависимости, venv и ключи остаются вне ZIP. Настройки endpoint/model в ZIP заменены placeholders.

Начать перенос с [README](../README.md), [runbook](06-runbook.md) и [handoff](07-handoff.md). Severity сохраняет `nit/minor/serious/critical`, complexity — `1..5`; точные рабочие judge rubrics нужно перенести отдельно, особенно смысл complexity. Если решающее знание доступно только teacher через repository context, исходный student input `comment + snippet + rationale` сам по себе его не получает.
