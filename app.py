from openai import OpenAI
import streamlit as st
import streamlit_authenticator as stauth

import yaml
from yaml.loader import SafeLoader

from botpage import botpage


def set_current_session(session):
    st.session_state.current_session = session


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

    init_bot = next(b for b in st.session_state.bots)

    if not init_bot:
        st.info(f"There is no bot")
        st.stop()

    if "current_session_name" not in st.session_state:
        st.session_state.current_session = {
            "name": None,
            "bot_id": init_bot["id"],
            "messages": [],
        }

    with st.sidebar:
        st.subheader("新建对话")
        for bot in st.session_state.bots:
            st.button(
                bot["name"],
                on_click=set_current_session,
                args=(
                    {
                        "name": None,
                        "bot_id": bot["id"],
                        "messages": [],
                    },
                ),
            )

        st.subheader("会话记录")
        for session in st.session_state.bot_sessions:
            st.button(
                session["name"],
                on_click=set_current_session,
                args=(session,),
                disabled=session["name"] == st.session_state.current_session["name"],
            )

    botpage()

elif st.session_state["authentication_status"] is False:
    st.error("Username/password is incorrect")
elif st.session_state["authentication_status"] is None:
    st.warning("Please enter your username and password")
