# Выбор агента для проверки комментариев

Решение от 21 октября 2026 года: использовать Pi SDK с локальной моделью `qwen3.8-flash-next-mirai-s`. Qwen Code остаётся альтернативным runtime. Это проектный выбор по интерфейсам и управляемости; качество ревью двух агентов на нашей задаче ещё не сравнивалось.

## Pi и Qwen Code

Pi SDK предоставляет готовые agent sessions, model/tool integration и события; позволяет явно задавать tools и resource loader. Это подходит для контролируемых independent sessions на каждый sample. SDK работает в Node.js/Bun; в реализации используем небольшой TypeScript worker. [Pi SDK](https://pi.dev/docs/latest/sdk).

Pi поддерживает custom endpoints через конфигурацию моделей и существующие API implementations, включая OpenAI Chat Completions. Для совместимого сервера не требуется писать новый provider transport. [Pi custom providers](https://pi.dev/docs/latest/custom-provider).

Qwen Code также поддерживает OpenAI-совместимые endpoints, headless invocation, JSON/stream-JSON и лимиты turns, tool calls, wall time. Он пригоден как готовый CLI runner и запасной адаптер. Название Qwen Code не требует использовать только модели Qwen и не доказывает лучшую совместимость с конкретным кастомным deployment. [Qwen Code providers](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/model-providers/), [headless mode](https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/).

Преимущество Pi для этого проекта — возможность задать узкую session configuration и свои evidence-aware tools через SDK. Не заявляется, что его рассуждения лучше Qwen Code: за выводы отвечает выбранная модель в конкретном контексте.

## Разделение ответственности

| Слой | Выбранный компонент |
| --- | --- |
| Модель | Локальная qwen3.8-flash-next-mirai-s |
| Agent loop и provider streaming | Pi SDK |
| Инструменты чтения snapshot | Наши list_paths/search_text/read_lines/read_diff |
| Сессия, явная конфигурация, события | Небольшой TypeScript PiRunner worker |
| Сбор GitHub, snapshots, batch queue, метрики | Python harness |
| Schema, semantic/evidence validation | Наши общие validators |
| Рабочий agent runtime | Будущий NessyRunner через тот же контракт |

Готовый агент экономит реализацию сессий и tool loop. Dataset contracts, temporal controls и quality metrics остаются предметной частью нашего прототипа.

## Обязательная конфигурация PiRunner

- Одна новая session на sample/mode; никакой shared conversational memory между комментариями.
- Явный model/provider без автоматического переключения на другую модель при ошибке.
- Custom resource loader: никакого auto-discovery чужих AGENTS.md, skills, packages, extensions и MCP из исследуемого репозитория или пользовательского профиля.
- Только snapshot tools; произвольный shell, edit/write, web access и delegation не регистрируются. Custom tools проверяют реальные границы путей; `cwd` сам по себе не является sandbox.
- Режимы local/static не имеют tools; agent использует только allowlist. Одинаковые базовые prompts и model settings.
- События tool calls, usage, retries и compaction переводятся в общий trace; секреты удаляются. Pi events не подменяют dataset schema.
- Ограничения контролируются worker и внешним batch process. Internal retries учитываются в общих budget, не образуют второй неконтролируемый retry loop.
- Контекст собирается в пределах лимита. Неявная compaction не должна незаметно менять экспериментальные условия; её настройка фиксируется, а срабатывание отражается в trace.
- Финал принимается только после нашей валидации. Runtime JSON/JSONL не гарантирует соответствие assessment JSON Schema.

Pi предоставляет hooks для наблюдения запросов и tool execution; конкретные обработчики и abort semantics проверяются на выбранной версии SDK. [Pi extensions](https://pi.dev/docs/latest/extensions).

## Проверка текущей модели

Адрес: `http://192.168.2.146:30000/v1`. Секрет использован из разрешённого локального источника и не сохранялся в проект. Доступ из sandbox был ограничен; проверка с разрешённым сетевым доступом успешна.

Наблюдения одного синтетического direct API probe:

| Проверка | Результат |
| --- | --- |
| GET models | HTTP 200; exact model ID qwen3.8-flash-next-mirai-s |
| Первый chat completion | HTTP 200; finish_reason tool_calls |
| Выбор read-only инструмента | read_probe, аргументы валидны, tool_choice auto |
| Tool result → второй completion | HTTP 200; finish_reason stop |
| Финальный JSON | Совпадает с переданным через tool результатом |
| Wall time двух completions | Около 3.0 s в одном запуске |
| Usage первого запроса | 376 input, 42 output tokens |
| Usage второго запроса | 444 input, 39 output tokens; reported cached input 417 |

Этот direct probe сам по себе не проверял качество аннотации и интеграцию Pi. Затем установлен `@earendil-works/pi-coding-agent` 1.3.0: реальный SDK прошёл synthetic cross-file roundtrip и loopback fixtures с SSE, tool call, JSON repair, timeout, API error и budget exhaustion. Зафиксированный основной smoke — 40 публичных комментариев × local/static/agent. Актуальные acceptance results вынесены в [статус реализации](IMPLEMENTATION_STATUS.md), а настройки reasoning и ограничения — в [runbook](06-runbook.md).
