---
name: wt
description: "Git worktree の一覧・作成・撤去を、標準の git worktree コマンドで扱う。"
---

# Git worktree

`git worktree list --porcelain` と対象ブランチを確認する。作成時は指定のブランチとパスを使用し、既存ブランチには `git worktree add <path> <branch>`、新規ブランチには `git worktree add -b <branch> <path> <base>` を使う。実行後に作業パスとブランチを確認する。

撤去前に対象 worktree の `git status --short` と一覧を確認する。作業差分がある場合は状況を報告して判断を求める。明示された対象を通常の `git worktree remove <path>` で撤去し、一覧から外れたことを確認する。
