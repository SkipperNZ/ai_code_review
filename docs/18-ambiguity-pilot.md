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

Расширенный capture и его bounded pilot фиксируются отдельно после завершения. Они не заменяют приведённые результаты и не создают human ground truth.
