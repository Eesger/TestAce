# X.com Bookmark Archive — Setup Guide

This repo provides a base Obsidian vault + Web Clipper templates for capturing and curating insights from your X.com bookmarks with AI-powered summarization.

## Architecture

```
You bookmark on X.com
    ↓
Click Web Clipper extension on the page
    ↓
Choose template (Tweet or Article)
    ↓
AI Interpreter runs Claude prompts (via OpenRouter)
    ↓
Markdown note with summary + key ideas + tags → Obsidian vault
    ↓
Browse, search, and discover connections in Obsidian
```

## Prerequisites

1. **Obsidian** (v1.4+) — [download](https://obsidian.md)
2. **Obsidian Web Clipper** extension — [Chrome](https://chromewebstore.google.com/detail/obsidian-web-clipper/cnjifjpddelmedmihgijeibhnjfabmlf), [Firefox](https://addons.mozilla.org/firefox/addon/web-clipper-obsidian/)
3. **OpenRouter API key** (free tier works) — [sign up](https://openrouter.ai)
   - OpenRouter gives you access to Claude and many other models
   - Free tier is sufficient for personal use; you only pay for tokens used

## Installation Steps

### 1. Clone or download this vault

```bash
git clone <repo-url>
cd TestAce
```

Or download the `vault/` folder and open it in Obsidian as your vault.

### 2. Open the vault in Obsidian

- Launch Obsidian
- Click "Open folder as vault"
- Select `vault/` from this repo

### 3. Get your OpenRouter API key

1. Go to [openrouter.ai](https://openrouter.ai)
2. Sign up (free)
3. Go to Keys section and create an API key
4. Copy it (you'll need it in the next step)

### 4. Configure Web Clipper with templates

1. Open any X.com page (tweet, article, or bookmark)
2. Click the **Obsidian Web Clipper** extension icon
3. Go to **Settings** (gear icon in the clipper panel)
4. Configure:
   - **Vault:** Select your vault from the dropdown
   - **Default folder:** `Bookmarks/`
   - **Interpreter settings:** 
     - Provider: `OpenRouter`
     - API Key: Paste your OpenRouter key
     - Model: `claude-3.5-sonnet` or `claude-3-opus`

### 5. Import templates

In the Web Clipper settings, under **Templates**:

1. Click **Import Template**
2. Open `templates/x-tweet-clipper.json` from this repo
3. Name it: `X Tweet - AI Summary`
4. Repeat for `templates/x-article-clipper.json` → `X Article/Linked Content`

### 6. Test it

1. Open a tweet on X.com
2. Click Obsidian Web Clipper
3. Select the **X Tweet - AI Summary** template
4. Click Clip
5. Watch the Interpreter run (it will fetch the page, send it to Claude, fill in the AI fields)
6. Check your `vault/Bookmarks/` folder — a new note should appear with summary + key ideas

## How to Capture Bookmarks

### Manual method (current workflow)

1. Go to your X.com bookmarks (`x.com/i/bookmarks`)
2. Open each bookmarked tweet or article
3. Click Web Clipper → choose template → Clip
4. The note auto-saves to `Bookmarks/` with AI analysis

### Semi-automated (for later)

The repo documents a future automated workflow using the Chrome extension "[X Clipper](https://github.com/ryotaunzai/x-clipper)" or a batch-fetch script. See `BACKLOG.md`.

## Organizing in Obsidian

After clipping a few items:

1. **Search:** Use the search bar to find notes by keyword
2. **Tags:** Notes have auto-suggested tags (e.g., `#transformers`, `#safety`). Click any tag to see related notes
3. **Graph view:** Open Graph View (left sidebar) to see connections between notes
4. **Backlinks:** Open a note and look at the "Backlinks" panel to see related clipped items

### Future enhancements

- **Dataview plugin** — query all clipped items by tag/theme/date
- **Smart Connections** — semantic search across your vault
- **Themes/** folder — manually organize related ideas
- **Dashboard** — a main overview page with recent clips + trending topics

(See `BACKLOG.md` for detailed planned features.)

## Template Fields Explained

### Tweet Template

- **Summary** — 2-3 sentence TL;DR of the tweet's core idea
- **Key Ideas** — 3-5 actionable takeaways
- **Why It Matters for AI Development** — context on relevance
- **Suggested Themes** — auto-generated tags for clustering

### Article Template

- **Executive Summary** — 3-4 sentence overview
- **Key Ideas & Takeaways** — 5-7 important concepts
- **Technical Concepts** — methodologies, frameworks, tools mentioned
- **Relevance to AI Development** — why this matters
- **Suggested Themes** — topic tags
- **Questions for Follow-up** — unexplored directions raised by the article

All AI-generated fields use Claude via OpenRouter (pay-per-token, ~$0.01 per article/tweet).

## Troubleshooting

### Web Clipper not capturing full text

- Ensure **Readability** is enabled in the Article template
- If the page has paywalls, it may not extract full content

### AI Interpreter fields empty

- Check that your OpenRouter API key is correct in Settings
- Verify you have API credits (free sign-up includes free trial credits)
- Check browser console (F12) for errors

### Can't find the vault in Web Clipper

- Ensure you've opened the `vault/` folder as your Obsidian vault
- Restart Web Clipper extension

## Next Steps

1. Clip your first 5-10 bookmarked tweets/articles
2. Review the summaries and key ideas (refine the AI prompts if needed)
3. Explore the connections in Graph View
4. Check `BACKLOG.md` for future automation features (batch bookmark pulling, semantic clustering, dashboard)

## Files Reference

- `vault/` — Obsidian vault (open this as your vault)
  - `Bookmarks/` — clipped tweets and articles
  - `Ideas/` — (future) extracted concepts
  - `Themes/` — (future) curated idea clusters
  - `Dashboard/` — (future) overview and insights
- `templates/` — Web Clipper JSON templates (import into Web Clipper settings)
- `SETUP.md` — this file
- `BACKLOG.md` — ideas and features for future versions

## Support

Questions? Issues?

- Check [Obsidian Web Clipper docs](https://obsidian.md/help/web-clipper/interpreter)
- Check [OpenRouter docs](https://openrouter.ai/docs)
- Review template JSON for syntax (Web Clipper uses a template language with `{{"prompt"}}` for AI fields)

---

**Happy clipping!** Your archive of AI insights awaits.
