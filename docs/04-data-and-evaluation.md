# Открытые данные и протокол оценки

Версия 0.1 от 21 октября 2026 года. GitHub выбран как источник публичных review-комментариев для проверки collector, context retrieval и разметки. Перенос качества на рабочий GitLab остаётся отдельной гипотезой.

## Что подтверждено и что предстоит проверить

GitHub различает inline review comments, issue comments и review submissions. У review comments доступны commit references, diff hunk и original/current coordinates; это основа восстановления контекста, но не гарантия доступности старого blob. [GitHub review comments API](https://docs.github.com/en/rest/pulls/comments).

API реакций имеет отдельные endpoints для issue comments и pull request review comments; возвращает тип реакции, автора и created_at. Это позволяет связывать существующие наблюдаемые reactions с нужным объектом. Наличие endpoint не доказывает достаточный объём human likes/dislikes на bot findings. [GitHub reactions API](https://docs.github.com/en/rest/reactions/reactions).

На этапе планирования search по `commenter:coderabbitai[bot]` дал seeds, включая [sveltejs/svelte PR 18042](https://github.com/sveltejs/svelte/pull/18042) и [vuejs/core PR 12359](https://github.com/vuejs/core/pull/12359); первоначальный connector-запрос завершился transport error. Затем обычный REST collector собрал основной capture: 342 inline comments / 6 repos, 19 snapshots, без наблюдаемых human thumbs. В [отдельном целевом capture Sourcery](11-reaction-probe.md) найдены 6 comments и 2 human likes. Актуальные ограничения и готовность этапов — в [статусе](IMPLEMENTATION_STATUS.md). Популярность PR не используется как показатель качества feedback.

Emoji могут выражать социальную поддержку, а не суждение о технической правильности. Исследование GitHub PR показывает такие расхождения между смыслом сообщения и emoji; его численные результаты нельзя считать оценкой шума в рабочем AICR или в будущей bot-выборке. [Wang et al., More Than React, 2023](https://arxiv.org/abs/2307.07111).

## Сбор и источники

Основной collector использует публичные read-only REST endpoints с `X-GitHub-Api-Version: 2022-11-28`; GraphQL допустим для metadata threads при необходимости. Нормализованный connector удобен для discovery, но raw collector должен сохранять поля и provenance без потерь.

| Объект | Источник | Использование |
| --- | --- | --- |
| PR metadata | `GET /repos/{owner}/{repo}/pulls/{number}` | Идентичность и текущая metadata; историчность отдельно |
| Inline comments | `GET /repos/{owner}/{repo}/pulls/{number}/comments` | Основной корпус factual remarks |
| Review bodies | `GET /repos/{owner}/{repo}/pulls/{number}/reviews` | Отдельный тип текста, без неявного переноса reactions |
| Conversation comments | `GET /repos/{owner}/{repo}/issues/{number}/comments` | Дополнительные remarks/replies/status, классифицировать явно |
| Inline reactions | `GET /repos/{owner}/{repo}/pulls/comments/{id}/reactions` | События на конкретном inline comment |
| Conversation reactions | `GET /repos/{owner}/{repo}/issues/comments/{id}/reactions` | События на конкретном issue comment |
| Code blobs | Git objects / repository blob API | Текст только из верифицированной версии |

Подтверждение bot identity: actor type/app identity плюс проверенный allowlist. Подстрока «bot» в имени и упоминание бота в тексте недостаточны. Реакции самих ботов и самого автора отделяются; человеческая identity не означает автоматически expert correctness. Минимальные actor IDs нужны для dedup; в аналитическом экспорте они псевдонимизируются без enrichment личных профилей.

Для borrowed datasets требуются источник, license/provenance, дата и соответствие object/reaction semantics. Наличие public repository не означает, что любые комментарии можно распространять под лицензией кода. Публикация корпуса вне текущего проекта требует отдельного решения; для воспроизводимости достаточно manifest IDs/URLs/hashes и collector.

## Targets реакций и применения

Хранить каждую реакцию отдельно. `+1/-1` — первичные наблюдаемые сигналы; heart/rocket/eyes/laugh/confused/hooray не переводятся автоматически в positive/negative. Если пользователь оставил несколько типов reactions, они не превращаются в независимые человеческие голоса.

`no_observed_reaction` — отсутствие наблюдаемого feedback при конкретном времени сбора. Оно не означает, что комментарий прочитан и отвергнут. Удалённые реакции и удалённые комментарии создают survivorship bias; текущий API snapshot не восстанавливает полную event history.

Для ограниченного исторического reaction target задаётся окно, например 14 дней после публикации. В target входят наблюдаемые reactions с `created_at <= t0 + window`; sample моложе окна right-censored. Даже старый sample не гарантирует полную историю удалённых событий. Если временные поля отсутствуют, строгий temporal target недоступен.

Это требование следующего target-building этапа. Текущий `signal_state` описывает все наблюдаемые события capture и не применяет 14-дневное окно; его нельзя выдавать за такой temporal target. Raw timestamps сохранены для последующей фильтрации.

Нельзя приравнивать merge PR, resolved thread или исчезновение строки к accept/apply замечания. Они сохраняются как отдельные proxies. Explicit human acknowledgement, verified matching patch и автоматически inferred apply имеют разные `method` и confidence; причинную связь в общем случае установить нельзя.

GitHub не даёт unpublished candidate pool чужих ботов и надёжный impression log. Внутреннее короткое обоснование генератора, которое получает рабочий реранкер, тоже может быть недоступно. Публичное объяснение можно выделять из body только с provenance и версионированным правилом; нельзя считать его гарантированно эквивалентным внутреннему rationale. Следовательно, здесь не оценивается production accept rate на всех кандидатах и не снимается selection bias опубликованной выборки. Сгенерированные нами скрытые кандидаты будут отдельным synthetic/source cohort без выдуманных human outcomes.

## Дизайн выборки

Discovery сначала измеряет доступность, затем фиксирует sampling frame. В отчёте указываются даты, репозитории, языки, bots, filters, missingness и число исключённых samples. Если выбирались активные проекты с известным ботом, выводы относятся к этому frame.

Natural cohort используется для оценок распространённости внутри frame. Enriched cohort помогает разбирать редкие случаи, но его доля conflicts/negative reactions не выдаётся за population rate. При объединении необходимы известные inclusion probabilities и веса; иначе отчёты раздельные.

Необходимо сохранить разнообразие: bot versions/templates, project size, язык, тип замечания, реакция/её отсутствие, local/repository/external dependence. Не следует выбирать только конфликт teacher-user для обучения router: это воспроизведёт проблему существующего ambiguous-класса.

## Разделение данных

Pilot dev/locked audit предназначен для оценки harness/teacher. Он не называется достаточным ML train/test набором. Будущий расширенный corpus делится отдельно:

- temporal holdout: последние по времени PR на уже наблюдавшихся проектах;
- unseen-project holdout: полностью исключённые из обучения репозитории и их близкие forks/clone families;
- diagnostic slices: bots, templates, languages, aspect/rule, conditional severity, unknown requirements.

Все комментарии одного PR, reply chain и semantic duplicate cluster остаются в одном split. Группы, пересекающие временную границу, помещаются целиком позже или исключаются с записанным правилом. Если связь дубликатов соединяет train и test, пересечение удаляется из train; нельзя подбирать правило после просмотра метрик.

Training label должен быть доступен к training cutoff. Последующая реакция может быть evaluation target для старого input, но не обучающей информацией, якобы известной до её появления. Для каждой строки разделяются feature cutoff, label observation end и capture time. Постфактум исправленный код не входит в teacher input.

## Ручная проверка

Разметчик видит исходное замечание, разрешённый контекст и рубрику. Он не видит reactions и teacher verdict до фиксации factual assessment. Gold status не присваивается автоматически: human reference может оставаться unresolved.

Нужны разные задачи: истинность claims на максимально допустимом контексте и достаточность local bundle. Расширенный human verdict не должен заставлять local judge угадывать недоступные факты; правильный local abstention учитывается как допустимое поведение.

На двух разметчиках показать raw agreement, per-class disagreement и подходящую ordinal/category agreement metric, затем adjudication спорных случаев. При одном разметчике явно ограничить статус reference; часть labels может проверить domain expert при переносе на работу.

## Основные метрики

Порог confident verdict выбирается только на dev. Все результаты показываются вместе с числителями/знаменателями, failure counts и интервалами неопределённости; нельзя публиковать одну красивую accuracy.

| Метрика | Определение и смысл |
| --- | --- |
| Schema validity | Валидный JSON / все запущенные sessions данного режима; до и после repair отдельно |
| End-to-end yield | Принятые assessments / все отобранные samples, включая unavailable snapshots |
| Evidence anchor validity | Корректно восстановленные evidence / все заявленные evidence |
| Semantic evidence validity | Поддержанные человеком отношения claim–evidence / проверенные отношения |
| Context resolution rate | Среди human local-insufficient, но repository-resolvable cases доля корректно разрешённых agent на human reference |
| Harmful revision rate | Среди local-correct cases доля, ставшая agent-wrong; показано рядом с beneficial revisions |
| Answer coverage | Доля samples с определённым factual verdict; отдельно от publication coverage |
| Selective factual risk | Доля ошибочных definitive verdicts среди не-abstained, с risk–coverage curve |
| Evaluability quality | Macro-F1/confusion matrix на human context labels, включая external/preference slices |
| Factual quality | Per-class precision/recall/F1 и confusion matrix, не correctness по реакциям |
| Severity/complexity | MAE по ordinal ranks и weighted agreement на assessable cases с совместимой рубрикой; severity nit/minor/serious/critical, complexity 1–5; conditional basis отдельно |
| Calibration | Brier/reliability для конкретно определённого события корректности verdict; на малом N прежде counts и интервалы |
| Cost | Tokens, calls, p50/p95 wall time, retry rate; деньги только при известной цене |

Brier score/калибровку по correctness labels нельзя вычислять из неполной «вероятности» без определения события. Self-reported confidence может проверяться как вероятность того, что выбранный verdict совпадает с human reference; multiclass Brier требует нормированного распределения всех классов.

Сравнение local/static/agent парное на одинаковых samples. Report содержит как complete-pair view, так и результаты всех выбранных samples, чтобы failures не создавали искусственный выигрыш. Confidence intervals: bootstrap по PR, а при достаточном числе проектов — по repo/PR hierarchy; при малом числе clusters показывать ограничение устойчивости. Не объявлять статистическую значимость на произвольном confidence delta без предзаданного анализа.

Частота teacher-user disagreement — описательная метрика. «Доля исправимого шума» требует заранее заданного target, human adjudication и объяснимого механизма; неизвестная причина реакции остаётся неизвестной. При наличии только реакций и code evidence эта величина может быть неидентифицируема.

## Оценка будущего ranking

Определить отдельно `publication coverage = published / eligible candidates`, `MR coverage = MR with publication / eligible MR`, `comments per MR` и `answer coverage` teacher. Равное coverage без знаменателя не является воспроизводимым условием.

На GitHub допустимо ранжировать наблюдаемый published subset внутри PR и считать nDCG/precision@k по human utility labels. PR с одним eligible sample не оценивает ranking и исключается только из ranking метрик с явным count. Полноценный production ranking требует рабочего candidate pool до отбора и собственных exposure/outcome logs.

Selection correction через inverse propensity weighting возможна только при известных/оценимо обоснованных propensity и overlap; в GitHub MVP таких данных нет. Нельзя заявлять debiasing всего pipeline на основании reactions опубликованных комментариев.

## Решения по итогам пилота

- Agent повышает разрешимость и human correctness при приемлемой цене: масштабировать annotation и проверить student inputs.
- Static даёт сравнимый результат дешевле: использовать static baseline как основной teacher context путь, agent оставить для трудных случаев.
- Большинство cases требует внешних требований: приоритет контекстным контрактам и явному abstention, а не дополнительным поисковым turns.
- Teacher плохо подтверждает свои выводы: улучшать retrieval/rubric, не массово заменять рабочие labels.
- Реакций мало или они не объясняют utility: завершить factual/context prototype и перенести reaction audit на рабочие логи.

Ни один из этих исходов не требует объявлять пользователей ошибающимися ради оправдания модели.
