from openai import OpenAI
import streamlit as st


def botpage():

    session = st.session_state.current_session

    bot = next(b for b in st.session_state.bots if b["id"] == session["bot_id"])

    name = session["name"] or bot["name"]

    st.title(name)

    system_prompt = {"role": "system", "content": bot["prompt"]}

    client = OpenAI(api_key=bot["api_key"], base_url=bot["base_url"])

    for msg in session["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input():
        session["messages"].append({"role": "user", "content": prompt})

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            stream = client.chat.completions.create(
                model=bot["model"],
                messages=[system_prompt]
                + [
                    {"role": msg["role"], "content": msg["content"]}
                    for msg in session["messages"]
                ],
                stream=True,
            )
            response = st.write_stream(stream)
        session["messages"].append({"role": "assistant", "content": response})

        if not session["name"]:
            session["name"] = prompt[0:50]
            st.session_state.bot_sessions.append(session)
            st.session_state.current_session_name = session["name"]
