# Ход реализации

Инженерный прототип реализован и проверен. [Итоговый отчёт](13-prototype-results.md) отделяет техническую работоспособность от качества teacher. Независимые human labels и эффекты на качестве ещё не измерены.

| Этап | Состояние |
| --- | --- |
| P0 Среда и Pi | Готово: Node 24.18.0, Python 3.13.0, Pi SDK 1.3.0, preflight модели, SDK+SSE mock |
| P1 Контракты и validators | Готово: assessment и storage schemas, межполевые проверки, canonical chunks |
| P2 Collector | Реализованы bounded discovery и inline collector; 342 samples / 6 repos, zero human thumbs; 3 PR с неполной пагинацией |
| P3 Snapshots | 19 exact-SHA архивов, anchors доступны для 342 samples; 32 exact / 310 partial; strict 5 |
| P4 PiRunner | Готово: 3 режима, 4 инструмента, budgets, queue lock/resume, trace, fail-closed labels |
| P5 Реальный smoke | Завершён `smoke-compact-e998172b268c`: 120/120, local 39/40, static 36/40, agent 18/40 прошли все validators; raw schema 40/40 во всех режимах после разрешённого repair |
| P6 Human pilot | Подготовлено 240 слепых packets; human annotations и независимый locked holdout отсутствуют |
| P7 Оценка и пакет переноса | Инженерные метрики, diagnostics/CSV, post-hoc triage, human import, runbook/handoff и итоговый отчёт готовы; human quality metrics не измерены |

69 Python tests прошли, включая 18 реальных Pi SDK loopback scenarios для двух response contracts, collector/discovery, восстановление interrupted queue, compact response compiler, p95 nearest-rank, сравнение прогонов, неопределённых reaction actors и проверку ZIP. TypeScript typecheck и 8 tests tools прошли. Это инженерные проверки, не подтверждённые review labels.

В [последующей итерации](14-hardening.md) вход получил номера строк и temporal metadata; tools возвращают подсказки для неверных путей/диапазонов. На заранее выбранных 16 samples первый повтор `hardening-v02-63c3729bc8d9` дал 12 валидных assessments против прежних 4: восстановлено 9 failures, возникла одна регрессия. Новый основной `compact-0.3.0` отдельно проверен на тех же 16 samples: 15 ok / 1 json_invalid, 11 восстановленных failures и ноль регрессий относительно исходного smoke; относительно промежуточной версии есть одна регрессия. Результаты разных контрактов не смешиваются. CLI `compare` и `scripts/verify_package.py` работают offline.

При проверке переноса исправлены output path `export-human` для отдельного `--data` и смещение p95 на одну позицию. Реальный экспорт 6 supplemental packets сохранил hash основных 240 packets. Эти исправления не изменяют worker текущего frozen model run. Добавлен offline `scripts/audit_run.py`: CSV попыток, список ошибок и проверка выбранных полей до/после format repair.

Отдельная [проверка реакций](11-reaction-probe.md): ещё 6 Sourcery comments / 3 repos, 2 human likes и 12 self/bot reactions. Collector верно отличает 2 positive от 4 no_observed_human_thumb, не создавая ложные conflicts из собственных 👍/👎 бота. Все 6 anchors доступны, body exact_at_t0; validate прошёл. Эти данные не входят в основной model smoke, новых model generations на них нет.

[Дополнительный capture Nuitka](12-reaction-followup.md): 7 comments / 2 PR, 2 человеческих дизлайка, 1 лайк и 14 bot/self reactions. Schema/data audit прошёл; оба выбранных отрицательных примера имеют подтверждённые historical body и anchors, snapshots partial. Run `reaction-demo-aa1873b6e430` выполнил local/agent на этих двух примерах: 4/4 validators passed, 0 repairs. Это не factual accuracy: внешний probe обнаружил смешение function.__builtins__ и глобального имени в обосновании teacher; test runner был доступен, но не прочитан. `triage` сохранил negative signals и отметил unresolved context/preferences, не исправляя labels.

Реальный frozen resume основного run пропустил все 120 завершённых попыток, включая failures; completed_now=0. Дополнительные blind exports находятся отдельно: 6 packets reaction-probe и 6 reaction-followup (один точный повтор исключён sampler).

## Диагностические прогоны

- Первый Pi synthetic cross-file run обнаружил ошибку cross-claim evidence references; validator отклонил результат. Уточнён prompt, повторный synthetic local/agent прошёл.
- smoke-v1 остановлен после двух валидных local/static результатов: output 4096 обрывал ответы и вызывал format repair. Незавершённый agent не считается label.
- Explicit reasoning probe подтвердил поддержку server `enable_thinking`; mode off ускорил synthetic local, но agent исчерпал бюджет. Default возвращён к explicit true, output увеличен до 8192, добавлено завершение tool phase по бюджету.
- smoke-v2 подтвердил отсутствие format repair на первом local и остановлен для фиксации execution bundle.
- `smoke-frozen-a948d5ff5fb9` — диагностический запуск полного JSON-контракта. Выявлены ошибки переписывания цитат и cross-claim IDs; запуск остановлен, результаты сохранены. Новый compact contract оставляет модели judgments и ссылки на chunks, а точные citations/IDs материализует harness. Старые и новые показатели evidence нельзя смешивать.
- Compact contract 0.2.0 прошёл fixtures и реальный synthetic local/agent probe. Прогон `smoke-compact-b5566019daf7` выявил пропущенные обязательные поля, которые первоначальный parser не отправлял на format repair.
- В 0.2.1 worker использует AJV 8.20.0: единственный format repair охватывает syntax и JSON Schema, но не source/semantic failures. Preference evidence необязательно, его отсутствие означает пустой список; factual evidence_links остаётся обязательным. Проверено 36 fixtures. Основной отчёт использует `smoke-compact-e998172b268c`; raw model schema validity и canonical record validity измеряются раздельно.
- Frozen resume dry-run прошёл на настоящем run: hashes и queue валидны, model requests 0. Пользоваться `scripts/resume_frozen.py`, если исходное дерево уже изменено.

## Границы текущей версии

Исходный исследовательский план шире инженерного прототипа. Нет нормализации summaries/issue comments, accept/apply labels, semantic duplicate clustering, статического retrieval импортов/тестов, locked test и human adjudication. Exact duplicates фильтруются при sampling. По текущей выборке нельзя оценить шум реакций, улучшение качества или перенос на рабочий reranker. Эти ограничения не маскируются синтетическими labels.
