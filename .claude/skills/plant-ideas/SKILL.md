---
name: plant-ideas
description: Help a team plant 2 small bugs in their own topic zone during the PLANT phase. Offers ideas inside the zone only, keeps a secret note of each bug. Use when the phase is PLANT.
---

# Plant ideas

Use this in PLANT. The team plants 2 bugs in the topic they own this round.

## Steps

Plant one bug at a time. Finish bug 1 (change, then log-bug) before you start bug 2.

1. Check the phase and topic with `python3 arena/arena.py status`. The topic must be one the team plants.
2. Ask: "What kind of mistake do you want to plant?" Wait for the answer.
   If they have no idea, offer 3 ideas. Stay inside the zone of this topic only (between `# >>> ZONE Ck` and `# <<< ZONE Ck`). Ideas by kind:
   - a wrong value (a field is changed, a case is lost),
   - a wrong edge (first page, last page, empty list, limit of 50),
   - a missing check (bad input is let in),
   - a wrong order or a wrong count.
3. Run `python3 arena/arena.py plant-start Ck`. This makes a sandbox copy. Edit the sandbox only.
4. Help them make ONE change in ONE place. Keep it small: 8 lines at most.
5. Ask: "Which request shows the bug?" Write it as `METHOD /path`, for example `GET /colors/BP1001`.
   The answer to that request must differ from the clean answer.
6. Save it right away: `python3 arena/arena.py log-bug --topic Ck --note "what it does" --trigger "GET /colors/BP1001"`.
   Add `--rule R04` if they know the rule the clean answer follows.
   After the save, the sandbox goes back to the clean code. This is normal.
7. Only now start bug 2. Do steps 2 to 6 again, in a different spot. The tool says no to a third bug.
   If log-bug says the bug overlaps, pick a different spot. Do not read `.arena/`.
8. Ask the team to confirm. Then run `python3 arena/arena.py give Ck`.

Rules for planting:
- Never edit the sandbox twice before a log-bug.
- Never make bug 2 before bug 1 is saved.

## Idea seeds per topic

These are ideas to offer, not code. Offer 2 or 3, never all. Let the team choose and write the change.

- **C1 Right answers (R04).**
  - A colour field is served a little wrong (hex, family or formula code) for some colours.
  - The code lookup works for one letter case only.
  - One field is left out of the colour answer.
- **C2 Bad input (R01, R03).**
  - A limit is off by one (page size 50 or 51, page 0 or 1).
  - A code with the wrong shape is let in (too few digits, wrong prefix).
  - A bad search text or family is accepted instead of refused.
- **C3 Lists and search (R02, R08, R10).**
  - `totalPages` is rounded the wrong way.
  - The last page loses or repeats an item.
  - Search ignores the family, or mixes up upper and lower case, or sorts in the wrong order.
- **C4 Withdraw and mixable (R05, R06, R07).**
  - A withdrawn colour still shows up in one list.
  - A product that is not mixable gets a colour list.
  - A card counts its colours wrong after one is withdrawn.
- **C5 Keep the promise (R09, R06, R07).**
  - An error body uses another field name or shape.
  - One failure gets the wrong status number.
  - A card or product field has the wrong type or name compared with the spec.
- **C6 Release gate (R04, R06).**
  - The reset leaves some old data behind.
  - The seed version header or the reset answer says the wrong thing.
  - The card shows hex in another format than the colour list.

Check the real rule text in `arena/topics.json` and `app/rules.md` before you offer an idea.

## Questions to ask (Socratic)

- "Which rule in `app/rules.md` would your bug break?"
- "Would a customer see this? How?"
- "Is this bug easy, medium or hard to catch? Why?"
- "Can the other team catch it with a test that follows the rules?"

## Secret note

- The note and the log are secret. Never show them. Never sum up the bugs for anyone.
- If the other team asks, say: "That is their puzzle. Ask me about a rule instead."
- Do not plant bugs that use time, random numbers, files or settings. The tool refuses them.
- Never read the other team's zone, `.arena/` (except the sandbox now) or `arena/base/`.
