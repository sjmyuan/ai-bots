# Persist Bot Sessions to MongoDB

## Purpose
Persist bot sessions in MongoDB for each user, allowing them to view their sessions when they reopen the website. Each session should be stored as one record in MongoDB with a specific structure and collection name "sessions". Implement caching using Streamlit's `cache_data` for query caching and `cache_resources` for database connection caching with a TTL of 10 minutes. Update the session in the database using an upsert operation when a new message is submitted by the user or returned by the bot, but only if there are messages in the session. Fetch only the current user's sessions from the database when there is no session in session_state, with a maximum size of 50. Fetch another 50 sessions if the user clicks the "load more" button. The sessions should be sorted by create_time.

## Session Structure
Each session should be stored as one record in MongoDB with the following structure:

```json
{
  "id": "<session id>",
  "user": "<user name>",
  "name": "<session name>",
  "create_time": "<session create date time>",
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

## Acceptance Criteria
- Given a new session with a unique id, user name, session name, create time, bot id, and messages, when the session is saved to MongoDB, then it replaces any existing session with the same id.
- Given a session with no messages, when attempting to save the session, then the session is not saved to MongoDB.
- Given a user with multiple sessions, when fetching sessions from MongoDB, then only the sessions belonging to the current user are retrieved, sorted by create_time, and limited to 50 sessions.
- Given a user with more than 50 sessions, when clicking the "load more" button, then another 50 sessions belonging to the current user are fetched, sorted by create_time.
- Given caching is implemented, when querying the database, then `cache_data` is used for query caching and `cache_resources` is used for database connection caching with a TTL of 10 minutes.