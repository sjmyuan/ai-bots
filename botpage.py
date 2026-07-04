# Import necessary libraries
from bs4 import BeautifulSoup
from openai import OpenAI
from datetime import datetime
import base64
import ipaddress
import json
import logging
import os
import re
import socket
import urllib.parse

import requests
import markdownify
from st_copy_to_clipboard import st_copy_to_clipboard
import streamlit as st
from typing import Optional, List, Dict, Any, Tuple

# Maximum number of tool-call rounds per user turn to prevent runaway loops.
MAX_TOOL_ROUNDS = 1000

# Maximum tool response content size (bytes) stored in session / sent to the API.
MAX_TOOL_RESPONSE_BYTES = 50_000

# Define tools as a constant
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web using Bing and return a list of relevant results with titles, URLs, and snippets. Use this to find up-to-date information, then call fetch_url on the result URLs to get full content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
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
                        "description": "The URL to fetch content from",
                    }
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
]

# Set up logging — set LOG_LEVEL=DEBUG in the environment to enable debug output.
# Defaults to INFO to avoid leaking secrets (e.g. API keys) from third-party SDKs.
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _log_level, logging.INFO))
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
                "updated_at": datetime.now(),
                "bot_id": session["bot_id"],
                "messages": session["messages"],
            },
            "$setOnInsert": {
                "create_time": datetime.now(),
            },
        },
        upsert=True,
    )


@st.cache_resource
def initialize_openai_client(api_key: str, base_url: str) -> OpenAI:
    """Initialize the OpenAI client."""
    try:
        return OpenAI(api_key=api_key, base_url=base_url, max_retries=2)
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        st.error("OpenAI 客户端初始化失败，请检查 API 密钥和接口地址。")
        st.stop()


def _is_safe_url(url: str) -> bool:
    """Return True only if the URL uses http/https and does not target a private/internal host."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        resolved_ip = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(resolved_ip)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            return False
        return True
    except Exception:
        return False


def search_web(query: str) -> Optional[List[Dict]]:
    """Search the web by scraping Bing search results."""
    try:
        response = requests.get(
            "https://www.bing.com/search",
            params={"q": query},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            },
            timeout=15,
        )
        logger.debug(f"Bing search HTTP {response.status_code} for query: {query!r}")
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        items = soup.select("#b_results li.b_algo")
        logger.debug(f"Bing search: found {len(items)} raw result elements")
        results = []
        for li in items[:5]:
            a_tag = li.select_one("h2 a")
            snippet_tag = li.select_one(".b_caption p")
            if a_tag:
                url = a_tag.get("href", "")
                if url.startswith(("http://", "https://")):
                    results.append(
                        {
                            "title": a_tag.get_text(),
                            "url": url,
                            "snippet": snippet_tag.get_text() if snippet_tag else "",
                        }
                    )
        logger.debug(f"Bing search: parsed {len(results)} results for query: {query!r}")
        return results if results else None
    except Exception as e:
        logger.error(f"Failed to search Bing for '{query}': {e}")
        return None


def fetch_url(url: str) -> Optional[str]:
    """Fetch and extract main content from a URL."""
    if not _is_safe_url(url):
        logger.warning(f"Blocked fetch to unsafe URL: {url}")
        return None
    try:
        response = requests.get(url, timeout=15, allow_redirects=False)
        if response.is_redirect:
            location = response.headers.get("Location", "")
            logger.warning(f"Blocked redirect from {url} to {location!r}")
            return None
        response.raise_for_status()
        soup = BeautifulSoup(
            response.content, "html.parser", from_encoding=response.encoding
        )
        body = soup.find("body")
        return markdownify.markdownify(str(body) if body else "", heading_style="ATX")
    except Exception as e:
        logger.error(f"Failed to fetch URL {url}: {e}")
        return None


def handle_function_call(function_name: str, arguments: dict) -> dict:
    """Handle function calls from the AI client."""
    try:
        if function_name == "search_web":
            query = arguments.get("query")
            if not query:
                return {"error": "Query parameter missing"}
            results = search_web(query)
            if results is not None:
                return {"content": json.dumps(results, ensure_ascii=False)}
            else:
                return {"error": f"Failed to search for: {query}"}
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


# --- Utility helpers ---


def _get_text_content(content) -> str:
    """Extract plain text from message content (string or list of parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content if part.get("type") == "text"
        )
    logger.warning("Unexpected content type: %s", type(content).__name__)
    return ""


# --- Message Display and Handling Functions ---


def display_truncation_message():
    """Display a truncation message in the chat."""
    st.markdown(
        """
        <div style='position: relative; text-align: center; margin: 20px 0; height: 20px;'>
            <hr style='position: absolute; width: 100%; top: 10px; border: none; border-top: 1px solid #ccc; margin: 0;'>
            <span style='position: absolute; top: 0; left: 50%; transform: translateX(-50%); background-color: #f0f2f6; padding: 0 10px; color: #888; font-size: 0.8rem;'>truncated</span>
        </div>
    """,
        unsafe_allow_html=True,
    )


def display_message_content(msg: Dict[str, Any]):
    """Display the content of a message."""
    if msg["role"] == "tool":
        with st.expander("点击展开/收起工具调用响应", expanded=False):
            st.text(msg["content"])
    else:
        reasoning = quote_content(msg.get("reasoning_content", ""))
        text_content = _get_text_content(msg["content"])
        message_content = (reasoning + "\n\n" if reasoning else "") + text_content

        if "tool_calls" in msg and msg["tool_calls"]:
            message_content += "\n\n**Tool Calls:**\n"
            for tool_call in msg["tool_calls"]:
                message_content += f"- **{tool_call['function']['name']}**: {tool_call['function']['arguments']}\n"

        st.markdown(message_content)

        # Display uploaded images from list content
        if isinstance(msg["content"], list):
            for part in msg["content"]:
                if part.get("type") == "image_url":
                    st.image(part["image_url"]["url"])

        # Extract SVG content using regular expressions
        svg_pattern = re.compile(r"<svg[^>]*>.*?</svg>", re.DOTALL)
        svg_matches = svg_pattern.findall(message_content)

        # Display each SVG image
        for i, svg in enumerate(svg_matches):
            # Convert SVG to base64 for display in st.image
            svg_bytes = svg.encode("utf-8")
            b64 = base64.b64encode(svg_bytes).decode("utf-8")
            svg_data_uri = f"data:image/svg+xml;base64,{b64}"
            st.image(svg_data_uri, use_container_width=True)


def display_message_actions(
    msg: Dict[str, Any], idx: int, session: Dict[str, Any], db, is_last_message: bool
):
    """Display action buttons for a message.

    Columns are sized dynamically based on which buttons are shown,
    so there are never empty placeholder columns.
    """
    text_content = _get_text_content(msg["content"])

    # Build the list of buttons from the right end (rightmost = last in list)
    buttons = []

    # Copy button — always at the far right end
    buttons.append("copy")

    # Truncate/remove button — to the left of copy, only for the last message
    if is_last_message and not st.session_state.get("generating_response", False):
        buttons.append("truncate")

    # Edit button — to the left of truncate, only for user messages
    if msg["role"] == "user":
        buttons.append("edit")

    # Retry button — to the left of edit, only for the last assistant message
    if (
        is_last_message
        and not st.session_state.get("generating_response", False)
        and msg["role"] == "assistant"
    ):
        buttons.append("retry")

    # Create dynamic columns: spacer + one per button
    col_ratios = [6] + [1] * len(buttons)
    cols = st.columns(col_ratios)

    for i, action in enumerate(buttons):
        with cols[i + 1]:
            if action == "copy":
                st_copy_to_clipboard(text_content, key=f"copy_{idx}")
            elif action == "edit":
                if st.button("📝", key=f"edit_{idx}"):
                    st.session_state.edit_message_idx = idx
                    st.rerun()
            elif action == "truncate":
                if st.button("✂️", key="truncate_button"):
                    session["messages"].append(
                        {"role": "truncation", "content": "", "reasoning_content": ""}
                    )
                    save_session_to_db(db, session)
                    st.rerun()
            elif action == "retry":
                if st.button("🔄", key="retry_button"):
                    st.session_state.retry_last_message = True
                    session["messages"].pop()
                    save_session_to_db(db, session)
                    st.rerun()


def display_edit_form(msg: Dict[str, Any], idx: int, session: Dict[str, Any], db):
    """Display the form for editing a message."""
    original_content = msg["content"]
    new_text = st.text_area(
        "编辑消息",
        value=_get_text_content(original_content),
        key=f"edit_text_{idx}",
        height=300,
    )
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("提交", key=f"submit_edit_{idx}"):
            if isinstance(original_content, list):
                # Preserve image parts; replace text part
                new_content: Any = []
                text_replaced = False
                for part in original_content:
                    if part.get("type") == "text" and not text_replaced:
                        new_content.append({"type": "text", "text": new_text})
                        text_replaced = True
                    else:
                        new_content.append(part)
                if not text_replaced:
                    new_content.insert(0, {"type": "text", "text": new_text})
            else:
                new_content = new_text
            session["messages"][idx]["content"] = new_content
            st.session_state.edit_message_idx = None
            # Clear all messages after the edited message
            session["messages"] = session["messages"][: idx + 1]

            # Reset the generating response flag
            st.session_state.generating_response = False

            # Save the updated session to the database
            save_session_to_db(db, session)

            # Trigger regeneration of the assistant's response
            st.session_state.retry_last_message = True

            # Rerun the app to refresh the UI
            st.rerun()
    with col2:
        if st.button("取消", key=f"cancel_edit_{idx}"):
            st.session_state.edit_message_idx = None
            st.rerun()


def display_chat_messages(session: Dict[str, Any], db):
    """Display all chat messages."""
    for idx, msg in enumerate(session["messages"]):
        if msg["role"] == "truncation":
            display_truncation_message()
            continue

        if not (
            msg["role"] == "user" and st.session_state.get("edit_message_idx") == idx
        ):
            with st.chat_message(msg["role"]):
                display_message_content(msg)

            display_message_actions(
                msg,
                idx,
                session,
                db,
                is_last_message=(idx == len(session["messages"]) - 1),
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
                        },
                    }
                else:
                    if tool_call.function.arguments:
                        final_tool_calls[index]["function"][
                            "arguments"
                        ] += tool_call.function.arguments

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
        message_to_add = {"role": msg["role"], "content": msg["content"]}

        if "tool_calls" in msg:
            message_to_add["tool_calls"] = msg["tool_calls"]

        if "tool_call_id" in msg:
            message_to_add["tool_call_id"] = msg["tool_call_id"]

        messages_to_send.insert(0, message_to_add)

    # If truncation was found, modify the first user message
    if found_truncation and messages_to_send:
        first_user_idx = next(
            (i for i, msg in enumerate(messages_to_send) if msg["role"] == "user"), None
        )
        if first_user_idx is not None:
            content = messages_to_send[first_user_idx]["content"]
            if isinstance(content, list):
                # Copy the list (and each part dict) to avoid mutating session state
                content = [dict(part) for part in content]
                messages_to_send[first_user_idx]["content"] = content
                wrapped = False
                for part in content:
                    if part.get("type") == "text":
                        part["text"] = f"<user_input>{part['text']}</user_input>"
                        wrapped = True
                        break
                if not wrapped:
                    content.insert(
                        0, {"type": "text", "text": "<user_input></user_input>"}
                    )
            else:
                messages_to_send[first_user_idx][
                    "content"
                ] = f"<user_input>{content}</user_input>"

    return messages_to_send


def _inject_system_prompt(
    messages: List[Dict[str, Any]],
    system_prompt_list: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """Prepend the system prompt to a prepared message list.

    When the model does not support a system role, the prompt content is
    prepended to the first user message so the instruction still reaches
    the model.  When system prompts are supported, the system message is
    prepended as a separate entry.
    """
    if not system_prompt_list:
        return messages

    if system_prompt_list[0]["role"] == "user" and messages:
        prefix = system_prompt_list[0]["content"] + "\n\n"
        first_content = messages[0]["content"]
        messages = [dict(messages[0])] + messages[1:]  # shallow-copy first entry
        if isinstance(first_content, list):
            messages[0]["content"] = [{"type": "text", "text": prefix}] + first_content
        else:
            messages[0]["content"] = prefix + first_content
        return messages

    return system_prompt_list + messages


# --- Main Chat Handling Functions ---


def handle_user_input(
    session: Dict[str, Any],
    client,
    model: str,
    system_prompt_list: List[Dict[str, str]],
    db,
):
    """Handle user input and generate assistant response."""
    # Check if we need to retry the last message
    retry_mode = False
    if st.session_state.get("retry_last_message", False):
        # Reset the flag
        st.session_state.retry_last_message = False
        retry_mode = True

    support_file_upload = st.session_state.current_model.get(
        "support_file_upload", False
    )
    uploaded_files = None
    if support_file_upload:
        uploaded_files = st.file_uploader(
            "上传图片",
            accept_multiple_files=True,
            type=["png", "jpg", "jpeg", "gif", "webp"],
            label_visibility="collapsed",
        )

    if prompt := st.chat_input() or retry_mode:
        # In retry mode, we don't need a new user prompt
        if not retry_mode:
            # Build message content (plain string or multipart list with images)
            if uploaded_files:
                content: Any = [{"type": "text", "text": prompt}]
                for f in uploaded_files:
                    encoded = base64.b64encode(f.read()).decode("utf-8")
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{f.type};base64,{encoded}"},
                        }
                    )
            else:
                content = prompt

            # Append the user message to the session
            session["messages"].append(
                {"role": "user", "content": content, "reasoning_content": ""}
            )

            # Display the user message
            with st.chat_message("user"):
                display_message_content(session["messages"][-1])

        try:
            # Set flag to indicate response is being generated
            st.session_state.generating_response = True

            # Build messages with system prompt injection once, before the loop
            messages_to_send = _inject_system_prompt(
                prepare_messages_for_api(session), system_prompt_list
            )

            supports_tools = st.session_state.current_model.get("support_tools", True)

            # Delegate tool-call loop to the extracted function
            process_tool_calls(messages_to_send, client, model, supports_tools, session)

            # Reset the generating response flag
            st.session_state.generating_response = False

        except Exception as e:
            # Reset the generating response flag in case of error
            st.session_state.generating_response = False
            logger.error(f"创建聊天回复失败: {e}", exc_info=True)
            st.error("创建聊天回复失败，请检查模型和消息内容。")
            st.stop()

        # Set the session name if it is not already set
        if not session["name"] and not retry_mode:
            session["name"] = str(prompt[:50])
            st.session_state.bot_sessions.append(session)

        save_session_to_db(db, session)
        st.rerun()  # Refresh the UI


def process_tool_calls(
    messages_to_send: List[Dict[str, Any]],
    client: OpenAI,
    model: str,
    supports_tools: bool,
    session: Dict[str, Any],
) -> None:
    """Run the tool-call loop: stream response, handle tool calls, repeat up to MAX_TOOL_ROUNDS times."""
    tool_rounds = 0
    while True:
        stream = client.chat.completions.create(
            model=model,
            messages=messages_to_send,
            tools=TOOLS if supports_tools else None,
            stream=True,
            timeout=300,
        )

        with st.chat_message("assistant"):
            response, reasoning_response, tool_calls = write_stream(stream)

        assistant_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": response,
        }
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages_to_send.append(assistant_msg)

        session["messages"].append(
            {
                "role": "assistant",
                "content": response,
                "reasoning_content": reasoning_response,
                **({"tool_calls": tool_calls} if tool_calls else {}),
            }
        )

        if not tool_calls:
            break

        tool_rounds += 1
        if tool_rounds >= MAX_TOOL_ROUNDS:
            logger.warning("工具调用次数已达上限 %d，停止。", MAX_TOOL_ROUNDS)
            st.warning(f"工具调用次数已达上限 ({MAX_TOOL_ROUNDS})，响应可能不完整。")
            break

        for tool_call in tool_calls:
            if "function" in tool_call and tool_call["function"]:
                try:
                    arguments = (
                        json.loads(tool_call["function"]["arguments"])
                        if tool_call["function"]["arguments"]
                        else {}
                    )
                except json.JSONDecodeError as e:
                    logger.error(f"工具参数格式错误: {e}")
                    arguments = {}
                function_response = handle_function_call(
                    tool_call["function"]["name"], arguments
                )
                tool_response_content = function_response.get(
                    "content",
                    function_response.get("error", "无效的函数响应"),
                )
                if len(tool_response_content) > MAX_TOOL_RESPONSE_BYTES:
                    logger.warning(
                        "工具 %s 的响应已从 %d 字节截断至 %d 字节。",
                        tool_call["function"]["name"],
                        len(tool_response_content),
                        MAX_TOOL_RESPONSE_BYTES,
                    )
                    tool_response_content = tool_response_content[
                        :MAX_TOOL_RESPONSE_BYTES
                    ]
                session["messages"].append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": tool_response_content,
                        "reasoning_content": "",
                    }
                )
                messages_to_send.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": tool_response_content,
                    }
                )
                with st.chat_message("tool"):
                    with st.expander(
                        "点击展开/收起工具调用响应",
                        expanded=False,
                    ):
                        st.text(tool_response_content)


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
        st.info("没有可用的机器人。")
        st.stop()

    # Set the name of the session
    name = session["name"] or bot["name"]

    # Display the title and captions
    st.title(name)
    st.caption(f"Bot: {bot['name']}")
    st.caption(f"模型: {model['name']}")

    # Inject CSS for mobile-friendly action buttons
    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            div[data-testid="column"] > div.stButton > button {
                min-height: 1.6rem;
                height: 1.8rem;
                padding: 0 0.35rem;
                font-size: 0.75rem;
                line-height: 1;
            }
            div[data-testid="column"] .st-copy-to-clipboard-btn {
                min-height: 1.6rem;
                height: 1.8rem;
                padding: 0 0.35rem;
                font-size: 0.75rem;
                line-height: 1;
            }
            div[data-testid="column"] {
                padding: 0 1px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Define the system prompt
    system_prompt = {
        "role": "user" if not model.get("support_system_prompt", True) else "system",
        "content": bot["prompt"],
    }
    system_prompt_list = (
        [system_prompt] if system_prompt["content"].strip() != "" else []
    )

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
