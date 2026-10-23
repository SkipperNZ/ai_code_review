# Дополнительные примеры с человеческими дизлайками

Отдельный capture `data/reaction-followup` содержит 7 inline-комментариев Sourcery из двух PR Nuitka: [3819](https://github.com/Nuitka/Nuitka/pull/3819) и [3763](https://github.com/Nuitka/Nuitka/pull/3763). Найдены 2 человеческих дизлайка, 1 человеческий лайк и 14 собственных реакций бота. После исключения bot/self events получаются 2 negative, 1 positive и 4 no_observed_human_thumb; конфликтов нет.

Это целевой отбор по наличию реакции, а не репрезентативная выборка. Просмотрены пять страниц по 100 последних inline-комментариев Nuitka; кандидаты Sourcery с агрегатами больше его стандартной пары +1/-1 проверены по отдельным reaction events. Для выбранных PR сохранены полные первые страницы обсуждений: 13 и 5 комментариев, обе пагинации завершены. Сбор нормализован обычным collector из кэша GitHub connector, без дополнительных сетевых запросов collector. Метаданные публичности repository взяты из сохранённого GitHub capture. Raw payloads и provenance остаются в data, за пределами ZIP исходников.

Все 7 code anchors проверены по двум исходным commit SHA. Snapshots частичные. У 6 комментариев исходный body совпадает с доступной версией по created_at/updated_at; единственный current_only комментарий имеет человеческий лайк. Оба выбранных дизлайка strict_eligible по body history и anchor. Это не означает полноту репозитория или достоверность вывода teacher. Schema/data audit прошёл.

Подготовлены 6 слепых human packets в `data/reaction-followup/human`: один точный повтор текста по тому же path исключён стандартным sampler. Ручных аннотаций пока нет. Основные 240 packets и первые 6 supplemental packets находятся в своих отдельных data roots.

## Два заранее выбранных случая

1. [Версия actions/checkout](https://github.com/Nuitka/Nuitka/pull/3819#discussion_r2937423021), `gh-1df3c3ec719b49e80b610c4f`. Комментарий от 15 марта 2026 утверждает, что `actions/checkout@v6` ещё не существует. Человеческий дизлайк зарегистрирован через несколько минут. Для проверки этого утверждения нужны сведения о внешней зависимости, а не только YAML репозитория.
2. [Регрессионный тест builtins](https://github.com/Nuitka/Nuitka/pull/3763#discussion_r2791294530), `gh-6cd2537d62b3951fd33a79cc`. Бот предлагает заменить печать полного словаря проверкой типа и идентичности. Человеческий дизлайк зарегистрирован в тот же день. Причину реакции нельзя установить из самой кнопки; для оценки рекомендации нужен контекст тестового harness и цель regression test.

Оба дизлайка принадлежат аккаунтам type=User и не автору-боту. Исходные events сохранены; реальные намерения людей не известны.

## Воспроизводимый демонстрационный запуск

```powershell
.\.venv\Scripts\python.exe scripts/run_selected.py --data data/reaction-followup --name reaction-demo --comment-id 2937423021 --comment-id 2791294530 --modes local agent
.\aicr.ps1 --data data/reaction-followup evaluate runs/<reaction-demo-id>
.\aicr.ps1 --data data/reaction-followup triage runs/<reaction-demo-id>
```

Выполнен run `reaction-demo-aa1873b6e430`: 2 комментария × 2 режима после освобождения основной очереди. Все 4 ответа прошли validators, без format repair; agent выполнил 12 tool calls. Такой запуск не проходит размерный gate основного 40×3 smoke и не используется для оценки noise rate. Входы модели построены тем же allowlist, без реакций, человеческих ответов и внешних проверок ниже. Подбор примеров после просмотра сигналов раскрыт явно.

| Случай | Local | Agent | Post-hoc triage |
| --- | --- | --- | --- |
| checkout v6 | partially_supported / rewrite | partially_supported / request_context | negative сохранён; context_unresolved, preference_present |
| function builtins | partially_supported / rewrite | partially_supported / rewrite | negative сохранён; context_unresolved, preference_present |

В первом случае agent подтвердил три ссылки на v6 в YAML, но оставил существование внешнего релиза unverifiable. Во втором прочитал getter в CompiledFunctionType.c, но не дошёл до поведения test runner. Общий verdict не изменился в обоих случаях. Подтверждение простых наблюдений о коде не разрешает центральный спор и не делает дизлайк ошибочным.

`tests/basics/run_all.py` существует в snapshot (124 строки), но агент его не прочитал. Последний поиск использовал другой prefix `tests/run_all.py`. Поэтому нехватка этого контекста здесь является ограничением retrieval/бюджета, а не доказанной недоступностью файла в архиве.

Blinded input исходного `reaction-demo-aa1873b6e430` не содержит отдельного comment timestamp или body-history status: они сохранены в capture/manifest и учитываются при отборе, но не передавались teacher. В следующей [итерации](14-hardening.md) эти поля добавлены в allowlist `blinded-context-0.2`. Они не заменяют внешние исторические источники и не дописываются в прежний frozen run.

## Отдельная проверка внешнего источника

GitHub API официального [релиза actions/checkout v6.0.0](https://github.com/actions/checkout/releases/tag/v6.0.0) сообщает `published_at=2025-11-20T16:24:08Z`: раньше комментария от 2026-03-15. Это противоречит утверждению бота о том, что версия ещё не опубликована. Проверка выполнена ассистентом по источнику и сохранена в `manifests/external-evidence.json`, отдельно от teacher input. Она не является независимой человеческой аннотацией и не доказывает мотивацию дизлайка.

Текущие инструменты Pi ограничены snapshot, поэтому teacher не может получить эту release chronology через tool. Для такого случая обоснованная неопределённость полезнее уверенной оценки по устаревшему знанию модели. Контракт внешних источников с temporal cutoff — отдельное расширение следующей итерации.

## Ошибка в обосновании самого teacher

Объяснение agent о builtins переносит свойства глобального имени `__builtins__` в модуле `__main__` на атрибут `emptyFunction.__builtins__`. Это разные объекты: [документация Python](https://docs.python.org/3.13/reference/datamodel.html#function.__builtins__) описывает атрибут функции как ссылку на словарь builtins namespace, начиная с Python 3.10.

После demo выполнен отдельный короткий probe на установленном CPython 3.13.0: глобальный `__builtins__` имеет тип module, `emptyFunction.__builtins__` — dict, а его идентичность `builtins.__dict__` равна true. Код из чужого репозитория не запускался. Snippet и результаты сохранены в `manifests/builtins-runtime-probe.json`. Это не проверка всей логики Nuitka и не human annotation, но она показывает ошибочность соответствующего обобщения teacher. Исходный assessment остаётся неизменным.

Таким образом, 4/4 технически валидных outputs не означают 4/4 фактически верных объяснений. Ошибку нельзя обнаружить одной проверкой JSON или точности цитат. Аналогично неизвестную причину дизлайка нельзя восстановить из уверенного текста модели.
