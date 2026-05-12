# Terminator — final answer style guide

When the reflector decides `done=True`, the `answer` field is what the user
sees as the final response. This file is the style guide for that answer.

## Format

A short paragraph (2-4 sentences), then a bulleted breakdown.

## Required elements

1. **Lead with the outcome** — "Got everything you asked for", "Got most of
   the basket — strawberries are off-season everywhere", etc.
2. **Itemize what was bought**, with quantities and the shop it came from:
   ```
   - 2 mangoes (alphonso) from tropical_paradise — $5.00
   - 1 pineapple from global_imports — $8.00
   ```
3. **Total cost**: `Total: $13.00 across 2 shops.`
4. **Anything missing or partial** — call it out explicitly:
   ```
   Couldn't source: strawberries (off-season at every shop in this market).
   ```

## Voice

Warm but factual. No marketing speak. No emojis. The user knows it's a
demo agent, not a person — they want clarity, not personality cosplay.

## Don't

- Don't apologize repeatedly for what's missing — mention it once, factually.
- Don't speculate about future availability ("try again next month") —
  this is a one-turn agent, no follow-up.
- Don't editorialize on price ("a great deal!") — just state numbers.
