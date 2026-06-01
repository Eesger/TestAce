from xarchiver.twitter import _parse_response, should_extract_article


SAMPLE_RESPONSE = {
    "data": [
        {
            "id": "1234567890",
            "author_id": "99",
            "text": "Great article on transformers https://t.co/abc",
            "created_at": "2024-03-01T12:00:00Z",
            "lang": "en",
            "entities": {
                "hashtags": [{"tag": "AI"}, {"tag": "LLM"}],
                "urls": [
                    {
                        "url": "https://t.co/abc",
                        "expanded_url": "https://arxiv.org/abs/2401.12345",
                        "title": "Attention Is All You Need",
                    }
                ],
            },
        }
    ],
    "includes": {
        "users": [{"id": "99", "username": "researcher", "name": "Dr. Researcher"}]
    },
    "meta": {"next_token": "abc123"},
}


def test_parse_response():
    tweets = _parse_response(SAMPLE_RESPONSE)
    assert len(tweets) == 1
    t = tweets[0]
    assert t.tweet_id == "1234567890"
    assert t.author_username == "researcher"
    assert "AI" in t.hashtags
    assert len(t.urls) == 1
    assert "arxiv.org" in t.urls[0]["expanded_url"]


def test_should_extract_article():
    assert should_extract_article("https://arxiv.org/abs/2401.12345")
    assert should_extract_article("https://techcrunch.com/2024/01/01/ai-news/")
    assert not should_extract_article("https://twitter.com/user/status/123")
    assert not should_extract_article("https://x.com/user/status/123")
    assert not should_extract_article("https://youtu.be/dQw4w9WgXcQ")
    assert not should_extract_article("https://pbs.twimg.com/media/image.jpg")


def test_empty_response():
    tweets = _parse_response({"data": [], "meta": {}})
    assert tweets == []
