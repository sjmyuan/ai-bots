# Import necessary libraries
from openai import OpenAI
from datetime import datetime
from st_copy_to_clipboard import st_copy_to_clipboard
import streamlit as st
import logging
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Function to format content with a quote
def quote_content(content: str) -> str:
    """Format content with a quote."""
    lines = content.splitlines()
    modified_lines = ["> " + line for line in lines]
    return "\n".join(modified_lines)

def save_session_to_db(db, session):
    """Save the session to MongoDB using an upsert operation."""
    if not session["messages"] or db is None:
        return
    db.sessions.update_one(
        {"id": session["id"]},
        {
            "$set": {
                "user": session["user"],
                "name": session["name"],
                "create_time": session.get("create_time", datetime.now()),
                "bot_id": session["bot_id"],
                "messages": session["messages"],
            }
        },
        upsert=True,
    )

def initialize_openai_client(api_key, base_url):
    """Initialize the OpenAI client."""
    try:
        return OpenAI(api_key=api_key, base_url=base_url)
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        st.error("Failed to initialize OpenAI client. Please check the API key and base URL.")
        st.stop()

def display_chat_messages(session, db):
    """Display chat messages."""
    for idx, msg in enumerate(session["messages"]):
        if msg["role"] == "truncation":
            # Display truncation message as a gray line
            st.markdown("<hr style='border-top: 1px solid #ccc; margin: 10px 0;'><div style='text-align: center; color: #888;'>truncated</div>", unsafe_allow_html=True)
            continue
            
        with st.chat_message(msg["role"]):
            message_content = quote_content(msg["reasoning_content"]) + msg["content"]
            st.markdown(message_content)
            
        # Use columns to position the buttons at the bottom right
        # If this is the last message and not generating a response, add the truncate button
        cols = st.columns([8, 1, 1])
        if idx == len(session["messages"]) - 1 and not st.session_state.get("generating_response", False):
            with cols[1]:
                if st.button("✂️", key="truncate_button"):
                    # Insert truncation message
                    session["messages"].append({
                        "role": "truncation",
                        "content": "",
                        "reasoning_content": ""
                    })
                    save_session_to_db(db, session)
                    st.rerun()  # Refresh the UI to show the truncation
        with cols[2]:
            st_copy_to_clipboard(msg["content"], key=f"copy_{hash(msg['content'])}_{idx}")

def handle_user_input(session, client, model, system_prompt_list, db):
    """Handle user input and generate assistant response."""
    if prompt := st.chat_input():
        # Append the user message to the session
        session["messages"].append({"role": "user", "content": prompt, "reasoning_content": ""})

        # Display the user message
        with st.chat_message("user"):
            st.markdown(prompt)
        cols = st.columns([8, 1, 1])
        with cols[2]:
            st_copy_to_clipboard(prompt, key=f"copy_{hash(prompt)}_input_latest")

        # Create the chat completion stream
        try:
            with st.chat_message("assistant"):
                # Set flag to indicate response is being generated
                st.session_state.generating_response = True
                
                # Get messages after the last truncation efficiently (reverse search)
                messages_to_send = []
                found_truncation = False
                
                # Scan messages from newest to oldest
                for msg in reversed(session["messages"]):
                    if msg["role"] == "truncation":
                        found_truncation = True
                        break
                    messages_to_send.insert(0, {
                        "role": msg["role"],
                        "content": msg["content"]
                    })
                
                # If truncation was found, modify the first user message
                if found_truncation and messages_to_send:
                    first_user_idx = next((i for i, msg in enumerate(messages_to_send) if msg["role"] == "user"), None)
                    if first_user_idx is not None:
                        messages_to_send[first_user_idx]["content"] = f"<user_input>{messages_to_send[first_user_idx]['content']}</user_input>"
                
                # If no truncation found, use all messages
                if not found_truncation:
                    messages_to_send = [
                        {"role": msg["role"], "content": msg["content"]}
                        for msg in session["messages"]
                    ]
                
                stream = client.chat.completions.create(
                    model=model,
                    messages=system_prompt_list + messages_to_send,
                    stream=True,
                )

                # Write the stream to the chat
                response, reasoning_response = write_stream(stream)
                
                # Reset the generating response flag
                st.session_state.generating_response = False
                
                
            cols = st.columns([8, 1, 1])
            with cols[2]:
                st_copy_to_clipboard(response, key=f"copy_{hash(response)}_output_latest_2")
            with cols[1]:
                if st.button("✂️", key="truncate_button_after_response"):
                    # Insert truncation message
                    session["messages"].append({
                        "role": "truncation",
                        "content": "",
                        "reasoning_content": ""
                    })
                    save_session_to_db(db, session)
        except Exception as e:
            # Reset the generating response flag in case of error
            st.session_state.generating_response = False
            logger.error(f"Failed to create chat completion: {e}")
            st.error("Failed to create chat completion. Please check the model and messages.")
            st.stop()

        # Append the assistant message to the session
        session["messages"].append({
            "role": "assistant",
            "content": response,
            "reasoning_content": reasoning_response,
        })

        # Set the session name if it is not already set
        if not session["name"]:
            session["name"] = prompt[:50]
            st.session_state.bot_sessions.append(session)

        save_session_to_db(db, session)

        st.rerun()  # Refresh the UI to show the truncation

# Main function to handle the bot page
def botpage(db):
    # Get the current session and model
    session = st.session_state.current_session
    model = st.session_state.current_model
    
    # Find the bot based on the session's bot ID
    try:
        bot = next(b for b in st.session_state.bots if b["id"] == session["bot_id"])
    except StopIteration:
        logger.error("No bot found with the specified ID.")
        st.info("There is no bot available.")
        st.stop()
    
    # Set the name of the session
    name = session["name"] or bot["name"]
    
    # Display the title and captions
    st.title(name)
    st.caption(f"Bot: {bot['name']}")
    st.caption(f"模型: {model['name']}")

    # Define the system prompt
    system_prompt = {"role": "system", "content": bot["prompt"]}

    # Initialize the OpenAI client
    client = initialize_openai_client(model["api_key"], model["base_url"])

    # Initialize the session state for generating_response if not already set
    if "generating_response" not in st.session_state:
        st.session_state.generating_response = False

    # Display the chat messages
    display_chat_messages(session, db)

    # Handle user input
    handle_user_input(session, client, model["model"], [system_prompt] if system_prompt["content"].strip() != "" else [], db)

# Function to handle the streaming of chat responses
def write_stream(stream):
    response = ""
    reasoning_response = ""
    container = None
    for chunk in stream:
        message = ""
        reasoning_message = ""
        if len(chunk.choices) == 0 or chunk.choices[0].delta is None:
            # The choices list can be empty, e.g., when using the AzureOpenAI client, the first chunk will always be empty.
            message = ""
        else:
            if hasattr(chunk.choices[0].delta, "reasoning_content") and chunk.choices[0].delta.reasoning_content:
                reasoning_message += chunk.choices[0].delta.reasoning_content
            else:
                message += chunk.choices[0].delta.content or ""

        # Continue if there is no content and reasoning content
        if not message and not reasoning_message:
            continue

        first_text = False
        if not container:
            container = st.empty()
            first_text = True

        response += message
        reasoning_response += reasoning_message

        # Only add the streaming symbol on the second text chunk
        container.markdown(quote_content(reasoning_response) + response + ("" if first_text else " | "))

    # Flush the stream
    if container:
        container.markdown(quote_content(reasoning_response) + response)
        container = None
    return response, reasoning_response
