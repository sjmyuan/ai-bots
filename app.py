import os
import time
from openai import OpenAI
import streamlit as st
import streamlit_authenticator as stauth

import yaml
from yaml.loader import SafeLoader

from botpage import botpage


def set_current_session(session):
    st.session_state.current_session = session


st.set_page_config(
    "AI Bots", page_icon="https://images.shangjiaming.com/bio-photo.jpeg"
)

with open(os.getenv("CONFIG_FILE")) as file:
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
    if "bots" not in st.session_state or len(st.session_state.bots) != len(
        config["bots"]
    ):
        st.session_state.bots = config["bots"]

    if "models" not in st.session_state or len(st.session_state.models) != len(
        config["models"]
    ):
        st.session_state.models = config["models"]

    if "bot_sessions" not in st.session_state:
        st.session_state.bot_sessions = []

    init_bot = next(b for b in st.session_state.bots)
    init_model = next(m for m in st.session_state.models)

    if not init_bot:
        st.info(f"There is no bot")
        st.stop()

    if not init_model:
        st.info(f"There is no model")
        st.stop()

    if "current_session" not in st.session_state:
        st.session_state.current_session = {
            "id": int(time.time()),
            "name": None,
            "bot_id": init_bot["id"],
            "messages": [],
        }

    if "current_model" not in st.session_state:
        st.session_state.current_model = init_model

    with st.sidebar:
        selected_model = st.selectbox(
            "选择模型",
            st.session_state.models,
            next(
                index
                for index, value in enumerate(st.session_state.models)
                if value["id"] == st.session_state.current_model["id"]
            ),
            lambda m: m["name"],
        )

        st.session_state.current_model = selected_model

        st.subheader("新建对话")
        for bot in st.session_state.bots:
            st.button(
                bot["name"],
                on_click=set_current_session,
                args=(
                    {
                        "id": int(time.time()),
                        "name": None,
                        "bot_id": bot["id"],
                        "messages": [],
                    },
                ),
                use_container_width=True,
            )

        st.subheader("会话记录")
        for session in st.session_state.bot_sessions:
            st.button(
                session["name"],
                key=session["id"],
                on_click=set_current_session,
                args=(session,),
                disabled=session["id"] == st.session_state.current_session["id"],
                use_container_width=True,
            )

    botpage()

elif st.session_state["authentication_status"] is False:
    st.error("Username/password is incorrect")
elif st.session_state["authentication_status"] is None:
    st.warning("Please enter your username and password")
