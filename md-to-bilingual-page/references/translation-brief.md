# Translation brief

Give this to whoever writes the other language. It works in both directions. The Chinese rules come from a real report that went through several rounds with the reader.

## The file

Write one Markdown file with the same shape as the source: the same headings at the same levels, the same table rows and columns, the same list items in the same order, the same links. The two languages sit side by side in one page. In the default 中英对照 view each paragraph and list item is shown next to its translation, and the switch keeps the reader's place by section, so one source paragraph is one translated paragraph. A merged bullet, a split paragraph or a dropped row breaks the pairing.

Write it with the Write tool, never through a shell heredoc. The shell eats `$0` and `$50` in the text.

These stay byte for byte the same: inline code, code blocks, file paths, commands, addresses, the target of every link (`(#anchor)` links included), numbers, dates' numbers, money.

Evidence labels change language and stay in the same place in the sentence: `[RUN]` is `[实测]`, `[READ]` is `[读过]`, `[EST]` is `[估算]`. Source numbers stay and notes are translated: `[READ, S15]` is `[读过, S15]`, `[RUN, on stand-ins]` is `[实测，替身]`, `[RUN on real GitHub, 3 Nov]` is `[实测，在真实 GitHub 上，11 月 3 日]`.

Other labels at the start of a line are translated plainly and keep their colon: `NOT TESTED:` is `没测过：`, `Why:` is `为什么：`, `Where:` is `在哪：`, `Risk:` is `风险：`.

## Accuracy comes first

Every fact, number, date, limit and hedge keeps its strength. "About", "probably", "may", "assumed", "likely", "not proven", "my guess" must survive. Add nothing and drop nothing. The one allowed addition is below, under the reader. Keep the person the same as the source: where it speaks to the reader, use 你; where it talks about a named person in the third person, keep the name, never turn it into 你 or a guessed pronoun.

## The reader

Unless the task says otherwise, the reader is the person who asked for the page: here assumed to be a native Chinese speaker who reads code comfortably but is new to the modern web stack and used to build in WordPress. Terms such as store, seam, gate, webhook or Worker are not self-explanatory to them. Adjust this paragraph to the real reader.

So the first time a technical term appears in the Chinese, follow it with a few plain words in full-width brackets, and use the WordPress equivalent if there is one: `webhook（一边出了事就去按另一边的门铃）`. Do this once per term in the whole file, and only for terms a website builder wouldn't know. Gloss at most about one term per paragraph, pick the one that matters, and skip terms the source already explains.

A gloss says what a word means in general, nothing more. It never carries a number, a claim, a comparison or a verdict about this project, because those can't be checked against the source.

## Into Chinese

Simplified Chinese. Call the reader 你, never 您. The author is 我.

Rewrite, don't translate. It should read as if a Chinese engineer wrote a plain memo to a friend. Test each sentence: would a Chinese writer have said it this way? Use short sentences, break long English sentences up, and keep one-word verdicts blunt.

Avoid translation tone: 进行, 关于, 对于, 基于, 作为, 通过……来, 以及, 其, 该, 将, 被, chains of 的, a needless 一个, and 然而, 此外, 因此 at the start of a sentence. Avoid marketing jargon: 赋能, 闭环, 抓手, 底层逻辑, 沉淀, 打造, 助力, 痛点.

Typography:

- Full-width punctuation in Chinese sentences: ，。：；？！（）“”、
- One space between Chinese and Latin letters or digits: `发布 20 分钟后`, `hub 的测试`, `在 GitHub 上`. The same around inline code. No space next to full-width punctuation.
- Ranges use 到: `2 到 3 分钟`.
- Dates: `11 月 11 日`, `2026 年 9 月 28 日`. NZDT becomes （新西兰夏令时）.
- Money stays as it is: `US$0`, `NZ$30`.
- No dashes (— or ——) and no ellipsis. Use a comma, colon or full stop.

Keep product and plan names in English: Astro, Cloudflare, Cloudflare Pages, Workers, D1, R2, KV, GitHub, GitHub Actions, Git, Claude, ChatGPT, OpenAI, CMS, CPU, JSON, Mac. Keep the reader's own working words such as `hub` and `token` in English (never write 令牌 for token).

Example glossary of words to use every time (replace it with the project's own terms, and keep one Chinese word per English word all the way through):

| English | Chinese |
|---|---|
| publish | 发布 |
| undo | 撤销 |
| draft | 草稿 |
| repository | 仓库 |
| store (where content lives) | 存储, never 商店 |
| commit, push | 提交, 推送 |
| build, deploy | 构建, 部署 |
| restore | 恢复 |
| workflow (GitHub) | 工作流 |

## Into English

Plain, direct British-leaning English, the way a capable colleague writes to a friend. Short sentences, plain verbs, contractions are fine. Keep the same words for the same things all the way through. Say what something does before naming it. No em dashes, and no marketing words.

## Before you finish

Reread the whole text once against the source, paragraph by paragraph: first for accuracy, looking for dropped hedges, then for whether it sounds native.
