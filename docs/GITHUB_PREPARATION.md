# Подготовка к публикации на GitHub

Описание репозитория (поле Description):

> A protocol and local toolkit for human–AI collaboration, with explicit reasoning, versioned memory, evidence checks, and task orchestration.

Варианты Topics: `ai-agents`, `human-ai-collaboration`, `reasoning`, `verification`, `workflow`, `python`.

## Что подготовлено

- Английская вводная и команды запуска в README.
- CONTRIBUTING.md с офлайн-проверками.
- GitHub Actions: тесты, проверка логического ядра и покрытия протокола на Windows/Linux, Python 3.10/3.12.
- Исключение секретов, локальных баз, результатов запусков и настроек `.codex`.
- Лицензия MIT в `LICENSE`.

## Перед публичной загрузкой

В `memory/` находятся рабочие записи автора, включая учебный профиль читателя, ошибки и решения. Автор разрешил сохранить эти файлы (2026-10-06). По отдельному поручению автора история Git заменена одним начальным коммитом с текущими файлами; прежние коммиты сохранены в локальной резервной копии вне публикации. Локальные `.protocol/`, `data/`, `runs/` и `.codex/` не входят в коммит.

Автор выбрал MIT. Текст лицензии находится в `LICENSE`; автор в строке copyright указан по имени автора Git-коммитов.

На GitHub создайте пустой репозиторий без автоматически созданных README и LICENSE. Затем проверьте состав коммита:

```powershell
git status --short
git add .
git diff --cached --stat
git diff --cached
```

После просмотра файлов создайте коммит и подключите адрес своего репозитория:

```powershell
git commit -m "Prepare project for GitHub"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin HEAD
```

Если `origin` уже настроен, проверьте `git remote -v` и используйте существующий адрес. Эти команды публикуют историю текущей ветки; сами подготовительные изменения публикацию не выполняют.
