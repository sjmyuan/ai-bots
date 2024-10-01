from openai import OpenAI
import streamlit as st


def botpage(bot):

    st.title(bot.name)
    st.caption(bot.description)

    system_prompt = {'role': 'system', 'content': bot.prompt}
    client = OpenAI(api_key=bot.api_key, base_url= bot.base_url)

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
         if msg.bot_id == bot.id:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    if prompt := st.chat_input():
        st.session_state.messages.append({"bot_id": bot.id, "role": "user", "content": prompt})

        with st.chat_message("user"):
            st.markdown(prompt)


        with st.chat_message("assistant"):
            stream = client.chat.completions.create(
                model=bot.model,
                messages= [system_prompt] + [{"role":msg.role, "content":msg.content} for msg in st.session_state.messages if msg.bot_id == bot_id],
                stream=True,
            )
            response = st.write_stream(stream)
        st.session_state.messages.append({"bot_id":bot.id, "role": "assistant", "content": response})