---
name: gitlab-commit-email
description: Use peter@chainlayer.io for git author/committer on all GitLab repos - GitLab rejects other emails
type: feedback
---

Always use `peter@chainlayer.io` as git author and committer email for any repo hosted on `gitlab.com/chainlayer/`.

**Why:** GitLab push rules enforce the regex `(@(chainlayer\.io|noreply\.gitlab\.com)$)|^bot@renovateapp\.com$` — commits with other emails (e.g. `tyrion70@gmail.com`) are rejected.

**How to apply:** Before committing to GitLab repos, check `git config user.email`. If not set to chainlayer.io, run `git config user.email "peter@chainlayer.io"` and `git config user.name "Peter van Mourik"`.
