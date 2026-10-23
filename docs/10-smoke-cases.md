# Десять случаев из основного smoke

Run: `smoke-compact-e998172b268c`, compact response `0.2.1`. Это первые десять samples в заранее сохранённом порядке manifest, без отбора по удачности ответа. Ниже разбор поведения модели и валидатора, **не human reference** и не измерение улучшения качества. Повторной генерации для этих случаев не было.

`ok` означает прохождение схемы, проверки источников и межполевых правил. `semantic_invalid` означает противоречие контракту, а не доказанную фактическую ошибку комментария. `evidence_invalid` означает непригодную ссылку/цитату. Неуспешный candidate сохраняется для диагностики, но не экспортируется как assessment.

| Случай | Local → static → agent | Что наблюдалось |
| --- | --- | --- |
| [CSS: перенос кнопок](https://github.com/LAF-US/loganfinney/pull/19#discussion_r4129364576) | unverifiable → unverifiable → partially_supported; все ok | Агент прочитал размеры, padding и HTML. Он подтвердил арифметику ширины, но оспорил именно обрезание и предложил rewrite. Такой переход требует проверки геометрии человеком/браузером; сам переход не доказывает пользу контекста. |
| [Node: ошибки файловой системы](https://github.com/OpenCut-app/OpenCut/pull/479#discussion_r2238538032) | supported → supported → supported; все ok | Агент дополнительно проверил вызов `findFiles` из `main`. Verdict сохранился. Local уже предлагал publish, хотя его rationale оговаривал неизвестную обработку ошибки вызывающим кодом: формальный валидатор не распознаёт все смысловые противоречия свободного текста. |
| [R: освобождённое соединение](https://github.com/mokaradag/MERGEN-Bilge/pull/705#discussion_r3836019223) | partially_supported во всех режимах; все ok | Агент нашёл release и fallback в разных файлах, но оставил последствие для пула непроверенным. Одинаковый aggregate verdict скрывает изменение объёма проверенных claims. |
| [Python: capsys и тестовые края](https://github.com/rjmurillo/ai-agents/pull/5078#discussion_r3789883513) | local ok; static/agent semantic_invalid | Утверждение о недостающем покрытии помечено partially_supported без ссылки relation=supports. Отсутствие найденного теста само по себе не является доказательством отсутствия теста во всём проекте. |
| [Python: reader threads](https://github.com/rmems/synthetic-factory/pull/134#discussion_r3869328547) | local/static ok; agent semantic_invalid | Агент подтвердил часть cleanup-пути, оставил накопление ресурсов зависимым от режима вызовов и всё равно выбрал publish. Это нарушает зафиксированное правило publish только при полностью supported factual claims. |
| [Svelte: custom renderer](https://github.com/sveltejs/svelte/pull/18042#discussion_r3021225754) | local/static ok; agent evidence_invalid | Агент сослался на диапазон вне выбранного показанного chunk. Наличие строк где-то в snapshot не разрешает считать их просмотренными в этом chunk. Candidate не материализован в валидный assessment. |
| [Playwright: подавленный timeout](https://github.com/OpenCut-app/OpenCut/pull/479#discussion_r2238731618) | local ok; static/agent semantic_invalid | Модель выделила ссылку на «другой feedback» как непроверенное утверждение, сохранила aggregate partially_supported, но выбрала publish. Случай показывает чувствительность правила к разбиению текста на claims; нужно отдельно исследовать существенность вспомогательных утверждений, не менять правило задним числом. |
| [R: неизвестный timezone](https://github.com/mokaradag/MERGEN-Bilge/pull/705#discussion_r3836019224) | local/static ok; agent evidence_invalid | Найдены `%||%` и вызывающий код, однако один выбранный span указывает на пустую строку. Компилятор честно получил пустую цитату; final schema её отвергла. Автоматическое копирование цитат не исправляет неверный выбор anchor. |
| [Python: ancestor package imports](https://github.com/rjmurillo/ai-agents/pull/5078#discussion_r3789883504) | local/static ok; agent semantic_invalid | Агент исследовал граф и selector, но выдал partially_supported claim без supports evidence и publish при частичной проверке. Ссылка на внешний issue осталась отдельным источником неопределённости. |
| [Quality gate: забытый cue](https://github.com/rmems/synthetic-factory/pull/134#discussion_r3869328541) | partially_supported во всех режимах; все ok | Агент нашёл реализацию gate и предложил rewrite: логика кода и требование считать забывание допустимым примером — разные вопросы. Репозиторный поиск может подтвердить механизм, не разрешив требование к продукту. |

## Проверяемые anchors и локальные материалы

Полные outputs и traces находятся в `runs/<run>/<sample>/<mode>/attempt-1/`. Для валидного результата есть `assessment.json`; для ошибки нужно читать `result.json`, `raw-candidate.json` и, если компиляция состоялась, `candidate.json`. Эти файлы не входят в исходный ZIP.

| № | Sample | Snapshot | Примеры выбранных agent anchors |
| --- | --- | --- | --- |
| 1 | `gh-5d2580b096f440eb0400d520` | `snap-ebc29ec5e5aad7949c86622f` | `styles.css:717–740`, `styles.css:240–330`, `index.html:1–88` |
| 2 | `gh-b8fb23d0e3962a55bb3f5101` | `snap-b35d36318e0de5f11fba46b9` | `apps/web/e2e/helpers/debug-scripts/electron-path-fixer-html-js-css-v2.js:6–22,140–197` |
| 3 | `gh-507fa604de2f0d8c774facdf` | `snap-76449205c90d69c82a882931` | `R/helpers_deep_analysis_reconcile.R:199–208`, `R/helpers_deep_analysis.R:411–413` |
| 4 | `gh-139d87c9a64a800c41418fc4` | `snap-72c0c2e0fec66f30b414f53e` | `tests/test_selection/test_select_tests.py:192–224`, `scripts/test_selection/select_tests.py:61–122` |
| 5 | `gh-3a73b96e81fe700fc20d2d96` | `snap-f00ac403c7515b4a00328799` | `pipelines/oracle_grounded/oracles.py:388–413,452–466` |
| 6 | `gh-760d0aa78044b65fff2a273e` | `snap-793a252abdce0a5ca3441de8` | Ошибка диапазона; непринятые ссылки смотреть в raw candidate и shown-chunks |
| 7 | `gh-6a0c0999e16a81b983fc8b74` | `snap-1829026ef6ad10a1242ae4d8` | `apps/web/e2e/ai-tests/ai-model-selection-bug-reproduction.spec.js:285–288,125–128` |
| 8 | `gh-6b04087fd6936168e90e7341` | `snap-76449205c90d69c82a882931` | `R/utils_common.R:11–14`, `R/helpers_pk_analysis_packet.R:141–146`; выбранная отдельно строка 146 пустая |
| 9 | `gh-7bc238198409aa1b17c2e7cd` | `snap-72c0c2e0fec66f30b414f53e` | `scripts/test_selection/import_graph.py:82–106`, `scripts/test_selection/select_tests.py:114–140` |
| 10 | `gh-dbde61af9c69642660a2ea01` | `snap-f00ac403c7515b4a00328799` | `pipelines/oracle_grounded/families.py:971–987,1087–1096` |

Например, точный исторический фрагмент открывается без сети:

```powershell
./aicr.ps1 read-snapshot snap-ebc29ec5e5aad7949c86622f styles.css --start 717 --end 740
```

## Что проверить в следующем исследовании

Ошибки выбора span, согласованности action и claims следует измерять отдельно от factual quality. Более строгий validator может уменьшать число пригодных outputs, не показывая, насколько модель права по существу.

В части исходных комментариев присутствуют встроенные приоритеты вроде `[P2]` и `[P3]`. Отдельные judge labels и реакции скрыты allowlist, но текст комментария сохранён, включая эти маркеры. Поэтому текущий smoke не является независимым тестом восстановления severity. Для такого теста нужен заранее зафиксированный вариант входа с маскированными bot metadata и отдельная абляция; выполненный run переписывать нельзя.

Для обучения student важно, что найденные агентом связи между файлами отсутствуют во входе текущего reranker. Сначала нужно измерить, какие задачи решаются по исходному snippet, а какие требуют нового контекста или abstention. Простая замена реакций verdict агента этот разрыв не устраняет.
