Push pending AI insights from the X bookmark archiver into Open Brain.

## Steps

1. Run this command and capture the output:
   ```
   xarchiver brain-sync --json
   ```

2. Parse the JSON array. If it is empty, report "No new ideas to push" and stop.

3. For each idea in the array, call the `capture_thought` tool with:
   - **content**: a formatted markdown string built like this:
     ```
     **[{category}]** {summary}

     **Key concepts:** {key_concepts joined with ", "}
     **Source:** @{author} — https://twitter.com/{author}/status/{tweet_id}
     {if article_title exists: "**Article:** {article_title}"}
     {if article_url exists: "{article_url}"}
     ```
   - **category**: the idea's `category` field (e.g. "rag", "agents", "architecture")
   - **tags**: the idea's `tags` array
   - **source**: `"x-bookmark-archiver"`

4. Collect the IDs of all successfully pushed ideas (the `id` field from the JSON).

5. Mark them as pushed by running:
   ```
   xarchiver brain-sync --mark-pushed {space-separated ids}
   ```

6. Report a summary: how many ideas were pushed, and list their categories and top tags.
