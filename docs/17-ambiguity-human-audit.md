# Независимый аудит контекстной зависимости

H используется при отборе H=R≠L. Это endorsement или явный proxy реакции, а не reference того, нужен ли для проверки комментария контекст репозитория. Для оценки детектора нужен отдельный аудит, скрывающий H, модельные ответы и факт отбора кандидата.

`ambiguity-export-audit` работает offline, без модели и настроенного endpoint. Экспортируются все доступные cases выбранных runs, включая non-candidates и технические failures R. Нужны зафиксированный core claim и canonical snippet; planned source cases учитываются отдельно. Повтор одного входа из разных версий detector запрещён: выбрать одну версию на пример.

```powershell
.\aicr.ps1 ambiguity-export-audit runs/<run-a> runs/<run-b> --output data/human/ambiguity-audit-1
```

| Путь | Получатель | Содержание |
| --- | --- | --- |
| `local/` | Проверяющий local-условие | Comment, общий excerpt, точный snippet, непрозрачные IDs |
| `repository/` | Проверяющий repository-условие | Тот же вход, inventory, partial flag, historical text blobs |
| `private/` и корневой manifest | Координатор | Связь с исходным sample/run, frozen predictions и hashes |
| `annotation.schema.json` | Оба проверяющих | Контракт ручной разметки |

Не передавать проверяющим корень audit directory: private index содержит predictions. В публичных packets нет H, source URL с реакциями, L/R/V rationale, candidate flag или ожидаемого verdict. Если работает один человек, сначала сохранить local-ответы и только затем открыть repository. Программа не может доказать соблюдение этой последовательности: поля `*_unseen` — подтверждение проверяющего, не техническая гарантия слепоты.

Reader работает с отдельно переданной папкой `repository/`, без private index. Он проверяет hash snapshot, inventory, partial flag и диапазон. Путь относится к snapshot, не к файловой системе; код не исполняется:

```powershell
.\aicr.ps1 ambiguity-audit-read data/human/ambiguity-audit-1/repository <packet-id> src/example.py --start 10 --end 30
```

## Отдельные annotations

Оба файла — JSONL, одна adjudicated строка на packet. Конфликты не агрегируются молча majority vote. `annotator_key` — стабильный псевдоним проверяющего. Повторное использование annotator исходной manual H исключается из независимого reference. Для thumbs proxy автоматически сопоставить личности нельзя; отсутствие предварительного знания H подтверждает проверяющий.

Local: `phase=local`, decision accept/reject/unknown, evaluability sufficient/insufficient и rationale. Unknown требует insufficient; известный verdict — sufficient. Repository evidence и context-dependency verdict в local-файле запрещены.

Repository: `phase=repository`, decision и отдельный context_dependency:

- `required`: нужна конкретная предпосылка вне snippet; указать её и точную outside-local цитату.
- `not_required`: исходного comment+snippet достаточно; нужны rationale и canonical evidence.
- `external`: нужен факт за пределами snapshot, например командная договорённость или история внешнего релиза; decision=unknown.
- `unresolved`: необходимость/достаточность контекста не установлена; decision=unknown.

Примеры ниже — **заглушки формы**, не готовые human labels. Все IDs и содержательные поля заполняет проверяющий:

```json
{"audit_id":"audit-REPLACE_24_HEX","packet_id":"REPLACE_24_HEX","phase":"local","source_kind":"human_manual","annotator_key":"REPLACE_REVIEWER","decision":"unknown","evaluability":"insufficient","rationale":"REPLACE_WITH_OWN_REASON","model_outputs_unseen":true,"human_signal_unseen":true}
```

```json
{"audit_id":"audit-REPLACE_24_HEX","packet_id":"REPLACE_24_HEX","phase":"repository","source_kind":"human_manual","annotator_key":"REPLACE_REVIEWER","decision":"reject","context_dependency":"required","missing_premise":"REPLACE_WITH_MISSING_PREMISE","evidence":[{"path":"src/example.py","start_line":10,"end_line":12,"excerpt":"REPLACE_WITH_EXACT_CANONICAL_TEXT"}],"rationale":"REPLACE_WITH_OWN_REASON","model_outputs_unseen":true,"human_signal_unseen":true}
```

Полные поля заданы schema. Цитата должна совпадать с blob. Для required нужен хотя бы один диапазон целиком вне local snippet: иной ID тех же строк недостаточен. Partial snapshot не доказывает отсутствие callers или правил в недоступной части проекта. Совпадение цитаты не доказывает semantic truth.

## Подсчёт

```powershell
.\aicr.ps1 ambiguity-score-audit data/human/ambiguity-audit-1 --local annotations/local.jsonl --repository annotations/repository.jsonl
```

Scorer проверяет IDs, source kind, подтверждения слепоты, дубли, согласованность полей и цитаты. Копии annotations и hashes сохраняются в `evaluations/<identity>/`; reactions, case.json и model verdicts не меняются. Candidate и model_confirmed оцениваются отдельно. Это качество на вручную проверенных экспортированных примерах, не population estimate или locked holdout.

Неполные пары, external и unresolved исключаются из бинарных метрик с явным coverage. Recall остаётся null, пока все exported cases не получили разрешённый human reference: аудит одних кандидатов не измеряет recall. Даже полный аудит целенаправленной выборки не даёт population recall. Различие человеческих local/repository решений сохраняется отдельно и не заменяет явную оценку необходимости контекста.

`synthetic_test_fixture` разрешён только с `--allow-synthetic-test`, исключительно в synthetic_diagnostics. Даже human_manual для synthetic sample не превращает его в реальный benchmark. Model-generated labels импорт не принимает. Независимая человеческая разметка пока не собрана; classifier не обучался.
