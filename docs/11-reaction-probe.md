# Проверка реальных реакций отдельно от model smoke

Дополнительный capture `data/reaction-probe` собран 22 октября 2026 года по московскому времени. Он не добавлялся в основной `smoke-compact-e998172b268c` и не использовался для изменения prompt. Выборка целевая: PR найдены поиском видимых реакций, поэтому по ней нельзя оценивать частоту реакций или noise rate.

| Репозиторий / PR | Комментарии Sourcery | Человеческие 👍 | Реакции самого бота | Состояния после фильтрации |
| --- | --- | --- | --- | --- |
| [Nuitka/Nuitka #3984](https://github.com/Nuitka/Nuitka/pull/3984#discussion_r3681309122) | 3 | 1 | 6 | 1 positive, 2 no_observed_human_thumb |
| [BoboTiG/python-mss #272](https://github.com/BoboTiG/python-mss/pull/272#discussion_r1466140111) | 2 | 1 | 4 | 1 positive, 1 no_observed_human_thumb |
| [streamyfin/streamyfin #664](https://github.com/streamyfin/streamyfin/pull/664#discussion_r2063913276) | 1 | 0 | 2 | 1 no_observed_human_thumb |
| Всего | 6 | 2 | 12 | 2 positive, 4 no_observed_human_thumb |

На каждом из шести замечаний Sourcery оставил собственные `+1` и `-1`. Поэтому агрегированные счётчики показывают оба знака даже там, где нет человеческой оценки. Collector сохраняет события, тип автора и `is_self`; `signal_state` исключает bot/self events из человеческого target. По одним summary counts все шесть ошибочно выглядели бы конфликтующими. Это проверенная ошибка возможной агрегации, а не обнаруженные случайные клики людей.

Человеческие dislikes в этой выборке отсутствуют. Наличие лайка не доказывает factual correctness и не объясняет мотивацию автора. Reaction head по двум примерам не обучалась. Дополнительных model generations на этих шести samples не выполнялось.

`positive` здесь означает наблюдаемое событие к моменту capture, без фиксированного 14-дневного окна. Один из лайков появился значительно позже комментария. Исходные timestamps сохранены; windowed targets и censoring должны строиться отдельно.

## Что проверено

Использован обычный collector без изменения его логики. Лимит дополнительного REST capture — 25 запросов; фактически сделано 10. Часть endpoints завершилась `HTTPError`; пять отсутствующих responses получены через подключённый GitHub fetch tool и сохранены с `capture_transport=github_connector`. Ранее сохранённые responses не перезаписывались. Повторная нормализация из кеша не обращалась к сети. Transport provenance и целевой характер отбора записаны в `manifests/selection.json`.

Собраны три исторических snapshots. Anchor доступен у всех шести samples, body history — exact_at_t0; два samples имеют exact snapshot, четыре — partial. Strict eligibility здесь означает неизменённый body и подтверждённый anchor, а не полноту всего репозитория. Валидатор записей прошёл без ошибок. Сигналы остаются отдельно от blinded model context.

Локальные артефакты:

- `data/reaction-probe/normalized/samples.jsonl` — комментарии и provenance;
- `data/reaction-probe/signals/user-signals.jsonl` — отдельные события;
- `data/reaction-probe/manifests/reaction-probe.json` — сводка и source links;
- `data/reaction-probe/manifests/data-audit.json` — результат валидации;
- `data/reaction-probe/raw/github/` — кеш с указанием transport;
- `.cache/reaction-probe-config.json` — использованный локальный config.

Для нового независимого capture скопировать default config, заменить seeds тремя PR из таблицы, добавить `sourcery-ai[bot]` в `bot_logins`, установить `github.max_requests=25`, `github.max_pages=2` и задать новый data root. Не объединять результаты с основным smoke задним числом.

```powershell
./aicr.ps1 --config configs/reaction-probe.local.json --data data/reaction-probe-new collect
./aicr.ps1 --config configs/reaction-probe.local.json --data data/reaction-probe-new snapshot --max-snapshots 6
./aicr.ps1 --data data/reaction-probe-new validate
```

Поиск сводок дал также реакцию на review submission Vercel, но этот тип объекта не нормализуется текущим inline collector. Его нельзя приписывать случайному inline finding. Для последующего расширения нужны отдельные object kinds и правила связи с claims.
