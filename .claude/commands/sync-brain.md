Push unpublished AI bookmark insights into the Notion "AI Bookmark Knowledge Base" database.

## Steps

**1. Get pending ideas**

Run this bash command and capture the output:
```
xarchiver notion-sync --json
```

If the array is empty, report "Nothing to publish — all ideas are already in Notion." and stop.

**2. Push each idea to Notion**

For each item in the JSON array, call the `notion-create-pages` tool with:

- **parent**: `{ "database_id": "f4875bf5afb4478495f651a8b28b55b1" }`
- **properties** (use the exact property names):
  - `Name`: the `summary` field (first 200 chars)
  - `Author`: the `author` field
  - `Category`: the `category` field
  - `Tags`: the `tags` array (as multi-select)
  - `Relevance`: the `relevance_score` number
  - `Status`: `"New"`
  - `Key Concepts`: the `key_concepts` joined with `, `
  - `Tweet ID`: the `tweet_id` field (required for deduplication)
  - `Tweet URL`: the `tweet_url` field
  - `Article URL`: the `article_url` field (if present)
  - `Article Title`: the `article_title` field (if present)
  - `Bookmarked`: the `bookmarked_at` date (if present)
- **content** (Notion Markdown):
```
> 💡 {summary}

## Key Concepts
{key_concepts as bullet list}

## Original Tweet
> {tweet_text}

{if article_title and article_body:}
## Article: {article_title}
{first 2000 chars of article_body}
```

Collect each `tweet_id` → Notion page ID mapping from the create response.

**3. Record page IDs in SQLite**

After all pages are created, run one bash command per idea to record the mapping:
```
xarchiver notion-sync --set-page-id {tweet_id} {notion_page_id}
```

Or batch them:
```
xarchiver notion-sync --set-page-id tweet1 page1 --set-page-id tweet2 page2
```

**4. Report**

Summarise: how many ideas were published, what categories they covered, and any failures.
