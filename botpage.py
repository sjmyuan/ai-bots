from openai import OpenAI
import streamlit as st


def quote_content(content):
    lines = content.splitlines()

    modified_lines = ["> " + line for line in lines]

    return "\n".join(modified_lines)


def botpage():

    session = st.session_state.current_session

    model = st.session_state.current_model

    bot = next(b for b in st.session_state.bots if b["id"] == session["bot_id"])

    name = session["name"] or bot["name"]

    st.title(name)
    st.caption("Bot：" + bot["name"])
    st.caption("模型：" + model["name"])

    system_prompt = {"role": "system", "content": bot["prompt"]}

    client = OpenAI(api_key=model["api_key"], base_url=model["base_url"])

    for msg in session["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(quote_content(msg["reasoning_content"]) + msg["content"])

    if prompt := st.chat_input():
        session["messages"].append(
            {"role": "user", "content": prompt, "reasoning_content": ""}
        )

        with st.chat_message("user"):
            st.markdown(prompt)

        system_prompt_list = (
            [system_prompt] if system_prompt["content"].strip() != "" else []
        )

        with st.chat_message("assistant"):
            stream = client.chat.completions.create(
                model=model["model"],
                messages=(
                    system_prompt_list
                    + [
                        {"role": msg["role"], "content": msg["content"]}
                        for msg in session["messages"][-7:]
                    ]
                ),
                stream=True,
            )

            response, reasoning_response = write_stream(stream)

        session["messages"].append(
            {
                "role": "assistant",
                "content": response,
                "reasoning_content": reasoning_response,
            }
        )

        if not session["name"]:
            session["name"] = prompt[0:50]
            st.session_state.bot_sessions.append(session)


def write_stream(stream):
    response = ""
    reasoning_response = ""
    container = None
    for chunk in stream:
        message = ""
        reasoning_message = ""
        if len(chunk.choices) == 0 or chunk.choices[0].delta is None:
            # The choices list# can be empty. E.g. when using the
            # AzureOpenAI clie nt, the first chunk will always be empty.
            message = ""  #
        else:
            if (
                hasattr(chunk.choices[0].delta, "reasoning_content")
                and chunk.choices[0].delta.reasoning_content
            ):
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
        container.markdown(
            quote_content(reasoning_response) + response + ("" if first_text else " | ")
        )

        # Flush stream
    if container:
        container.markdown(quote_content(reasoning_response) + response)
        container = None
    return response, reasoning_response
