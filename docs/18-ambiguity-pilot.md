# Первые прогоны L/R/H

27 октября 2026. Модель — deployment пользователя `qwen3.8-flash-next-mirai-s`, настоящий Pi SDK 1.3.0. Профиль клиента 64k проверен doctor; deployment metadata не являются fingerprint весов. GitHub capture и synthetic fixtures разделены, raw data/runs исключены из Git.

Это development pilot. Числа ниже не являются precision/recall, noise rate реакций или основанием для обучения classifier: независимого human reference контекстной зависимости пока нет.

## Исправление контракта

В `ambiguity-1.0.0`, run `amb-synthetic-v1-f536745a949d`, оба примера стали кандидатами, но V смешал local background citations и decisive evidence. Обе проверки evidence отклонены. Ошибки не были автоматически исправлены или объявлены подтверждением.

В `ambiguity-1.0.1` выделен context_links для фоновых/local цитат. Decisive links по-прежнему требуют supports/refutes и entirely outside-local chunks. Extractor уточнён: выбирать основное сообщение о дефекте с условиями, а не только «добавить guard». Старые runs сохранены.

## Контролируемые fixtures

| Run | Примеры | Кандидаты H=R≠L | Model-supported после контролей | Прочие результаты |
| --- | ---: | ---: | ---: | --- |
| `amb-synthetic-v101-3598528b74e2` | 2 | 2 | 1 | 1 context_addition_not_corroborated |
| `amb-controls-v101-e40dea5933ac` | 4 | 2 | 2 | 2 not_selected |

Первая пара: одинаковые comment+snippet, разные callers. В опасном варианте caller явно передаёт None: L/L_repeat=unknown, R/V/C=accept. В безопасном R/V отвергают замечание, но единственный выбранный защищённый caller не убеждает C, что других callers нет. Система сохраняет неподтверждённое вмешательство. R проверял полный inventory, C получил только выбранные chunks; информационные условия различаются. Минимальность или полнота decisive context не доказана.

В новой паре локально виден transform(None), а определение находится в другом файле. Безопасная и опасная реализации дали противоположные verdicts после добавления определения: оба примера прошли V, стабильный повтор L и C. Два locally decidable примера с делением на ноль дали L=R=synthetic H и не выбраны кандидатами.

Synthetic H и ожидаемые свойства заданы по построению, не являются реальными реакциями или human annotations. Воспроизведение: scripts/make_ambiguity_demo.py и scripts/make_ambiguity_controls.py; fixture code не запускается. Второй run: 31 model requests, 17 tools, 9954 generated tokens, 155.124 секунды stage wall time, 2 format repairs. Скорость зависит от deployment и конфигурации.

## Первые реальные реакции

| Run | Comments | H | Кандидаты | Model-supported | Технические отказы |
| --- | ---: | --- | ---: | ---: | --- |
| `amb-public-a-v101-334fbd9548bd` | 2 | Human negative thumbs proxy | 0 | 0 | 1 R evidence_invalid |
| `amb-public-b-v101-8e34d2e229b7` | 2 | Human positive thumbs proxy | 1 | 1 | 0 |

Поддержанный моделью пример — [GetIconInfo](https://github.com/BoboTiG/python-mss/pull/272#discussion_r1466140111). Snippet не содержал вызов и чтение полей структуры. R/V нашли декларацию BOOL return, вызов без проверки результата и последующее использование полей. L_repeat остался unknown; выбранные chunks привели C к accept. Это модельная гипотеза, ожидающая независимой проверки API semantics и применимости замечания.

Отказ R в другом примере — ссылка на source_chunk_id, которого модель не видела. Такой ответ не становится unknown, reject или candidate. Комментарий о версии action также показывает границу source-only проверки: строка версии в workflow не доказывает дату внешнего релиза. Нужен внешний temporal evidence contract либо unknown.

В сохранённых runs 1.0.0 реальные пары дали по одному кандидату, но C не воспроизвёл R. Это чувствительность к claim, контексту и вариативности judge; лучшие результаты разных версий не объединяются в quality estimate.

## Аудит и воспроизводимость

Реализован [offline human-аудит](17-ambiguity-human-audit.md), включающий non-candidates. Exporter не создаёт labels. Synthetic и human references разделены; incomplete audit не выдаёт recall. Настоящий frozen resume amb-public-b-v101-8e34d2e229b7 после изменения рабочего дерева: stages_executed_now=0, model_requests_now=0.

## Расширенный реальный pilot

Отдельный capture `data/reaction-expanded-20261027`: просмотрено 1000 repo-wide comments в трёх публичных repos; отбор целенаправленный по наличию thumbs. После исключения уже использованных примеров найдено 11 новых targets; один PR недоступен (404), поэтому он исключён с сохранением причины. Полные comment pages восьми доступных PR и actor-level reactions импортированы offline скриптом import_public_capture.py: 14 нормализованных comments, 6 positive и 4 negative human signals, ещё 4 incomplete. Эти четыре не объявляются no-reaction или negative. Получены 8 exact-SHA snapshots, все partial; body у всех 14 неизменён, anchors проверены. Первичные download timeouts разрешились одним повтором; старые snapshots не переписывались.

Run `amb-expanded-v101-1a838bbf4ad1` использует 10 known-H strict samples:

| Показатель | Результат |
| --- | ---: |
| Planned cases | 10 |
| Cases с завершёнными E/L/R | 9 |
| Input unavailable | 1: exact hunk превышает 160 строк |
| Кандидаты H=R≠L | 6, все resolved_local_uncertainty |
| Model-supported после V/L_repeat/C | 3 |
| External context needed | 1 |
| V расходится с R | 1 |
| C не воспроизводит R | 1 |
| Non-candidates среди выполненных | 3 |
| Model requests / tools | 106 / 92 |
| Generated tokens / format repairs | 73501 / 9 |
| Сумма stage wall time | 920.154 s |

Один особенно показательный отрицательный [пример libmagic](https://github.com/Nuitka/Nuitka/pull/2830#discussion_r1584548166): по YAML snippet L не знает, нужна ли предлагаемая настройка file_extensions. R/V находят schema с additionalProperties=false, фактический параметр suffixes, его обработчик и default extensions. R/V/C=reject при исходном negative thumb, L/L_repeat=unknown. Это как раз гипотеза «пользователь знает формат проекта, а local judge его не видит». Её смысловую корректность ещё должен проверить независимый человек.

Два других model-supported примера — [nested loop test](https://github.com/Nuitka/Nuitka/pull/3757#discussion_r2785774380) и [function reformulation](https://github.com/Nuitka/Nuitka/pull/3813#discussion_r2921978056), оба с positive H proxy. Наблюдений уверенного переворота accept↔reject у L здесь нет: все кандидаты связаны с исходным unknown. Распространённость такой ситуации в production не измерена.

Недоступный input не был молча усечён. В этом frozen run его legacy conclusion называется unresolved; status=input_unavailable однозначно фиксирует техническую причину. После прогона код получил отдельные conclusions input_unavailable/claim_unavailable/assessment_unavailable. Старый case и метрики не исправлялись задним числом.

Также исправлена будущая сборка snapshots: collection_policy=historical-text-2 помечает partial при пропуске sensitive/unsafe paths, symlinks, binary или non-UTF8 файлов. Раньше часть этих пропусков не отражалась в partial flag. Уже собранные blobs/метрики не пересозданы; все реальные snapshots этого pilot и так имели partial=true из-за бюджетов. Полный textual snapshot не доказывает отсутствие внешних требований или динамических вызовов.

Алгоритм показывает зависимость оценки от доступного контекста, но не восстанавливает достоверно мотив исторической реакции человека. Эти результаты не создают human ground truth и не обосновывают обучение classifier без следующего независимого аудита.

## Финальное усиление blinding: 1.0.2

В 1.0.1 модели передавался непрозрачный hash полного run ID. Он не раскрывал label, но косвенно менялся при замене H: H входил в outer identity. В 1.0.2 видимый ID зависит только от протокола и snapshot hash. Regression test меняет H и описательное имя запуска и проверяет полное равенство запросов E/L/R, кроме runtime_dir, который не отправляется модели. Внешний run identity по-прежнему сохраняет human hashes для provenance.

Новый bounded run `amb-blinding-v102-c987fafb4135` на двух missing-callee controls: 2/2 model-supported, все E/L/R/V/repeat/context stages прошли validators. 26 requests, 16 tools, 7644 generated tokens, 129.938 s stage wall time, 2 repairs. Это повтор synthetic controls для проверки изменения, не два новых независимых samples. Реальный corpus повторно не запускался; его результаты выше относятся к 1.0.1.

Финальный suite: 119 Python tests, TypeScript typecheck и 8 worker tests. Отдельная чистая копия исходного portable archive с sanitized config прошла предыдущие 118 tests после создания обязательного родительского .cache; Python и npm dependencies использовались из уже установленной среды. Setup дополнен этим шагом. Новые archives не перезаписывают предыдущие версии; финальная переносимая версия — 0.3.1.
