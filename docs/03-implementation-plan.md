# План реализации и переноса прототипа

Уточнение от 27 октября: следующий этап реализуется по [протоколу L/R/H и проверки ambiguity](15-context-dependence.md). Техническая готовность прежних этапов P0–P7 не означает готовность целевого детектора. Новая основная задача — отбор H=R≠L и проверка контекстной причины расхождения.

Версия 0.1 от 21 октября 2026 года. Исходный план сохранён как критерии эксперимента; пользователь затем разрешил реализацию прототипа. Фактический прогресс и оставшиеся требования — в [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md), рабочие команды — в [runbook](06-runbook.md). Обучение и рабочая интеграция выделены в P8–P10, поскольку зависят от измеренных данных и качества аннотации.

## Порядок и результаты

| Этап | Зависит от | Результат | Условие завершения |
| --- | --- | --- | --- |
| P0 Preflight | Спецификация | Проверка среды, endpoint и возможностей модели | Сохранён manifest; локальный mock позволяет работать без endpoint |
| P1 Контракты | P0 | Record schemas, semantic validator, fixtures | Валидные/невалидные случаи различаются, исходные сигналы изолированы |
| P2 Discovery и collector | P1 | Реальные GitHub samples и audit доступности | Измерен yield, полная пагинация и происхождение каждого sample |
| P3 Snapshots и tools | P1, P2 | Исторические blobs, context bundles, read-only tools | Exact/partial/unavailable различаются; нет подстановки текущего кода |
| P4 PiRunner | P0, P1, P3 | Pi SDK worker, local/static/agent, очередь, budgets, traces | Fixture suite и resume проходят, limit failures не становятся labels |
| P5 Smoke | P4 | 40 реальных samples × 3 режима | JSON validity ≥95% отдельно для local/agent; evidence и ошибки измерены |
| P6 Пилот | P5 | Слепые human labels и 240 samples, если доступны | Dev/test разделены; uncertainty и разногласия сохранены |
| P7 Оценка и пакет переноса | P6 | Воспроизводимые метрики и адаптерные контракты | Выводы следуют из human reference, нет необоснованного relabeling |
| P8 Student baselines | P7 и достаточные labels | Отдельные модели и controlled ablations | Один split/input budget, независимый test, task masks |
| P9 GitLab и Nessy | Рабочий доступ, P7 | Адаптация трёх интерфейсов | Тот же fixture suite и малый рабочий smoke |
| P10 Ranking и online | P8, P9 | Shadow policy и протокол эксперимента | Пользовательские outcomes и coverage определены в рабочих логах |

## P0 Preflight

Создать пакет, CLI entry point и конфиги с environment references для секретов. Проверить Python/Git/Node.js, доступ к GitHub, свободное место и версии runtime. Установить Pi SDK локально в проект с зафиксированной версией и lockfile, без изменения глобальной настройки пользовательского агента. GPU/VRAM нужно измерять перед локальным обучением; обслуживаемый по сети inference endpoint не требует угадывать возможности GPU десктопа.

Для модели проверить `/models`, фактический model ID, минимальный chat request, native tool calling, streaming, итоговый JSON, stop/timeout и usage fields через Pi. Default — `qwen3.8-flash-next-mirai-s`. На этапе планирования был проверен direct API roundtrip; при реализации затем проверены Pi SDK, SSE и failure fixtures — см. текущий статус. Не менять сервер модели и не запускать новый deployment без отдельной необходимости. Если endpoint недоступен, реализовать интерфейсы и интеграционные fixtures на deterministic mock, но реальный model smoke остаётся незавершённым.

Готово, когда doctor выдаёт машинный manifest без secrets и различает network failure, auth failure, model mismatch и отсутствие опциональной capability.

## P1 Контракты и защита данных

Использовать существующий assessment.schema.json как исходный контракт; дополнить схемами sample, snapshot, signal, manifest и run_attempt из описания. Реализовать межполевые и evidence проверки отдельно от JSON Schema. Версии фиксировать в каждом export.

Fixtures должны покрывать: supported/refuted/unverifiable/preference, mixed claims, отсутствие/конфликт reactions, реакцию на summary с несколькими рекомендациями, edited body, deleted ref, неизвестного автора реакции, future reply и дубликаты. Синтетический пример должен явно оставаться синтетическим во всех отчётах.

Готово, когда запрещённые поля не попадают в blinded context даже при наличии их в raw JSON; invalid evidence отклоняется; неизвестные targets маскируются, а не получают отрицательный класс.

## P2 Discovery и сбор

Начать с маленького discovery manifest: до 20 публичных репозиториев, до 100 PR на репозиторий, до 2 000 HTTP requests и двух часов на первый проход; остановка по любому пределу. Квоты — конфигурация. При 403/429 использовать rate-limit headers и ограниченный backoff, не обходить ограничения.

Поиск по bot accounts даёт кандидатов; наличие конкретных review-комментариев подтверждается collector. Собирать bot identity, object type и raw body, отделять substantive findings от summary/status/help. Для первого smoke предпочесть inline remarks с воспроизводимым anchor. Не выбирать весь корпус по числу реакций на PR.

Пагинация нужна для PR, review comments, issue comments, reactions и files. Сохранять ETag/response metadata, partial-page failures и capture timestamp. GitHub token имеет только необходимый read scope; публичный endpoint разрешено использовать без token в доступных лимитах. Нельзя брать неизвестные локальные credentials из других приложений.

Audit должен показать фактические counts по repo/bot/language, object kind, `+1/-1/other/no_observed_reaction`, human/bot reactor, temporal eligibility и snapshot availability. Dedup до split по parent/claim clusters.

Решение по данным: если найдено меньше 40 пригодных комментариев с human `+1/-1` хотя бы из трёх репозиториев, reaction часть считается демонстрацией pipeline. Расширить discovery в пределах нового явного бюджета или продолжить factual/context пилот; не заявлять обучение надёжной reaction модели. 40 — диагностический порог разнообразия, не достаточный объём для статистического вывода.

## P3 Исторические snapshots

Доверенный fetcher получает exact blobs и проверяет соответствие hunk/anchor; нельзя checkout с выполнением hooks, submodules или dependency scripts. Нормализовать кодировку/переводы строк с сохранением исходного checksum и однозначной нумерации строк.

Создать local bundle и immutable chunk store. Agent tools возвращают только chunks из manifest, ограниченные по размеру. Symlink/reparse/path traversal fixtures обязательны. Проверить deletion/rename/LEFT-side comments, multiline remarks, inaccessible base и force-push.

Готово, когда любой evidence можно открыть по его snapshot и строкам; отсутствие версии приводит к явному статусу, а не к правдоподобному ответу на другом коде.

## P4 Runner и бюджеты

Реализовать PiRunner: небольшой TypeScript SDK worker, независимая сессия на sample/mode, custom snapshot tools, event normalization, validator и persist/resume. Model transport и agent loop брать из Pi, не дублировать в Python. Python отвечает за dataset jobs, snapshots, внешний wall timeout и метрики. Отключить auto-loaded resources и лишние инструменты, явно зафиксировать retry/compaction behavior. Запустить сначала mock/fixtures, затем реальную модель. Уменьшить concurrency/context при необходимости по результатам preflight, записав новую конфигурацию.

Проверить cancellation, timeout во время tool/model call, invalid action, повторяющиеся бесполезные поиски, output truncation, retryable error, format repair и исчерпание общего бюджета. Agent умеет завершить успешный содержательный abstention; harness умеет сохранить техническую неудачу без assessment.

Готово, когда независимые повторные попытки различимы, одна успешная запись не запускается заново при resume, а trace объясняет каждый принятый evidence anchor.

## P5 Технический smoke

Выбрать 40 samples из нескольких PR/репозиториев с вариативным контекстом и статусами. Выполнить local/static/agent. Все samples одинаковы между режимами; недоступность запуска не удаляется молча из знаменателя.

Отдельно измерить schema validity, semantic validity, evidence validity, substantive abstention, technical failure, latency p50/p95, tokens/calls per sample и фактическую скорость обработки. Посмотреть вручную все ошибки и небольшую случайную часть успешных traces.

95% JSON validity — исходный технический критерий эпика. Он не является оценкой правильности teacher. Улучшение модели/промпта после smoke разрешено до фиксации pilot prompts.

## P6 Пилот и ручная разметка

Цель по объёму — 240 samples: 120 из probability sample подтверждённого collector frame и 120 диагностических примеров. В диагностическую часть входят rare negative reactions, mixed signals, репозиторные зависимости, unclear requirements и сложные claims. Описание sample frame обязательно; 120 случайных примеров из выбранных репозиториев не представляют весь GitHub.

80 samples используются для development рубрики/prompts; 160 откладываются для locked audit. Назначение происходит по PR groups до анализа ответов; при пересечении claims/clone families соблюдается группировка. Оба блока сохраняют provenance natural/enriched. При меньшем объёме сохранить принципы, уменьшить claims о достоверности и указать реальные counts.

Для оценки качества нужны человеческие labels. Желательны два независимых аннотатора на locked audit. Если доступен один человек, результат называется single-annotator pilot; повторная разметка через интервал показывает стабильность, но не межэкспертную согласованность. Сам LLM не становится вторым независимым человеком.

Человек сначала оценивает факт без reactions и teacher verdict. Для оценки достаточности local-контекста нужна отдельная слепая local-проверка; нельзя сначала показать этому же аннотатору полный репозиторий, а затем считать local label независимым. После фиксации factual annotation можно раскрыть reactions для исследования причин расхождений.

На небольшом поднаборе выполнить повторные model runs для оценки стабильности. Это диагностический эксперимент, не голосование за ground truth.

## P7 Оценка и переносимый пакет

Выпустить JSON/CSV метрики, краткое Markdown заключение и набор 10–20 разобранных случаев с anchors: контекст помог, навредил, не помог, обнаружил preference или внешнее требование. HTML не требуется.

Пакет для рабочего агента: конфиги без secrets, schemas, frozen prompts, fixtures, интерфейсы адаптеров, инструкция запуска и список известных ограничений. Для GitLab требуется явный mapping notes/discussions/award reactions/diff refs; для Nessy — отображение tool budgets, run status, traces и structured output. Нельзя угадать интерфейс закрытого Nessy CLI.

Готово, когда другой агент способен выполнить offline fixtures и описать, что нужно заменить для рабочего окружения, без переноса публичных реакций в рабочую taxonomy как эквивалентных.

## P8 Обучение и абляции

После аудита выбрать доступный embedding backbone; текущие рабочие LoRA/checkpoints не считаются доступными на личном десктопе. До больших LoRA экспериментов сравнить простые heads на frozen embeddings и отдельные tasks с masks. Severity и complexity сохраняют ordinal постановку с четырьмя и пятью уровнями соответственно. Рабочий baseline input — comment + snippet + generator rationale; неизвестный rationale остаётся null, missingness отражается в срезах.

Сравнения: raw signals; audited subset; teacher labels с проверкой evidence; context features; с/без generator rationale; отдельные vs multitask heads; abstention/router. Архитектура, train budget и search space фиксируются до test. Использовать те же splits и разрешённые на inference inputs. Сравнение с/без rationale проводится на одних и тех же available-rationale examples, а unavailable cohort показывается отдельно. Не переносить все уверенные teacher disagreement examples в противоположный reaction класс.

При недостатке human labels честный результат — проверенный data/agent pipeline и learning curves с большим uncertainty, а не утверждение об улучшении рабочей модели.

Active learning запускается только в train/dev pool, после первой проверки teacher. Стартовая квота на batch: 30% случайных примеров, 25% высокой неопределённости, 25% расхождений local/agent/student и 20% недопредставленных repo/language/aspect slices. Это конфиг, который можно менять по dev-результатам. Ограничить долю одного PR/repo и кластеров дублей; сохранять selection reason и вероятность включения, где она определима. Не подбирать только teacher-user conflicts. Locked test не используется для отбора, изменения рубрики или prompt. Сохранение uncertain examples не требует насильно превращать их в hard labels или равномерные soft labels.

## P9 и P10 Рабочая интеграция

Сначала read-only shadow на рабочих MR с историческими snapshots. Работа с внутренними репозиториями происходит в рабочем окружении; наличие локального прототипа не предполагает перенос туда/обратно закрытых данных.

Ranking policy сначала использует разрешённые признаки student и откалиброванные вероятности. Quality gate отбрасывает подтверждённо ошибочные замечания; неизвестные идут в context/review путь в пределах бюджета. Внутри MR сравнивается top-k при одинаковом publish budget, с сохранением дедупликации. Весовые суммы выбираются на dev, а не придумываются как окончательное решение.

Online протокол: единица рандомизации MR либо проект/команда при сильном переносе поведения; стратификация по проекту; одинаковый бюджет публикаций; заранее заданные observation window и правила accept/apply. Метрики: human positive/negative reaction rates, explicit acceptance, observed application, comments/MR и MR coverage. Жалобы/негативные реакции и latency — guardrails. Power analysis нужен по рабочим baseline rates; пилот не задаёт произвольный размер online эксперимента. Запуск эксперимента — отдельное рабочее решение.

## Соответствие исходным задачам

| Исходная задача | В прототипе | Уточнение |
| --- | --- | --- |
| 1 Batch harness Nessy | P0, P3–P5 | Локально переносимый runner; Nessy adapter в P9 |
| 2 Taxonomy и schema | Текущая спецификация, P1, P6 | Контракт и правила раньше массовой разметки |
| 3 Аудит данных | P2, P6, P7 | Начинается до большого model run и охватывает provenance/leakage |
| Остальной эпик | P8–P10 | Обучение и online после подтверждения качества данных |

## Инструкция агенту следующей задачи

Прочитай README и пять документов specs, включая решение по Pi SDK. Реализуй P0–P7 последовательно, начиная с контрактов, mock и маленького discovery. Используй JSON Schema и semantic invariants как контракт. Веди короткий implementation status с выполненными acceptance criteria. Не добавляй продуктовые функции сверх MVP. При нехватке реальных данных или endpoint не имитируй завершённый эксперимент; продолжай независимые инженерные задачи и укажи оставшиеся ограничения. Не публикуй комментарии, не меняй модельный сервер и не обучай новые LoRA до отдельного перехода к P8.
