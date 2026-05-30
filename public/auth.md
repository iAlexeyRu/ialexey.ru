# auth.md

Welcome, AI Agent! This page details how you can authenticate with the APIs and services hosted on `ialexey.ru`.

## Public APIs (No Auth Required)
For standard content access and reading, you do not need credentials:
- **Telegram Feed (JSON)**: `https://ialexey.ru/feed.json`
- **Telegram Feed (RSS)**: `https://ialexey.ru/feed.xml`
- **Sitemap**: `https://ialexey.ru/sitemap-index.xml`
- **LLMs Guide**: `https://ialexey.ru/llms.txt`
- **OpenAPI Spec**: `https://ialexey.ru/openapi.json`

## Protected APIs
Currently, all statistics, tracking, and content signals endpoints are write-only/public or protected via server-side secrets. If you require programmatic management access, please register:

### Registration Process
1. Contact the owner via email or Telegram (`@iAlexeyRu`).
2. Provide your agent client name, contact metadata, and intended scope.
3. Upon approval, you will receive a Client ID and Client Secret.

### OAuth Endpoints
We support OAuth 2.0 and OpenID Connect protocols:
- **OpenID Configuration**: `https://ialexey.ru/.well-known/openid-configuration`
- **OAuth Authorization Server**: `https://ialexey.ru/.well-known/oauth-authorization-server`
- **OAuth Protected Resource**: `https://ialexey.ru/.well-known/oauth-protected-resource`
