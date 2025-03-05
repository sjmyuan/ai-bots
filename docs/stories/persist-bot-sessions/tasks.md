Clarified Requirements:
- Persist bot sessions in MongoDB for data persistence and consistency between database and session_state
- Session structure includes id, name, bot_id, and messages array
- Use "sessions" as collection name
- Implement caching using Streamlit with 10 minute TTL
- Update sessions using upsert operation that appends new messages to existing array
- Ensure data consistency between database and session_state

Tasks:

1. Create MongoDB connection manager
   - Given no existing database connection, when initializing connection manager, then create new connection to MongoDB
   - Given existing connection in cache, when getting connection, then return cached connection

2. Implement session document model
   - Given valid session data, when creating session document, then document matches required structure
   - Given invalid session data, when creating session document, then raise validation error

3. Create session repository
   - Given valid session ID, when retrieving session, then return matching session document
   - Given non-existent session ID, when retrieving session, then return None

4. Implement upsert operation
   - Given existing session with messages, when adding new message, then append message to existing array
   - Given new session data, when saving session, then create new session document

5. Add caching layer
   - Given cache miss, when retrieving session, then fetch from database and store in cache
   - Given cache hit within TTL, when retrieving session, then return cached data
   - Given cache expired, when retrieving session, then refresh cache from database

6. Implement data consistency checks
   - Given database and session_state out of sync, when checking consistency, then raise consistency error
   - Given consistent data, when checking consistency, then return True
