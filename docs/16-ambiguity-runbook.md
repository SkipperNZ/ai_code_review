# Запуск L/R/H detector

Протокол `ambiguity-1.0.1` реализует постановку пользователя от 27 октября. Он работает поверх существующего collector/snapshot/Pi runtime и не заменяет рабочие heads или метаранкер. Старый CLI `run` остаётся общим judge с severity/complexity; для новой задачи использовать `ambiguity-run`.

## Этапы и шкала

1. E: из текста комментария выделяется точный непрерывный excerpt основного замечания. Это общий core claim для следующих проходов, без перефразирования или собственной оценки extractor.
2. L: независимая оценка только comment + точный snippet + общий excerpt из того же comment. Нет rationale, H или дополнительных строк.
3. R: другая Pi session с тем же комментарием и claim, начальным snippet и свободным планированием поиска по историческому snapshot. Нет результата L и H.
4. После фиксации L/R присоединяется H. Кандидат выбирается по H=R≠L. R/H должны быть известны; explicit unknown у L допускается и выделяется как resolved_local_uncertainty. Технический отказ не является unknown-оценкой.
5. Для кандидата повторяется L в новой сессии с тем же входом; затем V независимо проверяет недостающую предпосылку. V получает snippet и код из R как leads, но не оценки, rationale, relation из R или человеческий сигнал.
6. Если V нашёл решающий факт вне local input и независимо согласился с R, проводится L_plus_context: исходному local-входу добавляются только выбранные V исходные chunks. Если этот контроль совпал с R, а повтор L стабилен, сохраняется model_supported_context_dependency.

Шкала `comment-endorsement-v1`: accept — основное замечание обоснованно и его стоит поддержать; reject — оно опровергнуто или демонстрируемо неприменимо/контрпродуктивно; unknown — данных недостаточно. Это не severity и не угадывание намерения конкретного пользователя. Оценка accept/reject требует matching supports/refutes evidence. Подтверждённый фоновый факт не заменяет проверку основного замечания.

Model-supported outcome остаётся кандидатом на ручной аудит. Совпадение контрольных ответов не доказывает причинность или factual truth. Повтор L — ограниченный контроль стабильности, не полный эксперимент с равным compute budget local/free planning. Возможна слепая зона: L случайно угадал H и кандидат не отобран.

## Точный snippet

Если sample содержит `student_snippet: {path, start_line, end_line, excerpt?}`, используется именно этот исторический диапазон; переданный excerpt проверяется против blob. Иначе snippet извлекается из RIGHT-side строк исходного diff hunk и проверяется по SHA. Это доступное GitHub-приближение входа рабочего ранкера. Нет неявного окна ±12 и нет молчаливого усечения. Anchor должен входить в диапазон; по умолчанию max_local_lines=160, превышение даёт input_unavailable.

`student_features_hash` фиксирует comment+текст snippet, а `local_input_hash` дополнительно фиксирует canonical source metadata. Одинаковые тексты в двух fixtures имеют одинаковый feature hash; непрозрачные source IDs сохраняют разные provenance. Имена sample/run хешируются перед отправкой модели, чтобы название вроде «negative-case» не раскрывалось как подсказка.

## Источник H

Есть два явных режима:

- `--human annotations.jsonl`: готовая endorsement-оценка на нужной шкале. Manual требует annotator_key и source_ref. Duplicate sample IDs запрещены: конфликт нужно сохранить/разрешить явно, не агрегировать молча majority vote.
- `--reaction-proxy`: human thumbs переводятся в endorsement proxy: positive → accept, negative → reject. Это допущение для отбора кандидатов, не эквивалент factual truth. Bot/self reactions исключаются. Missing, conflicting, incomplete и неизвестный actor дают unknown. Отсутствие acceptance не означает reject; автоматического извлечения acceptance текущий collector не делает.

Пример одной строки для настоящей ручной оценки, которую заполняет человек:

```json
{"sample_id":"REPLACE_SAMPLE_ID","scale_id":"comment-endorsement-v1","label":"unknown","source_kind":"manual","source_ref":"REPLACE_REVIEW_REFERENCE","annotator_key":"REPLACE_REVIEWER_ID"}
```

Для предоставленного явного acceptance proxy можно использовать source_kind=explicit_acceptance_proxy. Отдельно разрешён synthetic_reference только с `--synthetic-demo`; это не human annotation. Если H не предоставлен, L/R могут выполняться, но кандидатов не будет. `--only-with-human` ограничивает выборку известными H; такое смещение отбора отражать в отчёте.

## Воспроизводимый synthetic smoke

Код fixtures не запускается. Script создаёт два in-memory snapshot с одинаковыми comment/snippet: в одном все вызовы защищены guard, во втором в render явно передаётся None. References заданы по построению и помечены synthetic.

```powershell
.\.venv\Scripts\python.exe scripts/make_ambiguity_demo.py
.\aicr.ps1 doctor
.\aicr.ps1 --data data/ambiguity-demo-v1 ambiguity-run --name amb-demo --limit 2 --human data/ambiguity-demo-v1/human/synthetic-references.jsonl --synthetic-demo
```

Для доступного на этом десктопе отдельно проверенного контекста 64k добавить глобальный `--config configs/context64k.local.json`. Перед новым run doctor проверяет mutable deployment; совпадение model ID не доказывает неизменность весов. Выбор лимита контекста для другой модели требует отдельной проверки.

## Реальные данные и аудит

```powershell
.\aicr.ps1 --data data/reaction-followup ambiguity-run --name amb-public --limit 2 --reaction-proxy --only-with-human --strict
.\aicr.ps1 ambiguity-evaluate runs/<ambiguity-run-id>
```

Папки supplemental captures существуют на исследовательском десктопе и исключены из Git. В чистом clone сначала собрать свой публичный capture обычными collect/snapshot командами либо передать нормализованные рабочие данные через будущий GitLab adapter. Нет подключения к корпоративному сервису или вызовов неизвестного Nessy API.

В run сохраняются manifest, frozen execution, human-inputs.jsonl отдельно от worker, case-hashes.json, case.json по sample и E/L/R/V/control attempts. В attempt лежат blinded input, trace, shown-chunks, raw candidate, прошедший проверки response и материализованные evidence. source labels не переписываются. Результаты: ambiguity-cases.jsonl, ambiguity-candidates.jsonl, ambiguity-metrics.json, AMBIGUITY-SUMMARY.md.

Верификация требует, чтобы каждый decisive chunk был полностью вне всех local ranges; новый ID для тех же/перекрывающихся строк не считается дополнительным контекстом. Source checks подтверждают происхождение цитат и согласованность полей, не истинность смысла. `ambiguity_gold_label` остаётся null; classifier_trained=false и precision/recall=null до отдельной ручной разметки именно контекстной зависимости. H, использованный для отбора, таким reference не является.

## Resume и проверки

С той же командой, кодом, данными и настройками завершённые stages берутся из проверенных артефактов. Поле executed_now показывает новые обращения отдельно от cumulative metrics. Завершённые failures повторяются только с `--retry-failed`; незавершённая attempt сохраняется, следующая получает новый номер.

После изменения рабочего кода использовать frozen resume:

```powershell
.\.venv\Scripts\python.exe scripts/resume_ambiguity.py runs/<run-id> --dry-run
.\.venv\Scripts\python.exe scripts/resume_ambiguity.py runs/<run-id>
```

Dry-run проверяет source, dependency lock, sample/snapshot/human hashes и сохранённые case hashes без model requests. Resume требует прежних deployment metadata и использует исходный snapshot человеческих сигналов; новый capture реакций создаёт новый run identity.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q --basetemp .cache/pytest
npm.cmd run typecheck
npm.cmd run test:worker
```

Loopback integration исполняет реальный Pi SDK. Он проверяет полный путь с обеими сторонами guard fixture, native read_lines, blinding, timeout, provider failure и malformed JSON. Эти проверки не являются измерением factual accuracy на реальных комментариях.

## Результаты пилота

[Первые реальные Qwen-прогоны и контролируемые fixtures](18-ambiguity-pilot.md) зафиксированы отдельно. Для независимого reference использовать [human-аудит](17-ambiguity-human-audit.md). Инженерная работоспособность и доля model-supported кандидатов не заменяют ручную проверку, достаточный corpus и независимый holdout для решения об обучении будущего ambiguity-классификатора.

Дополнительные controls: `.venv/Scripts/python.exe scripts/make_ambiguity_controls.py`, затем ambiguity-run с data/ambiguity-controls-v1 и явным synthetic-demo. Они включают missing-callee pair и два locally decidable примера.

В V массив context_links содержит фоновые/local citations; decisive_links допускает только supports/refutes и полностью outside-local диапазоны.
