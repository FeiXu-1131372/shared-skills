---
name: human-cover-letter
description: Write, rewrite or review a job cover letter (or a short "why this role" application answer) so it is short, true, specific and sounds like one real person wrote it. Use whenever the user asks for a cover letter, says a letter sounds like AI, robotic, generic or too long, wants it more human or more natural, pastes a job ad and asks for an application note, or asks to tailor or tighten a letter. Also use before sending any AI-drafted application text. Works for any country; has NZ notes.
---

# Human cover letters

A cover letter has one job: make a busy reader believe, in under a minute, that this person did something real that matches what the role needs, and that they chose this role on purpose. Everything below serves that. It is not a trick to fool AI detectors. It is a way to put real content on the page, which is also what makes a letter read as human.

## Why these rules (short evidence list)

Tags: `sourced` = read in full; `weak` = vendor, search summary or single study; `inferred` = my reading. Full list in `references/sources.md`.

- Recruiters "can often spot the difference" between AI-written and personal applications. Employers want to be "confident that your CV and cover letter are truthful and show who you are". NZ government careers site, updated 29 Sep 2026. `sourced`
- When AI made ad-matching letters easy, the link between a letter that matches the ad and a callback fell 51% in one platform study, and employers leaned on work history instead. Time spent editing the AI draft still helped. Cui, Dias, Ye, arXiv 2509.25054. `weak` (one working paper)
  - So matching the ad's words is now the entry fee, not the proof. What still works is detail only this person has.
- Wikipedia's AI-cleanup guide lists patterns in machine text: puffed-up importance words, "not just X but Y", lists of three, tails like "highlighting its significance", em dashes, bold labels on bullets. It also warns that humans are poor at spotting AI text, and that fixing symptoms is not the same as fixing the cause. `sourced`
  - So do not "scrub" a bad letter. Replace the empty content with true specifics.
- Short plain writing: ordinary words, simple sentences, draft fast then cut. Paul Graham, "Write Simply". Orwell: cut every word you can, use the active voice, use a short word where it will do. `sourced`
- Length: most career sites say 250 to 400 words. The numbers come from vendors and are `weak`. If the ad says "short", believe the ad. Aim for 200 to 280 words by default, and under 250 when the ad asks for short.

## Workflow

1. **Read the whole ad, live, and the form's own prompt.** Pull the exact words for what they ask. Note anything about the letter itself: length ("short", "briefly"), questions to answer, a named contact. The application form or box often has its own instruction (for example "introduce yourself, explain why you are suitable, consider skills, qualifications and experience"). Ask the person to paste it if you have not seen it. That prompt beats every default here: answer each thing it names, in its order, at the length it implies ("briefly" means about 150 to 220 words).
2. **Collect the facts.** Use the person's CV, their notes and their own words. Never invent a story, a feeling, a quote, a number, a name or a result. If the one detail that makes a letter human is missing (a moment, a mistake, what they noticed), ask for it as one question, such as "Tell me about a time this went wrong or surprised you, and what you saw that the tool or the team did not." Humanness comes from true detail. Do not fake it with typos or forced casual lines.
3. **Decide four things before writing a word.**
   - The one thing this reader most needs to believe.
   - The one proof story that shows it (not four claims).
   - The person's real reason for this role. It must come from the ad and be true for them. If you cannot tell, draft one from the ad's own words and mark it "confirm this is true".
   - The one gap a reader would notice, if any. It gets one plain sentence, no apology and no hedge.
4. **Draft in this shape** (about 5 short paragraphs, no headings):
   - Opening, 1 to 3 sentences: who the person is (name, place, years, main stack) if the prompt says "introduce yourself" or the ad names no contact; then the role and the real reason.
   - The story, 4 to 8 sentences: the situation in plain terms, what the person did, the choice or mistake, what happened, what they would do now. Use "I", past tense, concrete nouns.
   - The match, 1 to 3 sentences: connect the story to the ad in the ad's own words, without a checklist.
   - The gap, 1 sentence, only if it matters.
   - The close, 1 sentence: something concrete the person can do next, such as a demo to share or a time to talk.
5. **Cut.** Remove every sentence that works for any employer (swap test). Remove every adjective that is a claim with no proof ("passionate", "results-driven", "strong"). Remove restating of the CV.
6. **Run the checker:** `python3 ~/.claude/skills/human-cover-letter/scripts/check_letter.py letter.txt` (word count, long sentences, AI-pattern flags, bold or bullets, American spelling). Fix flags that are real. A flag is a prompt to look, not proof.
7. **Hand over** the letter in a plain-text block ready to paste. Add: word count, what the person must confirm, and what you left out on purpose. Never leave brackets in a letter marked ready.

## Voice rules

- Write as the person would say it to a sensible stranger across a table. Contractions are fine (I'm, I'd, couldn't). Say "I built", not "I was responsible for building".
- Plain verbs: "has" not "boasts" or "features", "is" not "serves as", "use" not "leverage", "help" not "facilitate".
- One idea per sentence. Average about 15 words, longest about 25. Mix in a few very short ones. Do not make every sentence the same length.
- Concrete over abstract: name the system, the number, the customer type, the day. "The first message of a chat carries no signals" beats "an edge case in the guard logic".
- First person, active voice, past tense for what happened. Present tense for what they want.
- Own the limits. "I haven't used X at work" is believable and short.
- Local spelling and phrasing (NZ and UK: organisation, optimise, programme only for a course). Greeting: "Kia ora" in NZ, a name if the ad gives one, otherwise "Hello".
- No em dashes. Few semicolons. At most one short list, and only when the ad is a pure checklist and the reader is a screener. Default to prose.
- Format for the box: plain text. Many application boxes (SEEK, LinkedIn) show markdown as stray symbols. No bold, no headings, no tables.

## Self-tests before handing over

- **Swap test:** change the company name. Does the letter still work? Then it is generic. Add the reason or cut the line.
- **Only-I test:** could a stranger with the same CV have written the story? If yes, the story lacks a detail only this person would know.
- **Friend test:** read it aloud. Mark every phrase the person would not say to a friend. Rewrite those.
- **Proof test:** next to every claim, can you point to a CV line, a repo, a note or the person's words? If not, cut it or mark it unconfirmed.
- **Prompt test:** list every thing the form or ad asks the letter to do (introduce, why suitable, skills, qualifications, experience, a specific example). Find the sentence that answers each. A missing item is a defect, even if the rest is good.
- **Length test:** under the ad's limit, and the opening says the point.

## Do not

- Do not promise it will pass an AI detector, and do not add errors on purpose.
- Do not claim hand-written work when tools did the work. Say what the person decided, specified and checked.
- Do not copy the ad's headings back as the letter's structure. That reads as a template.
- Do not send AI text unedited. Tell the person to read it aloud and change what is not theirs.

## Pattern list

For the full list of machine-sounding patterns, with plain replacements and where each came from, read `references/ai-tells.md`. For sources and how strong each is, read `references/sources.md`.
