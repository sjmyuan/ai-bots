from openai import OpenAI
import streamlit as st
import streamlit_authenticator as stauth

import yaml
from yaml.loader import SafeLoader

from botpage import botpage

with open("./config.yml") as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"],
)

authenticator.login()

if st.session_state["authentication_status"]:
    authenticator.logout()
    if "bots" not in st.session_state:
        st.session_state.bots = config["bots"]

    if "bot_sessions" not in st.session_state:
        st.session_state.bot_sessions = []

    with st.sidebar:
        st.subheader("新建对话")
        for bot in st.session_state.bots:
            if st.button(bot["name"]):
                botpage({"name": None, "bot_id": bot["id"], "messages": []})

        st.subheader("会话记录")

        for session in st.session_state.bot_sessions:
            if st.button(session["name"]):
                botpage(session)

    init_bot = next(b for b in st.session_state.bots)
    if not init_bot:
        st.info(f"There is no bot")
        st.stop()

    botpage({"name": None, "bot_id": init_bot["id"], "messages": []})

elif st.session_state["authentication_status"] is False:
    st.error("Username/password is incorrect")
elif st.session_state["authentication_status"] is None:
    st.warning("Please enter your username and password")
