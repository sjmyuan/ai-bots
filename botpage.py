# Import necessary libraries
from bs4 import BeautifulSoup
from openai import OpenAI
from datetime import datetime
import re
import base64

import requests
import markdownify
from st_copy_to_clipboard import st_copy_to_clipboard
import streamlit as st
import logging
import json
from typing import Optional, List, Dict, Any, Tuple

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

# --- Utility Functions ---

def quote_content(content: str) -> str:
    """Format content with a quote."""
    if not content:
        return ""
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

def fetch_url(url: str) -> Optional[str]:
    """Fetch and extract main content from a URL using trafilatura."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser', from_encoding=response.encoding)
        body = soup.find('body')
        return markdownify.markdownify(str(body) if body else "", heading_style="ATX")
    except Exception as e:
        logger.error(f"Failed to fetch URL {url}: {e}")
        return None

def handle_function_call(function_name: str, arguments: dict) -> dict:
    """Handle function calls from the AI client."""
    try:
        if function_name == "fetch_url":
            url = arguments.get("url")
            if not url:
                return {"error": "URL parameter missing"}
            content = fetch_url(url)
            if content:
                return {"content": content}
            else:   
                return {"error": f"Failed to fetch content from URL: {url}"}
        return {"error": f"Unknown function: {function_name}"}
    except Exception as e:
        logger.error(f"Error in function call {function_name}: {e}")
        return {"error": f"Function call failed: {e}"}

# --- Message Display and Handling Functions ---

def display_truncation_message():
    """Display a truncation message in the chat."""
    st.markdown("""
        <div style='position: relative; text-align: center; margin: 20px 0; height: 20px;'>
            <hr style='position: absolute; width: 100%; top: 10px; border: none; border-top: 1px solid #ccc; margin: 0;'>
            <span style='position: absolute; top: 0; left: 50%; transform: translateX(-50%); background-color: #f0f2f6; padding: 0 10px; color: #888; font-size: 0.8rem;'>truncated</span>
        </div>
    """, unsafe_allow_html=True)

def display_message_content(msg: Dict[str, Any]):
    """Display the content of a message."""
    if msg["role"] == "tool":
        with st.expander("Click to Expand/Collapse Tool Call Response", expanded=False):
            st.text(msg["content"])
    else:
        message_content = quote_content(msg.get("reasoning_content", "")) + "\n\n" + msg["content"]

        if "tool_calls" in msg and msg["tool_calls"]:
            message_content += "\n\n**Tool Calls:**\n"
            for tool_call in msg["tool_calls"]:
                message_content += f"- **{tool_call['function']['name']}**: {tool_call['function']['arguments']}\n"
        
        st.markdown(message_content)

        # Extract SVG content using regular expressions
        svg_pattern = re.compile(r'<svg[^>]*>.*?</svg>', re.DOTALL)
        svg_matches = svg_pattern.findall(message_content)
        
        # Display each SVG image
        for i, svg in enumerate(svg_matches):
            # Convert SVG to base64 for display in st.image
            svg_bytes = svg.encode('utf-8')
            b64 = base64.b64encode(svg_bytes).decode('utf-8')
            svg_data_uri = f"data:image/svg+xml;base64,{b64}"
            st.image(svg_data_uri, use_container_width=True)

def display_message_actions(msg: Dict[str, Any], idx: int, session: Dict[str, Any], db, is_last_message: bool):
    """Display action buttons for a message."""
    cols = st.columns([6, 1, 1, 1, 1])
    current_col = 4

    # Copy button
    with cols[current_col]:
        current_col -= 1
        st_copy_to_clipboard(msg["content"], key=f"copy_{hash(msg['content'])}_{idx}")

    # Edit button for user messages
    if msg["role"] == "user":
        with cols[current_col]:
            current_col -= 1
            if st.button("📝", key=f"edit_{hash(msg['content'])}_{idx}"):
                st.session_state.edit_message_idx = idx
                st.rerun()

    # Additional buttons for the last message
    if is_last_message and not st.session_state.get("generating_response", False):
        # Truncate button
        with cols[current_col]:
            current_col -= 1
            if st.button("✂️", key="truncate_button"):
                session["messages"].append({
                    "role": "truncation",
                    "content": "",
                    "reasoning_content": ""
                })
                save_session_to_db(db, session)
                st.rerun()

        # Retry button for assistant messages
        if msg["role"] == "assistant":
            with cols[current_col]:
                if st.button("🔄", key="retry_button"):
                    st.session_state.retry_last_message = True
                    session["messages"].pop()
                    save_session_to_db(db, session)
                    st.rerun()

def display_edit_form(msg: Dict[str, Any], idx: int, session: Dict[str, Any], db):
    """Display the form for editing a message."""
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

def display_chat_messages(session: Dict[str, Any], db):
    """Display all chat messages."""
    for idx, msg in enumerate(session["messages"]):
        if msg["role"] == "truncation":
            display_truncation_message()
            continue
            
        if not (msg["role"] == "user" and st.session_state.get("edit_message_idx") == idx):
            with st.chat_message(msg["role"]):
                display_message_content(msg)
            
            display_message_actions(
                msg, 
                idx, 
                session, 
                db, 
                is_last_message=(idx == len(session["messages"]) - 1)
            )
        else:
            display_edit_form(msg, idx, session, db)

# --- Stream Handling Functions ---

def write_stream(stream) -> Tuple[str, str, List[Dict]]:
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

        if final_tool_calls:
            tool_calls_content = render_tool_calls(final_tool_calls)
            container.markdown(tool_calls_content)
        else:
            # Only add the streaming symbol on the second text chunk
            content_to_display = quote_content(reasoning_response)
            if response:
                content_to_display += "\n\n" + response
            if not first_text:
                content_to_display += " | "
            container.markdown(content_to_display)

    # Flush the stream
    if container:
        if final_tool_calls:
            tool_calls_content = render_tool_calls(final_tool_calls)
            container.markdown(tool_calls_content)
        else:
            container.markdown(quote_content(reasoning_response) + "\n\n" + response)
        
    return response, reasoning_response, list(final_tool_calls.values())

def render_tool_calls(tool_calls: Dict) -> str:
    """Render tool calls as markdown."""
    tool_calls_content = "\n\n**Tool Calls:**\n"
    for tool_call in tool_calls.values():
        tool_calls_content += f"- **{tool_call['function']['name']}**: {tool_call['function']['arguments']}\n"
    return tool_calls_content

def prepare_messages_for_api(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Prepare messages for the API call, handling truncation properly."""
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

        if 'tool_call_id' in msg:
            message_to_add["tool_call_id"] = msg['tool_call_id']

        messages_to_send.insert(0, message_to_add)

    # If truncation was found, modify the first user message
    if found_truncation and messages_to_send:
        first_user_idx = next((i for i, msg in enumerate(messages_to_send) if msg["role"] == "user"), None)
        if first_user_idx is not None:
            messages_to_send[first_user_idx]["content"] = f"<user_input>{messages_to_send[first_user_idx]['content']}</user_input>"

    return messages_to_send

# --- Main Chat Handling Functions ---

def handle_user_input(session: Dict[str, Any], client, model: str, system_prompt_list: List[Dict[str, str]], db):
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

        try:
            # Set flag to indicate response is being generated
            st.session_state.generating_response = True
            
            # Start a do-while loop to handle tool calls
            while True:
                # Get messages after the last truncation efficiently
                messages_to_send = prepare_messages_for_api(session)

                # Create the chat completion stream
                stream = client.chat.completions.create(
                    model=model,
                    messages=system_prompt_list + messages_to_send,
                    tools=TOOLS if model != "deepseek-reasoner" and model != "deepseek-r1" else None,
                    function_call="auto",
                    stream=True,
                )

                with st.chat_message("assistant"):
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
                        tool_response_content = function_response.get("content", function_response.get("error", "Invalid function response"))
                        session["messages"].append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": tool_response_content,
                            "reasoning_content": "",
                        })
                        with st.chat_message("tool"):
                            with st.expander("Click to Expand/Collapse Tool Call Response", expanded=False):
                                st.text(tool_response_content)


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
        st.rerun()  # Refresh the UI

def botpage(db):
    """Main function to handle the bot page."""
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
    system_prompt_list = [system_prompt] if system_prompt["content"].strip() != "" else []

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
    handle_user_input(session, client, model["model"], system_prompt_list, db)
