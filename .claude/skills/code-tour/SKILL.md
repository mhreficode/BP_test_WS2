---
name: code-tour
description: Explain how the colour API code is built, the endpoints and the rules, in easy words. Use in the LEARN phase or when a team asks how the code works. Never point at suspicious code.
---

# Code tour

Use this to help a team understand the code. Keep every answer short and easy.

## Steps

1. Ask: "Which topic are we learning: C1, C2, C3, C4, C5 or C6?" Read its entry in `arena/topics.json`.
2. Say in 2 sentences what the topic is and why it matters. Use the "why" text of the topic.
3. Show the 4 layers, top to bottom:
   - API: takes the request, checks input, shapes the answer.
   - Libs: hold the colour rules (hex, family, withdrawn, mixable).
   - Data: where colours are stored. It is an in-memory stand-in for the colour database, filled from the seed data.
   - Sources: where the data comes from, and the sync step.
4. Open `app/colorlab.py` and show only the layer parts that the topic touches. Name the function. Do not paste long code.
5. Walk one endpoint of the topic from request to answer. Use `app/openapi/` for the shape of the answer.
6. Show the rules of the topic in `app/rules.md`. Say each rule in one short sentence.
7. Check understanding with one question at a time.

## Questions to ask (Socratic)

- "What does the API do when the code is spelled in small letters?"
- "Which layer should say no to a bad page number?"
- "What should the answer look like for a colour that is withdrawn?"
- "Where would you look to see the list of colours of a product?"
- "How would you know the answer is right? Which rule tells you?"

## Do not

- Do not hunt for bugs. Do not say "this line looks wrong".
- In HUNT, do not point at suspicious code. Send the team to the hunt-coach steps.
- Never read the other team's zone, `.arena/` or `arena/base/`.
- Explain a word the first time you use it: "contract = a promise about what the API sends back".
