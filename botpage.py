# Import necessary libraries
from openai import OpenAI
from datetime import datetime
from st_copy_to_clipboard import st_copy_to_clipboard
import streamlit as st
import logging
import os
import trafilatura
import json
from typing import Optional

# Define tools as a constant
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch and extract main content from a URL",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch content from"
                    }
                },
                "required": ["url"],
                "additionalProperties": False
            },
            "strict": True
        }
    }
]

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
                    "create_time": datetime.now(),  # Update timestamp on message changes
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
            # Display truncation message as a line crossing directly through the text
            st.markdown("""
                <div style='position: relative; text-align: center; margin: 20px 0; height: 20px;'>
                    <hr style='position: absolute; width: 100%; top: 10px; border: none; border-top: 1px solid #ccc; margin: 0;'>
                    <span style='position: absolute; top: 0; left: 50%; transform: translateX(-50%); background-color: #f0f2f6; padding: 0 10px; color: #888; font-size: 0.8rem;'>truncated</span>
                </div>
            """, unsafe_allow_html=True)
            continue
            
        if not (msg["role"] == "user" and st.session_state.get("edit_message_idx") == idx):
            with st.chat_message(msg["role"]):
                message_content = quote_content(msg["reasoning_content"]) + msg["content"]
                st.markdown(message_content)
                
            cols = st.columns([6, 1, 1, 1, 1])
            current_col =4

            with cols[current_col]:
                current_col -= 1
                st_copy_to_clipboard(msg["content"], key=f"copy_{hash(msg['content'])}_{idx}")

            if msg["role"] == "user":
                with cols[current_col]:
                    current_col -= 1
                    if st.button("📝", key=f"edit_{hash(msg['content'])}_{idx}"):
                        st.session_state.edit_message_idx = idx
                        st.rerun()

            if idx == len(session["messages"]) - 1 and not st.session_state.get("generating_response", False):

                with cols[current_col]:
                    current_col -= 1
                    if st.button("✂️", key="truncate_button"):
                        # Insert truncation message
                        session["messages"].append({
                            "role": "truncation",
                            "content": "",
                            "reasoning_content": ""
                        })
                        save_session_to_db(db, session)
                        st.rerun()  # Refresh the UI to show the truncation

                # Add retry button for the last assistant message
                if msg["role"] == "assistant":
                    with cols[current_col]:
                        if st.button("🔄", key="retry_button"):
                            # Set flag to trigger regeneration
                            st.session_state.retry_last_message = True
                            # Remove the last assistant message
                            session["messages"].pop()
                            save_session_to_db(db, session)
                            st.rerun()

        else:
            # Display the edit form
            new_content = st.text_area("Edit Message", value=msg["content"], key=f"edit_text_{idx}", height=300)
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("Submit", key=f"submit_edit_{idx}"):
                    session["messages"][idx]["content"] = new_content
                    st.session_state.edit_message_idx = None
                    # Clear all messages after the edited message
                    session["messages"] = session["messages"][:idx + 1]

                    # Reset the generating response flag
                    st.session_state.generating_response = False

                    # Save the updated session to the database
                    save_session_to_db(db, session)

                    # Trigger regeneration of the assistant's response
                    st.session_state.retry_last_message = True

                    # Rerun the app to refresh the UI
                    st.rerun()
            with col2:
                if st.button("Cancel", key=f"cancel_edit_{idx}"):
                    st.session_state.edit_message_idx = None
                    st.rerun()

def handle_user_input(session, client, model, system_prompt_list, db):
    """Handle user input and generate assistant response."""
    # Check if we need to retry the last message
    retry_mode = False
    if st.session_state.get("retry_last_message", False):
        # Reset the flag
        st.session_state.retry_last_message = False
        retry_mode = True

    if prompt := st.chat_input() or retry_mode:
        # In retry mode, we don't need a new user prompt
        if not retry_mode:
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
                
                # Start a do-while loop
                while True:
                    # Get messages after the last truncation efficiently (reverse search)
                    messages_to_send = []
                    found_truncation = False

                    # Scan messages from newest to oldest
                    for msg in reversed(session["messages"]):
                        if msg["role"] == "truncation":
                            found_truncation = True
                            break
                        message_to_add = {
                            "role": msg["role"],
                            "content": msg['content']
                        }
                        if 'tool_calls' in msg:
                            message_to_add["tool_calls"] = msg['tool_calls']
                        messages_to_send.insert(0, message_to_add)

                    # If truncation was found, modify the first user message
                    if found_truncation and messages_to_send:
                        first_user_idx = next((i for i, msg in enumerate(messages_to_send) if msg["role"] == "user"), None)
                        if first_user_idx is not None:
                            messages_to_send[first_user_idx]["content"] = f"<user_input>{messages_to_send[first_user_idx]['content']}</user_input>"

                    print(messages_to_send)

                    stream = client.chat.completions.create(
                        model=model,
                        messages=system_prompt_list + messages_to_send,
                        tools=TOOLS,
                        function_call="auto",
                        stream=True,
                    )

                    # Write the stream to the chat
                    response, reasoning_response, tool_calls = write_stream(stream)

                    session["messages"].append({
                        "role": "assistant",
                        "content": response,
                        "reasoning_content": reasoning_response,
                        **({"tool_calls": tool_calls} if tool_calls else {})
                    })

                    if not tool_calls:
                        break  # Exit the loop if there are no tool calls

                    # Handle tool calls
                    for tool_call in tool_calls:
                        if "function" in tool_call and tool_call["function"]:
                            arguments = json.loads(tool_call["function"]["arguments"]) if tool_call["function"]["arguments"] else {}
                            function_response = handle_function_call(tool_call["function"]["name"], arguments)
                            session["messages"].append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "content": function_response.get("content", ""),
                                "reasoning_content": "",
                            })
                            st.markdown(f"Tool call response: \n {function_response.get('content', '')}")
                # Reset the generating response flag
                st.session_state.generating_response = False
                
                
        except Exception as e:
            # Reset the generating response flag in case of error
            st.session_state.generating_response = False
            logger.error(f"Failed to create chat completion: {e}", exc_info=True)
            st.error("Failed to create chat completion. Please check the model and messages.")
            st.stop()

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

    # Initialize the retry flag if not already set
    if "retry_last_message" not in st.session_state:
        st.session_state.retry_last_message = False

    # Display the chat messages
    display_chat_messages(session, db)

    # Handle user input
    handle_user_input(session, client, model["model"], [system_prompt] if system_prompt["content"].strip() != "" else [], db)

def fetch_url(url: str) -> Optional[str]:
    """Fetch and extract main content from a URL using trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            return trafilatura.extract(downloaded)
        return None
    except Exception as e:
        logger.error(f"Failed to fetch URL {url}: {e}")
        return None

def handle_function_call(function_name: str, arguments: dict) -> dict:
    """Handle function calls from the AI client."""
    if function_name == "fetch_url":
        url = arguments.get("url")
        if not url:
            return {"error": "URL parameter missing"}
        content = fetch_url(url)
        return {"content": content if content else "Failed to fetch URL content"}
    return {"error": f"Unknown function: {function_name}"}

# Function to handle the streaming of chat responses
def write_stream(stream):
    """
    Handle the streaming of chat responses including tool calls.
    Returns the response, reasoning response, and function call data if any.
    """
    response = ""
    reasoning_response = ""
    container = None
    final_tool_calls = {}
    
    for chunk in stream:
        message = ""
        reasoning_message = ""
        
        if len(chunk.choices) == 0 or chunk.choices[0].delta is None:
            continue
            
        delta = chunk.choices[0].delta
        
        # Handle tool calls
        if hasattr(delta, "tool_calls") and delta.tool_calls:
            for tool_call in delta.tool_calls:
                index = tool_call.index

                print(f"Tool call: {tool_call}")
                
                if index not in final_tool_calls:
                    final_tool_calls[index] = {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        }
                    }
                else:
                    if tool_call.function.arguments:
                        final_tool_calls[index]["function"]["arguments"] += tool_call.function.arguments
                
        # Handle normal content
        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            reasoning_message += delta.reasoning_content
        elif delta.content:
            message += delta.content

        # Continue if there is no content and reasoning content
        if not message and not reasoning_message and not final_tool_calls:
            continue

        first_text = False
        if not container:
            container = st.empty()
            first_text = True

        response += message
        reasoning_response += reasoning_message

        if not final_tool_calls:
            container.markdown("Calling functions...")
        else:
        # Only add the streaming symbol on the second text chunk
            container.markdown(quote_content(reasoning_response) + response + ("" if first_text else " | "))

    # Flush the stream
    if container:
        if not final_tool_calls:
            container.markdown("Calling functions...")
        else:
            container.markdown(quote_content(reasoning_response) + response)
        container = None
        
    return response, reasoning_response, list(final_tool_calls.values())
