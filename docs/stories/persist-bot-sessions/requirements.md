# Persist Bot Sessions to MongoDB

## Purpose
To store bot sessions in MongoDB for data persistence and consistency between the database and session_state.

## Documented Requirements

### 1. Session Structure
Each session should be stored as one record in MongoDB with the following structure:

```json
{
  "id": "<session id>",
  "name": "<session name>",
  "bot_id": "<bot id>",
  "messages": [
    {
      "role": "<system|user>",
      "content": "<content>",
      "reasoning_content": "<reasoning content>"
    }
  ]
}
```

### 2. Collection Name
Use "sessions" as the collection name in MongoDB.

### 3. Caching
Implement caching using Streamlit:
- `cache_data` for query caching
- `cache_resources` for database connection caching
Set cache TTL to 10 minutes.

### 4. Session Updates
Update the session in the database using an upsert operation when:
- A new message is submitted by the user or returned by the bot
- There are messages in the session
Do not save sessions to the database if there are no messages.

### 5. Data Consistency
Ensure data consistency between the database and session_state.
