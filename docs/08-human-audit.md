Для нового L/R/H detector использовать [отдельный контекстный аудит](17-ambiguity-human-audit.md). Ниже сохранён аудит прежнего общего judge.

# Независимый ручной аудит

`export-human` создаёт слепые JSONL packets: comment, snippet, необязательный rationale, snapshot ID и показанные chunks. `assessment` и `annotator_key` пусты. Индекс с источниками сохраняется отдельно в `.index.json`; его нельзя открывать до фиксации независимой factual annotation, иначе через GitHub можно увидеть пользовательские реакции или поздние исправления.

По умолчанию output находится внутри выбранного `--data`: `<data>/human/blind-packets.jsonl`. `--output` позволяет задать другой путь явно. Отдельный capture не должен перезаписывать основную аннотацию; это проверено на supplemental export из 6 samples, при котором hash основного файла из 240 packets остался прежним.

Текущий экспорт — development pool. Он **не** выдаётся за locked test: публичных PR пока слишком мало, и их примеры уже используются в инженерной отладке. Для запланированного split 80 dev / 160 test нужно отдельно собрать будущие PR и/или новые репозитории, зафиксировать группировку по PR и дублям до просмотра ответов teacher и не менять prompt по locked test.

## Два независимых этапа

1. Local stage: аннотатор видит только packet. Заполняет assessment по schema, указывает конкретно недостающие условия. `context_mode=local`, `annotation_stage=local`.
2. Repository stage: другой аннотатор исследует тот же исторический snapshot, не видя ответ local-аннотатора, teacher и reactions. `context_mode=agent`, `annotation_stage=repository`. Если людей мало, последовательное раскрытие допустимо как отдельный эксперимент, но не как независимая оценка local sufficiency.

Читать фрагменты без открытия нынешней версии GitHub:

```powershell
.\aicr.ps1 read-snapshot snap-<id> src/example.py --start 10 --end 40
```

Вывод содержит canonical source_chunk_id и точные lines. Добавить реально прочитанные chunks в `shown_chunks` annotation record. `snapshot_id` должен совпадать с packet. Поля `sample_id` и `schema_version=0.1.0` обязательны; `run_id` для ручного assessment можно задать как `human-audit-v1`. Указать свой непубличный псевдоним в `annotator_key`, не подставлять имя модели. `annotation_source=human` не меняется.

Оценивать атомарные factual claims отдельно от предпочтений. Ненайденное доказательство не означает опровержение. Внешние продуктовые требования, недоступные конфигурации и частичный snapshot могут оставить verdict unverifiable. Значение severity может быть null; complexity-рубрика пока временная. Самооценка confidence не считается калиброванной вероятностью.

## Сравнение

```powershell
.\aicr.ps1 evaluate runs/<run-id> --human data/human/completed.jsonl
```

Evaluator принимает только заполненные repository-stage human annotations с корректными evidence. Отдельно считает число людей, single-annotator случаи и расхождения. При расхождении correctness между людьми пример не превращается в majority label: он исключается из consensus и требует adjudication. Сравнение выдаёт correctness agreement и confusion matrix по режимам; даже высокое agreement не является причинным доказательством улучшения продукта.

После factual verdict можно отдельно раскрыть user signals и классифицировать расхождения: обоснованное preference, недоступный проектный контекст, ошибка teacher, неоднозначная реакция, вероятный label noise. Последняя категория требует ручного основания; нельзя вывести её только из уверенного teacher. Исходные реакции сохраняются неизменными. Основной capture не содержит human thumbs; два отдельных Sourcery captures суммарно содержат три человеческих лайка и два дизлайка. Этого недостаточно для оценки естественного шума.

## Список случаев для раскрытия сигналов

```powershell
.\aicr.ps1 triage runs/<run-id> --mode agent
```

Команда работает offline и сохраняет `audit-links-agent.jsonl` и `triage-agent.json`. Она связывает исходный signal с последним завершённым валидным model assessment, проверяет hashes samples против manifest и сохраняет hashes раскрытых signal/assessment. При отсутствии валидного assessment вывод модели остаётся null; failed candidate не становится отрицательным label. Нет реакции также не превращается в dislike.

Флаги `human_positive_teacher_refuted` и `human_negative_teacher_supported` обозначают наблюдаемое расхождение между разными источниками, а не доказанную ошибку пользователя. `context_unresolved` и `preference_present` независимы от реакции и могут встречаться одновременно. `reaction_error=null` и `explanation_status=unresolved` сохраняются до настоящего человеческого adjudication. Этот файл не давать слепому teacher или аннотатору до завершения независимой оценки. Окно сигналов — все наблюдаемые события, а не фиксированные 14 дней.
