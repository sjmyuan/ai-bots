from openai import OpenAI
import streamlit as st


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
            st.markdown(msg["content"])

    if prompt := st.chat_input():
        session["messages"].append({"role": "user", "content": prompt})

        with st.chat_message("user"):
            st.markdown(prompt)

        system_prompt_list = (
            [system_prompt] if system_prompt["content"].strip() != "" else []
        )

        response = ""
        container = None
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

            for chunk in stream:
                message = ""
                if len(chunk.choices) == 0 or chunk.choices[0].delta is None:
                    # The choices list can be empty. E.g. when using the
                    # AzureOpenAI client, the first chunk will always be empty.
                    message = ""
                else:
                    message = chunk.choices[0].delta.content or ""

                if not message:
                    continue

                first_text = False
                if not container:
                    container = st.empty()
                    first_text = True

                response += message

                # Only add the streaming symbol on the second text chunk
                container.markdown(response + ("" if first_text else " | "))

        # Flush stream
        container.markdown(response)
        container = None

        session["messages"].append({"role": "assistant", "content": response})

        if not session["name"]:
            session["name"] = prompt[0:50]
            st.session_state.bot_sessions.append(session)
